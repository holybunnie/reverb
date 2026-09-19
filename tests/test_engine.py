from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from reverb.errors import LedgerError
from reverb.gate import evaluate_option
from reverb.ledger import Ledger
from reverb.math import BlackScholesInputs, greeks, implied_volatility, price
from reverb.models import Direction, OptionQuote, ReasonCode, Thesis, UnderlyingQuote, View


class EngineTests(unittest.TestCase):
    def test_black_scholes_round_trip_uses_scipy_root(self):
        inputs = BlackScholesInputs(Decimal("100"), Decimal("100"), Decimal("0.5"), Decimal("0.02"))
        known_vol = Decimal("0.35")
        option_price = price(inputs, Direction.CALL, known_vol)
        recovered = implied_volatility(inputs, Direction.CALL, option_price)
        self.assertAlmostEqual(float(recovered), float(known_vol), places=9)
        values = greeks(inputs, Direction.CALL, recovered)
        self.assertGreater(values["gamma"], 0)
        self.assertGreater(values["vega"], 0)

    def test_option_quote_without_bid_ask_is_a_refusal(self):
        now = datetime(2026, 9, 19, 10, 0, tzinfo=timezone.utc)
        thesis = Thesis(symbol="NVDA", view=View.BEAT, expected_move_pct=Decimal("0.08"),
                        max_loss=Decimal("1000"), event_at=datetime(2026, 9, 20, 20, 5, tzinfo=timezone.utc),
                        user_timezone="Africa/Lagos")
        underlying = UnderlyingQuote(symbol="NVDA.US", price=Decimal("100"), observed_at=now,
                                     source_timestamp=now)
        option = OptionQuote(symbol="NVDA260925C100000.US", underlying_symbol="NVDA.US",
                             direction=Direction.CALL, strike=Decimal("100"), expiry=date(2026, 9, 25),
                             contract_multiplier=Decimal("100"), last_done=Decimal("2.5"),
                             observed_at=now, source_timestamp=now)
        decision = evaluate_option(thesis=thesis, underlying=underlying, option=option,
                                   paired_straddle_move_pct=None, risk_free_rate=Decimal("0.03"),
                                   dividend_yield=Decimal("0"), post_event_volatility=Decimal("0.25"),
                                   per_contract_fees=Decimal("1"), max_quote_age_ms=5000, now=now)
        self.assertEqual(decision.status.value, "refuse")
        self.assertEqual(decision.reason_codes, (ReasonCode.OPTION_BID_ASK_UNAVAILABLE,))

    def test_source_timestamp_not_receipt_time_controls_freshness(self):
        received = datetime(2026, 9, 19, 10, 0, tzinfo=timezone.utc)
        stale = datetime(2026, 9, 19, 9, 59, 50, tzinfo=timezone.utc)
        thesis = Thesis(symbol="NVDA", view=View.BEAT, expected_move_pct=Decimal("0.08"),
                        max_loss=Decimal("1000"), event_at=datetime(2026, 9, 20, 20, 5, tzinfo=timezone.utc),
                        user_timezone="Africa/Lagos")
        underlying = UnderlyingQuote(symbol="NVDA.US", price=Decimal("100"), observed_at=received,
                                     source_timestamp=stale)
        option = OptionQuote(symbol="NVDA260925C100000.US", underlying_symbol="NVDA.US",
                             direction=Direction.CALL, strike=Decimal("100"), expiry=date(2026, 9, 25),
                             contract_multiplier=Decimal("100"), bid=Decimal("2"), ask=Decimal("2.5"),
                             observed_at=received, source_timestamp=received)
        decision = evaluate_option(thesis=thesis, underlying=underlying, option=option,
                                   paired_straddle_move_pct=None, risk_free_rate=Decimal("0.03"),
                                   dividend_yield=Decimal("0"), post_event_volatility=Decimal("0.25"),
                                   per_contract_fees=Decimal("1"), max_quote_age_ms=5000, now=received)
        self.assertEqual(decision.reason_codes, (ReasonCode.STALE_UNDERLYING,))

    def test_ledger_requires_registration_before_outcome(self):
        with TemporaryDirectory() as temp:
            ledger = Ledger(Path(temp) / "ledger.jsonl")
            with self.assertRaises(LedgerError):
                ledger.outcome("missing", {"result": "unknown"})
            entry = ledger.register({"decision_id": "d1", "status": "refuse", "reason_codes": ["stale_option"]})
            self.assertEqual(entry["sequence"], 1)
            ledger.outcome("d1", {"result": "refused"})
            self.assertEqual(len(ledger.verify()), 2)


if __name__ == "__main__":
    unittest.main()
