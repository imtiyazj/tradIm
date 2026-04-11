"""
scheduler/jobs.py — Daily automated workflow.

Schedule:
  08:00 ET  market open prep  — fetch data, screen, analyse, alert
  16:30 ET  market close wrap — log summary, update daily report
  Weekly    refresh halal cache for watchlist

Run this file directly:  python -m scheduler.jobs
Or import and attach to an existing APScheduler instance.
"""

import os
import json
import logging
import requests
from datetime import datetime, timezone
from typing import Optional

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.orm import Session, sessionmaker

from db.models import (
    get_engine, HalalStatus, WatchlistItem,
    Signal, AlertLog, DailyReport, AlertType, AlertChannel
)
import claude as claude_module
import halal_screen as halal_module

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

POLYGON_API_KEY  = os.environ.get("POLYGON_API_KEY", "")
FINNHUB_API_KEY  = os.environ.get("FINNHUB_API_KEY", "")
ALPACA_KEY       = os.environ.get("ALPACA_KEY", "")
ALPACA_SECRET    = os.environ.get("ALPACA_SECRET", "")
ALPACA_BASE_URL  = os.environ.get("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

POLYGON_BASE  = "https://api.polygon.io/v2"
FINNHUB_BASE  = "https://finnhub.io/api/v1"


# ── Database session factory ──────────────────────────────────────────────────

engine = get_engine()
SessionLocal = sessionmaker(bind=engine)


def get_db() -> Session:
    return SessionLocal()


# ── Data fetchers ─────────────────────────────────────────────────────────────

def fetch_market_data(symbols: list[str]) -> dict:
    """
    Fetch latest prices from Polygon.io for each symbol.

    Returns:
        {"AAPL": {"price": 182.5, "change_pct": 1.2, "volume": 45000000}, ...}
    """
    data = {}
    headers = {"Authorization": f"Bearer {POLYGON_API_KEY}"}

    for symbol in symbols:
        try:
            url = f"{POLYGON_BASE}/aggs/ticker/{symbol}/prev"
            resp = requests.get(url, headers=headers, timeout=10)
            resp.raise_for_status()
            results = resp.json().get("results", [])
            if results:
                bar = results[0]
                prev_close = bar.get("c", 0)
                open_price = bar.get("o", prev_close)
                change_pct = ((prev_close - open_price) / open_price * 100) if open_price else 0
                data[symbol] = {
                    "price":      prev_close,
                    "open":       open_price,
                    "high":       bar.get("h"),
                    "low":        bar.get("l"),
                    "volume":     bar.get("v"),
                    "change_pct": round(change_pct, 2),
                }
        except Exception as e:
            logger.warning(f"Polygon fetch failed for {symbol}: {e}")
            data[symbol] = {}

    return data


def fetch_news(symbols: list[str], limit_per_symbol: int = 5) -> list[dict]:
    """
    Fetch recent news headlines from Finnhub for watchlist symbols.
    """
    news_items = []
    headers = {"X-Finnhub-Token": FINNHUB_API_KEY}

    for symbol in symbols:
        try:
            resp = requests.get(
                f"{FINNHUB_BASE}/company-news",
                params={"symbol": symbol, "from": "2024-01-01", "to": "2099-01-01"},
                headers=headers,
                timeout=10,
            )
            resp.raise_for_status()
            items = resp.json()[:limit_per_symbol]
            for item in items:
                news_items.append({
                    "symbol":    symbol,
                    "headline":  item.get("headline", ""),
                    "summary":   item.get("summary", "")[:200],
                    "sentiment": item.get("sentiment", "neutral"),
                    "datetime":  item.get("datetime"),
                })
        except Exception as e:
            logger.warning(f"Finnhub news fetch failed for {symbol}: {e}")

    return news_items


# ── Alpaca helpers ────────────────────────────────────────────────────────────

def get_alpaca_positions() -> list[dict]:
    """Fetch current open positions from Alpaca."""
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
        return resp.json()
    except Exception as e:
        logger.error(f"Alpaca positions fetch failed: {e}")
        return []


def place_alpaca_order(symbol: str, qty: float, side: str) -> Optional[dict]:
    """
    Place a market order on Alpaca.

    Args:
        symbol: "AAPL"
        qty:    number of shares (float for fractional)
        side:   "buy" | "sell"

    Returns:
        Alpaca order dict or None on failure.
    """
    payload = {
        "symbol":        symbol,
        "qty":           str(qty),
        "side":          side,
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
        logger.info(f"Alpaca order placed: {side} {qty} {symbol} — order_id={order.get('id')}")
        return order
    except Exception as e:
        logger.error(f"Alpaca order failed for {symbol}: {e}")
        return None


# ── Alert senders ─────────────────────────────────────────────────────────────

def send_telegram(message: str) -> bool:
    """Send a message to the configured Telegram chat."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram not configured — skipping alert")
        return False
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": message},
            timeout=10,
        )
        resp.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"Telegram send failed: {e}")
        return False


def log_alert(
    db: Session,
    user_id,
    alert_type: AlertType,
    channel: AlertChannel,
    message: str,
    symbol: Optional[str] = None,
    sent_ok: bool = True,
):
    """Persist an alert to the database."""
    record = AlertLog(
        user_id    = user_id,
        alert_type = alert_type,
        channel    = channel,
        symbol     = symbol,
        message    = message,
        sent_ok    = sent_ok,
    )
    db.add(record)
    db.commit()


# ── Core daily job ────────────────────────────────────────────────────────────

def morning_job():
    """
    Main daily workflow — runs at 08:00 ET on trading days.

    Flow:
      1. Load watchlist from DB
      2. Fetch market data (Polygon) + news (Finnhub)
      3. Halal screen each symbol (Zoya + Claude ratios)
      4. Run Claude analysis → signals
      5. Send Telegram morning brief
      6. Check strategy rules → place orders if triggered
      7. Log daily report
    """
    logger.info("=" * 60)
    logger.info("MORNING JOB STARTED")
    logger.info("=" * 60)

    db = get_db()
    try:
        # ── 1. Load watchlist ──
        watchlist_items = (
            db.query(WatchlistItem)
            .filter(WatchlistItem.is_active == True)
            .all()
        )
        if not watchlist_items:
            logger.warning("Watchlist is empty — nothing to process")
            send_telegram("Halal Trader: Watchlist is empty. Add stocks via the dashboard.")
            return

        symbols = [item.symbol for item in watchlist_items]
        # Use the first user for now (private single-user app)
        user_id = watchlist_items[0].user_id
        logger.info(f"Processing {len(symbols)} symbols: {symbols}")

        # ── 2. Fetch market data + news ──
        logger.info("Fetching market data from Polygon...")
        market_data = fetch_market_data(symbols)

        logger.info("Fetching news from Finnhub...")
        news_items = fetch_news(symbols)

        # ── 3. Halal screen ──
        logger.info("Running halal screening (Zoya + Claude ratios)...")
        screen_results = halal_module.screen_watchlist(symbols, db)

        halal_passed = [
            r for r in screen_results
            if r.get("final_status") == HalalStatus.COMPLIANT
        ]
        halal_blocked = [
            r for r in screen_results
            if r.get("final_status") == HalalStatus.NON_COMPLIANT
        ]

        logger.info(
            f"Halal screen: {len(halal_passed)} passed, "
            f"{len(halal_blocked)} blocked, "
            f"{len(screen_results) - len(halal_passed) - len(halal_blocked)} uncertain"
        )

        # Alert if a previously watchlisted stock is now non-compliant
        for blocked in halal_blocked:
            sym = blocked["symbol"]
            msg = claude_module.draft_alert_message(
                "halal_change", sym,
                {"reason": blocked.get("notes", ""), "status": "non_compliant"}
            )
            sent = send_telegram(f"HALAL ALERT\n{msg}")
            log_alert(
                db, user_id,
                AlertType.HALAL_CHANGE, AlertChannel.TELEGRAM,
                msg, symbol=sym, sent_ok=sent
            )

        # Build watchlist context for Claude (only halal-passed stocks)
        watchlist_for_claude = [
            {
                "symbol":       r["symbol"],
                "halal_status": str(r.get("final_status", "unknown")),
                "sector":       r.get("sector", ""),
                "notes":        r.get("notes", ""),
            }
            for r in halal_passed
        ]

        if not watchlist_for_claude:
            logger.warning("No halal-compliant stocks to analyse today")
            send_telegram("Halal Trader: No compliant stocks found in watchlist today. Review your watchlist.")
            return

        # ── 4. Claude analysis ──
        logger.info("Running Claude analysis...")
        analysis = claude_module.analyse_stocks(
            watchlist_for_claude, market_data, news_items
        )

        signals    = analysis.get("signals", [])
        summary    = analysis.get("summary", "No summary available.")
        tax_flags  = analysis.get("tax_flags", [])

        # Save signals to DB
        for sig in signals:
            signal_record = Signal(
                user_id     = user_id,
                symbol      = sig.get("symbol", ""),
                signal_type = sig.get("type", "watch"),
                confidence  = sig.get("confidence"),
                reasoning   = sig.get("reasoning", ""),
                price_at    = market_data.get(sig.get("symbol", ""), {}).get("price"),
            )
            db.add(signal_record)
        db.commit()
        logger.info(f"Saved {len(signals)} signals to database")

        # ── 5. Telegram morning brief ──
        morning_msg = (
            f"HALAL TRADER — Morning Brief\n"
            f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n\n"
            f"{summary}\n\n"
            f"Screened: {len(symbols)} | Halal: {len(halal_passed)} | "
            f"Signals: {len(signals)}"
        )
        send_telegram(morning_msg)
        log_alert(
            db, user_id,
            AlertType.STRATEGY, AlertChannel.TELEGRAM,
            morning_msg, sent_ok=True
        )

        # Alert on individual strong signals
        for sig in signals:
            if sig.get("confidence", 0) >= 0.75:
                msg = claude_module.draft_alert_message(
                    "strategy", sig["symbol"],
                    {"signal": sig["type"], "confidence": sig["confidence"],
                     "reasoning": sig["reasoning"]}
                )
                sent = send_telegram(msg)
                log_alert(
                    db, user_id,
                    AlertType.STRATEGY, AlertChannel.TELEGRAM,
                    msg, symbol=sig["symbol"], sent_ok=sent
                )

        # Alert on tax flags
        for flag in tax_flags:
            msg = claude_module.draft_alert_message(
                "tax", flag["symbol"], {"note": flag["note"]}
            )
            sent = send_telegram(msg)
            log_alert(
                db, user_id,
                AlertType.TAX, AlertChannel.TELEGRAM,
                msg, symbol=flag["symbol"], sent_ok=sent
            )

        # ── 6. Strategy rules → orders (placeholder) ──
        # Add your rule-based logic here, e.g.:
        #   if signal.type == "buy" and signal.confidence > 0.8:
        #       place_alpaca_order(signal.symbol, qty=1, side="buy")
        # Keeping this as a stub so you wire it up deliberately
        logger.info("Strategy rule engine: no automated orders configured yet")

        # ── 7. Save daily report ──
        report_data = {
            "stocks_screened": len(symbols),
            "halal_passed":    len(halal_passed),
            "signals_fired":   len(signals),
            "trades_executed": 0,
            "alerts_sent":     len(signals) + len(halal_blocked) + len(tax_flags) + 1,
            "signals":         signals,
            "summary":         summary,
        }
        full_summary = claude_module.generate_daily_summary(report_data)

        daily_report = DailyReport(
            user_id         = user_id,
            report_date     = datetime.now(timezone.utc),
            stocks_screened = len(symbols),
            halal_passed    = len(halal_passed),
            signals_fired   = len(signals),
            trades_executed = 0,
            alerts_sent     = report_data["alerts_sent"],
            summary         = full_summary,
            raw_json        = json.dumps(report_data),
        )
        db.add(daily_report)
        db.commit()

        logger.info("Morning job completed successfully")

    except Exception as e:
        logger.error(f"Morning job FAILED: {e}", exc_info=True)
        send_telegram(f"HALAL TRADER ERROR: Morning job failed.\n{str(e)[:200]}")
    finally:
        db.close()


def weekly_refresh_halal_cache():
    """
    Force-refresh the halal screening cache for the entire watchlist.
    Runs Sunday 06:00 ET so Monday's cache is warm.
    """
    logger.info("Weekly halal cache refresh starting...")
    db = get_db()
    try:
        items = db.query(WatchlistItem).filter(WatchlistItem.is_active == True).all()
        symbols = [i.symbol for i in items]
        for symbol in symbols:
            halal_module.screen_stock(symbol, db, force_refresh=True)
            logger.info(f"Refreshed halal cache: {symbol}")
        logger.info(f"Weekly refresh done — {len(symbols)} symbols updated")
    except Exception as e:
        logger.error(f"Weekly refresh failed: {e}", exc_info=True)
    finally:
        db.close()


# ── Scheduler setup ───────────────────────────────────────────────────────────

def create_scheduler() -> BlockingScheduler:
    scheduler = BlockingScheduler(timezone="America/New_York")

    # Daily morning job — weekdays at 08:00 ET
    scheduler.add_job(
        morning_job,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour=8,
            minute=0,
            timezone="America/New_York",
        ),
        id="morning_job",
        name="Daily morning analysis",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,   # 5 min grace if container was sleeping
    )

    # Weekly halal cache refresh — Sundays at 06:00 ET
    scheduler.add_job(
        weekly_refresh_halal_cache,
        trigger=CronTrigger(
            day_of_week="sun",
            hour=6,
            minute=0,
            timezone="America/New_York",
        ),
        id="halal_cache_refresh",
        name="Weekly halal cache refresh",
        max_instances=1,
        coalesce=True,
    )

    return scheduler


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logger.info("Halal Trader Scheduler starting...")
    send_telegram("Halal Trader Scheduler started successfully.")

    scheduler = create_scheduler()

    # List scheduled jobs on startup
    for job in scheduler.get_jobs():
        logger.info(f"  Scheduled: {job.name} — next run: {job.next_run_time}")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped.")
