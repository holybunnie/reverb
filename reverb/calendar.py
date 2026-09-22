from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

from .errors import ConfigurationError, DataUnavailable
from .config import CalendarConfig, load_config


@dataclass(frozen=True)
class EarningsEvent:
    symbol: str
    event_at: datetime | None
    event_date: date
    source: str
    source_id: str
    time_basis: str
    timing_category: str | None = None


class EarningsCalendar:
    """Strict adapter for a configured calendar; it never invents events."""

    def __init__(self, url: str | None = None, timeout: float | None = None, client: httpx.Client | None = None,
                 config_path: str | None = None):
        path = Path(config_path) if config_path else Path(__file__).resolve().parents[1] / "config" / "calendar.json"
        loaded = load_config(path, CalendarConfig)
        self.config_sha256 = loaded.sha256
        self.url = url or loaded.value.url
        self.timeout = timeout if timeout is not None else loaded.value.timeout_seconds
        self.default_event_time_et = loaded.value.default_event_time_et
        self._client = client or httpx.Client(timeout=self.timeout)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "EarningsCalendar":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def this_week(self, now: datetime | None = None) -> tuple[EarningsEvent, ...]:
        if not self.url:
            raise ConfigurationError("calendar.url is required; no earnings feed is hardcoded")
        now = now or datetime.now(timezone.utc)
        start = (now.date() - timedelta(days=now.weekday()))
        events: list[EarningsEvent] = []
        for offset in range(7):
            event_date = start + timedelta(days=offset)
            try:
                response = self._client.get(self.url, params={"date": event_date.isoformat()},
                                            headers={"User-Agent": "Reverb-calendar/0.1", "Accept": "application/json"})
                response.raise_for_status()
                document = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                raise DataUnavailable(f"earnings calendar request failed for {event_date}: {type(exc).__name__}") from exc
            for row in self._rows(document, allow_empty=True):
                events.append(self._parse_row({**row, "_event_date": event_date.isoformat()}, self.default_event_time_et))
        if not events:
            raise DataUnavailable("earnings calendar returned no validated events")
        return tuple(events)

    @staticmethod
    def _rows(document: Any, allow_empty: bool = False) -> list[dict[str, Any]]:
        candidates: Any = document
        if isinstance(document, dict):
            status = document.get("status")
            if isinstance(status, dict) and status.get("rCode") not in (None, 200):
                raise DataUnavailable("earnings calendar returned a non-success status")
            candidates = document.get("data", document)
            if isinstance(candidates, dict):
                candidates = candidates.get("rows", candidates.get("results"))
        if candidates is None and allow_empty:
            return []
        if not isinstance(candidates, list) or (not candidates and not allow_empty) or any(not isinstance(row, dict) for row in candidates):
            raise DataUnavailable("earnings calendar response has no validated rows")
        return candidates

    @staticmethod
    def _parse_row(row: dict[str, Any], default_event_time_et: str | None = None) -> EarningsEvent:
        symbol = row.get("symbol") or row.get("ticker")
        event_value = row.get("event_at") or row.get("eventAt") or row.get("event_time") or row.get("date") or row.get("_event_date")
        source_id = row.get("id") or row.get("eventId") or f"{symbol}:{event_value}"
        if not isinstance(symbol, str) or not symbol.strip() or not isinstance(event_value, str):
            raise DataUnavailable("earnings calendar row is missing symbol or event time")
        timing_category = _timing_category(row)
        try:
            if ("T" in event_value or event_value.endswith("Z")
                    or (" " in event_value and ":" in event_value)):
                event_at = datetime.fromisoformat(event_value.replace("Z", "+00:00"))
                if event_at.tzinfo is None:
                    raise ValueError("event time has no timezone")
                event_at = event_at.astimezone(timezone.utc)
                event_date = event_at.astimezone(ZoneInfo("America/New_York")).date()
                time_basis = "source_exact"
            else:
                event_date = _parse_event_date(event_value)
                explicit_time = _explicit_event_time(row)
                event_time = _parse_clock_time(explicit_time) if explicit_time is not None else None
                if event_time is None:
                    if timing_category == "pre_market":
                        return EarningsEvent(
                            symbol=symbol.upper(), event_at=None, event_date=event_date,
                            source="configured-earnings-calendar", source_id=str(source_id),
                            time_basis="unresolved_source_category", timing_category=timing_category,
                        )
                    configured_time = default_event_time_et
                    if not configured_time:
                        raise DataUnavailable("calendar supplied a date without a time; set calendar.default_event_time_et explicitly")
                    event_time = _parse_clock_time(configured_time)
                    time_basis = "configured_default_assumption"
                else:
                    time_basis = "source_exact"
                event_at = datetime.combine(event_date, event_time, tzinfo=ZoneInfo("America/New_York")).astimezone(timezone.utc)
        except (ValueError, ZoneInfoNotFoundError) as exc:
            raise DataUnavailable(f"earnings calendar event time is invalid: {event_value}") from exc
        if not isinstance(source_id, (str, int)):
            raise DataUnavailable("earnings calendar event id is invalid")
        return EarningsEvent(symbol=symbol.upper(), event_at=event_at, event_date=event_date,
                             source="configured-earnings-calendar", source_id=str(source_id),
                             time_basis=time_basis, timing_category=timing_category)


def _parse_event_date(value: str) -> date:
    for pattern in ("%Y-%m-%d", "%m/%d/%Y", "%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(value.strip(), pattern).date()
        except ValueError:
            continue
    raise ValueError(f"unsupported earnings date: {value}")


def _explicit_event_time(row: dict[str, Any]) -> str | None:
    value = row.get("time") or row.get("reportTime") or row.get("report_time")
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    categorical = {
        "time-not-supplied", "time-after-hours", "time-before-hours", "time-pre-market",
        "after-hours", "before-hours", "pre-market", "post-market",
        "not-supplied", "unknown", "n/a", "tbd",
    }
    if not normalized or normalized.lower() in categorical:
        return None
    return normalized


def _timing_category(row: dict[str, Any]) -> str | None:
    value = row.get("time") or row.get("reportTime") or row.get("report_time")
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    if normalized in {"time-pre-market", "time-before-hours", "before-hours", "pre-market"}:
        return "pre_market"
    if normalized in {"time-after-hours", "after-hours", "post-market"}:
        return "after_hours"
    if normalized in {"time-not-supplied", "not-supplied", "unknown", "n/a", "tbd"}:
        return "unspecified"
    return None


def _parse_clock_time(value: str) -> time:
    normalized = value.strip().upper().replace(" EASTERN", "").replace(" ET", "")
    for pattern in ("%H:%M", "%H:%M:%S", "%I:%M %p", "%I:%M:%S %p"):
        try:
            return datetime.strptime(normalized, pattern).time()
        except ValueError:
            continue
    raise ValueError(f"unsupported earnings clock time: {value}")
