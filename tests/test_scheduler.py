from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from reverb.ledger import Ledger
from reverb.scheduler import WakeAction, build_schedule, due_action, heartbeat_from_ledger


class SchedulerTests(unittest.TestCase):
    def test_schedule_is_utc_and_has_three_windows(self):
        event = datetime(2026, 9, 24, 20, 5, tzinfo=timezone.utc)
        schedule = build_schedule("nvda-2026-09-24", event)
        self.assertEqual(schedule.position_at_utc, event - timedelta(minutes=30))
        self.assertEqual(due_action(schedule, event - timedelta(minutes=10)), WakeAction.POSITION)
        self.assertEqual(due_action(schedule, event + timedelta(minutes=10)), WakeAction.REACT)
        # Weekday arithmetic is only a tentative timestamp; holiday/early
        # close verification is required before the option leg is managed.
        self.assertIsNone(due_action(schedule, schedule.next_open_at_utc))

    def test_heartbeat_writes_gap_marker(self):
        with TemporaryDirectory() as temp:
            ledger = Ledger(Path(temp) / "ledger.jsonl")
            heartbeat = heartbeat_from_ledger(ledger)
            heartbeat.tick(datetime(2026, 9, 19, 0, 0, tzinfo=timezone.utc))
            heartbeat.tick(datetime(2026, 9, 19, 0, 3, tzinfo=timezone.utc))
            kinds = [row["kind"] for row in ledger.verify()]
            self.assertEqual(kinds, ["heartbeat", "heartbeat_gap", "heartbeat"])
