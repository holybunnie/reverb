from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from decimal import Decimal
from math import exp, log, pi, sqrt
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from scipy.optimize import brentq

from .errors import ValuationError
from .models import Direction, OptionQuote, UnderlyingQuote, Valuation


@dataclass(frozen=True)
class BlackScholesInputs:
    spot: Decimal
    strike: Decimal
    time_years: Decimal
    risk_free_rate: Decimal
    dividend_yield: Decimal = Decimal("0")


def _number(value: Decimal, name: str) -> float:
    if not value.is_finite():
        raise ValuationError(f"{name} is not finite")
    result = float(value)
    if result <= 0 and name in {"spot", "strike", "time_years"}:
        raise ValuationError(f"{name} must be positive")
    return result


def _cdf(value: float) -> float:
    from math import erf

    return 0.5 * (1.0 + erf(value / sqrt(2.0)))


def _pdf(value: float) -> float:
    return exp(-0.5 * value * value) / sqrt(2.0 * pi)


def _d1_d2(inputs: BlackScholesInputs, volatility: float) -> tuple[float, float]:
    spot = _number(inputs.spot, "spot")
    strike = _number(inputs.strike, "strike")
    time = _number(inputs.time_years, "time_years")
    if volatility <= 0 or not inputs.risk_free_rate.is_finite() or not inputs.dividend_yield.is_finite():
        raise ValuationError("invalid volatility or rate")
    carry = float(inputs.risk_free_rate - inputs.dividend_yield)
    d1 = (log(spot / strike) + (carry + 0.5 * volatility**2) * time) / (volatility * sqrt(time))
    return d1, d1 - volatility * sqrt(time)


def price(inputs: BlackScholesInputs, direction: Direction, volatility: Decimal) -> Decimal:
    vol = _number(volatility, "volatility")
    spot = _number(inputs.spot, "spot")
    strike = _number(inputs.strike, "strike")
    time = _number(inputs.time_years, "time_years")
    rate = float(inputs.risk_free_rate)
    dividend = float(inputs.dividend_yield)
    d1, d2 = _d1_d2(inputs, vol)
    discount_r = exp(-rate * time)
    discount_q = exp(-dividend * time)
    if direction is Direction.CALL:
        result = spot * discount_q * _cdf(d1) - strike * discount_r * _cdf(d2)
    else:
        result = strike * discount_r * _cdf(-d2) - spot * discount_q * _cdf(-d1)
    return Decimal(str(result))


def implied_volatility(inputs: BlackScholesInputs, direction: Direction, option_price: Decimal) -> Decimal:
    target = _number(option_price, "option_price")
    spot = _number(inputs.spot, "spot")
    strike = _number(inputs.strike, "strike")
    time = _number(inputs.time_years, "time_years")
    rate = float(inputs.risk_free_rate)
    dividend = float(inputs.dividend_yield)
    intrinsic = max(spot * exp(-dividend * time) - strike * exp(-rate * time), 0.0) if direction is Direction.CALL else max(strike * exp(-rate * time) - spot * exp(-dividend * time), 0.0)
    upper = spot * exp(-dividend * time) if direction is Direction.CALL else strike * exp(-rate * time)
    if target <= intrinsic or target >= upper:
        raise ValuationError("option price is outside the strict no-arbitrage interval")
    root = brentq(lambda sigma: float(price(inputs, direction, Decimal(str(sigma)))) - target, 1e-8, 8.0, xtol=1e-12, rtol=1e-12)
    return Decimal(str(root))


def greeks(inputs: BlackScholesInputs, direction: Direction, volatility: Decimal) -> dict[str, Decimal]:
    vol = _number(volatility, "volatility")
    spot = _number(inputs.spot, "spot")
    strike = _number(inputs.strike, "strike")
    time = _number(inputs.time_years, "time_years")
    rate = float(inputs.risk_free_rate)
    dividend = float(inputs.dividend_yield)
    d1, d2 = _d1_d2(inputs, vol)
    discount_q = exp(-dividend * time)
    discount_r = exp(-rate * time)
    delta = discount_q * _cdf(d1) if direction is Direction.CALL else discount_q * (_cdf(d1) - 1.0)
    gamma = discount_q * _pdf(d1) / (spot * vol * sqrt(time))
    vega = spot * discount_q * _pdf(d1) * sqrt(time)
    theta_call = -(spot * discount_q * _pdf(d1) * vol / (2 * sqrt(time))) - rate * strike * discount_r * _cdf(d2) + dividend * spot * discount_q * _cdf(d1)
    theta_put = -(spot * discount_q * _pdf(d1) * vol / (2 * sqrt(time))) + rate * strike * discount_r * _cdf(-d2) - dividend * spot * discount_q * _cdf(-d1)
    theta = theta_call if direction is Direction.CALL else theta_put
    return {k: Decimal(str(v)) for k, v in {"delta": delta, "gamma": gamma, "vega": vega, "theta_per_year": theta}.items()}


def option_expiry_at(expiry: date) -> datetime:
    """Return the documented 16:00 New York expiry boundary in UTC."""
    try:
        return datetime.combine(expiry, time(16, 0), tzinfo=ZoneInfo("America/New_York")).astimezone(timezone.utc)
    except ZoneInfoNotFoundError as exc:  # pragma: no cover - standard Python zone data
        raise ValuationError("America/New_York timezone data is unavailable") from exc


def time_to_expiry(valuation_at: datetime, expiry: date) -> Decimal:
    """Compute year fraction from the quote timestamp to the expiry boundary.

    Date-only subtraction overstates time value whenever a quote arrives partway
    through a session.  The valuation timestamp must be aware and expiry is
    treated as 16:00 America/New_York on the contract's expiry date.
    """
    if not isinstance(valuation_at, datetime) or valuation_at.tzinfo is None:
        raise ValuationError("valuation timestamp must include a timezone")
    remaining_seconds = (option_expiry_at(expiry) - valuation_at.astimezone(timezone.utc)).total_seconds()
    if remaining_seconds <= 0:
        raise ValuationError("option must expire after the valuation timestamp")
    return Decimal(str(remaining_seconds)) / Decimal(365 * 24 * 60 * 60)


def straddle_implied_move(call_price: Decimal, put_price: Decimal, spot: Decimal) -> Decimal:
    if call_price <= 0 or put_price <= 0 or spot <= 0:
        raise ValuationError("straddle inputs must be positive")
    return (call_price + put_price) / spot


def value_option(underlying: UnderlyingQuote, option: OptionQuote, event_at, risk_free_rate: Decimal,
                 dividend_yield: Decimal, post_event_volatility: Decimal,
                 implied_move_pct: Decimal | None, expected_move_pct: Decimal,
                 fees: Decimal, valuation_at: datetime | None = None) -> Valuation:
    if not option.executable:
        raise ValuationError("option bid and ask are required for an executable valuation")
    if option.ask is None:
        raise ValuationError("option ask is missing")
    if fees < 0 or not fees.is_finite():
        raise ValuationError("per-contract fees must be finite and non-negative")
    premium = option.ask
    valuation_at = valuation_at or option.source_timestamp
    if valuation_at.tzinfo is None or event_at.tzinfo is None:
        raise ValuationError("valuation and event timestamps must include a timezone")
    quote_inputs = BlackScholesInputs(
        underlying.price, option.strike, time_to_expiry(valuation_at, option.expiry),
        risk_free_rate, dividend_yield,
    )
    # The post-event scenario starts at the event timestamp, not at the quote
    # timestamp.  IV/Greeks and post-print valuation therefore use different T.
    scenario_time = time_to_expiry(event_at, option.expiry)
    inputs = quote_inputs
    iv = implied_volatility(inputs, option.direction, premium)
    greek_values = greeks(inputs, option.direction, iv)
    fee_per_share = fees / option.contract_multiplier
    breakeven = (option.strike + premium + fee_per_share if option.direction is Direction.CALL
                 else option.strike - premium - fee_per_share)
    breakeven_move = abs(breakeven - underlying.price) / underlying.price
    scenario_spot = underlying.price * (Decimal("1") + expected_move_pct if option.direction is Direction.CALL else Decimal("1") - expected_move_pct)
    scenario_inputs = BlackScholesInputs(scenario_spot, option.strike, scenario_time, risk_free_rate, dividend_yield)
    scenario_value = price(scenario_inputs, option.direction, post_event_volatility)
    scenario_pnl = (scenario_value - premium) * option.contract_multiplier - fees
    return Valuation(
        premium=premium, implied_volatility=iv, published_implied_volatility=option.published_iv,
        delta=greek_values["delta"], gamma=greek_values["gamma"], vega=greek_values["vega"],
        theta_per_year=greek_values["theta_per_year"], breakeven_price=breakeven,
        breakeven_move_pct=breakeven_move, implied_move_pct=implied_move_pct,
        scenario_value_after_event=scenario_value, scenario_pnl=scenario_pnl,
    )
