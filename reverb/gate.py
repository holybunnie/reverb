from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from uuid import uuid4

from .errors import FreshnessError, ValuationError
from .math import value_option
from .models import Decision, DecisionStatus, OptionQuote, ReasonCode, Thesis, UnderlyingQuote


def _age_ms(observed_at: datetime, now: datetime) -> int:
    return int((now - observed_at).total_seconds() * 1000)


def _refusal(thesis, code, arithmetic, inputs, instrument=None):
    return Decision(
        decision_id=str(uuid4()), status=DecisionStatus.REFUSE, symbol=thesis.symbol,
        reason_codes=(code,), thesis=thesis, instrument=instrument, contracts=0,
        maximum_loss=None, valuation=None, arithmetic=arithmetic, inputs=inputs,
        created_at=datetime.now(timezone.utc),
    )


def evaluate_option(*, thesis: Thesis, underlying: UnderlyingQuote, option: OptionQuote,
                    paired_straddle_move_pct: Decimal | None, risk_free_rate: Decimal,
                    dividend_yield: Decimal, post_event_volatility: Decimal,
                    per_contract_fees: Decimal, max_quote_age_ms: int,
                    now: datetime | None = None) -> Decision:
    now = now or datetime.now(timezone.utc)
    inputs = {"underlying_observed_at": underlying.observed_at.isoformat(), "option_observed_at": option.observed_at.isoformat(),
              "max_quote_age_ms": str(max_quote_age_ms), "post_event_volatility": str(post_event_volatility)}
    if thesis.view.direction is not option.direction:
        return _refusal(thesis, ReasonCode.INVALID_CONTRACT, {"view_direction": thesis.view.direction.value, "option_direction": option.direction.value}, inputs, option)
    try:
        underlying_age = _age_ms(underlying.observed_at, now)
        option_age = _age_ms(option.observed_at, now)
        if underlying_age < 0 or underlying_age > max_quote_age_ms:
            raise FreshnessError(f"underlying age {underlying_age}ms exceeds {max_quote_age_ms}ms")
        if option_age < 0 or option_age > max_quote_age_ms:
            return _refusal(thesis, ReasonCode.STALE_OPTION, {"option_age_ms": str(option_age), "max_quote_age_ms": str(max_quote_age_ms)}, inputs, option)
        if not option.executable:
            return _refusal(thesis, ReasonCode.OPTION_BID_ASK_UNAVAILABLE, {"last_done": str(option.last_done), "bid": str(option.bid), "ask": str(option.ask)}, inputs, option)
        valuation = value_option(underlying, option, thesis.event_at, risk_free_rate, dividend_yield,
                                 post_event_volatility, paired_straddle_move_pct, thesis.expected_move_pct, per_contract_fees)
    except FreshnessError as exc:
        return _refusal(thesis, ReasonCode.STALE_UNDERLYING, {"error": str(exc)}, inputs, option)
    except ValuationError as exc:
        return _refusal(thesis, ReasonCode.INVALID_CONTRACT, {"error": str(exc)}, inputs, option)

    if paired_straddle_move_pct is not None and paired_straddle_move_pct >= thesis.expected_move_pct:
        return Decision(
            decision_id=str(uuid4()), status=DecisionStatus.REFUSE, symbol=thesis.symbol,
            reason_codes=(ReasonCode.MARKET_EXPECTS_LARGER_MOVE,), thesis=thesis, instrument=option,
            contracts=0, maximum_loss=None, valuation=valuation,
            arithmetic={"market_implied_move_pct": str(paired_straddle_move_pct), "thesis_move_pct": str(thesis.expected_move_pct),
                        "comparison": "market_implied_move_pct >= thesis_move_pct"}, inputs=inputs,
            created_at=datetime.now(timezone.utc),
        )
    if valuation.scenario_pnl is None or valuation.scenario_pnl <= 0:
        return Decision(
            decision_id=str(uuid4()), status=DecisionStatus.REFUSE, symbol=thesis.symbol,
            reason_codes=(ReasonCode.NEGATIVE_EXPECTED_VALUE,), thesis=thesis, instrument=option,
            contracts=0, maximum_loss=None, valuation=valuation,
            arithmetic={"scenario_pnl": str(valuation.scenario_pnl), "decision": "scenario_pnl <= 0"}, inputs=inputs,
            created_at=datetime.now(timezone.utc),
        )

    if option.ask is None:
        raise ValuationError("option ask disappeared after valuation")
    total_per_contract = option.ask * option.contract_multiplier + per_contract_fees
    contracts = int((thesis.max_loss / total_per_contract).to_integral_value(rounding=ROUND_DOWN))
    if contracts < 1:
        return _refusal(thesis, ReasonCode.MAX_LOSS_EXCEEDED,
                        {"max_loss": str(thesis.max_loss), "one_contract_loss": str(total_per_contract)}, inputs, option)
    maximum_loss = total_per_contract * contracts
    return Decision(
        decision_id=str(uuid4()), status=DecisionStatus.ACT, symbol=thesis.symbol,
        reason_codes=(), thesis=thesis, instrument=option, contracts=contracts,
        maximum_loss=maximum_loss, valuation=valuation,
        arithmetic={"premium_per_contract": str(option.ask * option.contract_multiplier),
                    "fees_per_contract": str(per_contract_fees), "contracts": str(contracts),
                    "maximum_loss": str(maximum_loss), "breakeven_move_pct": str(valuation.breakeven_move_pct)},
        inputs=inputs, created_at=datetime.now(timezone.utc),
    )
