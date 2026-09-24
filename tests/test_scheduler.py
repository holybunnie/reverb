from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from reverb.calendar import EarningsEvent
from reverb.errors import DataUnavailable
from reverb.ledger import Ledger
from reverb.scheduler import WakeAction, build_schedule, dispatch_action, due_action, heartbeat_from_ledger
from scripts.scheduler_once import _dispatcher, _evaluate_spot_position
from reverb.models import View


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

    def test_due_wake_without_dispatcher_is_a_blocked_non_success(self):
        with TemporaryDirectory() as temp:
            ledger = Ledger(Path(temp) / "ledger.jsonl")
            event = datetime(2026, 9, 24, 20, 5, tzinfo=timezone.utc)
            schedule = build_schedule("nvda-2026-09-24", event)
            result = dispatch_action(
                ledger=ledger, event_id=schedule.event_id, action=WakeAction.POSITION,
                schedule=schedule, now=event - timedelta(minutes=10), dispatcher=None,
            )
            self.assertEqual(result["status"], "blocked")
            self.assertEqual(ledger.verify()[-1]["kind"], "dispatch_blocked")

    def test_dispatcher_result_is_recorded(self):
        with TemporaryDirectory() as temp:
            ledger = Ledger(Path(temp) / "ledger.jsonl")
            event = datetime(2026, 9, 24, 20, 5, tzinfo=timezone.utc)
            schedule = build_schedule("nvda-2026-09-24", event)
            result = dispatch_action(
                ledger=ledger, event_id=schedule.event_id, action=WakeAction.REACT,
                schedule=schedule, now=event + timedelta(minutes=10),
                dispatcher=lambda action, current_schedule, now: {
                    "decision_id": "decision-1", "status": "refuse",
                    "action": action.value, "event_id": current_schedule.event_id,
                    "at": now.isoformat(),
                },
            )
            self.assertEqual(result["status"], "dispatched")
            self.assertEqual(ledger.verify()[-1]["kind"], "action_dispatched")

    def test_pre_event_dispatch_uses_spot_paper_path_and_never_submits(self):
        with TemporaryDirectory() as temp:
            ledger = Ledger(Path(temp) / "ledger.jsonl")
            event = datetime(2026, 9, 24, 20, 5, tzinfo=timezone.utc)
            schedule = build_schedule("calendar-event-1", event)
            seen = {}

            def evaluate(**kwargs):
                seen.update(kwargs)
                return {
                    "status": "hold", "tool": "spot_position",
                    "execution_allowed": False, "orders_submitted": False,
                }

            callback = _dispatcher(
                symbol="NVDA", view=View.BEAT,
                expected_move_pct=Decimal("0.05"),
                max_loss=Decimal("6"),
                user_timezone="Africa/Lagos", enable_live=True,
                ledger=ledger, spot_evaluator=evaluate,
            )
            result = callback(WakeAction.POSITION, schedule, event - timedelta(minutes=10))

            self.assertEqual(result["tool"], "spot_position")
            self.assertFalse(result["orders_submitted"])
            self.assertEqual(seen["event_id"], "calendar-event-1")
            self.assertEqual(seen["symbol"], "NVDA")
            self.assertEqual(seen["view"], View.BEAT)
            self.assertFalse(any(row["kind"] == "execution_blocked" for row in ledger.verify()))

    def test_spot_scheduler_revalidates_source_event_and_uses_public_client(self):
        event_at = datetime(2026, 9, 24, 20, 5, tzinfo=timezone.utc)
        event = EarningsEvent(
            symbol="NVDA", event_at=event_at, event_date=event_at.date(),
            source="calendar", source_id="source-42", time_basis="source_exact",
        )
        calendar = MagicMock()
        calendar.this_week.return_value = (event,)
        service = MagicMock()
        service.__enter__.return_value = service
        service.prepare_spot_position.return_value.model_dump.return_value = {
            "status": "hold", "orders_submitted": False,
        }
        ledger = MagicMock()

        with patch("scripts.scheduler_once.load_config",
                   return_value=SimpleNamespace(value=object(), sha256="config-hash")), \
                patch("scripts.scheduler_once.EarningsCalendar", return_value=calendar), \
                patch("scripts.scheduler_once.BitgetClient") as bitget, \
                patch("scripts.scheduler_once.DecisionService", return_value=service) as decision_service:
            result = _evaluate_spot_position(
                event_id="source-42", symbol="NVDA", view=View.BEAT,
                expected_move_pct=Decimal("0.04"), max_loss=Decimal("6"),
                event_at=event_at, user_timezone="Africa/Lagos", ledger=ledger,
            )

        self.assertFalse(result["orders_submitted"])
        bitget.assert_called_once_with()
        decision_service.assert_called_once()
        service.prepare_spot_position.assert_called_once_with(
            event=event, direction="beat", expected_move_pct=Decimal("0.04"),
            max_loss=Decimal("6"), user_timezone="Africa/Lagos",
        )
        calendar.close.assert_not_called()  # DecisionService owns it.

    def test_spot_scheduler_refuses_event_id_or_time_mismatch(self):
        event = EarningsEvent(
            symbol="NVDA", event_at=datetime(2026, 9, 24, 20, 5, tzinfo=timezone.utc),
            event_date=datetime(2026, 9, 24).date(), source="calendar",
            source_id="source-42", time_basis="source_exact",
        )
        calendar = MagicMock()
        calendar.this_week.return_value = (event,)
        ledger = MagicMock()
        with patch("scripts.scheduler_once.load_config",
                   return_value=SimpleNamespace(value=object(), sha256="config-hash")), \
                patch("scripts.scheduler_once.EarningsCalendar", return_value=calendar), \
                patch("scripts.scheduler_once.DecisionService") as decision_service:
            with self.assertRaises(DataUnavailable):
                _evaluate_spot_position(
                    event_id="wrong-source-id", symbol="NVDA", view=View.BEAT,
                    expected_move_pct=Decimal("0.04"), max_loss=Decimal("6"),
                    event_at=event.event_at, user_timezone="Africa/Lagos", ledger=ledger,
                )
        decision_service.assert_not_called()
        calendar.close.assert_called_once()
