"""
performance.py — Signal forward-return tracking.

The feedback loop for the whole system: for every signal Claude fires, we
measure what the stock actually did 1 week / 1 month / 3 months later, and
what the SPUS halal-index benchmark did over the same window. Without this
there is no way to know whether the signals — or their confidence scores —
beat simply holding the index.

Updated by the nightly job (scheduler/jobs.py) and exposed via
GET /api/performance/summary.
"""

import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from sqlalchemy.orm import Session

from db.models import Signal, SignalPerformance

logger = logging.getLogger(__name__)

ALPACA_KEY      = os.environ.get("ALPACA_KEY", "")
ALPACA_SECRET   = os.environ.get("ALPACA_SECRET", "")
ALPACA_DATA_URL = "https://data.alpaca.markets"

BENCHMARK = "SPUS"   # SP Funds S&P 500 Sharia ETF

HORIZONS = {          # label -> calendar days
    "1w": 7,
    "1m": 30,
    "3m": 90,
}

# Per-run bar cache: symbol -> list[(date, close)] sorted ascending
_bar_cache: dict[str, list[tuple[str, float]]] = {}


# ── Price data ────────────────────────────────────────────────────────────────

def _fetch_daily_closes(symbol: str, start: datetime) -> list[tuple[str, float]]:
    """
    Daily closes from `start` to now as [(YYYY-MM-DD, close), ...] ascending.
    Cached per run. Empty list on failure.
    """
    if symbol in _bar_cache:
        return _bar_cache[symbol]
    try:
        resp = httpx.get(
            f"{ALPACA_DATA_URL}/v2/stocks/{symbol}/bars",
            params={
                "timeframe": "1Day",
                "start":     start.strftime("%Y-%m-%dT00:00:00Z"),
                "limit":     10000,
                "feed":      "iex",
            },
            headers={
                "APCA-API-KEY-ID":     ALPACA_KEY,
                "APCA-API-SECRET-KEY": ALPACA_SECRET,
            },
            timeout=15,
        )
        resp.raise_for_status()
        bars = resp.json().get("bars") or []
        closes = [(b["t"][:10], float(b["c"])) for b in bars if b.get("c")]
        closes.sort(key=lambda x: x[0])
        _bar_cache[symbol] = closes
        return closes
    except Exception as e:
        logger.warning(f"Bar fetch failed for {symbol}: {e}")
        _bar_cache[symbol] = []
        return []


def _close_on_or_after(closes: list[tuple[str, float]], target_date: str) -> Optional[float]:
    """First trading-day close on or after target_date (YYYY-MM-DD)."""
    for d, c in closes:
        if d >= target_date:
            return c
    return None


def _pct_return(entry: float, exit_: Optional[float]) -> Optional[float]:
    if exit_ is None or entry <= 0:
        return None
    return round((exit_ - entry) / entry * 100.0, 4)


# ── Core updater ──────────────────────────────────────────────────────────────

def update_signal_performance(db: Session, lookback_days: int = 120) -> dict:
    """
    Fill in forward returns for signals whose horizons have become measurable.

    Idempotent — safe to run nightly. Only touches signals with a price_at,
    triggered within `lookback_days` (older ones are already final).
    """
    _bar_cache.clear()
    now    = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=lookback_days)

    signals = (
        db.query(Signal)
        .filter(
            Signal.price_at.isnot(None),
            Signal.triggered_at >= cutoff,
            # Need at least the 1-week horizon to have anything to measure
            Signal.triggered_at <= now - timedelta(days=HORIZONS["1w"]),
        )
        .all()
    )

    updated = skipped = 0
    for sig in signals:
        perf = (
            db.query(SignalPerformance)
            .filter(SignalPerformance.signal_id == sig.id)
            .first()
        )
        # Fully measured already? Nothing to do.
        if perf and perf.return_3m is not None:
            skipped += 1
            continue

        entry = float(sig.price_at)
        if entry <= 0:
            skipped += 1
            continue

        trig = sig.triggered_at
        if trig.tzinfo is None:
            trig = trig.replace(tzinfo=timezone.utc)

        closes       = _fetch_daily_closes(sig.symbol, trig)
        bench_closes = _fetch_daily_closes(BENCHMARK, trig)
        if not closes:
            skipped += 1
            continue

        bench_entry = _close_on_or_after(bench_closes, trig.strftime("%Y-%m-%d"))

        if not perf:
            perf = SignalPerformance(
                signal_id    = sig.id,
                symbol       = sig.symbol,
                signal_type  = sig.signal_type,
                confidence   = sig.confidence,
                price_at     = sig.price_at,
                triggered_at = sig.triggered_at,
            )
            db.add(perf)

        changed = False
        for label, days in HORIZONS.items():
            horizon_date = trig + timedelta(days=days)
            if horizon_date > now:
                continue   # not measurable yet
            if getattr(perf, f"return_{label}") is not None:
                continue   # already recorded
            target = horizon_date.strftime("%Y-%m-%d")
            ret = _pct_return(entry, _close_on_or_after(closes, target))
            if ret is not None:
                setattr(perf, f"return_{label}", ret)
                changed = True
            if bench_entry:
                bench_ret = _pct_return(bench_entry, _close_on_or_after(bench_closes, target))
                if bench_ret is not None:
                    setattr(perf, f"bench_return_{label}", bench_ret)

        if changed:
            updated += 1

    db.commit()
    logger.info(f"Signal performance update: {updated} updated, {skipped} skipped, {len(signals)} eligible")
    return {"eligible": len(signals), "updated": updated, "skipped": skipped}


# ── Aggregation for the dashboard ─────────────────────────────────────────────

def _confidence_bucket(conf: Optional[float]) -> str:
    if conf is None:
        return "unscored"
    if conf >= 0.85:
        return ">=0.85"
    if conf >= 0.75:
        return "0.75-0.85"
    if conf >= 0.65:
        return "0.65-0.75"
    return "<0.65"


def performance_summary(db: Session) -> dict:
    """
    Aggregate hit-rates and average returns by signal type and confidence
    bucket, per horizon, with alpha vs the SPUS benchmark.
    """
    rows = db.query(SignalPerformance).all()

    def _aggregate(group_rows: list) -> dict:
        out = {}
        for label in HORIZONS:
            rets    = [float(getattr(r, f"return_{label}")) for r in group_rows
                       if getattr(r, f"return_{label}") is not None]
            alphas  = [
                float(getattr(r, f"return_{label}")) - float(getattr(r, f"bench_return_{label}"))
                for r in group_rows
                if getattr(r, f"return_{label}") is not None
                and getattr(r, f"bench_return_{label}") is not None
            ]
            if not rets:
                out[label] = None
                continue
            out[label] = {
                "n":          len(rets),
                "avg_return": round(sum(rets) / len(rets), 2),
                "win_rate":   round(sum(1 for r in rets if r > 0) / len(rets) * 100, 1),
                "avg_alpha":  round(sum(alphas) / len(alphas), 2) if alphas else None,
            }
        return out

    by_type: dict[str, list] = {}
    by_bucket: dict[str, list] = {}
    for r in rows:
        by_type.setdefault(r.signal_type, []).append(r)
        by_bucket.setdefault(_confidence_bucket(float(r.confidence) if r.confidence else None), []).append(r)

    return {
        "total_tracked": len(rows),
        "benchmark":     BENCHMARK,
        "overall":       _aggregate(rows),
        "by_type":       {k: _aggregate(v) for k, v in sorted(by_type.items())},
        "by_confidence": {k: _aggregate(v) for k, v in sorted(by_bucket.items())},
    }


def recent_performance(db: Session, limit: int = 50) -> list[dict]:
    """Most recent tracked signals with their forward returns."""
    rows = (
        db.query(SignalPerformance)
        .order_by(SignalPerformance.triggered_at.desc())
        .limit(limit)
        .all()
    )
    def _f(v):
        return float(v) if v is not None else None
    return [
        {
            "symbol":       r.symbol,
            "type":         r.signal_type,
            "confidence":   _f(r.confidence),
            "price_at":     _f(r.price_at),
            "triggered_at": r.triggered_at.isoformat(),
            "return_1w":    _f(r.return_1w),
            "return_1m":    _f(r.return_1m),
            "return_3m":    _f(r.return_3m),
            "alpha_1m":     round(_f(r.return_1m) - _f(r.bench_return_1m), 2)
                            if r.return_1m is not None and r.bench_return_1m is not None else None,
        }
        for r in rows
    ]
