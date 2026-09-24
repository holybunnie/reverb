from datetime import datetime, timedelta, timezone
from decimal import Decimal
import unittest

from reverb.errors import DataUnavailable
from reverb.reaction import baseline_price, evaluate_reaction, select_reaction_observation
from reverb.sessions import Session, session_at


class ReactionTests(unittest.TestCase):
    def test_completed_window_uses_first_trigger_crossing(self):
        event = datetime(2026, 8, 26, 20, 5, tzinfo=timezone.utc)
        rows = [
            [str(int((event + timedelta(minutes=i)).timestamp() * 1000)), "100", "100", "100", close]
            for i, close in enumerate(("101", "104", "102"))
        ]
        observed_at, observed_price = select_reaction_observation(
            rows=rows, event_at=event, end_at=event + timedelta(minutes=3),
            baseline=Decimal("100"), trigger_pct=Decimal("0.03"),
        )
        self.assertEqual(observed_at, event + timedelta(minutes=1))
        self.assertEqual(observed_price, Decimal("104"))

    def test_completed_window_keeps_largest_excursion_below_threshold(self):
        event = datetime(2026, 8, 26, 20, 5, tzinfo=timezone.utc)
        rows = [
            [str(int((event + timedelta(minutes=i)).timestamp() * 1000)), "100", "100", "100", close]
            for i, close in enumerate(("101", "97.03", "99.9"))
        ]
        observed_at, observed_price = select_reaction_observation(
            rows=rows, event_at=event, end_at=event + timedelta(minutes=3),
            baseline=Decimal("100"), trigger_pct=Decimal("0.03"),
        )
        self.assertEqual(observed_at, event + timedelta(minutes=1))
        self.assertEqual(observed_price, Decimal("97.03"))

    def test_baseline_requires_contiguous_one_minute_candles(self):
        event = datetime(2026, 9, 19, 16, 5, tzinfo=timezone.utc)
        rows = [[int((event - timedelta(minutes=60 - i)).timestamp() * 1000), "99", "101", "98", str(100 + i / 100), "1"] for i in range(60)]
        baseline, arithmetic = baseline_price(rows, event, 60, 30)
        self.assertGreater(baseline, Decimal("100"))
        self.assertEqual(arithmetic["timestamp_gaps"], "0")
        rows.pop(10)
        with self.assertRaises(DataUnavailable):
            baseline_price(rows, event, 60, 30)

    def test_weekend_market_order_is_refused(self):
        event = datetime(2026, 9, 19, 16, 5, tzinfo=timezone.utc)
        observed = event
        decision = evaluate_reaction(symbol="RNVDAUSDT", baseline=Decimal("100"), observed_price=Decimal("105"),
                                     observed_at=observed, baseline_observed_at=event - timedelta(minutes=5),
                                     trigger_pct=Decimal("0.03"), session=Session.WEEKEND,
                                     order_type="market", max_quote_age_ms=5000, now=observed)
        self.assertEqual(decision.status.value, "refuse")
        self.assertEqual(decision.reason_codes[0].value, "session_unavailable")

    def test_triggered_move_without_registered_order_intent_is_refused(self):
        event = datetime(2026, 9, 19, 20, 5, tzinfo=timezone.utc)
        decision = evaluate_reaction(
            symbol="RNVDAUSDT", baseline=Decimal("100"), observed_price=Decimal("105"),
            observed_at=event, baseline_observed_at=event - timedelta(minutes=1),
            trigger_pct=Decimal("0.03"), session=Session.AFTER_HOURS,
            order_type="limit", max_quote_age_ms=5000, now=event,
        )
        self.assertEqual(decision.status.value, "refuse")
        self.assertEqual(decision.reason_codes[0].value, "invalid_order_intent")

    def test_triggered_move_cannot_exceed_reaction_budget(self):
        event = datetime(2026, 9, 19, 20, 5, tzinfo=timezone.utc)
        decision = evaluate_reaction(
            symbol="RNVDAUSDT", baseline=Decimal("100"), observed_price=Decimal("105"),
            observed_at=event, baseline_observed_at=event - timedelta(minutes=1),
            trigger_pct=Decimal("0.03"), session=Session.AFTER_HOURS,
            order_type="limit", max_quote_age_ms=5000, now=event,
            intended_side="buy", order_quantity=Decimal("2"), order_price=Decimal("105"),
            risk_budget=Decimal("100"),
        )
        self.assertEqual(decision.status.value, "refuse")
        self.assertEqual(decision.reason_codes[0].value, "risk_budget_exceeded")

    def test_session_uses_new_york_clock(self):
        instant = datetime(2026, 9, 18, 20, 5, tzinfo=timezone.utc)
        self.assertEqual(session_at(instant).session, Session.AFTER_HOURS)


if __name__ == "__main__":
    unittest.main()
