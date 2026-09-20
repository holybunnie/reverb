from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from statistics import median
from uuid import uuid4

from .errors import ConfigurationError, DataUnavailable
from .models import DecisionStatus, ReactionDecision, ReasonCode
from .sessions import Session, validate_order_type


def parse_candle(row: list[str | int | float]) -> tuple[datetime, Decimal]:
    if len(row) < 5:
        raise DataUnavailable("candle row has fewer than timestamp and OHLC fields")
    try:
        timestamp = datetime.fromtimestamp(int(row[0]) / 1000, timezone.utc)
        close = Decimal(str(row[4]))
    except (ValueError, TypeError, ArithmeticError) as exc:
        raise DataUnavailable("candle row contains an invalid timestamp or close") from exc
    if close <= 0 or not close.is_finite():
        raise DataUnavailable("candle close must be a positive finite value")
    return timestamp, close


def baseline_price(rows: list[list[str | int | float]], event_at: datetime,
                   window_minutes: int, minimum_points: int) -> tuple[Decimal, dict[str, str]]:
    if event_at.tzinfo is None:
        raise DataUnavailable("baseline event timestamp must include a timezone")
    if window_minutes <= 0 or minimum_points <= 0:
        raise DataUnavailable("baseline configuration must be positive")
    start = event_at - timedelta(minutes=window_minutes)
    closes = []
    timestamps = []
    for row in rows:
        timestamp, close = parse_candle(row)
        if start <= timestamp < event_at:
            closes.append(close)
            timestamps.append(timestamp)
    if len(closes) < minimum_points:
        raise DataUnavailable(f"baseline has {len(closes)} points; {minimum_points} required")
    ordered = sorted(timestamps)
    expected_spacing = timedelta(minutes=1)
    gaps = sum((right - left) != expected_spacing for left, right in zip(ordered, ordered[1:]))
    if gaps:
        raise DataUnavailable(f"baseline has {gaps} timestamp gaps")
    baseline = Decimal(str(median(closes)))
    return baseline, {"points": str(len(closes)), "window_minutes": str(window_minutes),
                      "timestamp_gaps": str(gaps), "baseline_first_at": ordered[0].isoformat(),
                      "baseline_last_at": ordered[-1].isoformat()}


def evaluate_reaction(*, symbol: str, baseline: Decimal | None, observed_price: Decimal | None,
                      observed_at: datetime, baseline_observed_at: datetime | None,
                      trigger_pct: Decimal, session: Session, order_type: str,
                      max_quote_age_ms: int, now: datetime | None = None,
                      intended_side: str | None = None, order_quantity: Decimal | None = None,
                      order_price: Decimal | None = None, risk_budget: Decimal | None = None) -> ReactionDecision:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ConfigurationError("reaction evaluation timestamp must include a timezone")
    now = now.astimezone(timezone.utc)
    if not trigger_pct.is_finite() or trigger_pct <= 0 or trigger_pct >= 1:
        raise ConfigurationError("reaction trigger must be a finite percentage between zero and one")
    arithmetic = {"trigger_pct": str(trigger_pct), "order_type": order_type, "session": session.value,
                  "intended_side": str(intended_side), "order_quantity": str(order_quantity),
                  "order_price": str(order_price), "risk_budget": str(risk_budget)}
    if baseline is None or observed_price is None or baseline <= 0 or observed_price <= 0:
        return ReactionDecision(decision_id=str(uuid4()), status=DecisionStatus.REFUSE, symbol=symbol,
                                session=session.value, baseline_price=baseline, observed_price=observed_price,
                                move_pct=None, trigger_pct=trigger_pct,
                                reason_codes=(ReasonCode.DATA_UNAVAILABLE,), observed_at=observed_at,
                                arithmetic={**arithmetic, "error": "baseline and observed price are required"},
                                intended_side=intended_side, order_quantity=order_quantity,
                                order_price=order_price, risk_budget=risk_budget)
    if baseline_observed_at is None or baseline_observed_at.tzinfo is None:
        return ReactionDecision(decision_id=str(uuid4()), status=DecisionStatus.REFUSE, symbol=symbol,
                                session=session.value, baseline_price=baseline, observed_price=observed_price,
                                move_pct=None, trigger_pct=trigger_pct,
                                reason_codes=(ReasonCode.BASELINE_UNAVAILABLE,), observed_at=observed_at,
                                arithmetic={**arithmetic, "error": "baseline source timestamp is required"},
                                intended_side=intended_side, order_quantity=order_quantity,
                                order_price=order_price, risk_budget=risk_budget)
    if observed_at.tzinfo is None:
        raise ConfigurationError("reaction quote timestamp must include a timezone")
    baseline_observed_at = baseline_observed_at.astimezone(timezone.utc)
    observed_at = observed_at.astimezone(timezone.utc)
    if baseline_observed_at > observed_at:
        return ReactionDecision(decision_id=str(uuid4()), status=DecisionStatus.REFUSE, symbol=symbol,
                                session=session.value, baseline_price=baseline, observed_price=observed_price,
                                move_pct=None, trigger_pct=trigger_pct,
                                reason_codes=(ReasonCode.BASELINE_UNAVAILABLE,), observed_at=observed_at,
                                arithmetic={**arithmetic, "error": "baseline timestamp is after reaction quote"},
                                intended_side=intended_side, order_quantity=order_quantity,
                                order_price=order_price, risk_budget=risk_budget)
    age_ms = int((now - observed_at).total_seconds() * 1000)
    if age_ms < 0 or age_ms > max_quote_age_ms:
        return ReactionDecision(decision_id=str(uuid4()), status=DecisionStatus.REFUSE, symbol=symbol,
                                session=session.value, baseline_price=baseline, observed_price=observed_price,
                                move_pct=None, trigger_pct=trigger_pct,
                                reason_codes=(ReasonCode.STALE_REACTION,), observed_at=observed_at,
                                arithmetic={**arithmetic, "quote_age_ms": str(age_ms), "max_quote_age_ms": str(max_quote_age_ms)},
                                intended_side=intended_side, order_quantity=order_quantity,
                                order_price=order_price, risk_budget=risk_budget)
    try:
        validate_order_type(session, order_type)
    except ConfigurationError as exc:
        return ReactionDecision(decision_id=str(uuid4()), status=DecisionStatus.REFUSE, symbol=symbol,
                                session=session.value, baseline_price=baseline, observed_price=observed_price,
                                move_pct=None, trigger_pct=trigger_pct,
                                reason_codes=(ReasonCode.SESSION_UNAVAILABLE,), observed_at=observed_at,
                                arithmetic={**arithmetic, "error": str(exc)}, intended_side=intended_side,
                                order_quantity=order_quantity, order_price=order_price, risk_budget=risk_budget)
    move = (observed_price - baseline) / baseline
    arithmetic.update({"baseline": str(baseline), "observed": str(observed_price), "move_pct": str(move),
                       "quote_age_ms": str(age_ms), "baseline_observed_at": baseline_observed_at.isoformat(),
                       "baseline_age_at_event_ms": str(int((observed_at - baseline_observed_at).total_seconds() * 1000))})
    status = DecisionStatus.ACT if abs(move) >= trigger_pct else DecisionStatus.HOLD
    if status is DecisionStatus.ACT:
        valid_intent = (intended_side in {"buy", "sell"} and order_quantity is not None
                        and order_quantity.is_finite() and order_quantity > 0
                        and order_price is not None and order_price.is_finite() and order_price > 0
                        and risk_budget is not None and risk_budget.is_finite() and risk_budget > 0)
        if not valid_intent:
            return ReactionDecision(decision_id=str(uuid4()), status=DecisionStatus.REFUSE, symbol=symbol,
                                    session=session.value, baseline_price=baseline, observed_price=observed_price,
                                    move_pct=move, trigger_pct=trigger_pct,
                                    reason_codes=(ReasonCode.INVALID_ORDER_INTENT,), observed_at=observed_at,
                                    arithmetic={**arithmetic, "error": "ACT requires explicit side, quantity, limit price, and risk budget"},
                                    intended_side=intended_side, order_quantity=order_quantity,
                                    order_price=order_price, risk_budget=risk_budget)
        notional = order_quantity * order_price
        if notional > risk_budget:
            return ReactionDecision(decision_id=str(uuid4()), status=DecisionStatus.REFUSE, symbol=symbol,
                                    session=session.value, baseline_price=baseline, observed_price=observed_price,
                                    move_pct=move, trigger_pct=trigger_pct,
                                    reason_codes=(ReasonCode.RISK_BUDGET_EXCEEDED,), observed_at=observed_at,
                                    arithmetic={**arithmetic, "order_notional": str(notional),
                                                "risk_budget": str(risk_budget)},
                                    intended_side=intended_side, order_quantity=order_quantity,
                                    order_price=order_price, maximum_loss=notional,
                                    risk_budget=risk_budget)
    return ReactionDecision(decision_id=str(uuid4()), status=status, symbol=symbol,
                            session=session.value, baseline_price=baseline, observed_price=observed_price,
                            move_pct=move, trigger_pct=trigger_pct, reason_codes=(), observed_at=observed_at,
                            arithmetic=arithmetic, intended_side=intended_side,
                            order_quantity=order_quantity, order_price=order_price,
                            maximum_loss=(order_quantity * order_price if order_quantity is not None and order_price is not None else None),
                            risk_budget=risk_budget)
