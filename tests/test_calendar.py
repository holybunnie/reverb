from datetime import timezone
import unittest

from reverb.calendar import EarningsCalendar
from reverb.errors import DataUnavailable


class CalendarTests(unittest.TestCase):
    def test_date_only_calendar_row_requires_explicit_time_resolution(self):
        with self.assertRaises(DataUnavailable):
            EarningsCalendar._parse_row({"symbol": "NVDA", "_event_date": "2026-09-24"})

    def test_date_only_row_uses_explicit_new_york_time(self):
        event = EarningsCalendar._parse_row({"symbol": "NVDA", "_event_date": "2026-09-24"}, "16:05")
        self.assertEqual(event.symbol, "NVDA")
        self.assertEqual(event.event_at.hour, 20)
        self.assertEqual(event.event_at.tzinfo, timezone.utc)
