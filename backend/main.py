"""
main.py — FastAPI backend entry point.

Routes:
  GET  /health                    — health check
  GET  /api/watchlist             — list watchlist
  POST /api/watchlist             — add symbol
  DELETE /api/watchlist/{symbol}  — remove symbol
  GET  /api/screen/{symbol}       — halal screen result
  GET  /api/signals               — today's signals
  GET  /api/portfolio             — current Alpaca positions
  GET  /api/reports               — daily reports
  GET  /api/reports/{date}        — specific day's report
  POST /api/scheduler/run         — manually trigger morning job
  GET  /api/tax/summary           — tax summary for a year
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone, date
from typing import Optional

import requests
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session, sessionmaker

from db.models import (
    get_engine, create_tables,
    WatchlistItem, Signal, DailyReport, Trade,
    HalalStatus, HalalScreenResult,
)
import halal_screen as halal_module
import claude as claude_module

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ── Config ─────────────────────────────────────────────────────────────────────

ALPACA_KEY      = os.environ.get("ALPACA_KEY", "")
ALPACA_SECRET   = os.environ.get("ALPACA_SECRET", "")
ALPACA_BASE_URL = os.environ.get("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

ALLOWED_ORIGINS = os.environ.get(
    "ALLOWED_ORIGINS",
    "http://localhost:3000"   # overridden in Railway via env var
).split(",")


# ── Database ────────────────────────────────────────────────────────────────────

engine = get_engine()
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── App lifecycle ───────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run on startup — ensure tables exist."""
    logger.info("Starting Halal Trader API...")
    create_tables()
    logger.info("Database tables ready.")
    yield
    logger.info("Halal Trader API shutting down.")


# ── App ──────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Halal Trader API",
    version="0.1.0",
    description="AI-powered halal stock research and passive trading backend.",
    lifespan=lifespan,
    docs_url="/docs",   # disable in production: docs_url=None
    redoc_url=None,
)

# CORS — locked to your frontend domain
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "PATCH"],
    allow_headers=["*"],
)


# ── Pydantic schemas ─────────────────────────────────────────────────────────

class WatchlistAddRequest(BaseModel):
    symbol: str
    notes: Optional[str] = None

    @field_validator("symbol")
    @classmethod
    def symbol_upper(cls, v: str) -> str:
        return v.upper().strip()


class HealthResponse(BaseModel):
    status: str
    timestamp: str
    alpaca_mode: str


# ── Auth placeholder ─────────────────────────────────────────────────────────
# TODO: Replace with Clerk JWT verification middleware
# For now, a simple API key check gates all /api/ routes

def verify_api_key(
    # In production this will be: token: str = Depends(clerk_auth)
    # For now just accept all requests from the same-origin frontend
):
    pass  # Replace with real auth before going live


# ── Routes ───────────────────────────────────────────────────────────────────

@app.get("/health", response_model=HealthResponse, tags=["system"])
def health_check():
    """Healthcheck endpoint — used by Railway to verify the service is up."""
    return {
        "status":      "ok",
        "timestamp":   datetime.now(timezone.utc).isoformat(),
        "alpaca_mode": "paper" if "paper" in ALPACA_BASE_URL else "live",
    }


# ── Watchlist ─────────────────────────────────────────────────────────────────

@app.get("/api/watchlist", tags=["watchlist"])
def get_watchlist(db: Session = Depends(get_db)):
    """Return all active watchlist items."""
    items = db.query(WatchlistItem).filter(WatchlistItem.is_active == True).all()
    return [
        {
            "id":       str(item.id),
            "symbol":   item.symbol,
            "notes":    item.notes,
            "added_at": item.added_at.isoformat(),
        }
        for item in items
    ]


@app.post("/api/watchlist", status_code=status.HTTP_201_CREATED, tags=["watchlist"])
def add_to_watchlist(
    body: WatchlistAddRequest,
    db:   Session = Depends(get_db),
):
    """Add a symbol to the watchlist and run an immediate halal screen."""
    # Check for duplicate
    existing = (
        db.query(WatchlistItem)
        .filter(
            WatchlistItem.symbol == body.symbol,
            WatchlistItem.is_active == True,
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{body.symbol} is already on your watchlist.",
        )

    # Run halal screen before adding
    screen = halal_module.screen_stock(body.symbol, db)
    if screen["final_status"] == HalalStatus.NON_COMPLIANT:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{body.symbol} is not Shariah-compliant and cannot be added. "
                   f"Reason: {screen.get('notes', 'Non-compliant per Zoya screen')}",
        )

    item = WatchlistItem(
        symbol  = body.symbol,
        notes   = body.notes,
        # user_id will come from Clerk JWT once auth is wired
        # hard-coded temporarily for single-user setup
        user_id = _get_default_user_id(db),
    )
    db.add(item)
    db.commit()
    db.refresh(item)

    return {
        "id":           str(item.id),
        "symbol":       item.symbol,
        "halal_status": str(screen["final_status"]),
        "notes":        item.notes,
        "added_at":     item.added_at.isoformat(),
    }


@app.delete("/api/watchlist/{symbol}", tags=["watchlist"])
def remove_from_watchlist(symbol: str, db: Session = Depends(get_db)):
    """Soft-delete a symbol from the watchlist."""
    item = (
        db.query(WatchlistItem)
        .filter(
            WatchlistItem.symbol   == symbol.upper(),
            WatchlistItem.is_active == True,
        )
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail=f"{symbol} not found in watchlist.")
    item.is_active = False
    db.commit()
    return {"message": f"{symbol} removed from watchlist."}


# ── Halal screening ───────────────────────────────────────────────────────────

@app.get("/api/screen/{symbol}", tags=["halal"])
def screen_symbol(
    symbol:        str,
    force_refresh: bool = False,
    db:            Session = Depends(get_db),
):
    """Run (or return cached) halal screen for a symbol."""
    result = halal_module.screen_stock(symbol.upper(), db, force_refresh=force_refresh)
    return result


# ── Signals ───────────────────────────────────────────────────────────────────

@app.get("/api/signals", tags=["signals"])
def get_signals(
    days: int = 7,
    db:   Session = Depends(get_db),
):
    """Return Claude-generated signals from the last N days."""
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    signals = (
        db.query(Signal)
        .filter(Signal.triggered_at >= cutoff)
        .order_by(Signal.triggered_at.desc())
        .limit(100)
        .all()
    )
    return [
        {
            "id":           str(s.id),
            "symbol":       s.symbol,
            "type":         s.signal_type,
            "confidence":   float(s.confidence) if s.confidence else None,
            "reasoning":    s.reasoning,
            "price_at":     float(s.price_at) if s.price_at else None,
            "triggered_at": s.triggered_at.isoformat(),
            "acted_on":     s.acted_on,
        }
        for s in signals
    ]


# ── Portfolio ──────────────────────────────────────────────────────────────────

@app.get("/api/portfolio", tags=["portfolio"])
def get_portfolio():
    """Return current Alpaca positions."""
    try:
        resp = requests.get(
            f"{ALPACA_BASE_URL}/v2/positions",
            headers={
                "APCA-API-KEY-ID":     ALPACA_KEY,
                "APCA-API-SECRET-KEY": ALPACA_SECRET,
            },
            timeout=10,
        )
        resp.raise_for_status()
        positions = resp.json()
        return {
            "positions":  positions,
            "count":      len(positions),
            "alpaca_mode": "paper" if "paper" in ALPACA_BASE_URL else "live",
        }
    except Exception as e:
        logger.error(f"Failed to fetch Alpaca positions: {e}")
        raise HTTPException(status_code=503, detail="Could not reach Alpaca API.")


# ── Daily reports ─────────────────────────────────────────────────────────────

@app.get("/api/reports", tags=["reports"])
def list_reports(limit: int = 30, db: Session = Depends(get_db)):
    """Return the most recent daily reports."""
    reports = (
        db.query(DailyReport)
        .order_by(DailyReport.report_date.desc())
        .limit(limit)
        .all()
    )
    return [_report_to_dict(r) for r in reports]


@app.get("/api/reports/{report_date}", tags=["reports"])
def get_report(report_date: str, db: Session = Depends(get_db)):
    """Return a specific day's report by date (YYYY-MM-DD)."""
    try:
        target = datetime.strptime(report_date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Date must be YYYY-MM-DD format.")

    report = (
        db.query(DailyReport)
        .filter(DailyReport.report_date >= datetime(target.year, target.month, target.day))
        .order_by(DailyReport.report_date)
        .first()
    )
    if not report:
        raise HTTPException(status_code=404, detail=f"No report found for {report_date}.")
    return _report_to_dict(report)


def _report_to_dict(r: DailyReport) -> dict:
    return {
        "id":               str(r.id),
        "report_date":      r.report_date.strftime("%Y-%m-%d"),
        "stocks_screened":  r.stocks_screened,
        "halal_passed":     r.halal_passed,
        "signals_fired":    r.signals_fired,
        "trades_executed":  r.trades_executed,
        "alerts_sent":      r.alerts_sent,
        "summary":          r.summary,
    }


# ── Tax ───────────────────────────────────────────────────────────────────────

@app.get("/api/tax/summary", tags=["tax"])
def get_tax_summary(
    year: int = datetime.now().year,
    db:   Session = Depends(get_db),
):
    """Generate a tax summary for the given year using Claude."""
    # Fetch closed trades for the year
    year_start = datetime(year, 1, 1, tzinfo=timezone.utc)
    year_end   = datetime(year, 12, 31, 23, 59, 59, tzinfo=timezone.utc)

    trades = (
        db.query(Trade)
        .filter(
            Trade.traded_at >= year_start,
            Trade.traded_at <= year_end,
        )
        .order_by(Trade.traded_at)
        .all()
    )

    trades_data = [
        {
            "symbol":      t.symbol,
            "side":        str(t.side),
            "quantity":    float(t.quantity),
            "price":       float(t.price),
            "total_value": float(t.total_value),
            "traded_at":   t.traded_at.isoformat(),
        }
        for t in trades
    ]

    # Current positions as potential harvesting opportunities
    try:
        resp = requests.get(
            f"{ALPACA_BASE_URL}/v2/positions",
            headers={
                "APCA-API-KEY-ID":     ALPACA_KEY,
                "APCA-API-SECRET-KEY": ALPACA_SECRET,
            },
            timeout=10,
        )
        current_positions = resp.json() if resp.ok else []
    except Exception:
        current_positions = []

    summary = claude_module.generate_tax_summary(trades_data, current_positions, year)
    return {"year": year, "trade_count": len(trades_data), "summary": summary}


# ── Manual scheduler trigger ──────────────────────────────────────────────────

@app.post("/api/scheduler/run", tags=["system"])
def trigger_morning_job():
    """
    Manually trigger the morning job — useful for testing.
    Protected: only call from dashboard, never expose publicly.
    """
    import threading
    from scheduler.jobs import morning_job

    def run_in_thread():
        morning_job()

    thread = threading.Thread(target=run_in_thread, daemon=True)
    thread.start()
    return {"message": "Morning job triggered in background. Check Telegram for updates."}


# ── Utility ───────────────────────────────────────────────────────────────────
# ── One-time setup ────────────────────────────────────────────────────────────

class SetupRequest(BaseModel):
    email: str
    clerk_id: str = "local-dev-user"


@app.post("/api/setup", tags=["system"])
def setup_first_user(body: SetupRequest, db: Session = Depends(get_db)):
    """
    Create the initial user record. Run once after first deploy.
    Remove or protect this endpoint after setup is complete.
    """
    from db.models import User
    existing = db.query(User).filter(User.email == body.email).first()
    if existing:
        return {"message": "User already exists.", "user_id": str(existing.id)}

    user = User(email=body.email, clerk_id=body.clerk_id)
    db.add(user)
    db.commit()
    db.refresh(user)
    return {
        "message": "User created successfully.",
        "user_id": str(user.id),
        "email":   user.email,
    }

def _get_default_user_id(db: Session):
    """
    Return the first user's ID.
    Replace with Clerk JWT extraction once auth middleware is in place.
    """
    from db.models import User
    user = db.query(User).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No user found. Please complete onboarding.",
        )
    return user.id

@app.delete("/api/screen/cache/{symbol}", tags=["halal"])
def clear_halal_cache(symbol: str, db: Session = Depends(get_db)):
    """Delete cached halal screen result for a symbol — forces fresh screen next call."""
    from datetime import timezone
    deleted = (
        db.query(HalalScreenResult)
        .filter(HalalScreenResult.symbol == symbol.upper())
        .delete()
    )
    db.commit()
    return {"message": f"Cleared {deleted} cache entries for {symbol.upper()}"}
