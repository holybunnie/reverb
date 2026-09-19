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
    return baseline, {"points": str(len(closes)), "window_minutes": str(window_minutes), "timestamp_gaps": str(gaps)}


def evaluate_reaction(*, symbol: str, baseline: Decimal | None, observed_price: Decimal | None,
                      observed_at: datetime, baseline_observed_at: datetime | None,
                      trigger_pct: Decimal, session: Session, order_type: str,
                      max_quote_age_ms: int, now: datetime | None = None) -> ReactionDecision:
    now = now or datetime.now(timezone.utc)
    arithmetic = {"trigger_pct": str(trigger_pct), "order_type": order_type, "session": session.value}
    if baseline is None or observed_price is None or baseline <= 0 or observed_price <= 0:
        return ReactionDecision(decision_id=str(uuid4()), status=DecisionStatus.REFUSE, symbol=symbol,
                                session=session.value, baseline_price=baseline, observed_price=observed_price,
                                move_pct=None, trigger_pct=trigger_pct,
                                reason_codes=(ReasonCode.DATA_UNAVAILABLE,), observed_at=observed_at,
                                arithmetic={**arithmetic, "error": "baseline and observed price are required"})
    age_ms = int((now - observed_at).total_seconds() * 1000)
    if age_ms < 0 or age_ms > max_quote_age_ms:
        return ReactionDecision(decision_id=str(uuid4()), status=DecisionStatus.REFUSE, symbol=symbol,
                                session=session.value, baseline_price=baseline, observed_price=observed_price,
                                move_pct=None, trigger_pct=trigger_pct,
                                reason_codes=(ReasonCode.STALE_REACTION,), observed_at=observed_at,
                                arithmetic={**arithmetic, "quote_age_ms": str(age_ms), "max_quote_age_ms": str(max_quote_age_ms)})
    try:
        validate_order_type(session, order_type)
    except ConfigurationError as exc:
        return ReactionDecision(decision_id=str(uuid4()), status=DecisionStatus.REFUSE, symbol=symbol,
                                session=session.value, baseline_price=baseline, observed_price=observed_price,
                                move_pct=None, trigger_pct=trigger_pct,
                                reason_codes=(ReasonCode.SESSION_UNAVAILABLE,), observed_at=observed_at,
                                arithmetic={**arithmetic, "error": str(exc)})
    move = (observed_price - baseline) / baseline
    arithmetic.update({"baseline": str(baseline), "observed": str(observed_price), "move_pct": str(move), "quote_age_ms": str(age_ms)})
    status = DecisionStatus.ACT if abs(move) >= trigger_pct else DecisionStatus.HOLD
    return ReactionDecision(decision_id=str(uuid4()), status=status, symbol=symbol,
                            session=session.value, baseline_price=baseline, observed_price=observed_price,
                            move_pct=move, trigger_pct=trigger_pct, reason_codes=(), observed_at=observed_at,
                            arithmetic=arithmetic)
