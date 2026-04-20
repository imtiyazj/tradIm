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
FINNHUB_API_KEY  = os.environ.get("FINNHUB_API_KEY", "")
ALPACA_KEY       = os.environ.get("ALPACA_KEY", "")
ALPACA_SECRET    = os.environ.get("ALPACA_SECRET", "")

# ── Halal universe ────────────────────────────────────────────────────────────
# Sourced from SPUS + HLAL ETF holdings + curated halal-friendly sectors
# All pre-filtered to exclude hard-blocked sectors (banking, alcohol, weapons etc.)

HALAL_UNIVERSE = [
    # ── Semiconductors & AI infrastructure ──
    "NVDA", "AMD", "AVGO", "QCOM", "TSM", "AMAT", "LRCX", "KLAC", "MRVL", "ON",
    "TXN", "ADI", "MCHP", "SWKS", "MPWR", "ENTG", "ONTO", "ACLS", "WOLF",
    # ── Software & Cloud ──
    "MSFT", "GOOGL", "ORCL", "CRM", "ADBE", "NOW", "SNOW", "DDOG", "PANW",
    "CRWD", "NET", "ZS", "MDB", "GTLB", "HUBS", "TEAM", "OKTA", "COUP",
    "SPLK", "VEEV", "WDAY", "ANSS", "CDNS", "SNPS", "PTC", "PAYC", "PCTY",
    "BILL", "FRSH", "S", "ESTC", "CFLT", "DOMO",
    # ── Hardware & Devices ──
    "AAPL", "DELL", "HPQ", "PSTG", "NTAP", "WDC", "STX", "FFIV", "JNPR",
    "ZBRA", "TRMB", "ITRI",
    # ── Healthcare & Biotech ──
    "LLY", "ABBV", "TMO", "DHR", "ISRG", "DXCM", "IDXX", "MTD", "WAT",
    "REGN", "VRTX", "MRNA", "AMGN", "GILD", "BIIB", "ILMN", "IQV", "IQVIA",
    "CRL", "MEDP", "NTRA", "EXAS", "QDEL", "HOLOGIC", "HOLX", "ALGN",
    "STE", "WST", "PODD", "INSP", "TNDM", "IRTC",
    # ── Industrials & Engineering ──
    "CAT", "DE", "HON", "GE", "ETN", "PWR", "EMR", "ROK", "PH", "AME",
    "CSGP", "FAST", "GWW", "VRSK", "CPRT", "CTAS", "RSG", "WM", "ROP",
    "FTV", "GNRC", "AIXA", "AXON", "TDY", "LDOS", "SAIC", "BWXT",
    "TT", "CARR", "OTIS", "XYL", "XYLEM", "IDEX", "IEX",
    # ── Clean energy & Utilities ──
    "NEE", "ENPH", "FSLR", "SEDG", "RUN", "BE", "PLUG", "ARRY",
    "AEE", "WEC", "CMS", "LNT", "EVRG",
    # ── Consumer & Retail (halal-compliant) ──
    "AMZN", "COST", "WMT", "TGT", "NKE", "LULU", "SBUX", "MCD", "CMG",
    "TSLA", "F", "GM", "RIVN", "LCID", "TM", "HMC",
    "DECK", "SKX", "CROX", "WWW", "COLM",
    "MNST", "CELH", "KDP",
    # ── Communications & Media ──
    "META", "NFLX", "DIS", "TTWO", "EA", "RBLX", "U", "UNITY",
    "GOOGL", "GOOG", "AKAM", "FSLY", "LLNW",
    # ── Real estate & Infrastructure (non-REIT or halal-structured) ──
    "PLD", "AMT", "EQIX", "DLR", "CCI",
    # ── Materials & Chemicals (non-haram) ──
    "LIN", "APD", "ECL", "SHW", "NEM", "FCX", "ALB", "LTHM", "LAC",
    "MP", "NOVT",
    # ── E-commerce & Fintech (non-interest) ──
    "SHOP", "SQ", "PYPL", "MELI", "SE", "GRAB", "GLBE",
    # ── Space & Defence-adjacent (non-weapons) ──
    "RKLB", "ASTS", "LUNR",
]


# ── Market data fetchers ──────────────────────────────────────────────────────

_ALPACA_HEADERS = lambda: {
    "APCA-API-KEY-ID":     ALPACA_KEY,
    "APCA-API-SECRET-KEY": ALPACA_SECRET,
}

def _fetch_snapshot(symbols: list[str]) -> dict:
    """
    Fetch market snapshot for multiple symbols using Alpaca market data API.
    Free with paper trading credentials. Supports up to 1000 symbols per call.
    Falls back to Polygon per-symbol calls if Alpaca is unavailable.
    """
    results = {}

    # ── Try Alpaca first (free with paper account) ──
    if ALPACA_KEY and ALPACA_SECRET:
        try:
            # Alpaca accepts comma-separated symbols list
            resp = httpx.get(
                "https://data.alpaca.markets/v2/stocks/snapshots",
                params={"symbols": ",".join(symbols), "feed": "iex"},
                headers=_ALPACA_HEADERS(),
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()
            for sym, snap in data.items():
                daily  = snap.get("dailyBar") or {}
                prev   = snap.get("prevDailyBar") or {}
                latest = snap.get("latestTrade") or {}
                quote  = snap.get("latestQuote") or {}

                # Price cascade: latest trade → daily close → prev close → mid quote
                price = (
                    latest.get("p")
                    or daily.get("c")
                    or prev.get("c")
                    or ((quote.get("bp", 0) + quote.get("ap", 0)) / 2) or 0
                )
                prev_close = prev.get("c") or 0
                change_pct = (
                    ((price - prev_close) / prev_close * 100)
                    if prev_close else 0
                )
                results[sym] = {
                    "price":      round(price, 4),
                    "change_pct": round(change_pct, 2),
                    "volume":     daily.get("v", 0) or prev.get("v", 0),
                    "avg_volume": prev.get("v", 0),
                    "high":       daily.get("h", 0) or prev.get("h", 0),
                    "low":        daily.get("l", 0) or prev.get("l", 0),
                    "prev_close": prev_close,
                }
            logger.info(f"Alpaca snapshot: got data for {len(results)}/{len(symbols)} symbols")
            return results
        except Exception as e:
            logger.warning(f"Alpaca snapshot failed, falling back to Polygon: {e}")

    # ── Fallback: Polygon per-symbol prev-day endpoint (free tier) ──
    logger.info("Using Polygon per-symbol fallback for market data...")
    for sym in symbols:
        try:
            resp = httpx.get(
                f"https://api.polygon.io/v2/aggs/ticker/{sym}/prev",
                params={"apiKey": POLYGON_API_KEY},
                timeout=8,
            )
            if resp.is_success:
                bars = resp.json().get("results", [])
                if bars:
                    bar = bars[0]
                    results[sym] = {
                        "price":      bar.get("c", 0),
                        "change_pct": round(
                            ((bar.get("c", 0) - bar.get("o", 0)) / bar.get("o", 1)) * 100, 2
                        ),
                        "volume":     bar.get("v", 0),
                        "avg_volume": bar.get("v", 0),
                        "high":       bar.get("h", 0),
                        "low":        bar.get("l", 0),
                        "prev_close": bar.get("c", 0),
                    }
        except Exception:
            pass
    logger.info(f"Polygon fallback: got data for {len(results)}/{len(symbols)} symbols")
    return results


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
