from datetime import timezone
import unittest
from zoneinfo import ZoneInfo

from reverb.calendar import EarningsCalendar
from reverb.errors import DataUnavailable


class CalendarTests(unittest.TestCase):
    def test_categorical_after_hours_uses_explicit_configured_clock(self):
        event = EarningsCalendar._parse_row(
            {"symbol": "NVDA", "date": "2026-09-21", "time": "time-after-hours"},
            "16:05",
        )
        self.assertEqual(event.event_at.astimezone(ZoneInfo("America/New_York")).strftime("%H:%M"), "16:05")
        self.assertEqual(event.time_basis, "configured_default_assumption")

    def test_pre_market_category_never_inherits_after_hours_fallback(self):
        event = EarningsCalendar._parse_row(
            {"symbol": "AZO", "date": "2026-09-22", "time": "time-pre-market"},
            "16:05",
        )
        self.assertIsNone(event.event_at)
        self.assertEqual(event.time_basis, "unresolved_source_category")
        self.assertEqual(event.timing_category, "pre_market")

    def test_date_only_calendar_row_requires_explicit_time_resolution(self):
        with self.assertRaises(DataUnavailable):
            EarningsCalendar._parse_row({"symbol": "NVDA", "_event_date": "2026-09-24"})

    def test_date_only_row_uses_explicit_new_york_time(self):
        event = EarningsCalendar._parse_row({"symbol": "NVDA", "_event_date": "2026-09-24"}, "16:05")
        self.assertEqual(event.symbol, "NVDA")
        self.assertEqual(event.event_at.hour, 20)
        self.assertEqual(event.event_at.tzinfo, timezone.utc)
        self.assertEqual(event.time_basis, "configured_default_assumption")

    def test_source_reporting_time_is_used_when_it_is_explicit(self):
        event = EarningsCalendar._parse_row({"symbol": "NVDA", "date": "09/24/2026", "time": "4:05 PM ET"})
        self.assertEqual(event.event_at.isoformat(), "2026-09-24T20:05:00+00:00")
        self.assertEqual(event.time_basis, "source_exact")

    def test_unresolved_source_time_still_requires_a_configured_fallback(self):
        with self.assertRaises(DataUnavailable):
            EarningsCalendar._parse_row({"symbol": "NVDA", "date": "2026-09-24", "time": "time-not-supplied"})
