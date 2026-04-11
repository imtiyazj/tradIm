"""
halal_screen.py — Two-layer Shariah compliance screening.

Layer 1: Zoya API    — sector hard block (pass / fail / doubtful)
Layer 2: Finnhub API — financial ratio verification via Claude

Result is cached in PostgreSQL for 7 days to minimise API calls.
"""

import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from sqlalchemy.orm import Session

from db.models import HalalStatus, HalalScreenResult, get_engine
import claude as claude_module

logger = logging.getLogger(__name__)

ZOYA_API_KEY    = os.environ.get("ZOYA_API_KEY", "")
FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY", "")

ZOYA_BASE_URL    = "https://api.zoya.finance/graphql"
FINNHUB_BASE_URL = "https://finnhub.io/api/v1"

CACHE_DAYS = 7


# ── Layer 1: Zoya ─────────────────────────────────────────────────────────────

def _zoya_screen(symbol: str) -> dict:
    """
    Call Zoya GraphQL API and return compliance info.

    Returns:
        {"status": "compliant|non_compliant|doubtful", "sector": "...", "raw": {...}}
    """
    query = """
    query GetCompliance($symbol: String!) {
      compliance(symbol: $symbol) {
        status
        businessScreen {
          verdict
          activities { name isCompliant }
        }
      }
    }
    """
    headers = {
        "Authorization": f"Bearer {ZOYA_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {"query": query, "variables": {"symbol": symbol}}

    try:
        with httpx.Client(timeout=10) as client:
            resp = client.post(ZOYA_BASE_URL, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        compliance = data.get("data", {}).get("compliance", {})
        raw_status = compliance.get("status", "unknown").lower()

        # Map Zoya statuses → our enum
        status_map = {
            "halal":       HalalStatus.COMPLIANT,
            "compliant":   HalalStatus.COMPLIANT,
            "haram":       HalalStatus.NON_COMPLIANT,
            "non_compliant": HalalStatus.NON_COMPLIANT,
            "not_halal":   HalalStatus.NON_COMPLIANT,
            "questionable": HalalStatus.DOUBTFUL,
            "doubtful":    HalalStatus.DOUBTFUL,
        }
        status = status_map.get(raw_status, HalalStatus.UNKNOWN)

        # Try to extract sector from business screen
        activities = (
            compliance.get("businessScreen", {}).get("activities", []) or []
        )
        sector = activities[0].get("name", "") if activities else ""

        return {"status": status, "sector": sector, "raw": compliance}

    except httpx.HTTPError as e:
        logger.error(f"Zoya API error for {symbol}: {e}")
        return {"status": HalalStatus.UNKNOWN, "sector": "", "raw": {}}
    except Exception as e:
        logger.error(f"Unexpected Zoya error for {symbol}: {e}")
        return {"status": HalalStatus.UNKNOWN, "sector": "", "raw": {}}


# ── Layer 2: Finnhub + Claude ratio check ─────────────────────────────────────

def _finnhub_financials(symbol: str) -> dict:
    """
    Fetch company profile and key financial metrics from Finnhub.

    Returns raw dict combining profile + metric data.
    """
    results = {}
    endpoints = {
        "profile":  f"/stock/profile2?symbol={symbol}",
        "metrics":  f"/stock/metric?symbol={symbol}&metric=all",
        "financials": f"/financials-reported?symbol={symbol}&freq=annual&limit=1",
    }
    headers = {"X-Finnhub-Token": FINNHUB_API_KEY}

    with httpx.Client(base_url=FINNHUB_BASE_URL, timeout=10, follow_redirects=True) as client:
        for key, path in endpoints.items():
            try:
                resp = client.get(path, headers=headers)
                resp.raise_for_status()
                results[key] = resp.json()
            except httpx.HTTPError as e:
                logger.warning(f"Finnhub {key} error for {symbol}: {e}")
                results[key] = {}

    return results


def _ratio_screen(symbol: str, company_name: str) -> dict:
    """
    Run Layer 2 ratio check using Finnhub data analysed by Claude.
    """
    financials = _finnhub_financials(symbol)
    if not financials.get("profile"):
        logger.warning(f"No Finnhub profile for {symbol} — skipping ratio check")
        return {
            "debt_ratio": None,
            "interest_income_pct": None,
            "haram_revenue_pct": None,
            "ratio_pass": None,
            "notes": "Finnhub data unavailable.",
        }

    return claude_module.check_financial_ratios(symbol, company_name, financials)


# ── Cache helpers ─────────────────────────────────────────────────────────────

def _get_cached(symbol: str, db: Session) -> Optional[HalalScreenResult]:
    """Return a non-expired cached screen result, or None."""
    now = datetime.now(timezone.utc)
    return (
        db.query(HalalScreenResult)
        .filter(
            HalalScreenResult.symbol == symbol,
            HalalScreenResult.expires_at > now,
        )
        .order_by(HalalScreenResult.screened_at.desc())
        .first()
    )


def _save_result(result: dict, db: Session) -> HalalScreenResult:
    """Persist a new screening result to the cache table."""
    record = HalalScreenResult(
        symbol              = result["symbol"],
        zoya_status         = result["zoya_status"],
        sector              = result.get("sector", ""),
        debt_ratio          = result.get("debt_ratio"),
        interest_income_pct = result.get("interest_income_pct"),
        haram_revenue_pct   = result.get("haram_revenue_pct"),
        ratio_pass          = result.get("ratio_pass"),
        final_status        = result["final_status"],
        notes               = result.get("notes", ""),
        expires_at          = datetime.now(timezone.utc) + timedelta(days=CACHE_DAYS),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


# ── Main public function ──────────────────────────────────────────────────────

def screen_stock(symbol: str, db: Session, force_refresh: bool = False) -> dict:
    """
    Run the full two-layer halal screen for a symbol.

    Returns:
        {
            "symbol": "AAPL",
            "zoya_status": "compliant",
            "final_status": "compliant",
            "sector": "Technology",
            "debt_ratio": 0.12,
            "interest_income_pct": 0.8,
            "haram_revenue_pct": 0.0,
            "ratio_pass": True,
            "notes": "Passes all AAOIFI thresholds.",
            "from_cache": True
        }
    """
    # Check cache first unless force refresh requested
    if not force_refresh:
        cached = _get_cached(symbol, db)
        if cached:
            logger.info(f"Halal screen cache hit: {symbol}")
            return {
                "symbol":              cached.symbol,
                "zoya_status":         cached.zoya_status,
                "final_status":        cached.final_status,
                "sector":              cached.sector,
                "debt_ratio":          float(cached.debt_ratio) if cached.debt_ratio else None,
                "interest_income_pct": float(cached.interest_income_pct) if cached.interest_income_pct else None,
                "haram_revenue_pct":   float(cached.haram_revenue_pct) if cached.haram_revenue_pct else None,
                "ratio_pass":          cached.ratio_pass,
                "notes":               cached.notes,
                "from_cache":          True,
            }

    logger.info(f"Running fresh halal screen for {symbol}")

    # ── Layer 1: Zoya ──
    zoya = _zoya_screen(symbol)
    zoya_status: HalalStatus = zoya["status"]

    # Hard block — skip ratio check entirely if Zoya says non-compliant
    if zoya_status == HalalStatus.NON_COMPLIANT:
        result = {
            "symbol":              symbol,
            "zoya_status":         zoya_status,
            "final_status":        HalalStatus.NON_COMPLIANT,
            "sector":              zoya.get("sector", ""),
            "debt_ratio":          None,
            "interest_income_pct": None,
            "haram_revenue_pct":   None,
            "ratio_pass":          None,
            "notes":               f"Hard blocked by Zoya sector screen. Sector: {zoya.get('sector', 'unknown')}",
            "from_cache":          False,
        }
        _save_result(result, db)
        return result

    # ── Layer 2: Financial ratios (only for compliant / doubtful / unknown) ──
    # Get company name from Finnhub for Claude prompt
    try:
        profile_resp = httpx.get(
            f"{FINNHUB_BASE_URL}/stock/profile2",
            params={"symbol": symbol},
            headers={"X-Finnhub-Token": FINNHUB_API_KEY},
            timeout=5,
        )
        company_name = profile_resp.json().get("name", symbol)
    except Exception:
        company_name = symbol

    ratios = _ratio_screen(symbol, company_name)
    ratio_pass = ratios.get("ratio_pass")

    # Determine final combined verdict
    if zoya_status == HalalStatus.COMPLIANT and ratio_pass is True:
        final_status = HalalStatus.COMPLIANT
    elif zoya_status == HalalStatus.NON_COMPLIANT or ratio_pass is False:
        final_status = HalalStatus.NON_COMPLIANT
    elif zoya_status == HalalStatus.DOUBTFUL or ratio_pass is None:
        final_status = HalalStatus.DOUBTFUL
    else:
        final_status = HalalStatus.UNKNOWN

    result = {
        "symbol":              symbol,
        "zoya_status":         zoya_status,
        "final_status":        final_status,
        "sector":              zoya.get("sector", ""),
        "debt_ratio":          ratios.get("debt_ratio"),
        "interest_income_pct": ratios.get("interest_income_pct"),
        "haram_revenue_pct":   ratios.get("haram_revenue_pct"),
        "ratio_pass":          ratio_pass,
        "notes":               ratios.get("notes", ""),
        "from_cache":          False,
    }
    _save_result(result, db)
    return result


def screen_watchlist(symbols: list[str], db: Session) -> list[dict]:
    """
    Screen a list of symbols. Returns results for all, even failures.
    """
    results = []
    for symbol in symbols:
        try:
            result = screen_stock(symbol, db)
            results.append(result)
        except Exception as e:
            logger.error(f"Failed to screen {symbol}: {e}")
            results.append({
                "symbol":       symbol,
                "final_status": HalalStatus.UNKNOWN,
                "notes":        f"Screening error: {str(e)}",
                "from_cache":   False,
            })
    return results
