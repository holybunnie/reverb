from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from enum import Enum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .errors import ConfigurationError, LedgerError
from .ledger import Ledger


class WakeAction(str, Enum):
    POSITION = "position"
    REACT = "react"
    MANAGE = "manage_option_leg"


@dataclass(frozen=True)
class EarningsSchedule:
    event_id: str
    event_at_utc: datetime
    position_at_utc: datetime
    react_until_utc: datetime
    next_open_at_utc: datetime
    next_open_status: str

    def as_dict(self) -> dict[str, str]:
        return {
            "event_id": self.event_id,
            "event_at_utc": self.event_at_utc.isoformat(),
            "position_at_utc": self.position_at_utc.isoformat(),
            "react_until_utc": self.react_until_utc.isoformat(),
            "next_open_at_utc": self.next_open_at_utc.isoformat(),
            "next_open_status": self.next_open_status,
        }


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ConfigurationError("scheduler timestamps must carry a timezone")
    return value.astimezone(timezone.utc)


def _next_weekday_open(event_at_utc: datetime) -> datetime:
    try:
        local = event_at_utc.astimezone(ZoneInfo("America/New_York"))
    except ZoneInfoNotFoundError as exc:  # pragma: no cover - standard Python zone data
        raise ConfigurationError("America/New_York timezone data is unavailable") from exc
    candidate = local.date() + timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return datetime.combine(candidate, time(9, 30), tzinfo=ZoneInfo("America/New_York")).astimezone(timezone.utc)


def build_schedule(event_id: str, event_at: datetime) -> EarningsSchedule:
    if not event_id:
        raise ConfigurationError("earnings schedule requires an event id")
    event_at_utc = _utc(event_at)
    next_open = _next_weekday_open(event_at_utc)
    if next_open <= event_at_utc:
        raise ConfigurationError("next options-open timestamp is not after the event")
    return EarningsSchedule(
        event_id=event_id,
        event_at_utc=event_at_utc,
        position_at_utc=event_at_utc - timedelta(minutes=30),
        react_until_utc=event_at_utc + timedelta(minutes=30),
        next_open_at_utc=next_open,
        next_open_status="weekday_only; exchange-holiday calendar still unverified",
    )


def due_action(schedule: EarningsSchedule, now: datetime) -> WakeAction | None:
    current = _utc(now)
    if schedule.position_at_utc <= current < schedule.event_at_utc:
        return WakeAction.POSITION
    if schedule.event_at_utc <= current <= schedule.react_until_utc:
        return WakeAction.REACT
    if current >= schedule.next_open_at_utc:
        return WakeAction.MANAGE
    return None


@dataclass
class Heartbeat:
    ledger: Ledger
    expected_interval_seconds: int = 60
    last_at: datetime | None = None

    def tick(self, now: datetime) -> dict[str, object]:
        current = _utc(now)
        if self.last_at is not None:
            gap_seconds = int((current - self.last_at).total_seconds())
            if gap_seconds < 0:
                raise ConfigurationError("scheduler clock moved backwards")
            if gap_seconds > self.expected_interval_seconds * 2:
                self.ledger.append("heartbeat_gap", {
                    "from": self.last_at.isoformat(), "to": current.isoformat(),
                    "gap_seconds": str(gap_seconds), "expected_interval_seconds": str(self.expected_interval_seconds),
                })
        record = self.ledger.append("heartbeat", {
            "at": current.isoformat(), "expected_interval_seconds": str(self.expected_interval_seconds),
        })
        self.last_at = current
        return record


def heartbeat_from_ledger(ledger: Ledger, expected_interval_seconds: int = 60) -> Heartbeat:
    if expected_interval_seconds <= 0:
        raise ConfigurationError("heartbeat interval must be positive")
    records = ledger.verify()
    heartbeat_records = [record for record in records if record.get("kind") == "heartbeat"]
    last_at = None
    if heartbeat_records:
        value = heartbeat_records[-1]["payload"].get("at")
        if not isinstance(value, str):
            raise LedgerError("last heartbeat has no timestamp")
        try:
            last_at = datetime.fromisoformat(value)
        except ValueError as exc:
            raise LedgerError("last heartbeat timestamp is invalid") from exc
    return Heartbeat(ledger=ledger, expected_interval_seconds=expected_interval_seconds, last_at=last_at)

