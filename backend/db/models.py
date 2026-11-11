from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import (
    Column, String, Integer, Numeric, Boolean,
    DateTime, Text, ForeignKey, Enum, Index,
    create_engine, event
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, relationship
from sqlalchemy.sql import func, text
import uuid
import enum
import os


DATABASE_URL = os.environ["DATABASE_URL"].replace("postgres://", "postgresql://", 1)


class Base(DeclarativeBase):
    pass


# ── Enums ─────────────────────────────────────────────────────────────────────

class TradeSide(str, enum.Enum):
    BUY  = "buy"
    SELL = "sell"


class HalalStatus(str, enum.Enum):
    COMPLIANT     = "compliant"
    NON_COMPLIANT = "non_compliant"
    DOUBTFUL      = "doubtful"
    UNKNOWN       = "unknown"


class AlertType(str, enum.Enum):
    PRICE_TARGET   = "price_target"
    NEWS_SENTIMENT = "news_sentiment"
    HALAL_CHANGE   = "halal_change"
    STRATEGY       = "strategy"
    TAX            = "tax"


class AlertChannel(str, enum.Enum):
    TELEGRAM = "telegram"
    EMAIL    = "email"


# ── Models ────────────────────────────────────────────────────────────────────

class User(Base):
    """Single user — private app, but proper auth is enforced."""
    __tablename__ = "users"

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email      = Column(String(255), unique=True, nullable=False, index=True)
    # Clerk manages auth; this clerk_id links to the Clerk user record
    clerk_id   = Column(String(255), unique=True, nullable=False, index=True)
    is_active  = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    trades     = relationship("Trade",         back_populates="user", cascade="all, delete-orphan")
    signals    = relationship("Signal",        back_populates="user", cascade="all, delete-orphan")
    alerts     = relationship("AlertLog",      back_populates="user", cascade="all, delete-orphan")
    watchlist  = relationship("WatchlistItem", back_populates="user", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<User {self.email}>"


class Trade(Base):
    """Every trade executed via Alpaca — logged for tax + audit purposes."""
    __tablename__ = "trades"

    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id         = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    alpaca_order_id = Column(String(100), unique=True, nullable=True, index=True)
    symbol          = Column(String(20), nullable=False, index=True)
    side            = Column(Enum(TradeSide), nullable=False)
    quantity        = Column(Numeric(18, 8), nullable=False)
    price           = Column(Numeric(18, 4), nullable=False)
    fees            = Column(Numeric(18, 4), default=Decimal("0.00"), nullable=False)
    total_value     = Column(Numeric(18, 4), nullable=False)  # price * qty
    halal_status    = Column(Enum(HalalStatus), nullable=False)
    is_paper        = Column(Boolean, default=True, nullable=False)  # paper vs live
    traded_at       = Column(DateTime(timezone=True), nullable=False)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="trades")

    __table_args__ = (
        Index("ix_trades_user_symbol", "user_id", "symbol"),
        Index("ix_trades_user_traded_at", "user_id", "traded_at"),
    )

    def __repr__(self):
        return f"<Trade {self.side} {self.quantity} {self.symbol} @ {self.price}>"


class HalalScreenResult(Base):
    """Cache of Zoya + financial ratio screening results per ticker."""
    __tablename__ = "halal_screen_results"

    id                  = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    symbol              = Column(String(20), nullable=False, index=True)
    zoya_status         = Column(Enum(HalalStatus), nullable=False)
    sector              = Column(String(100), nullable=True)
    # Financial ratios (Layer 2 — from Finnhub + Claude)
    debt_ratio          = Column(Numeric(8, 4), nullable=True)   # debt / market cap
    interest_income_pct = Column(Numeric(8, 4), nullable=True)   # % of revenue
    haram_revenue_pct   = Column(Numeric(8, 4), nullable=True)   # % of revenue
    ratio_pass          = Column(Boolean, nullable=True)
    # Combined verdict
    final_status        = Column(Enum(HalalStatus), nullable=False)
    notes               = Column(Text, nullable=True)
    screened_at         = Column(DateTime(timezone=True), server_default=func.now())
    # Cache expires after 7 days — scheduler refreshes weekly
    expires_at          = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_halal_symbol_expires", "symbol", "expires_at"),
    )

    def __repr__(self):
        return f"<HalalScreenResult {self.symbol}: {self.final_status}>"


class Signal(Base):
    """Research signals generated by Claude each morning."""
    __tablename__ = "signals"

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id      = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    symbol       = Column(String(20), nullable=False, index=True)
    signal_type  = Column(String(50), nullable=False)   # e.g. "buy", "sell", "watch", "avoid"
    confidence   = Column(Numeric(4, 3), nullable=True) # 0.0 – 1.0
    reasoning    = Column(Text, nullable=False)          # Claude's explanation
    price_at     = Column(Numeric(18, 4), nullable=True)
    triggered_at = Column(DateTime(timezone=True), server_default=func.now())
    acted_on     = Column(Boolean, default=False)        # did a trade fire from this?

    user = relationship("User", back_populates="signals")

    __table_args__ = (
        Index("ix_signals_user_triggered", "user_id", "triggered_at"),
    )

    def __repr__(self):
        return f"<Signal {self.signal_type} {self.symbol} conf={self.confidence}>"


class AlertLog(Base):
    """Record of every alert sent — Telegram, email, etc."""
    __tablename__ = "alert_logs"

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id    = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    alert_type = Column(Enum(AlertType), nullable=False)
    channel    = Column(Enum(AlertChannel), nullable=False)
    symbol     = Column(String(20), nullable=True)
    message    = Column(Text, nullable=False)
    sent_ok    = Column(Boolean, default=True)
    sent_at    = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="alerts")

    def __repr__(self):
        return f"<AlertLog {self.alert_type} via {self.channel} at {self.sent_at}>"


class WatchlistItem(Base):
    """Stocks the user wants the system to track and screen daily."""
    __tablename__ = "watchlist_items"

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id    = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    symbol     = Column(String(20), nullable=False)
    notes      = Column(Text, nullable=True)
    added_at   = Column(DateTime(timezone=True), server_default=func.now())
    is_active  = Column(Boolean, default=True)

    user = relationship("User", back_populates="watchlist")

    __table_args__ = (
        Index("ix_watchlist_user_symbol", "user_id", "symbol", unique=True),
    )

    def __repr__(self):
        return f"<WatchlistItem {self.symbol}>"


class DailyReport(Base):
    """Summary of each day's scheduler run — stored for dashboard display."""
    __tablename__ = "daily_reports"

    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id         = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    report_date     = Column(DateTime(timezone=True), nullable=False, index=True)
    stocks_screened = Column(Integer, default=0)
    halal_passed    = Column(Integer, default=0)
    signals_fired   = Column(Integer, default=0)
    trades_executed = Column(Integer, default=0)
    alerts_sent     = Column(Integer, default=0)
    summary         = Column(Text, nullable=True)   # Claude's plain-English summary
    raw_json        = Column(Text, nullable=True)   # full JSON payload for debugging
    created_at      = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self):
        return f"<DailyReport {self.report_date.date()}>"


class SignalPerformance(Base):
    """
    Forward returns for each signal — the feedback loop that tells us whether
    Claude's signals (and their confidence scores) actually predict anything.

    One row per signal. Horizons are filled in as they become measurable
    (1w after ~7 calendar days, etc.) by the nightly performance job.
    bench_* columns hold the SPUS (halal S&P 500 ETF) return over the same
    window, so alpha = return_X - bench_return_X.
    """
    __tablename__ = "signal_performance"

    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    signal_id       = Column(UUID(as_uuid=True), ForeignKey("signals.id", ondelete="CASCADE"),
                             nullable=False, unique=True, index=True)
    # Copied from the signal for cheap aggregate queries
    symbol          = Column(String(20), nullable=False, index=True)
    signal_type     = Column(String(50), nullable=False)
    confidence      = Column(Numeric(4, 3), nullable=True)
    price_at        = Column(Numeric(18, 4), nullable=False)
    triggered_at    = Column(DateTime(timezone=True), nullable=False)
    # Forward returns in percent (e.g. 4.2 = +4.2%); NULL until measurable
    return_1w       = Column(Numeric(10, 4), nullable=True)
    return_1m       = Column(Numeric(10, 4), nullable=True)
    return_3m       = Column(Numeric(10, 4), nullable=True)
    bench_return_1w = Column(Numeric(10, 4), nullable=True)
    bench_return_1m = Column(Numeric(10, 4), nullable=True)
    bench_return_3m = Column(Numeric(10, 4), nullable=True)
    updated_at      = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    signal = relationship("Signal")

    __table_args__ = (
        Index("ix_signal_perf_type_conf", "signal_type", "confidence"),
    )

    def __repr__(self):
        return f"<SignalPerformance {self.symbol} {self.signal_type} 1m={self.return_1m}>"


class ComplianceCheck(Base):
    """
    Audit trail of the quarterly Shariah compliance review.

    One row per symbol per review run. Unlike halal_screen_results (a cache
    that is overwritten in spirit every week), these rows are never expired:
    they record what each holding's status was at each review and whether it
    changed since the previous one.
    """
    __tablename__ = "compliance_checks"

    id                = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id           = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    # All rows written by one review share a run_id
    run_id            = Column(UUID(as_uuid=True), nullable=False, index=True)
    period            = Column(String(10), nullable=False, index=True)   # e.g. "2026-Q4"
    symbol            = Column(String(20), nullable=False, index=True)
    previous_status   = Column(Enum(HalalStatus), nullable=True)         # NULL = first time reviewed
    new_status        = Column(Enum(HalalStatus), nullable=False)
    status_changed    = Column(Boolean, default=False, nullable=False)
    # True when the screen could not reach a verdict (Zoya down, UNKNOWN) —
    # such rows never count as a status change.
    inconclusive      = Column(Boolean, default=False, nullable=False)
    is_held           = Column(Boolean, default=False, nullable=False)   # open position at review time
    quantity          = Column(Numeric(18, 8), nullable=True)
    market_value      = Column(Numeric(18, 4), nullable=True)
    debt_ratio        = Column(Numeric(8, 4), nullable=True)
    haram_revenue_pct = Column(Numeric(8, 4), nullable=True)
    notes             = Column(Text, nullable=True)
    checked_at        = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_compliance_symbol_checked", "symbol", "checked_at"),
    )

    def __repr__(self):
        return f"<ComplianceCheck {self.period} {self.symbol}: {self.new_status}>"


class PurificationEntry(Base):
    """
    Dividend purification ledger.

    One row per dividend received. purification_amount is the share of the
    dividend attributable to impermissible income (income_amount * impure_pct)
    that should be given to charity. is_paid tracks whether it has been donated.
    """
    __tablename__ = "purification_entries"

    id                  = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id             = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    symbol              = Column(String(20), nullable=False, index=True)
    # Alpaca account-activity id — makes the dividend sync idempotent
    alpaca_activity_id  = Column(String(100), unique=True, nullable=True, index=True)
    income_date         = Column(DateTime(timezone=True), nullable=False)
    income_amount       = Column(Numeric(18, 4), nullable=False)
    impure_pct          = Column(Numeric(8, 4), nullable=False)    # fraction, e.g. 0.0210 = 2.1%
    # "screen" = haram-revenue share from the halal screen;
    # "default_cap" = share unknown, 5% compliance ceiling used as an upper bound
    rate_source         = Column(String(20), nullable=False)
    purification_amount = Column(Numeric(18, 4), nullable=False)
    is_paper            = Column(Boolean, default=True, nullable=False)
    is_paid             = Column(Boolean, default=False, nullable=False)
    paid_at             = Column(DateTime(timezone=True), nullable=True)
    note                = Column(Text, nullable=True)
    created_at          = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_purification_user_date", "user_id", "income_date"),
    )

    def __repr__(self):
        return f"<PurificationEntry {self.symbol} {self.income_amount} -> {self.purification_amount}>"


# ── Database engine helpers ───────────────────────────────────────────────────

def get_engine():
    return create_engine(
        DATABASE_URL,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
        echo=False,
    )


def create_tables():
    """Create all tables. Call once at startup if not using Alembic yet."""
    engine = get_engine()
    Base.metadata.create_all(engine)
    print("✅ Database tables created.")


def enable_rls(engine):
    """
    Enable PostgreSQL row-level security on sensitive tables.
    Run once after table creation — ensures users only see their own data.
    """
    rls_statements = [
        "ALTER TABLE trades           ENABLE ROW LEVEL SECURITY;",
        "ALTER TABLE signals          ENABLE ROW LEVEL SECURITY;",
        "ALTER TABLE alert_logs       ENABLE ROW LEVEL SECURITY;",
        "ALTER TABLE watchlist_items  ENABLE ROW LEVEL SECURITY;",
        "ALTER TABLE daily_reports    ENABLE ROW LEVEL SECURITY;",
    ]
    with engine.connect() as conn:
        for stmt in rls_statements:
            try:
                conn.execute(text(stmt))
                print(f"✅ RLS enabled: {stmt}")
            except Exception as e:
                print(f"⚠️  RLS skip (may already be set): {e}")
        conn.commit()
