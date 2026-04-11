"""
claude.py — Anthropic API integration.

Handles all Claude calls:
  - Morning stock research & signal generation
  - Financial ratio analysis for halal Layer 2 screening
  - Tax flag detection
  - Daily summary generation
  - Alert message drafting
"""

import os
import json
import logging
from typing import Optional
import anthropic

logger = logging.getLogger(__name__)

# ── Client ────────────────────────────────────────────────────────────────────

_client: Optional[anthropic.Anthropic] = None


def get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


MODEL = "claude-sonnet-4-5"
MAX_TOKENS = 2048


# ── Shared system prompt ──────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a Shariah-compliant stock research assistant for a private investor.

CORE RULES:
- Only recommend or analyse stocks that pass Shariah (AAOIFI) screening
- Hard-blocked sectors: alcohol, tobacco, weapons/defence, gambling, 
  conventional banking/insurance, pork, cannabis, adult entertainment
- Financial ratio thresholds: debt/market-cap <33%, interest income <5% of revenue,
  haram revenue <5% of total revenue
- The investor is on an H-1B visa — passive investing only, no day trading
- Always be factual, cite your reasoning, flag uncertainty clearly
- Never provide direct buy/sell advice — provide research and signals only
- Respond ONLY with valid JSON when JSON is requested — no markdown, no preamble"""


# ── 1. Morning stock research ─────────────────────────────────────────────────

def analyse_stocks(
    watchlist: list[dict],
    market_data: dict,
    news_items: list[dict],
) -> dict:
    """
    Run morning analysis on the watchlist.

    Args:
        watchlist:   [{"symbol": "AAPL", "halal_status": "compliant", ...}]
        market_data: {"AAPL": {"price": 182.5, "change_pct": 1.2, ...}, ...}
        news_items:  [{"symbol": "AAPL", "headline": "...", "sentiment": "positive"}]

    Returns:
        {
            "signals": [{"symbol": "AAPL", "type": "watch", "confidence": 0.72, "reasoning": "..."}],
            "summary": "Plain-English summary of today's analysis",
            "tax_flags": [{"symbol": "AAPL", "note": "approaching 1-year hold for long-term gains"}]
        }
    """
    prompt = f"""Analyse the following halal-screened stocks for today's session.

WATCHLIST WITH HALAL STATUS:
{json.dumps(watchlist, indent=2)}

MARKET DATA (prices, % change, volume):
{json.dumps(market_data, indent=2)}

RECENT NEWS:
{json.dumps(news_items[:20], indent=2)}

Return a JSON object with exactly these keys:
{{
  "signals": [
    {{
      "symbol": "TICKER",
      "type": "buy|sell|watch|avoid",
      "confidence": 0.0-1.0,
      "reasoning": "2-3 sentence explanation"
    }}
  ],
  "summary": "3-5 sentence plain-English summary of today's market picture",
  "tax_flags": [
    {{
      "symbol": "TICKER",
      "note": "tax-relevant observation e.g. approaching 365-day hold"
    }}
  ]
}}"""

    fallback = {"signals": [], "summary": "Analysis unavailable today.", "tax_flags": []}
    try:
        response = get_client().messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()

        if not raw:
            logger.warning("Claude returned empty response in analyse_stocks")
            return fallback

        # Strip markdown code fences if present
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(
                line for line in lines
                if not line.strip().startswith("```")
            ).strip()

        return json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error(f"Claude JSON parse error in analyse_stocks: {e}\nRaw: {raw!r}")
        return fallback
    except Exception as e:
        logger.error(f"Claude API error in analyse_stocks: {e}")
        return fallback

# ── 2. Halal financial ratio check (Layer 2) ──────────────────────────────────

def check_financial_ratios(
    symbol: str,
    company_name: str,
    financials: dict,
) -> dict:
    """
    Analyse financial ratios from Finnhub data for AAOIFI compliance.

    Args:
        symbol:       "AAPL"
        company_name: "Apple Inc"
        financials:   raw Finnhub metric + profile data

    Returns:
        {
            "debt_ratio": 0.12,
            "interest_income_pct": 0.8,
            "haram_revenue_pct": 0.0,
            "ratio_pass": true,
            "notes": "All ratios within AAOIFI limits."
        }
    """
    prompt = f"""Analyse the following financial data for {company_name} ({symbol}) 
against AAOIFI Shariah financial screening thresholds.

FINANCIAL DATA:
{json.dumps(financials, indent=2)}

AAOIFI thresholds to check:
1. Total debt / market capitalisation must be < 33%
2. Interest income / total revenue must be < 5%
3. Revenue from haram activities / total revenue must be < 5%

Extract or estimate each ratio from the data provided. If a ratio cannot be determined, 
set it to null and explain why in notes.

Return ONLY a JSON object:
{{
  "debt_ratio": <number or null>,
  "interest_income_pct": <number or null>,
  "haram_revenue_pct": <number or null>,
  "ratio_pass": <true|false|null>,
  "notes": "<brief explanation>"
}}"""

    fallback = {
        "debt_ratio": None, "interest_income_pct": None,
        "haram_revenue_pct": None, "ratio_pass": None,
        "notes": "Ratio data unavailable."
    }
    try:
        response = get_client().messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        logger.info(f"Claude ratio raw response for {symbol}: {raw[:200]}")

        if not raw:
            logger.warning(f"Claude returned empty response for {symbol} ratios")
            fallback["notes"] = "Claude returned empty response."
            return fallback

        # Strip markdown code fences if present (```json ... ```)
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(
                line for line in lines
                if not line.strip().startswith("```")
            ).strip()

        return json.loads(raw)

    except json.JSONDecodeError as e:
        logger.error(f"Claude JSON parse error in check_financial_ratios: {e}\nRaw: {raw!r}")
        fallback["notes"] = "Could not parse ratio response."
        return fallback
    except Exception as e:
        logger.error(f"Claude API error in check_financial_ratios: {e}")
        fallback["notes"] = f"API error: {str(e)}"
        return fallback


# ── 3. Tax analysis ───────────────────────────────────────────────────────────

def generate_tax_summary(
    trades: list[dict],
    current_positions: list[dict],
    tax_year: int,
) -> dict:
    """
    Generate a tax summary from logged trades.

    Args:
        trades:            list of trade dicts from PostgreSQL
        current_positions: current open positions with cost basis
        tax_year:          e.g. 2024

    Returns:
        {
            "short_term_gains": 1234.56,
            "long_term_gains": 4567.89,
            "total_realized": 5802.45,
            "harvesting_opportunities": [...],
            "quarterly_estimate": 890.00,
            "schedule_d_rows": [...],
            "notes": "..."
        }
    """
    prompt = f"""Generate a tax summary for tax year {tax_year} from these trades.

COMPLETED TRADES (buy and sell pairs):
{json.dumps(trades, indent=2)}

CURRENT OPEN POSITIONS (potential loss harvesting):
{json.dumps(current_positions, indent=2)}

Using FIFO cost basis method, calculate:
1. Short-term capital gains (held < 365 days)
2. Long-term capital gains (held >= 365 days)
3. Total realized gains/losses
4. Tax-loss harvesting opportunities in open positions
5. Estimated quarterly tax owed (assume 25% effective rate for simplicity)
6. Schedule D summary rows

Return ONLY a JSON object:
{{
  "short_term_gains": <number>,
  "long_term_gains": <number>,
  "total_realized": <number>,
  "harvesting_opportunities": [
    {{"symbol": "TICKER", "unrealized_loss": <number>, "note": "..."}}
  ],
  "quarterly_estimate": <number>,
  "schedule_d_rows": [
    {{
      "symbol": "TICKER", "acquired": "YYYY-MM-DD", "sold": "YYYY-MM-DD",
      "proceeds": <number>, "cost_basis": <number>, "gain_loss": <number>,
      "term": "short|long"
    }}
  ],
  "notes": "<any important caveats>"
}}"""

    try:
        response = get_client().messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        return json.loads(raw)
    except Exception as e:
        logger.error(f"Claude API error in generate_tax_summary: {e}")
        return {"error": str(e), "notes": "Tax summary unavailable."}


# ── 4. Draft alert message ────────────────────────────────────────────────────

def draft_alert_message(
    alert_type: str,
    symbol: str,
    context: dict,
) -> str:
    """
    Draft a concise Telegram / email alert message.

    Args:
        alert_type: "price_target" | "news_sentiment" | "halal_change" | "strategy" | "tax"
        symbol:     "AAPL"
        context:    dict with relevant data for the alert type

    Returns:
        Plain-text message string suitable for Telegram.
    """
    prompt = f"""Draft a concise alert message for the following event.

ALERT TYPE: {alert_type}
SYMBOL: {symbol}
CONTEXT:
{json.dumps(context, indent=2)}

Rules:
- Maximum 5 lines
- No markdown formatting (plain text only)
- Include: ticker, what happened, why it matters
- Tone: informational, not alarmist
- End with one suggested action to consider (not a buy/sell recommendation)

Return ONLY the message text, nothing else."""

    try:
        response = get_client().messages.create(
            model=MODEL,
            max_tokens=256,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()
    except Exception as e:
        logger.error(f"Claude API error in draft_alert_message: {e}")
        return f"Alert: {alert_type} triggered for {symbol}. Check dashboard for details."


# ── 5. Daily summary ──────────────────────────────────────────────────────────

def generate_daily_summary(report_data: dict) -> str:
    """
    Generate the plain-English daily summary shown on the dashboard.

    Args:
        report_data: dict with stocks_screened, signals, trades, alerts counts + details

    Returns:
        3-5 sentence summary string.
    """
    prompt = f"""Write a 3-5 sentence plain-English summary of today's trading app activity.

REPORT DATA:
{json.dumps(report_data, indent=2)}

Rules:
- Write as if briefing yourself at end of day
- Mention: stocks screened, any notable signals, trades executed, alerts sent
- Flag anything requiring attention tomorrow
- No jargon, no markdown, just clear sentences

Return ONLY the summary text."""

    try:
        response = get_client().messages.create(
            model=MODEL,
            max_tokens=512,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()
    except Exception as e:
        logger.error(f"Claude API error in generate_daily_summary: {e}")
        return "Daily summary unavailable."
