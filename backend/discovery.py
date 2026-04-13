"""
discovery.py — Halal stock discovery engine.

Scans a curated universe of Shariah-friendly stocks daily,
screens them via Zoya, runs Claude momentum analysis,
and surfaces the top opportunities ranked by confidence.

Universe sources:
  - SPUS (SP Funds S&P 500 Sharia ETF) holdings
  - HLAL (Wahed FTSE USA Shariah ETF) holdings
  - Manually curated halal-friendly sectors
"""

import os
import logging
from datetime import datetime, timezone
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

POLYGON_API_KEY = os.environ.get("POLYGON_API_KEY", "")
FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY", "")

# ── Halal universe ────────────────────────────────────────────────────────────
# Sourced from SPUS + HLAL ETF holdings + curated halal-friendly sectors
# All pre-filtered to exclude hard-blocked sectors (banking, alcohol, weapons etc.)

HALAL_UNIVERSE = [
    # ── Semiconductors & AI infrastructure ──
    "NVDA", "AMD", "AVGO", "QCOM", "TSM", "AMAT", "LRCX", "KLAC", "MRVL", "ON",
    # ── Software & Cloud ──
    "MSFT", "GOOGL", "ORCL", "CRM", "ADBE", "NOW", "SNOW", "DDOG", "PANW",
    "CRWD", "NET", "ZS", "MDB", "GTLB",
    # ── Hardware & Devices ──
    "AAPL", "DELL", "HPQ", "PSTG",
    # ── Healthcare & Biotech ──
    "LLY", "ABBV", "TMO", "DHR", "ISRG", "DXCM", "IDXX", "MTD", "WAT",
    "REGN", "VRTX", "MRNA", "AMGN",
    # ── Industrials & Engineering ──
    "CAT", "DE", "HON", "GE", "ETN", "PWR", "EMR", "ROK", "PH", "AME",
    "CSGP", "FAST", "GWW",
    # ── Clean energy & Utilities ──
    "NEE", "ENPH", "FSLR", "SEDG", "RUN", "BE",
    # ── Consumer & Retail (halal-compliant) ──
    "AMZN", "COST", "WMT", "TGT", "NKE", "LULU", "SBUX", "MCD", "CMG",
    "TSLA", "F", "GM",
    # ── Communications & Media ──
    "META", "NFLX", "DIS", "TTWO", "EA",
    # ── Real estate & Infrastructure ──
    "PLD", "AMT", "EQIX", "DLR", "CCI",
    # ── Materials & Chemicals (non-haram) ──
    "LIN", "APD", "ECL", "SHW", "NEM", "FCX",
]


# ── Polygon data fetchers ─────────────────────────────────────────────────────

def _fetch_snapshot(symbols: list[str]) -> dict:
    """
    Fetch market snapshot for multiple symbols from Polygon.
    Returns dict keyed by symbol with price, volume, change data.
    """
    # Polygon supports up to 250 tickers in one snapshot call
    tickers = ",".join(symbols)
    results = {}
    try:
        resp = httpx.get(
            "https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/tickers",
            params={"tickers": tickers, "apiKey": POLYGON_API_KEY},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        for item in data.get("tickers", []):
            sym = item.get("ticker", "")
            day = item.get("day", {})
            prev = item.get("prevDay", {})
            results[sym] = {
                "price":       item.get("lastTrade", {}).get("p") or day.get("c", 0),
                "change_pct":  item.get("todaysChangePerc", 0),
                "volume":      day.get("v", 0),
                "avg_volume":  item.get("prevDay", {}).get("v", 0),
                "high":        day.get("h", 0),
                "low":         day.get("l", 0),
                "prev_close":  prev.get("c", 0),
            }
    except Exception as e:
        logger.error(f"Polygon snapshot fetch failed: {e}")
    return results


def _fetch_top_movers() -> list[dict]:
    """
    Fetch today's top gainers from Polygon for additional discovery.
    """
    movers = []
    try:
        resp = httpx.get(
            "https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/gainers",
            params={"apiKey": POLYGON_API_KEY},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        for item in data.get("tickers", [])[:20]:
            movers.append({
                "symbol":     item.get("ticker", ""),
                "change_pct": item.get("todaysChangePerc", 0),
                "price":      item.get("lastTrade", {}).get("p", 0),
                "volume":     item.get("day", {}).get("v", 0),
            })
    except Exception as e:
        logger.warning(f"Top movers fetch failed: {e}")
    return movers


def _fetch_news_batch(symbols: list[str], limit: int = 3) -> dict[str, list]:
    """
    Fetch recent news headlines for a batch of symbols from Finnhub.
    Returns dict keyed by symbol.
    """
    news_by_symbol: dict[str, list] = {}
    headers = {"X-Finnhub-Token": FINNHUB_API_KEY}
    for sym in symbols:
        try:
            resp = httpx.get(
                "https://finnhub.io/api/v1/company-news",
                params={"symbol": sym, "from": "2024-01-01", "to": "2099-01-01"},
                headers=headers,
                timeout=8,
                follow_redirects=True,
            )
            if resp.is_success:
                items = resp.json()[:limit]
                news_by_symbol[sym] = [
                    {"headline": i.get("headline", ""), "sentiment": i.get("sentiment", "")}
                    for i in items
                ]
        except Exception:
            pass
    return news_by_symbol


# ── Scoring ───────────────────────────────────────────────────────────────────

def _momentum_score(market_data: dict) -> float:
    """
    Simple momentum score 0-1 based on:
    - Price change % today (50%)
    - Volume vs prev day (50%)
    """
    change_pct  = market_data.get("change_pct", 0)
    volume      = market_data.get("volume", 0)
    avg_volume  = market_data.get("avg_volume", 1) or 1
    vol_ratio   = min(volume / avg_volume, 5) / 5   # cap at 5x, normalize to 0-1

    # Normalize change_pct: assume ±5% is the full range
    change_norm = max(min((change_pct + 5) / 10, 1), 0)

    return round((change_norm * 0.5) + (vol_ratio * 0.5), 3)


# ── Main discovery function ───────────────────────────────────────────────────

def run_discovery(
    db,
    top_n: int = 10,
    min_price: float = 10.0,
    extra_symbols: Optional[list[str]] = None,
) -> dict:
    """
    Run the full discovery pipeline.

    Args:
        db:             SQLAlchemy session (for halal cache)
        top_n:          Number of top opportunities to return
        min_price:      Minimum stock price to consider
        extra_symbols:  Additional symbols to include (e.g. today's top movers)

    Returns:
        {
            "top_picks": [...],
            "screened":  int,
            "compliant": int,
            "run_at":    str,
        }
    """
    import halal_screen as halal_module
    import claude as claude_module

    universe = list(set(HALAL_UNIVERSE + (extra_symbols or [])))
    logger.info(f"Discovery: scanning {len(universe)} symbols")

    # ── 1. Fetch market data for entire universe ──
    logger.info("Fetching Polygon snapshot for universe...")
    market_data = _fetch_snapshot(universe)

    # Filter out low-price stocks and those with no data
    candidates = [
        sym for sym in universe
        if market_data.get(sym, {}).get("price", 0) >= min_price
    ]
    logger.info(f"Discovery: {len(candidates)} candidates after price filter")

    # ── 2. Halal screen (uses cache — very fast for already-screened stocks) ──
    logger.info("Running halal screening (cached where possible)...")
    from db.models import HalalStatus
    screen_results = halal_module.screen_watchlist(candidates, db)

    compliant = [
        r for r in screen_results
        if r.get("final_status") in [HalalStatus.COMPLIANT, "compliant"]
    ]
    logger.info(f"Discovery: {len(compliant)} halal-compliant stocks")

    if not compliant:
        return {
            "top_picks": [],
            "screened":  len(candidates),
            "compliant": 0,
            "run_at":    datetime.now(timezone.utc).isoformat(),
        }

    # ── 3. Score by momentum and pick top candidates for Claude ──
    scored = []
    for r in compliant:
        sym  = r["symbol"]
        mdata = market_data.get(sym, {})
        score = _momentum_score(mdata)
        scored.append({
            "symbol":       sym,
            "momentum":     score,
            "market_data":  mdata,
            "halal_notes":  r.get("notes", ""),
            "debt_ratio":   r.get("debt_ratio"),
        })

    # Sort by momentum, take top 20 for Claude to analyse
    scored.sort(key=lambda x: x["momentum"], reverse=True)
    top_candidates = scored[:20]

    # ── 4. Fetch news for top candidates ──
    logger.info("Fetching news for top candidates...")
    top_syms  = [c["symbol"] for c in top_candidates]
    news_data = _fetch_news_batch(top_syms)

    # ── 5. Claude ranks and analyses top candidates ──
    logger.info("Running Claude discovery analysis...")
    claude_result = claude_module.analyse_discovery(
        candidates   = top_candidates,
        market_data  = {c["symbol"]: c["market_data"] for c in top_candidates},
        news_by_symbol = news_data,
        top_n        = top_n,
    )

    return {
        "top_picks": claude_result.get("picks", []),
        "summary":   claude_result.get("summary", ""),
        "screened":  len(candidates),
        "compliant": len(compliant),
        "run_at":    datetime.now(timezone.utc).isoformat(),
    }
