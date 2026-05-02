"""
technicals.py — Technical indicator calculations (RSI + MACD) using Alpaca historical bars.

Pure-Python math, no numpy/pandas. Module-level cache with 1-hour TTL to keep
morning_job fast and avoid rate-limiting Alpaca.
"""

import os
import time
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

ALPACA_KEY    = os.environ.get("ALPACA_KEY", "")
ALPACA_SECRET = os.environ.get("ALPACA_SECRET", "")

ALPACA_DATA_URL = "https://data.alpaca.markets"

_ALPACA_HEADERS = lambda: {
    "APCA-API-KEY-ID":     ALPACA_KEY,
    "APCA-API-SECRET-KEY": ALPACA_SECRET,
}

# ── Cache (symbol -> (timestamp, indicators_dict)) ────────────────────────────

_CACHE: dict[str, tuple[float, dict]] = {}
_CACHE_TTL_SECONDS = 60 * 60   # 1 hour


# ── Bar fetcher ───────────────────────────────────────────────────────────────

def _fetch_bars(symbol: str, days: int = 60) -> list[dict]:
    """
    Fetch daily bars from Alpaca market data.
    Returns list of bar dicts (oldest first per Alpaca default).
    Empty list on any failure.
    """
    if not (ALPACA_KEY and ALPACA_SECRET):
        logger.warning(f"Alpaca credentials missing — cannot fetch bars for {symbol}")
        return []
    try:
        resp = httpx.get(
            f"{ALPACA_DATA_URL}/v2/stocks/{symbol}/bars",
            params={"timeframe": "1Day", "limit": days, "feed": "iex"},
            headers=_ALPACA_HEADERS(),
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        bars = data.get("bars") or []
        return bars
    except Exception as e:
        logger.warning(f"Alpaca bars fetch failed for {symbol}: {e}")
        return []


# ── Pure-Python indicator math ────────────────────────────────────────────────

def calculate_rsi(closes: list[float], period: int = 14) -> Optional[float]:
    """
    Wilder's RSI. Returns None if not enough data.
    """
    if not closes or len(closes) < period + 1:
        return None

    gains: list[float] = []
    losses: list[float] = []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0.0))
        losses.append(max(-diff, 0.0))

    # Initial averages
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    # Wilder smoothing for the remainder
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return round(rsi, 1)


def _ema(values: list[float], period: int) -> list[float]:
    """
    Exponential moving average. Returns a list aligned to input
    (values before the first computable EMA are skipped — output len = len(values) - period + 1).
    """
    if len(values) < period:
        return []
    k = 2.0 / (period + 1)
    seed = sum(values[:period]) / period
    emas = [seed]
    for v in values[period:]:
        emas.append(v * k + emas[-1] * (1 - k))
    return emas


def calculate_macd(closes: list[float]) -> dict:
    """
    MACD = EMA(12) - EMA(26)
    Signal = EMA(9) of MACD line
    Histogram = MACD - Signal
    Trend: bullish if MACD > Signal AND histogram rising; bearish if MACD < Signal AND histogram falling; else neutral.
    Empty dict if insufficient data.
    """
    if len(closes) < 26 + 9:
        return {}

    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)
    if not ema12 or not ema26:
        return {}

    # Align so both EMAs cover the same trailing window (length = len(closes) - 26 + 1)
    offset = len(ema12) - len(ema26)
    ema12_aligned = ema12[offset:]
    macd_line = [a - b for a, b in zip(ema12_aligned, ema26)]

    if len(macd_line) < 9:
        return {}

    signal_line = _ema(macd_line, 9)
    if not signal_line:
        return {}

    macd_now    = macd_line[-1]
    signal_now  = signal_line[-1]
    hist_now    = macd_now - signal_now

    # Histogram direction (last 2 hist points)
    if len(signal_line) >= 2:
        macd_prev   = macd_line[-2]
        signal_prev = signal_line[-2]
        hist_prev   = macd_prev - signal_prev
    else:
        hist_prev = 0.0

    if macd_now > signal_now and hist_now >= hist_prev:
        trend = "bullish"
    elif macd_now < signal_now and hist_now <= hist_prev:
        trend = "bearish"
    else:
        trend = "neutral"

    return {
        "macd":      round(macd_now, 4),
        "signal":    round(signal_now, 4),
        "histogram": round(hist_now, 4),
        "trend":     trend,
    }


# ── Public API ────────────────────────────────────────────────────────────────

def get_indicators(symbol: str) -> dict:
    """
    Fetch + compute RSI and MACD for a symbol. Returns combined verdict.
    Empty dict on failure. 1-hour cache.
    """
    now = time.time()
    cached = _CACHE.get(symbol)
    if cached and (now - cached[0]) < _CACHE_TTL_SECONDS:
        return cached[1]

    bars = _fetch_bars(symbol, days=60)
    if not bars:
        return {}

    closes = [float(b.get("c", 0)) for b in bars if b.get("c") is not None]
    if len(closes) < 30:
        return {}

    rsi  = calculate_rsi(closes)
    macd = calculate_macd(closes)
    if rsi is None or not macd:
        return {}

    if rsi < 30:
        rsi_signal = "oversold"
    elif rsi > 70:
        rsi_signal = "overbought"
    else:
        rsi_signal = "neutral"

    macd_trend = macd.get("trend", "neutral")

    # Combined verdict
    if rsi < 70 and macd_trend == "bullish":
        verdict = "bullish"
    elif rsi > 70 or macd_trend == "bearish":
        verdict = "bearish"
    else:
        verdict = "neutral"

    indicators = {
        "rsi":               rsi,
        "rsi_signal":        rsi_signal,
        "macd":              macd["macd"],
        "macd_signal_line":  macd["signal"],
        "macd_histogram":    macd["histogram"],
        "macd_trend":        macd_trend,
        "verdict":           verdict,
    }

    _CACHE[symbol] = (now, indicators)
    return indicators


def get_indicators_batch(symbols: list[str]) -> dict[str, dict]:
    """
    Batch-fetch indicators. Per-symbol failures are logged but never raise.
    """
    results: dict[str, dict] = {}
    for sym in symbols:
        try:
            data = get_indicators(sym)
            if data:
                results[sym] = data
        except Exception as e:
            logger.warning(f"Indicator fetch failed for {sym}: {e}")
    return results
