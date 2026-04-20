"""
main.py — FastAPI backend entry point.
"""

import sys
import os

# Ensure the app root is always on the Python path
# This fixes Railway's module resolution regardless of how uvicorn is invoked
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

import requests
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session, sessionmaker

from db.models import (
    get_engine, create_tables,
    WatchlistItem, Signal, DailyReport, Trade,
    HalalStatus,
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
    "http://localhost:3000"
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
    logger.info("Starting Halal Trader API...")
    create_tables()
    logger.info("Database tables ready.")

    # Start the background scheduler (cron jobs)
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    from scheduler.jobs import morning_job, weekly_refresh_halal_cache

    scheduler = BackgroundScheduler(timezone="America/New_York")
    scheduler.add_job(
        morning_job,
        trigger=CronTrigger(day_of_week="mon-fri", hour=8, minute=0, timezone="America/New_York"),
        id="morning_job",
        name="Daily morning analysis",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        weekly_refresh_halal_cache,
        trigger=CronTrigger(day_of_week="sun", hour=6, minute=0, timezone="America/New_York"),
        id="halal_cache_refresh",
        name="Weekly halal cache refresh",
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    logger.info("Background scheduler started.")
    for job in scheduler.get_jobs():
        logger.info(f"  Scheduled: {job.name} — next run: {job.next_run_time}")

    yield

    scheduler.shutdown(wait=False)
    logger.info("Halal Trader API shutting down.")


# ── App ──────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Halal Trader API",
    version="0.1.0",
    description="AI-powered halal stock research and passive trading backend.",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "PATCH"],
    allow_headers=["*"],
)


# ── Pydantic schemas ──────────────────────────────────────────────────────────

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


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health", response_model=HealthResponse, tags=["system"])
def health_check():
    return {
        "status":      "ok",
        "timestamp":   datetime.now(timezone.utc).isoformat(),
        "alpaca_mode": "paper" if "paper" in ALPACA_BASE_URL else "live",
    }


# ── Watchlist ─────────────────────────────────────────────────────────────────

@app.get("/api/watchlist", tags=["watchlist"])
def get_watchlist(db: Session = Depends(get_db)):
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
    existing = (
        db.query(WatchlistItem)
        .filter(
            WatchlistItem.symbol    == body.symbol,
            WatchlistItem.is_active == True,
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{body.symbol} is already on your watchlist.",
        )

    screen = halal_module.screen_stock(body.symbol, db)
    if screen["final_status"] == HalalStatus.NON_COMPLIANT:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{body.symbol} is not Shariah-compliant. "
                   f"Reason: {screen.get('notes', 'Non-compliant per Zoya screen')}",
        )

    item = WatchlistItem(
        symbol  = body.symbol,
        notes   = body.notes,
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
    item = (
        db.query(WatchlistItem)
        .filter(
            WatchlistItem.symbol    == symbol.upper(),
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
    return halal_module.screen_stock(symbol.upper(), db, force_refresh=force_refresh)


@app.delete("/api/screen/cache", tags=["halal"])
def clear_halal_cache(status_filter: str = "doubtful,unknown", db: Session = Depends(get_db)):
    """
    Delete cached halal screen results for DOUBTFUL/UNKNOWN stocks so they get re-screened.
    Useful after fixing screening logic. Pass status_filter=all to wipe everything.
    """
    from db.models import HalalScreenResult
    statuses = [s.strip().upper() for s in status_filter.split(",")]
    query = db.query(HalalScreenResult)
    if "ALL" not in statuses:
        query = query.filter(
            HalalScreenResult.final_status.in_(statuses)
        )
    deleted = query.delete(synchronize_session=False)
    db.commit()
    logger.info(f"Cleared {deleted} halal cache entries (filter: {status_filter})")
    return {"deleted": deleted, "filter": status_filter}


# ── Signals ───────────────────────────────────────────────────────────────────

@app.get("/api/signals", tags=["signals"])
def get_signals(days: int = 7, db: Session = Depends(get_db)):
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
        return {
            "positions":   resp.json(),
            "count":       len(resp.json()),
            "alpaca_mode": "paper" if "paper" in ALPACA_BASE_URL else "live",
        }
    except Exception as e:
        logger.error(f"Failed to fetch Alpaca positions: {e}")
        raise HTTPException(status_code=503, detail="Could not reach Alpaca API.")


# ── Daily reports ─────────────────────────────────────────────────────────────

@app.get("/api/reports", tags=["reports"])
def list_reports(limit: int = 30, db: Session = Depends(get_db)):
    reports = (
        db.query(DailyReport)
        .order_by(DailyReport.report_date.desc())
        .limit(limit)
        .all()
    )
    return [_report_to_dict(r) for r in reports]


@app.get("/api/reports/{report_date}", tags=["reports"])
def get_report(report_date: str, db: Session = Depends(get_db)):
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
        "id":              str(r.id),
        "report_date":     r.report_date.strftime("%Y-%m-%d"),
        "stocks_screened": r.stocks_screened,
        "halal_passed":    r.halal_passed,
        "signals_fired":   r.signals_fired,
        "trades_executed": r.trades_executed,
        "alerts_sent":     r.alerts_sent,
        "summary":         r.summary,
    }


# ── Tax ───────────────────────────────────────────────────────────────────────

@app.get("/api/tax/summary", tags=["tax"])
def get_tax_summary(year: int = datetime.now().year, db: Session = Depends(get_db)):
    year_start = datetime(year, 1, 1, tzinfo=timezone.utc)
    year_end   = datetime(year, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
    trades = (
        db.query(Trade)
        .filter(Trade.traded_at >= year_start, Trade.traded_at <= year_end)
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
    import threading
    from scheduler.jobs import morning_job

    thread = threading.Thread(target=morning_job, daemon=True)
    thread.start()
    return {"message": "Morning job triggered. Check Telegram for updates."}


# ── Discovery ─────────────────────────────────────────────────────────────────

@app.get("/api/discover", tags=["discovery"])
def discover_stocks(
    top_n:     int  = 10,
    min_price: float = 10.0,
    db:        Session = Depends(get_db),
):
    """
    Run the halal stock discovery engine.
    Scans ~100 pre-screened halal-friendly stocks, ranks by momentum + Claude analysis.
    Results are cached for 1 hour to avoid excessive API costs.
    """
    import redis as redis_lib
    import json as json_lib

    REDIS_URL = os.environ.get("REDIS_URL", "")
    cache_key = f"discovery:top{top_n}:min{min_price}"

    # Try cache first (1 hour TTL)
    if REDIS_URL:
        try:
            r = redis_lib.from_url(REDIS_URL)
            cached = r.get(cache_key)
            if cached:
                logger.info("Discovery cache hit")
                return json_lib.loads(cached)
        except Exception as e:
            logger.warning(f"Redis cache miss: {e}")

    # Run fresh discovery
    import discovery as discovery_module
    result = discovery_module.run_discovery(db=db, top_n=top_n, min_price=min_price)

    # Cache for 1 hour
    if REDIS_URL:
        try:
            r = redis_lib.from_url(REDIS_URL)
            r.setex(cache_key, 3600, json_lib.dumps(result, default=str))
        except Exception as e:
            logger.warning(f"Redis cache set failed: {e}")

    return result


@app.post("/api/discover/refresh", tags=["discovery"])
def refresh_discovery(
    top_n:     int   = 10,
    min_price: float = 10.0,
    db:        Session = Depends(get_db),
):
    """Force refresh discovery — bypasses cache."""
    import discovery as discovery_module
    return discovery_module.run_discovery(db=db, top_n=top_n, min_price=min_price)


# ── Paper trading ─────────────────────────────────────────────────────────────

class TradeRequest(BaseModel):
    symbol: str
    qty: float
    side: str  # "buy" | "sell"

    @field_validator("symbol")
    @classmethod
    def symbol_upper(cls, v: str) -> str:
        return v.upper().strip()

    @field_validator("side")
    @classmethod
    def side_lower(cls, v: str) -> str:
        v = v.lower()
        if v not in ("buy", "sell"):
            raise ValueError("side must be 'buy' or 'sell'")
        return v

    @field_validator("qty")
    @classmethod
    def qty_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("qty must be positive")
        return v


@app.post("/api/trade", tags=["trading"])
def place_trade(req: TradeRequest, db: Session = Depends(get_db)):
    """
    Place a paper (or live) market order via Alpaca.
    Currently wired to Alpaca paper trading by default.
    """
    if not ALPACA_KEY or not ALPACA_SECRET:
        raise HTTPException(status_code=503, detail="Alpaca credentials not configured")

    payload = {
        "symbol":        req.symbol,
        "qty":           str(req.qty),
        "side":          req.side,
        "type":          "market",
        "time_in_force": "day",
    }
    try:
        resp = requests.post(
            f"{ALPACA_BASE_URL}/v2/orders",
            json=payload,
            headers={
                "APCA-API-KEY-ID":     ALPACA_KEY,
                "APCA-API-SECRET-KEY": ALPACA_SECRET,
            },
            timeout=10,
        )
        resp.raise_for_status()
        order = resp.json()
        logger.info(f"Order placed: {req.side} {req.qty} {req.symbol} id={order.get('id')}")

        # Log to Trade table
        from db.models import Trade, TradeSide
        user_id = _get_default_user_id(db)
        # Market orders don't fill instantly — filled_avg_price is null at submission.
        # Use submitted_at from the order response, fall back to now().
        filled_price = float(order.get("filled_avg_price") or 0)
        trade = Trade(
            user_id          = user_id,
            alpaca_order_id  = order.get("id"),
            symbol           = req.symbol,
            side             = TradeSide.BUY if req.side == "buy" else TradeSide.SELL,
            quantity         = req.qty,
            price            = filled_price,
            total_value      = filled_price * req.qty,
            halal_status     = "compliant",
            is_paper         = "paper" in ALPACA_BASE_URL,
            traded_at        = datetime.now(timezone.utc),
        )
        db.add(trade)
        db.commit()

        return {
            "ok":       True,
            "order_id": order.get("id"),
            "symbol":   req.symbol,
            "side":     req.side,
            "qty":      req.qty,
            "status":   order.get("status"),
            "paper":    "paper" in ALPACA_BASE_URL,
        }
    except requests.HTTPError as e:
        detail = e.response.text if e.response else str(e)
        logger.error(f"Alpaca order failed: {detail}")
        raise HTTPException(status_code=502, detail=f"Alpaca error: {detail}")
    except Exception as e:
        logger.error(f"Trade placement error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Utility ───────────────────────────────────────────────────────────────────

def _get_default_user_id(db: Session):
    from db.models import User
    user = db.query(User).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No user found. Please complete onboarding.",
        )
    return user.id
