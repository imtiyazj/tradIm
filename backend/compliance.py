"""
compliance.py — Quarterly Shariah compliance review + dividend purification.

Two related jobs that the weekly cache refresh does not cover:

1. Quarterly compliance review
   Re-screens every open position (plus the active watchlist) with a forced
   fresh screen, compares each result with the status at the previous review,
   and writes a permanent audit row per symbol (compliance_checks). Holdings
   that are now non-compliant are surfaced as "action required" — the review
   never sells anything itself.

2. Purification ledger
   Pulls dividend payments from Alpaca and records, per dividend, the share
   that came from impermissible income (purification_entries) so it can be
   donated and marked as paid.

   purification = dividend * impure share
   impure share = haram-revenue share from the halal screen; when the screen
   has no figure, the 5% compliance ceiling is used as an upper bound and the
   entry is flagged rate_source="default_cap".

Scheduling and Telegram alerts live in scheduler/jobs.py.
"""

import os
import uuid
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Optional

import requests
from sqlalchemy.orm import Session

from db.models import (
    HalalStatus, HalalScreenResult, WatchlistItem,
    ComplianceCheck, PurificationEntry,
)
import halal_screen as halal_module

logger = logging.getLogger(__name__)

ALPACA_KEY      = os.environ.get("ALPACA_KEY", "")
ALPACA_SECRET   = os.environ.get("ALPACA_SECRET", "")
ALPACA_BASE_URL = os.environ.get("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

# A compliant stock has < 5% impermissible income, so 5% is a safe upper
# bound when the actual share is unknown.
DEFAULT_IMPURE_CAP = Decimal("0.05")

_ACTIVITY_PAGE_SIZE = 100
_ACTIVITY_MAX_PAGES = 20


def is_paper_mode() -> bool:
    return "paper" in ALPACA_BASE_URL


def _alpaca_headers() -> dict:
    return {
        "APCA-API-KEY-ID":     ALPACA_KEY,
        "APCA-API-SECRET-KEY": ALPACA_SECRET,
    }


def _status_str(status) -> Optional[str]:
    if status is None:
        return None
    return status.value if hasattr(status, "value") else str(status)


def _f(value) -> Optional[float]:
    return float(value) if value is not None else None


def _to_decimal(value) -> Optional[Decimal]:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def quarter_label(dt: datetime) -> str:
    """Calendar quarter of a date, e.g. 2026-11-10 -> '2026-Q4'."""
    return f"{dt.year}-Q{(dt.month - 1) // 3 + 1}"


# ── Alpaca fetchers ───────────────────────────────────────────────────────────

def fetch_positions() -> Optional[list]:
    """Open positions from Alpaca. None (not []) when the call fails, so a
    failed fetch is never mistaken for an empty portfolio."""
    try:
        resp = requests.get(
            f"{ALPACA_BASE_URL}/v2/positions",
            headers=_alpaca_headers(),
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error(f"Compliance review: Alpaca positions fetch failed: {e}")
        return None


def fetch_dividend_activities(after: Optional[datetime] = None) -> Optional[list]:
    """
    Dividend (DIV) account activities from Alpaca, newest first.
    None when the call fails.
    """
    activities: list = []
    page_token = None
    try:
        for _ in range(_ACTIVITY_MAX_PAGES):
            params = {"page_size": _ACTIVITY_PAGE_SIZE, "direction": "desc"}
            if after is not None:
                params["after"] = after.strftime("%Y-%m-%d")
            if page_token:
                params["page_token"] = page_token
            resp = requests.get(
                f"{ALPACA_BASE_URL}/v2/account/activities/DIV",
                params=params,
                headers=_alpaca_headers(),
                timeout=15,
            )
            resp.raise_for_status()
            page = resp.json() or []
            activities.extend(page)
            if len(page) < _ACTIVITY_PAGE_SIZE:
                break
            page_token = page[-1].get("id")
            if not page_token:
                break
        return activities
    except Exception as e:
        logger.error(f"Purification sync: Alpaca dividend fetch failed: {e}")
        return None


# ── Quarterly compliance review ───────────────────────────────────────────────

def period_already_reviewed(db: Session, period: str) -> bool:
    """True once the period has at least one conclusive check. A run where
    every screen failed (e.g. Zoya down) does not count, so it is retried."""
    return (
        db.query(ComplianceCheck.id)
        .filter(
            ComplianceCheck.period == period,
            ComplianceCheck.inconclusive == False,
        )
        .first()
        is not None
    )


def _previous_status(db: Session, symbol: str):
    """
    Status to compare the fresh screen against: the last conclusive review
    of this symbol, else the most recent cached screen, else None.
    Must be called BEFORE the forced re-screen writes a new cache row.
    """
    last_review = (
        db.query(ComplianceCheck)
        .filter(
            ComplianceCheck.symbol == symbol,
            ComplianceCheck.inconclusive == False,
        )
        .order_by(ComplianceCheck.checked_at.desc())
        .first()
    )
    if last_review:
        return last_review.new_status
    last_screen = (
        db.query(HalalScreenResult)
        .filter(HalalScreenResult.symbol == symbol)
        .order_by(HalalScreenResult.screened_at.desc())
        .first()
    )
    return last_screen.final_status if last_screen else None


def _check_to_dict(c: ComplianceCheck) -> dict:
    return {
        "id":                str(c.id),
        "period":            c.period,
        "symbol":            c.symbol,
        "previous_status":   _status_str(c.previous_status),
        "new_status":        _status_str(c.new_status),
        "status_changed":    bool(c.status_changed),
        "inconclusive":      bool(c.inconclusive),
        "is_held":           bool(c.is_held),
        "quantity":          _f(c.quantity),
        "market_value":      _f(c.market_value),
        "debt_ratio":        _f(c.debt_ratio),
        "haram_revenue_pct": _f(c.haram_revenue_pct),
        "notes":             c.notes,
        "checked_at":        _iso(c.checked_at),
    }


def _review_payload(rows: list) -> dict:
    """Group one run's rows into the buckets the dashboard and alerts use."""
    conclusive = [r for r in rows if not r["inconclusive"]]
    return {
        "checked":         len(rows),
        "held":            sum(1 for r in rows if r["is_held"]),
        # Held and non-compliant: divest. Reported every review until sold.
        "action_required": [r for r in conclusive
                            if r["is_held"] and r["new_status"] == HalalStatus.NON_COMPLIANT.value],
        # Held and doubtful: needs a human decision.
        "review":          [r for r in conclusive
                            if r["is_held"] and r["new_status"] == HalalStatus.DOUBTFUL.value],
        "changed":         [r for r in rows if r["status_changed"]],
        "inconclusive":    [r["symbol"] for r in rows if r["inconclusive"]],
        "rows":            rows,
    }


def run_compliance_review(
    db: Session,
    user_id,
    positions: Optional[list] = None,
    now: Optional[datetime] = None,
) -> dict:
    """
    Force a fresh halal screen of every open position and active watchlist
    symbol, and record one ComplianceCheck row per symbol.

    Args:
        positions: Alpaca position dicts; fetched when omitted.
        now:       review timestamp (injectable for tests).
    """
    now    = now or datetime.now(timezone.utc)
    period = quarter_label(now)
    run_id = uuid.uuid4()

    positions_unavailable = False
    if positions is None:
        positions = fetch_positions()
        if positions is None:
            positions_unavailable = True
            positions = []

    held: dict = {}
    for p in positions:
        symbol = (p.get("symbol") or "").upper().strip()
        if not symbol or p.get("asset_class", "us_equity") != "us_equity":
            continue
        held[symbol] = {
            "quantity":     _to_decimal(p.get("qty")),
            "market_value": _to_decimal(p.get("market_value")),
        }

    watchlist = [
        i.symbol.upper()
        for i in db.query(WatchlistItem).filter(WatchlistItem.is_active == True).all()
    ]
    symbols = list(held)
    for s in watchlist:
        if s not in held and s not in symbols:
            symbols.append(s)

    logger.info(
        f"Compliance review {period}: {len(symbols)} symbols "
        f"({len(held)} held, positions_unavailable={positions_unavailable})"
    )

    rows = []
    for symbol in symbols:
        previous = _previous_status(db, symbol)

        screen: dict = {}
        error = None
        try:
            screen = halal_module.screen_stock(symbol, db, force_refresh=True)
        except Exception as e:
            logger.error(f"Compliance review: screen failed for {symbol}: {e}")
            db.rollback()
            error = str(e)

        new_status = screen.get("final_status") or HalalStatus.UNKNOWN
        inconclusive = bool(
            error
            or screen.get("zoya_unavailable")
            or new_status == HalalStatus.UNKNOWN
        )
        changed = (not inconclusive) and previous is not None and previous != new_status

        position = held.get(symbol, {})
        check = ComplianceCheck(
            user_id           = user_id,
            run_id            = run_id,
            period            = period,
            symbol            = symbol,
            previous_status   = previous,
            new_status        = new_status,
            status_changed    = changed,
            inconclusive      = inconclusive,
            is_held           = symbol in held,
            quantity          = position.get("quantity"),
            market_value      = position.get("market_value"),
            debt_ratio        = _to_decimal(screen.get("debt_ratio")),
            haram_revenue_pct = _to_decimal(screen.get("haram_revenue_pct")),
            notes             = f"Screening error: {error}" if error else screen.get("notes"),
            checked_at        = now,
        )
        db.add(check)
        # Commit per symbol: a later screen failure rolls the session back and
        # must not discard rows already reviewed.
        db.commit()
        rows.append(_check_to_dict(check))

    result = _review_payload(rows)
    result.update({
        "run_id":                str(run_id),
        "period":                period,
        "checked_at":            _iso(now),
        "positions_unavailable": positions_unavailable,
    })
    logger.info(
        f"Compliance review {period} done: {result['checked']} checked, "
        f"{len(result['action_required'])} action required, "
        f"{len(result['changed'])} changed, {len(result['inconclusive'])} inconclusive"
    )
    return result


def latest_review(db: Session) -> Optional[dict]:
    """The most recent review run, or None if no review has ever run."""
    last = (
        db.query(ComplianceCheck)
        .order_by(ComplianceCheck.checked_at.desc())
        .first()
    )
    if not last:
        return None
    checks = (
        db.query(ComplianceCheck)
        .filter(ComplianceCheck.run_id == last.run_id)
        .order_by(ComplianceCheck.is_held.desc(), ComplianceCheck.symbol)
        .all()
    )
    result = _review_payload([_check_to_dict(c) for c in checks])
    result.update({
        "run_id":     str(last.run_id),
        "period":     last.period,
        "checked_at": _iso(last.checked_at),
    })
    return result


def recent_changes(db: Session, limit: int = 50) -> list:
    """Status changes across all reviews, newest first."""
    checks = (
        db.query(ComplianceCheck)
        .filter(ComplianceCheck.status_changed == True)
        .order_by(ComplianceCheck.checked_at.desc())
        .limit(limit)
        .all()
    )
    return [_check_to_dict(c) for c in checks]


# ── Purification ledger ───────────────────────────────────────────────────────

def impure_rate(symbol: str, db: Session) -> tuple:
    """
    Share of a dividend that must be purified, as (rate, source, note).
    rate is a Decimal fraction in [0, 1].
    """
    screen: dict = {}
    try:
        screen = halal_module.screen_stock(symbol, db)
    except Exception as e:
        logger.warning(f"Purification: screen failed for {symbol}: {e}")
        db.rollback()

    notes = []
    haram = _to_decimal(screen.get("haram_revenue_pct"))
    if haram is not None and haram >= 0:
        # Screen stores a fraction; tolerate a percent-style value.
        rate = haram / 100 if haram > 1 else haram
        rate = min(rate, Decimal("1"))
        source = "screen"
    else:
        rate = DEFAULT_IMPURE_CAP
        source = "default_cap"
        notes.append(
            "Impermissible-income share not available — the 5% compliance "
            "ceiling was used as an upper bound."
        )

    if screen.get("final_status") == HalalStatus.NON_COMPLIANT:
        notes.append(
            "Stock was non-compliant when this was recorded — a larger share "
            "may need purifying; check with a scholar."
        )
    return rate, source, " ".join(notes) or None


def _entry_to_dict(e: PurificationEntry) -> dict:
    return {
        "id":                  str(e.id),
        "symbol":              e.symbol,
        "income_date":         _iso(e.income_date),
        "income_amount":       _f(e.income_amount),
        "impure_pct":          _f(e.impure_pct),
        "rate_source":         e.rate_source,
        "purification_amount": _f(e.purification_amount),
        "is_paid":             bool(e.is_paid),
        "paid_at":             _iso(e.paid_at),
        "note":                e.note,
    }


def sync_dividends(db: Session, user_id, activities: Optional[list] = None) -> dict:
    """
    Record a purification entry for every Alpaca dividend not yet in the
    ledger. Idempotent — keyed on the Alpaca activity id.
    """
    paper = is_paper_mode()

    if activities is None:
        latest = (
            db.query(PurificationEntry)
            .filter(PurificationEntry.is_paper == paper)
            .order_by(PurificationEntry.income_date.desc())
            .first()
        )
        # Overlap a week so late-posted dividends are not missed.
        after = latest.income_date - timedelta(days=7) if latest else None
        activities = fetch_dividend_activities(after)
        if activities is None:
            return {"error": "Could not reach Alpaca.", "fetched": 0, "added": 0, "skipped": 0}

    added = skipped = 0
    new_total = Decimal("0")
    rate_cache: dict = {}

    for activity in activities:
        activity_id = activity.get("id")
        symbol      = (activity.get("symbol") or "").upper().strip()
        amount      = _to_decimal(activity.get("net_amount"))
        if not activity_id or not symbol or amount is None or amount <= 0:
            skipped += 1
            continue

        exists = (
            db.query(PurificationEntry.id)
            .filter(PurificationEntry.alpaca_activity_id == activity_id)
            .first()
        )
        if exists:
            continue

        try:
            income_date = datetime.strptime(
                str(activity.get("date", ""))[:10], "%Y-%m-%d"
            ).replace(tzinfo=timezone.utc)
        except ValueError:
            skipped += 1
            continue

        if symbol not in rate_cache:
            rate_cache[symbol] = impure_rate(symbol, db)
        rate, source, note = rate_cache[symbol]

        owed = (amount * rate).quantize(Decimal("0.0001"))
        db.add(PurificationEntry(
            user_id             = user_id,
            symbol              = symbol,
            alpaca_activity_id  = activity_id,
            income_date         = income_date,
            income_amount       = amount,
            impure_pct          = rate.quantize(Decimal("0.0001")),
            rate_source         = source,
            purification_amount = owed,
            is_paper            = paper,
            note                = note,
        ))
        db.commit()
        added += 1
        new_total += owed

    logger.info(f"Purification sync: {len(activities)} fetched, {added} added, {skipped} skipped")
    return {
        "fetched":          len(activities),
        "added":            added,
        "skipped":          skipped,
        "new_purification": float(new_total),
    }


def purification_summary(db: Session, limit: int = 500) -> dict:
    """Ledger totals and entries for the current Alpaca mode (paper or live)."""
    paper = is_paper_mode()
    entries = (
        db.query(PurificationEntry)
        .filter(PurificationEntry.is_paper == paper)
        .order_by(PurificationEntry.income_date.desc())
        .all()
    )

    zero = Decimal("0")
    total_income = sum((e.income_amount for e in entries), zero)
    total_owed   = sum((e.purification_amount for e in entries), zero)
    total_paid   = sum((e.purification_amount for e in entries if e.is_paid), zero)

    by_year: dict = {}
    for e in entries:
        y = by_year.setdefault(e.income_date.year, {"dividends": zero, "owed": zero, "paid": zero})
        y["dividends"] += e.income_amount
        y["owed"]      += e.purification_amount
        if e.is_paid:
            y["paid"]  += e.purification_amount

    return {
        "paper":           paper,
        "total_dividends": float(total_income),
        "total_owed":      float(total_owed),
        "total_paid":      float(total_paid),
        "outstanding":     float(total_owed - total_paid),
        "estimated_count": sum(1 for e in entries if e.rate_source == "default_cap"),
        "by_year": [
            {
                "year":        year,
                "dividends":   float(v["dividends"]),
                "owed":        float(v["owed"]),
                "paid":        float(v["paid"]),
                "outstanding": float(v["owed"] - v["paid"]),
            }
            for year, v in sorted(by_year.items(), reverse=True)
        ],
        "entries": [_entry_to_dict(e) for e in entries[:limit]],
    }


def set_entry_paid(db: Session, entry_id: str, paid: bool) -> Optional[dict]:
    """Mark one entry as donated (or undo). None if the id does not exist."""
    try:
        key = uuid.UUID(str(entry_id))
    except ValueError:
        return None
    entry = db.query(PurificationEntry).filter(PurificationEntry.id == key).first()
    if not entry:
        return None
    entry.is_paid = paid
    entry.paid_at = datetime.now(timezone.utc) if paid else None
    db.commit()
    return _entry_to_dict(entry)


def mark_all_paid(db: Session) -> dict:
    """Mark every outstanding entry in the current mode as donated."""
    now = datetime.now(timezone.utc)
    entries = (
        db.query(PurificationEntry)
        .filter(
            PurificationEntry.is_paper == is_paper_mode(),
            PurificationEntry.is_paid == False,
        )
        .all()
    )
    total = Decimal("0")
    for e in entries:
        e.is_paid = True
        e.paid_at = now
        total += e.purification_amount
    db.commit()
    return {"marked": len(entries), "amount": float(total)}
