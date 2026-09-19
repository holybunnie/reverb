from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

from .errors import ConfigurationError, DataUnavailable


@dataclass(frozen=True)
class EarningsEvent:
    symbol: str
    event_at: datetime
    source: str
    source_id: str


class EarningsCalendar:
    """Strict adapter for a configured calendar; it never invents events."""

    def __init__(self, url: str | None = None, timeout: float = 15.0, client: httpx.Client | None = None):
        self.url = url or os.getenv("REVERB_EARNINGS_CALENDAR_URL")
        self.timeout = timeout
        self._client = client or httpx.Client(timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "EarningsCalendar":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def this_week(self, now: datetime | None = None) -> tuple[EarningsEvent, ...]:
        if not self.url:
            raise ConfigurationError("REVERB_EARNINGS_CALENDAR_URL is required; no earnings feed is hardcoded")
        now = now or datetime.now(timezone.utc)
        start = (now.date() - timedelta(days=now.weekday()))
        end = start + timedelta(days=6)
        try:
            response = self._client.get(self.url, params={"fromdate": start.isoformat(), "todate": end.isoformat()})
            response.raise_for_status()
            document = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise DataUnavailable(f"earnings calendar request failed: {type(exc).__name__}") from exc
        rows = self._rows(document)
        events = tuple(self._parse_row(row) for row in rows)
        if not events:
            raise DataUnavailable("earnings calendar returned no validated events")
        return events

    @staticmethod
    def _rows(document: Any) -> list[dict[str, Any]]:
        candidates: Any = document
        if isinstance(document, dict):
            candidates = document.get("data", document)
            if isinstance(candidates, dict):
                candidates = candidates.get("rows", candidates.get("results"))
        if not isinstance(candidates, list) or not candidates or any(not isinstance(row, dict) for row in candidates):
            raise DataUnavailable("earnings calendar response has no validated rows")
        return candidates

    @staticmethod
    def _parse_row(row: dict[str, Any]) -> EarningsEvent:
        symbol = row.get("symbol") or row.get("ticker")
        event_value = row.get("event_at") or row.get("eventAt") or row.get("date")
        source_id = row.get("id") or row.get("eventId") or f"{symbol}:{event_value}"
        if not isinstance(symbol, str) or not symbol.strip() or not isinstance(event_value, str):
            raise DataUnavailable("earnings calendar row is missing symbol or event time")
        try:
            if len(event_value) == 10:
                configured_time = os.getenv("REVERB_DEFAULT_EARNINGS_TIME_ET")
                if not configured_time:
                    raise DataUnavailable("calendar supplied a date without a time; set REVERB_DEFAULT_EARNINGS_TIME_ET explicitly")
                hour, minute = (int(part) for part in configured_time.split(":", 1))
                event_date = date.fromisoformat(event_value)
                event_at = datetime.combine(event_date, time(hour, minute), tzinfo=ZoneInfo("America/New_York")).astimezone(timezone.utc)
            else:
                event_at = datetime.fromisoformat(event_value.replace("Z", "+00:00"))
                if event_at.tzinfo is None:
                    raise ValueError("event time has no timezone")
                event_at = event_at.astimezone(timezone.utc)
        except (ValueError, ZoneInfoNotFoundError) as exc:
            raise DataUnavailable(f"earnings calendar event time is invalid: {event_value}") from exc
        if not isinstance(source_id, (str, int)):
            raise DataUnavailable("earnings calendar event id is invalid")
        return EarningsEvent(symbol=symbol.upper(), event_at=event_at, source=self.__class__.__name__, source_id=str(source_id))
