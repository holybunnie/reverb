from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from enum import Enum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .errors import ConfigurationError


class Session(str, Enum):
    OVERNIGHT = "overnight"
    PRE_MARKET = "pre_market"
    REGULAR = "regular"
    AFTER_HOURS = "after_hours"
    WEEKEND = "weekend"


@dataclass(frozen=True)
class SessionAt:
    session: Session
    timezone: str
    local_time: str
    weekday: int


def session_at(instant: datetime, timezone_name: str = "America/New_York") -> SessionAt:
    try:
        local = instant.astimezone(ZoneInfo(timezone_name))
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ConfigurationError(f"unknown session timezone: {timezone_name}") from exc
    if local.weekday() >= 5:
        session = Session.WEEKEND
    elif time(4, 0) <= local.time() < time(9, 30):
        session = Session.PRE_MARKET
    elif time(9, 30) <= local.time() < time(16, 0):
        session = Session.REGULAR
    elif time(16, 0) <= local.time() < time(20, 0):
        session = Session.AFTER_HOURS
    else:
        session = Session.OVERNIGHT
    return SessionAt(session, timezone_name, local.isoformat(), local.weekday())


def validate_order_type(session: Session, order_type: str) -> None:
    if order_type not in {"limit", "market", "tp_sl"}:
        raise ConfigurationError(f"unsupported order type: {order_type}")
    if session is Session.WEEKEND and order_type == "market":
        raise ConfigurationError("Bitget weekend stock-token trading does not permit market orders")
