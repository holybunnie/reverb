from __future__ import annotations

from decimal import Decimal

from .bitget import BitgetClient
from .errors import ConfigurationError, LedgerError
from .ledger import Ledger
from .models import DecisionStatus, ReactionDecision
from .sessions import Session, validate_order_type


def place_reaction_limit(*, client: BitgetClient, ledger: Ledger, decision: ReactionDecision,
                         symbol: str, side: str, quantity: Decimal, price: Decimal,
                         client_oid: str) -> dict:
    if decision.status is not DecisionStatus.ACT:
        raise ConfigurationError("cannot submit an order for a non-ACT reaction decision")
    if decision.symbol != symbol:
        raise ConfigurationError("order symbol does not match reaction decision")
    try:
        session = Session(decision.session)
    except ValueError as exc:
        raise ConfigurationError(f"unknown decision session: {decision.session}") from exc
    validate_order_type(session, "limit")
    if side not in {"buy", "sell"} or quantity <= 0 or price <= 0 or not client_oid:
        raise ConfigurationError("invalid reaction order intent")
    registrations = [row for row in ledger.verify() if row["kind"] == "pre_registration" and row["payload"].get("decision_id") == decision.decision_id]
    if not registrations:
        raise LedgerError("pre-registration is required before a reaction order")
    try:
        response = client.place_reality_limit(symbol=symbol, side=side, quantity=quantity, price=price, client_oid=client_oid)
    except Exception as exc:
        ledger.append("order_failed", {"decision_id": decision.decision_id, "symbol": symbol, "error_type": type(exc).__name__})
        raise
    ledger.append("order_submitted", {"decision_id": decision.decision_id, "symbol": symbol,
                                      "side": side, "quantity": str(quantity), "price": str(price),
                                      "client_oid": client_oid, "order_id": response.get("orderId")})
    return response
