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
    Auth: pass the API key exactly as stored — Zoya expects it as-is
    in the Authorization header (key already contains live- prefix).
    """
    query = """
    query GetCompliance($symbol: String!) {
      basicCompliance {
        report(symbol: $symbol) {
          symbol
          name
          exchange
          status
        }
      }
    }
    """
    headers = {
        "Authorization": ZOYA_API_KEY,
        "Content-Type": "application/json",
    }
    payload = {"query": query, "variables": {"symbol": symbol}}

    logger.info(f"Calling Zoya for {symbol} (key prefix: {ZOYA_API_KEY[:10]}...)")

    try:
        with httpx.Client(timeout=15) as client:
            resp = client.post(ZOYA_BASE_URL, json=payload, headers=headers)

        logger.info(f"Zoya response status: {resp.status_code}")

        if resp.status_code == 401:
            logger.error(f"Zoya 401 — check API key. Response: {resp.text[:200]}")
            return {"status": HalalStatus.UNKNOWN, "sector": "", "raw": {}}

        resp.raise_for_status()
        data = resp.json()
        logger.info(f"Zoya raw response for {symbol}: {data}")

        # Navigate basicCompliance.report path
        report = (
            data.get("data", {})
                .get("basicCompliance", {})
                .get("report", {})
        )

        if not report:
            logger.warning(f"Zoya returned no report for {symbol}: {data}")
            return {"status": HalalStatus.UNKNOWN, "sector": "", "raw": data}

        raw_status = report.get("status", "unknown").upper()
        logger.info(f"Zoya status for {symbol}: {raw_status}")

        status_map = {
            "COMPLIANT":     HalalStatus.COMPLIANT,
            "HALAL":         HalalStatus.COMPLIANT,
            "NON_COMPLIANT": HalalStatus.NON_COMPLIANT,
            "NOT_HALAL":     HalalStatus.NON_COMPLIANT,
            "HARAM":         HalalStatus.NON_COMPLIANT,
            "QUESTIONABLE":  HalalStatus.DOUBTFUL,
            "DOUBTFUL":      HalalStatus.DOUBTFUL,
            "UNKNOWN":       HalalStatus.UNKNOWN,
        }
        status = status_map.get(raw_status, HalalStatus.UNKNOWN)

        return {
            "status":  status,
            "sector":  report.get("exchange", ""),
            "raw":     report,
        }

    except httpx.HTTPStatusError as e:
        logger.error(f"Zoya HTTP error for {symbol}: {e} — {e.response.text[:200]}")
        return {"status": HalalStatus.UNKNOWN, "sector": "", "raw": {}}
    except Exception as e:
        logger.error(f"Unexpected Zoya error for {symbol}: {e}")
        return {"status": HalalStatus.UNKNOWN, "sector": "", "raw": {}}


# ── Layer 2: Finnhub + Claude ratio check ──────────────────────────────────────

def _finnhub_financials(symbol: str) -> dict:
    """
    Fetch company profile and key financial metrics from Finnhub.
    Handles redirects and non-JSON responses gracefully.
    """
    results = {}
    endpoints = {
        "profile": f"/stock/profile2?symbol={symbol}",
        "metrics": f"/stock/metric?symbol={symbol}&metric=all",
    }
    headers = {"X-Finnhub-Token": FINNHUB_API_KEY}

    with httpx.Client(
        base_url=FINNHUB_BASE_URL,
        timeout=10,
        follow_redirects=True,
    ) as client:
        for key, path in endpoints.items():
            try:
                resp = client.get(path, headers=headers)
                resp.raise_for_status()
                # Guard against empty or non-JSON responses
                content = resp.text.strip()
                if not content or content.startswith("<"):
                    logger.warning(f"Finnhub {key} for {symbol}: non-JSON response, skipping")
                    results[key] = {}
                    continue
                results[key] = resp.json()
            except httpx.HTTPStatusError as e:
                logger.warning(f"Finnhub {key} HTTP error for {symbol}: {e}")
                results[key] = {}
            except Exception as e:
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
            "debt_ratio":          None,
            "interest_income_pct": None,
            "haram_revenue_pct":   None,
            "ratio_pass":          None,
            "notes":               "Finnhub data unavailable — ratio check skipped.",
        }
    return claude_module.check_financial_ratios(symbol, company_name, financials)


# ── Cache helpers ─────────────────────────────────────────────────────────────

def _get_cached(symbol: str, db: Session) -> Optional[HalalScreenResult]:
    now = datetime.now(timezone.utc)
    return (
        db.query(HalalScreenResult)
        .filter(
            HalalScreenResult.symbol     == symbol,
            HalalScreenResult.expires_at >  now,
        )
        .order_by(HalalScreenResult.screened_at.desc())
        .first()
    )


def _save_result(result: dict, db: Session) -> HalalScreenResult:
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
    """
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
    zoya        = _zoya_screen(symbol)
    zoya_status = zoya["status"]

    # Hard block — skip ratio check entirely
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
            "notes":               f"Hard blocked by Zoya. Sector: {zoya.get('sector', 'unknown')}",
            "from_cache":          False,
        }
        _save_result(result, db)
        return result

    # ── Layer 2: Financial ratios ──
    try:
        profile_resp = httpx.get(
            f"{FINNHUB_BASE_URL}/stock/profile2",
            params={"symbol": symbol},
            headers={"X-Finnhub-Token": FINNHUB_API_KEY},
            timeout=5,
            follow_redirects=True,
        )
        company_name = profile_resp.json().get("name", symbol) if profile_resp.is_success else symbol
    except Exception:
        company_name = symbol

    ratios     = _ratio_screen(symbol, company_name)
    ratio_pass = ratios.get("ratio_pass")

    # Decision matrix:
    # - Zoya COMPLIANT + ratios pass      → COMPLIANT
    # - Zoya COMPLIANT + ratios unavailable → COMPLIANT (trust Zoya; Finnhub free tier
    #   is unreliable and rate-limits frequently — don't penalise for missing data)
    # - Zoya COMPLIANT + ratios fail       → NON_COMPLIANT (explicit financial violation)
    # - Zoya NON_COMPLIANT (any ratios)    → NON_COMPLIANT (hard sector block)
    # - Zoya DOUBTFUL                      → DOUBTFUL
    # - Zoya UNKNOWN                       → UNKNOWN
    if zoya_status == HalalStatus.NON_COMPLIANT:
        final_status = HalalStatus.NON_COMPLIANT
    elif ratio_pass is False:
        final_status = HalalStatus.NON_COMPLIANT
    elif zoya_status == HalalStatus.COMPLIANT:
        # Trust Zoya as authoritative — pass regardless of whether ratio data was available
        final_status = HalalStatus.COMPLIANT
    elif zoya_status == HalalStatus.DOUBTFUL:
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
    results = []
    for symbol in symbols:
        try:
            results.append(screen_stock(symbol, db))
        except Exception as e:
            logger.error(f"Failed to screen {symbol}: {e}")
            results.append({
                "symbol":       symbol,
                "final_status": HalalStatus.UNKNOWN,
                "notes":        f"Screening error: {str(e)}",
                "from_cache":   False,
            })
    return results
