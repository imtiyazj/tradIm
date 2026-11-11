"""
Tests for the quarterly compliance review and purification ledger.

Runs against a throwaway SQLite file — never a real database — with the
halal screen, Alpaca, and Telegram stubbed out.

    cd backend && python -m pytest tests/
"""

import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from decimal import Decimal

# Must be set before any backend module is imported.
_TMP = tempfile.mkdtemp(prefix="tradim-test-")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP}/test.db"
os.environ.pop("CLERK_ISSUER", None)
os.environ["TELEGRAM_BOT_TOKEN"] = ""
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from sqlalchemy.orm import sessionmaker

from db.models import (
    Base, User, WatchlistItem, HalalStatus, HalalScreenResult,
    ComplianceCheck, PurificationEntry, AlertLog, get_engine,
)
import compliance
import halal_screen

engine = get_engine()
Session = sessionmaker(bind=engine)

C, NC, D, U = (
    HalalStatus.COMPLIANT, HalalStatus.NON_COMPLIANT,
    HalalStatus.DOUBTFUL, HalalStatus.UNKNOWN,
)


def _screen(status, haram=None, **extra):
    result = {
        "final_status": status, "zoya_status": status, "debt_ratio": 0.1,
        "haram_revenue_pct": haram, "notes": f"stub {status.value}",
    }
    result.update(extra)
    return result


@pytest.fixture()
def db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture()
def user(db):
    u = User(email="test@example.com", clerk_id="user_test")
    db.add(u)
    db.commit()
    return u


@pytest.fixture()
def screens(monkeypatch):
    """Stub halal_screen.screen_stock; tests fill in {symbol: result | Exception}."""
    table = {}

    def fake(symbol, db, force_refresh=False):
        result = table[symbol]
        if isinstance(result, Exception):
            raise result
        return dict(result, symbol=symbol)

    monkeypatch.setattr(halal_screen, "screen_stock", fake)
    return table


def _watch(db, user, *symbols):
    for s in symbols:
        db.add(WatchlistItem(user_id=user.id, symbol=s))
    db.commit()


def _cached(db, symbol, status):
    db.add(HalalScreenResult(
        symbol=symbol, zoya_status=status, final_status=status,
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    ))
    db.commit()


def _pos(symbol, qty="10", value="1500.00"):
    return {"symbol": symbol, "qty": qty, "market_value": value, "asset_class": "us_equity"}


# ── Compliance review ─────────────────────────────────────────────────────────

def test_quarter_label():
    assert compliance.quarter_label(datetime(2026, 3, 1)) == "2026-Q1"
    assert compliance.quarter_label(datetime(2026, 12, 7)) == "2026-Q4"


def test_review_flags_holding_that_became_non_compliant(db, user, screens):
    _watch(db, user, "MSFT", "AAPL")
    _cached(db, "AAPL", C)
    _cached(db, "MSFT", C)
    screens.update({"AAPL": _screen(NC), "MSFT": _screen(C), "NEW": _screen(C)})

    result = compliance.run_compliance_review(
        db, user.id, positions=[_pos("AAPL"), _pos("NEW", "2", "50")],
        now=datetime(2026, 12, 1, tzinfo=timezone.utc),
    )

    assert result["period"] == "2026-Q4"
    assert result["checked"] == 3 and result["held"] == 2
    rows = {r["symbol"]: r for r in result["rows"]}

    assert rows["AAPL"]["status_changed"] and rows["AAPL"]["previous_status"] == "compliant"
    assert rows["AAPL"]["quantity"] == 10 and rows["AAPL"]["market_value"] == 1500
    assert [r["symbol"] for r in result["action_required"]] == ["AAPL"]
    assert [r["symbol"] for r in result["changed"]] == ["AAPL"]

    # Watchlist-only, unchanged
    assert not rows["MSFT"]["is_held"] and not rows["MSFT"]["status_changed"]
    # Held, never screened before: no previous status, so not a "change"
    assert rows["NEW"]["previous_status"] is None and not rows["NEW"]["status_changed"]

    assert db.query(ComplianceCheck).count() == 3


def test_non_compliant_holding_is_reported_every_review_until_sold(db, user, screens):
    screens["AAPL"] = _screen(NC)
    for month in (9, 12):
        result = compliance.run_compliance_review(
            db, user.id, positions=[_pos("AAPL")],
            now=datetime(2026, month, 1, tzinfo=timezone.utc),
        )
    assert not result["changed"]                       # NC -> NC
    assert [r["symbol"] for r in result["action_required"]] == ["AAPL"]


def test_zoya_outage_is_inconclusive_not_a_status_change(db, user, screens):
    _cached(db, "AAPL", C)
    screens["AAPL"] = _screen(D, zoya_unavailable=True)

    result = compliance.run_compliance_review(db, user.id, positions=[_pos("AAPL")])

    assert result["inconclusive"] == ["AAPL"]
    assert not result["changed"] and not result["review"] and not result["action_required"]
    # A run with nothing conclusive must not mark the quarter as done
    assert not compliance.period_already_reviewed(db, result["period"])


def test_next_review_compares_against_last_conclusive_review(db, user, screens):
    screens["AAPL"] = _screen(C)
    compliance.run_compliance_review(db, user.id, positions=[_pos("AAPL")],
                                     now=datetime(2026, 3, 1, tzinfo=timezone.utc))
    screens["AAPL"] = _screen(U)                        # inconclusive quarter
    compliance.run_compliance_review(db, user.id, positions=[_pos("AAPL")],
                                     now=datetime(2026, 6, 1, tzinfo=timezone.utc))
    screens["AAPL"] = _screen(D)
    result = compliance.run_compliance_review(db, user.id, positions=[_pos("AAPL")],
                                              now=datetime(2026, 9, 1, tzinfo=timezone.utc))

    row = result["rows"][0]
    assert row["previous_status"] == "compliant" and row["new_status"] == "doubtful"
    assert row["status_changed"]
    assert [r["symbol"] for r in result["review"]] == ["AAPL"]
    assert compliance.period_already_reviewed(db, "2026-Q3")
    assert len(compliance.recent_changes(db)) == 1


def test_screen_exception_does_not_lose_earlier_rows(db, user, screens):
    screens.update({"AAPL": _screen(C), "BAD": RuntimeError("boom"), "MSFT": _screen(C)})

    result = compliance.run_compliance_review(
        db, user.id, positions=[_pos("AAPL"), _pos("BAD"), _pos("MSFT")],
    )

    assert result["checked"] == 3 and result["inconclusive"] == ["BAD"]
    assert db.query(ComplianceCheck).count() == 3
    assert "boom" in {r["symbol"]: r for r in result["rows"]}["BAD"]["notes"]


def test_alpaca_failure_is_not_treated_as_empty_portfolio(db, user, screens, monkeypatch):
    _watch(db, user, "MSFT")
    screens["MSFT"] = _screen(C)
    monkeypatch.setattr(compliance, "fetch_positions", lambda: None)

    result = compliance.run_compliance_review(db, user.id)

    assert result["positions_unavailable"] is True and result["checked"] == 1


def test_latest_review_returns_only_the_last_run(db, user, screens):
    screens.update({"AAPL": _screen(C), "MSFT": _screen(C)})
    compliance.run_compliance_review(db, user.id, positions=[_pos("AAPL"), _pos("MSFT")],
                                     now=datetime(2026, 3, 1, tzinfo=timezone.utc))
    compliance.run_compliance_review(db, user.id, positions=[_pos("AAPL")],
                                     now=datetime(2026, 6, 1, tzinfo=timezone.utc))

    latest = compliance.latest_review(db)
    assert latest["period"] == "2026-Q2" and latest["checked"] == 1


# ── Purification ──────────────────────────────────────────────────────────────

def _div(activity_id, symbol, amount, date="2026-10-15"):
    return {"id": activity_id, "activity_type": "DIV", "symbol": symbol,
            "net_amount": amount, "date": date}


def test_sync_dividends_computes_purification_and_is_idempotent(db, user, screens):
    screens.update({
        "AAPL": _screen(C, haram=0.02),     # 2% impure
        "MSFT": _screen(C, haram=0.0),      # genuinely 0% — must not fall back to the cap
        "TSLA": _screen(C, haram=None),     # unknown -> 5% ceiling
        "KO":   _screen(C, haram=3.5),      # percent-style value -> 3.5%
    })
    activities = [
        _div("a1", "AAPL", "100.00"),
        _div("a2", "MSFT", "50.00"),
        _div("a3", "TSLA", "20.00"),
        _div("a4", "KO",   "10.00"),
        _div("a5", "AAPL", "-5.00"),        # reversal — skipped
    ]

    first = compliance.sync_dividends(db, user.id, activities=activities)
    again = compliance.sync_dividends(db, user.id, activities=activities)

    assert first["added"] == 4 and first["skipped"] == 1
    assert again["added"] == 0
    entries = {e.symbol: e for e in db.query(PurificationEntry).all()}
    assert len(entries) == 4
    assert entries["AAPL"].purification_amount == Decimal("2.0000")
    assert entries["AAPL"].rate_source == "screen"
    assert entries["MSFT"].purification_amount == Decimal("0") and entries["MSFT"].rate_source == "screen"
    assert entries["TSLA"].purification_amount == Decimal("1.0000")
    assert entries["TSLA"].rate_source == "default_cap" and "5%" in entries["TSLA"].note
    assert entries["KO"].purification_amount == Decimal("0.3500")
    assert first["new_purification"] == pytest.approx(3.35)


def test_non_compliant_dividend_is_flagged_for_scholar_review(db, user, screens):
    screens["XYZ"] = _screen(NC, haram=None)
    compliance.sync_dividends(db, user.id, activities=[_div("x1", "XYZ", "40.00")])
    entry = db.query(PurificationEntry).one()
    assert "non-compliant" in entry.note


def test_sync_reports_alpaca_failure(db, user, monkeypatch):
    monkeypatch.setattr(compliance, "fetch_dividend_activities", lambda after=None: None)
    result = compliance.sync_dividends(db, user.id)
    assert result["error"] and result["added"] == 0


def test_summary_and_paid_tracking(db, user, screens):
    screens.update({"AAPL": _screen(C, haram=0.02), "TSLA": _screen(C, haram=None)})
    compliance.sync_dividends(db, user.id, activities=[
        _div("a1", "AAPL", "100.00", "2025-11-01"),
        _div("a2", "AAPL", "100.00", "2026-02-01"),
        _div("a3", "TSLA", "20.00",  "2026-05-01"),
    ])

    summary = compliance.purification_summary(db)
    assert summary["total_dividends"] == 220 and summary["total_owed"] == 5
    assert summary["outstanding"] == 5 and summary["estimated_count"] == 1
    assert [y["year"] for y in summary["by_year"]] == [2026, 2025]
    assert summary["entries"][0]["symbol"] == "TSLA"       # newest first

    entry_id = summary["entries"][0]["id"]
    paid = compliance.set_entry_paid(db, entry_id, True)
    assert paid["is_paid"] and paid["paid_at"]
    assert compliance.purification_summary(db)["outstanding"] == 4

    assert compliance.set_entry_paid(db, entry_id, False)["paid_at"] is None
    assert compliance.set_entry_paid(db, "not-a-uuid", True) is None

    assert compliance.mark_all_paid(db) == {"marked": 3, "amount": 5.0}
    assert compliance.purification_summary(db)["outstanding"] == 0


def test_paper_entries_are_hidden_in_live_mode(db, user, screens, monkeypatch):
    screens["AAPL"] = _screen(C, haram=0.02)
    compliance.sync_dividends(db, user.id, activities=[_div("a1", "AAPL", "100.00")])
    monkeypatch.setattr(compliance, "ALPACA_BASE_URL", "https://api.alpaca.markets")
    assert compliance.purification_summary(db)["entries"] == []


def test_cached_screen_preserves_zero_ratio(db):
    """Regression: a cached 0% haram share used to come back as None."""
    db.add(HalalScreenResult(
        symbol="ZERO", zoya_status=C, final_status=C, haram_revenue_pct=Decimal("0"),
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    ))
    db.commit()
    assert halal_screen.screen_stock("ZERO", db)["haram_revenue_pct"] == 0.0


# ── Scheduled job ─────────────────────────────────────────────────────────────

@pytest.fixture()
def jobs(monkeypatch):
    from scheduler import jobs as jobs_module
    sent = []
    monkeypatch.setattr(jobs_module, "send_telegram", lambda msg: sent.append(msg) or True)
    jobs_module.sent = sent
    return jobs_module


def test_quarterly_job_alerts_once_per_quarter(db, user, screens, jobs, monkeypatch):
    _cached(db, "AAPL", C)
    screens["AAPL"] = _screen(NC, haram=None)
    monkeypatch.setattr(compliance, "fetch_positions", lambda: [_pos("AAPL")])
    monkeypatch.setattr(compliance, "fetch_dividend_activities",
                        lambda after=None: [_div("a1", "AAPL", "100.00")])

    jobs.quarterly_compliance_job()

    assert len(jobs.sent) == 2
    assert "AAPL is NON-COMPLIANT (was compliant)" in jobs.sent[0]
    assert "Nothing was sold automatically" in jobs.sent[0]
    assert "Action required: 1" in jobs.sent[1] and "$5.00 outstanding" in jobs.sent[1]
    db.expire_all()
    assert db.query(AlertLog).count() == 2

    jobs.quarterly_compliance_job()                      # retry day: already reviewed
    assert len(jobs.sent) == 2 and db.query(ComplianceCheck).count() == 1

    jobs.quarterly_compliance_job(force=True)            # manual run always runs
    assert db.query(ComplianceCheck).count() == 2


def test_quarterly_job_waits_when_alpaca_is_down(db, user, screens, jobs, monkeypatch):
    monkeypatch.setattr(compliance, "fetch_positions", lambda: None)
    jobs.quarterly_compliance_job()
    assert jobs.sent == [] and db.query(ComplianceCheck).count() == 0


def test_weekly_purification_job_only_messages_on_new_dividends(db, user, screens, jobs, monkeypatch):
    screens["AAPL"] = _screen(C, haram=0.02)
    monkeypatch.setattr(compliance, "fetch_dividend_activities",
                        lambda after=None: [_div("a1", "AAPL", "100.00")])
    jobs.purification_sync_job()
    jobs.purification_sync_job()
    assert len(jobs.sent) == 1 and "$2.00 to purify" in jobs.sent[0]


# ── API ───────────────────────────────────────────────────────────────────────

@pytest.fixture()
def client(db):
    from fastapi.testclient import TestClient
    import main
    return TestClient(main.app)      # no context manager: lifespan/scheduler not started


def test_api_endpoints(db, user, screens, client, monkeypatch):
    assert client.get("/api/compliance/latest").json() == {"review": None, "changes": []}

    screens["AAPL"] = _screen(C, haram=0.02)
    compliance.run_compliance_review(db, user.id, positions=[_pos("AAPL")])
    body = client.get("/api/compliance/latest").json()
    assert body["review"]["checked"] == 1 and body["review"]["rows"][0]["symbol"] == "AAPL"

    monkeypatch.setattr(compliance, "fetch_dividend_activities",
                        lambda after=None: [_div("a1", "AAPL", "100.00")])
    assert client.post("/api/purification/sync").json()["added"] == 1

    ledger = client.get("/api/purification").json()
    assert ledger["outstanding"] == 2
    entry_id = ledger["entries"][0]["id"]

    assert client.patch(f"/api/purification/{entry_id}", json={"is_paid": True}).json()["is_paid"]
    assert client.get("/api/purification").json()["outstanding"] == 0
    assert client.patch("/api/purification/nope", json={"is_paid": True}).status_code == 404
    assert client.post("/api/purification/mark-all-paid").json()["marked"] == 0

    monkeypatch.setattr(compliance, "fetch_dividend_activities", lambda after=None: None)
    assert client.post("/api/purification/sync").status_code == 503
