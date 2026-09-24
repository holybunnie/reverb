"""Deterministic sizing primitives for long-only Reality-token proposals."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING, ROUND_DOWN
from typing import Any

from .errors import DataUnavailable
from .models import UnderlyingQuote


@dataclass(frozen=True)
class SpotLimitPlan:
    quantity: Decimal
    limit_price: Decimal
    principal_notional: Decimal
    bid: Decimal
    ask: Decimal
    spread_bps: Decimal
    minimum_quantity: Decimal
    minimum_notional: Decimal
    quantity_precision: int
    price_precision: int

    @property
    def meets_exchange_minimum(self) -> bool:
        return self.quantity >= self.minimum_quantity and self.principal_notional >= self.minimum_notional


def calculate_long_limit_plan(*, risk_budget: Decimal, quote: UnderlyingQuote,
                              instrument: dict[str, Any]) -> SpotLimitPlan:
    """Size a principal-only limit-buy proposal from live quote/instrument fields.

    This is not an execution approval. Callers must separately gate fees,
    account buying power, session policy, and event-time liquidity.
    """
    if not risk_budget.is_finite() or risk_budget <= 0:
        raise DataUnavailable("spot risk budget must be positive and finite")
    if quote.bid is None or quote.ask is None or quote.ask < quote.bid:
        raise DataUnavailable("spot sizing requires a valid live bid and ask")
    try:
        price_precision = int(instrument["pricePrecision"])
        quantity_precision = int(instrument["quantityPrecision"])
        minimum_quantity = Decimal(str(instrument["minOrderQty"]))
        minimum_notional = Decimal(str(instrument["minOrderAmount"]))
    except (KeyError, ArithmeticError, TypeError, ValueError) as exc:
        raise DataUnavailable("live instrument precision or minimum-order metadata is incomplete") from exc
    if (price_precision < 0 or quantity_precision < 0
            or not minimum_quantity.is_finite() or minimum_quantity <= 0
            or not minimum_notional.is_finite() or minimum_notional <= 0):
        raise DataUnavailable("live instrument precision or minimum-order metadata is invalid")

    price_tick = Decimal(1).scaleb(-price_precision)
    quantity_tick = Decimal(1).scaleb(-quantity_precision)
    limit_price = (quote.ask / price_tick).to_integral_value(rounding=ROUND_CEILING) * price_tick
    quantity = (risk_budget / limit_price).quantize(quantity_tick, rounding=ROUND_DOWN)
    principal_notional = quantity * limit_price
    midpoint = (quote.bid + quote.ask) / Decimal("2")
    if midpoint <= 0:
        raise DataUnavailable("spot quote midpoint is invalid")
    spread_bps = (quote.ask - quote.bid) / midpoint * Decimal("10000")
    if principal_notional > risk_budget:
        raise DataUnavailable("rounded spot proposal exceeds its principal budget")
    return SpotLimitPlan(
        quantity=quantity, limit_price=limit_price, principal_notional=principal_notional,
        bid=quote.bid, ask=quote.ask, spread_bps=spread_bps,
        minimum_quantity=minimum_quantity, minimum_notional=minimum_notional,
        quantity_precision=quantity_precision, price_precision=price_precision,
    )
