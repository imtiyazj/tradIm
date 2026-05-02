"""
risk.py — Position sizing and stop-loss management.

Kelly criterion-lite position tiers:
  confidence >= 0.85  →  6% of portfolio  (strong signal)
  confidence >= 0.75  →  4% of portfolio  (good signal)
  confidence >= 0.65  →  2% of portfolio  (moderate signal)
  confidence < 0.65   →  0% (skip — not worth the risk)

Stop-loss:   7% below entry price
Take-profit: 15% above entry price
"""

# ── Constants ─────────────────────────────────────────────────────────────────

STOP_LOSS_PCT   = 0.07
TAKE_PROFIT_PCT = 0.15
MIN_CONFIDENCE  = 0.65


# ── Internal helpers ──────────────────────────────────────────────────────────

def _portfolio_pct(confidence: float) -> float:
    """Return the portfolio allocation fraction for a given confidence score."""
    if confidence >= 0.85:
        return 0.06
    if confidence >= 0.75:
        return 0.04
    if confidence >= 0.65:
        return 0.02
    return 0.0


def _confidence_tier(confidence: float) -> str:
    """Return a human-readable confidence tier label."""
    if confidence >= 0.85:
        return "Strong (>=85%)"
    if confidence >= 0.75:
        return "Good (>=75%)"
    if confidence >= 0.65:
        return "Moderate (>=65%)"
    return "Below minimum (<65%)"


# ── Public API ────────────────────────────────────────────────────────────────

def position_size_dollars(confidence: float, portfolio_value: float) -> float:
    """
    Return the dollar amount to invest based on confidence and portfolio value.
    Returns 0.0 if confidence is below MIN_CONFIDENCE.
    """
    pct = _portfolio_pct(confidence)
    return round(pct * portfolio_value, 2)


def position_size_shares(confidence: float, portfolio_value: float, price: float) -> float:
    """
    Return the number of shares (fractional) to buy, rounded to 3 decimal places.
    Returns 0.0 if confidence is below MIN_CONFIDENCE or price is zero.
    """
    if price <= 0:
        return 0.0
    dollars = position_size_dollars(confidence, portfolio_value)
    if dollars == 0.0:
        return 0.0
    return round(dollars / price, 3)


def stop_loss_price(entry: float) -> float:
    """Return the stop-loss price: 7% below entry, rounded to 2 decimal places."""
    return round(entry * (1.0 - STOP_LOSS_PCT), 2)


def take_profit_price(entry: float) -> float:
    """Return the take-profit price: 15% above entry, rounded to 2 decimal places."""
    return round(entry * (1.0 + TAKE_PROFIT_PCT), 2)


def size_summary(confidence: float, portfolio_value: float, price: float) -> dict:
    """
    Return a full sizing breakdown dictionary.

    Keys:
      dollars          - dollar amount to invest
      shares           - fractional shares to buy (3dp)
      stop_loss        - stop-loss price (2dp)
      take_profit      - take-profit price (2dp)
      portfolio_pct    - allocation as a percentage (e.g. 6.0 for 6%)
      confidence_tier  - human-readable tier label
      tradeable        - True if confidence >= MIN_CONFIDENCE
    """
    pct     = _portfolio_pct(confidence)
    dollars = position_size_dollars(confidence, portfolio_value)
    shares  = position_size_shares(confidence, portfolio_value, price)

    return {
        "dollars":         dollars,
        "shares":          shares,
        "stop_loss":       stop_loss_price(price),
        "take_profit":     take_profit_price(price),
        "portfolio_pct":   round(pct * 100, 1),
        "confidence_tier": _confidence_tier(confidence),
        "tradeable":       confidence >= MIN_CONFIDENCE,
    }
