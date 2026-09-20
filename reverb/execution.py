from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from typing import Any, Protocol

from .errors import ConfigurationError, LedgerError
from .ledger import Ledger
from .models import DecisionStatus, LivenessDecision, ReactionDecision
from .sessions import Session, validate_order_type


class OrderExecutor(Protocol):
    def place_reality_limit(self, *, symbol: str, side: str, quantity: Decimal,
                            price: Decimal, client_oid: str) -> dict[str, Any]: ...


@dataclass(frozen=True)
class RealityOrderConstraints:
    """Runtime instrument rules returned by Bitget's instruments endpoint."""

    price_precision: int
    quantity_precision: int
    min_order_qty: Decimal
    min_order_amount: Decimal
    buy_limit_price_ratio: Decimal | None = None
    sell_limit_price_ratio: Decimal | None = None

    @classmethod
    def from_instrument(cls, row: dict[str, Any]) -> "RealityOrderConstraints":
        try:
            result = cls(
                price_precision=int(row["pricePrecision"]),
                quantity_precision=int(row["quantityPrecision"]),
                min_order_qty=Decimal(str(row["minOrderQty"])),
                min_order_amount=Decimal(str(row["minOrderAmount"])),
                buy_limit_price_ratio=Decimal(str(row["buyLimitPriceRatio"])) if row.get("buyLimitPriceRatio") not in (None, "") else None,
                sell_limit_price_ratio=Decimal(str(row["sellLimitPriceRatio"])) if row.get("sellLimitPriceRatio") not in (None, "") else None,
            )
        except (ArithmeticError, KeyError, TypeError, ValueError) as exc:
            raise ConfigurationError("Reality instrument precision/minimums are incomplete") from exc
        if (result.min_order_qty <= 0 or result.min_order_amount <= 0
                or not result.min_order_qty.is_finite() or not result.min_order_amount.is_finite()):
            raise ConfigurationError("Reality instrument minimums are invalid")
        for ratio in (result.buy_limit_price_ratio, result.sell_limit_price_ratio):
            if ratio is not None and (not ratio.is_finite() or ratio < 0):
                raise ConfigurationError("Reality instrument price bands are invalid")
        return result

    def validate(self, *, side: str, quantity: Decimal, price: Decimal,
                 reference_price: Decimal | None = None) -> None:
        if self.price_precision < 0 or self.quantity_precision < 0:
            raise ConfigurationError("instrument precision is invalid")
        if not quantity.is_finite() or not price.is_finite() or price <= 0 or quantity <= 0:
            raise ConfigurationError("reaction order values must be finite and positive")
        if quantity < self.min_order_qty or quantity * price < self.min_order_amount:
            raise ConfigurationError("reaction order is below Bitget's runtime minimum")
        if quantity.quantize(Decimal(1).scaleb(-self.quantity_precision), rounding=ROUND_DOWN) != quantity:
            raise ConfigurationError("reaction quantity exceeds the instrument precision")
        if price.quantize(Decimal(1).scaleb(-self.price_precision), rounding=ROUND_DOWN) != price:
            raise ConfigurationError("reaction price exceeds the instrument precision")
        if reference_price is not None:
            if not reference_price.is_finite() or reference_price <= 0:
                raise ConfigurationError("reference price must be finite and positive")
            ratio = self.buy_limit_price_ratio if side == "buy" else self.sell_limit_price_ratio
            if ratio is not None and abs(price - reference_price) / reference_price > ratio:
                raise ConfigurationError("reaction price exceeds Bitget's runtime limit-price band")


def place_reaction_limit(*, executor: OrderExecutor, ledger: Ledger, decision: ReactionDecision,
                         symbol: str, side: str, quantity: Decimal, price: Decimal,
                         client_oid: str, liveness: LivenessDecision | None = None,
                         constraints: RealityOrderConstraints | None = None,
                         reference_price: Decimal | None = None,
                         available_quantity: Decimal | None = None) -> dict:
    if decision.status is not DecisionStatus.ACT:
        raise ConfigurationError("cannot submit an order for a non-ACT reaction decision")
    if (liveness is None or not liveness.read_verified or not liveness.trade_permission
            or liveness.withdrawal_permission or not liveness.account_settings_verified):
        raise ConfigurationError("a verified read-and-trade liveness decision without withdrawal permission is required")
    if decision.symbol != symbol:
        raise ConfigurationError("order symbol does not match reaction decision")
    try:
        session = Session(decision.session)
    except ValueError as exc:
        raise ConfigurationError(f"unknown decision session: {decision.session}") from exc
    validate_order_type(session, "limit")
    registrations = [row for row in ledger.verify() if row["kind"] == "pre_registration" and row["payload"].get("decision_id") == decision.decision_id]
    if not registrations:
        raise LedgerError("pre-registration is required before a reaction order")
    if registrations[-1]["payload"].get("status") != DecisionStatus.ACT.value:
        raise LedgerError("reaction order requires an ACT pre-registration")
    if side not in {"buy", "sell"} or not quantity.is_finite() or not price.is_finite() or quantity <= 0 or price <= 0 or not client_oid:
        raise ConfigurationError("invalid reaction order intent")
    # The order intent is immutable once the deterministic decision is
    # registered.  Callers cannot replace a decision's side, size, price, or
    # budget at the execution boundary.
    if (decision.intended_side is None or decision.order_quantity is None
            or decision.order_price is None or decision.risk_budget is None):
        raise ConfigurationError("reaction decision has no complete registered order intent")
    if side != decision.intended_side or quantity != decision.order_quantity or price != decision.order_price:
        raise ConfigurationError("order intent does not match the registered reaction decision")
    notional = quantity * price
    if notional > decision.risk_budget:
        raise ConfigurationError("order intent exceeds the registered reaction risk budget")
    if decision.maximum_loss is not None and decision.maximum_loss != notional:
        raise ConfigurationError("order intent notional does not match the registered maximum loss")
    if constraints is None:
        raise ConfigurationError("runtime Reality instrument constraints are required before submission")
    if side == "sell":
        if available_quantity is None or not available_quantity.is_finite() or available_quantity < quantity:
            raise ConfigurationError("sell order exceeds the verified available Reality balance")
    constraints.validate(side=side, quantity=quantity, price=price, reference_price=reference_price)
    try:
        response = executor.place_reality_limit(symbol=symbol, side=side, quantity=quantity, price=price, client_oid=client_oid)
        if not isinstance(response, dict) or not isinstance(response.get("orderId"), str) or not response["orderId"]:
            raise ConfigurationError("Agent Hub did not return a verified order id")
    except Exception as exc:
        ledger.append("order_failed", {"decision_id": decision.decision_id, "symbol": symbol, "error_type": type(exc).__name__})
        raise
    ledger.append("order_submitted", {"decision_id": decision.decision_id, "symbol": symbol,
                                      "side": side, "quantity": str(quantity), "price": str(price),
                                      "client_oid": client_oid, "order_id": response["orderId"],
                                      "notional": str(notional)})
    return response
