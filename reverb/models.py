from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Direction(str, Enum):
    CALL = "call"
    PUT = "put"


class View(str, Enum):
    BEAT = "beat"
    MISS = "miss"

    @property
    def direction(self) -> Direction:
        return Direction.CALL if self is View.BEAT else Direction.PUT


class DecisionStatus(str, Enum):
    ACT = "act"
    HOLD = "hold"
    REFUSE = "refuse"


class ReasonCode(str, Enum):
    MARKET_EXPECTS_LARGER_MOVE = "market_expects_larger_move"
    NEGATIVE_EXPECTED_VALUE = "negative_expected_value_after_volatility_scenario"
    STALE_UNDERLYING = "stale_underlying"
    STALE_OPTION = "stale_option"
    STALE_REACTION = "stale_reaction_quote"
    OPTION_BID_ASK_UNAVAILABLE = "option_bid_ask_unavailable"
    MISSING_LEG = "missing_leg"
    MAX_LOSS_EXCEEDED = "max_loss_exceeded"
    SESSION_UNAVAILABLE = "session_unavailable"
    INVALID_CONTRACT = "invalid_contract"
    API_NOT_ENTITLED = "api_not_entitled"
    DATA_UNAVAILABLE = "data_unavailable"
    PAIR_BID_ASK_UNAVAILABLE = "paired_straddle_bid_ask_unavailable"
    CALENDAR_UNAVAILABLE = "earnings_calendar_unavailable"
    INVALID_INPUT = "invalid_input"
    UNVERIFIED_ASSUMPTION = "unverified_assumption"
    BASELINE_UNAVAILABLE = "baseline_unavailable"
    INVALID_ORDER_INTENT = "invalid_order_intent"
    INSTRUMENT_UNAVAILABLE = "instrument_unavailable"
    PRECISION_UNVERIFIED = "precision_unverified"
    RISK_BUDGET_EXCEEDED = "risk_budget_exceeded"
    REPLAY_UNAVAILABLE = "replay_unavailable"


class Thesis(StrictModel):
    symbol: str = Field(min_length=1)
    view: View
    expected_move_pct: Decimal = Field(gt=Decimal("0"), lt=Decimal("1"))
    max_loss: Decimal = Field(gt=Decimal("0"))
    event_at: datetime
    user_timezone: str = Field(min_length=1)

    @field_validator("symbol")
    @classmethod
    def symbol_is_uppercase(cls, value: str) -> str:
        return value.upper()

    @field_validator("event_at")
    @classmethod
    def event_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("event_at must include a timezone")
        return value


class UnderlyingQuote(StrictModel):
    symbol: str
    price: Decimal = Field(gt=Decimal("0"))
    bid: Decimal | None = Field(default=None, gt=Decimal("0"))
    ask: Decimal | None = Field(default=None, gt=Decimal("0"))
    observed_at: datetime
    source_timestamp: datetime

    @field_validator("observed_at", "source_timestamp")
    @classmethod
    def timestamps_are_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("quote timestamps must include a timezone")
        return value


class OptionQuote(StrictModel):
    symbol: str
    underlying_symbol: str
    direction: Direction
    strike: Decimal = Field(gt=Decimal("0"))
    expiry: date
    contract_multiplier: Decimal = Field(gt=Decimal("0"))
    last_done: Decimal | None = Field(default=None, gt=Decimal("0"))
    bid: Decimal | None = Field(default=None, gt=Decimal("0"))
    ask: Decimal | None = Field(default=None, gt=Decimal("0"))
    published_iv: Decimal | None = Field(default=None, gt=Decimal("0"), lt=Decimal("10"))
    observed_at: datetime
    source_timestamp: datetime
    trade_status: str | None = None

    @field_validator("observed_at", "source_timestamp")
    @classmethod
    def timestamps_are_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("option timestamps must include a timezone")
        return value

    @property
    def executable(self) -> bool:
        return (self.bid is not None and self.ask is not None and self.ask >= self.bid
                and self.trade_status in {None, "1", "online", "ONLINE", "active", "ACTIVE"})


class Valuation(StrictModel):
    premium: Decimal
    implied_volatility: Decimal
    published_implied_volatility: Decimal | None
    delta: Decimal
    gamma: Decimal
    vega: Decimal
    theta_per_year: Decimal
    breakeven_price: Decimal
    breakeven_move_pct: Decimal
    implied_move_pct: Decimal | None
    scenario_value_after_event: Decimal | None
    scenario_pnl: Decimal | None


class Decision(StrictModel):
    decision_id: str
    status: DecisionStatus
    symbol: str
    reason_codes: tuple[ReasonCode, ...]
    thesis: Thesis
    instrument: OptionQuote | None
    contracts: int
    maximum_loss: Decimal | None
    valuation: Valuation | None
    arithmetic: dict[str, str]
    inputs: dict[str, Any]
    created_at: datetime


class ReactionDecision(StrictModel):
    decision_id: str
    status: DecisionStatus
    symbol: str
    session: str
    baseline_price: Decimal | None
    observed_price: Decimal | None
    move_pct: Decimal | None
    trigger_pct: Decimal
    reason_codes: tuple[ReasonCode, ...]
    observed_at: datetime
    arithmetic: dict[str, str]
    intended_side: str | None = None
    order_quantity: Decimal | None = None
    order_price: Decimal | None = None
    maximum_loss: Decimal | None = None
    risk_budget: Decimal | None = None


class ToolDecision(StrictModel):
    """Stable consumer-facing envelope; it never contains a raw API response."""

    decision_id: str
    tool: str
    status: DecisionStatus
    symbol: str | None
    reason_codes: tuple[ReasonCode, ...]
    decision: dict[str, Any] | None
    arithmetic: dict[str, str]
    explanation: str
    created_at: datetime


class LivenessDecision(StrictModel):
    checked_at: datetime
    read_verified: bool
    trade_permission: bool
    withdrawal_permission: bool
    ip_binding_present: bool
    account_permission_type: str
    account_settings_verified: bool
    arithmetic: dict[str, str]
