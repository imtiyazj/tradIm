"""
earnings.py — Finnhub earnings calendar lookup.

Module-level cache with 24-hour TTL. All fetches try/except — never raises
to callers.
"""

import os
import time
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY", "")
FINNHUB_BASE_URL = "https://finnhub.io/api/v1"

# ── Cache (symbol -> (timestamp, payload)) ────────────────────────────────────

_CACHE: dict[str, tuple[float, Optional[dict]]] = {}
_CACHE_TTL_SECONDS = 24 * 60 * 60   # 24 hours


def get_next_earnings(symbol: str) -> Optional[dict]:
    """
    Fetch the soonest upcoming earnings entry within the next 90 days.
    Returns {"date": "YYYY-MM-DD", "estimate_eps": float|None, "time": "amc"|"bmo"|""} or None.
    """
    now = time.time()
    cached = _CACHE.get(symbol)
    if cached and (now - cached[0]) < _CACHE_TTL_SECONDS:
        return cached[1]

    if not FINNHUB_API_KEY:
        logger.warning("FINNHUB_API_KEY not set — cannot fetch earnings calendar")
        return None

    today    = datetime.now(timezone.utc).date()
    to_date  = today + timedelta(days=90)

    try:
        resp = httpx.get(
            f"{FINNHUB_BASE_URL}/calendar/earnings",
            params={
                "from":   today.isoformat(),
                "to":     to_date.isoformat(),
                "symbol": symbol,
            },
            headers={"X-Finnhub-Token": FINNHUB_API_KEY},
            timeout=10,
            follow_redirects=True,
        )
        resp.raise_for_status()
        data = resp.json()
        items = data.get("earningsCalendar") or []

        if not items:
            _CACHE[symbol] = (now, None)
            return None

        # Sort by date ascending — soonest first
        def _key(e):
            return e.get("date") or "9999-12-31"
        items.sort(key=_key)
        nearest = items[0]

        result = {
            "date":         nearest.get("date", ""),
            "estimate_eps": nearest.get("epsEstimate"),
            "time":         (nearest.get("hour") or "").lower(),
        }
        _CACHE[symbol] = (now, result)
        return result

    except Exception as e:
        logger.warning(f"Finnhub earnings fetch failed for {symbol}: {e}")
        _CACHE[symbol] = (now, None)
        return None


def days_until_earnings(symbol: str) -> Optional[int]:
    """Days from today until the next earnings event. None if no upcoming earnings."""
    info = get_next_earnings(symbol)
    if not info or not info.get("date"):
        return None
    try:
        target = datetime.strptime(info["date"], "%Y-%m-%d").date()
        today  = datetime.now(timezone.utc).date()
        return (target - today).days
    except Exception:
        return None


def is_imminent(symbol: str, threshold_days: int = 3) -> bool:
    """True if next earnings is within threshold_days (inclusive)."""
    days = days_until_earnings(symbol)
    return days is not None and 0 <= days <= threshold_days


def get_earnings_batch(symbols: list[str]) -> dict[str, dict]:
    """
    Returns {symbol: {"days_until": int|None, "next_date": str|None, "imminent": bool}}.
    Per-symbol failures logged, batch never crashes.
    """
    out: dict[str, dict] = {}
    for sym in symbols:
        try:
            info = get_next_earnings(sym)
            if info and info.get("date"):
                days = days_until_earnings(sym)
                out[sym] = {
                    "days_until": days,
                    "next_date":  info["date"],
                    "imminent":   days is not None and 0 <= days <= 3,
                }
            else:
                out[sym] = {
                    "days_until": None,
                    "next_date":  None,
                    "imminent":   False,
                }
        except Exception as e:
            logger.warning(f"Earnings fetch failed for {sym}: {e}")
            out[sym] = {"days_until": None, "next_date": None, "imminent": False}
    return out
