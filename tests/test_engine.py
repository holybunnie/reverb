from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from reverb.errors import LedgerError
from reverb.gate import evaluate_option
from reverb.ledger import Ledger
from reverb.math import BlackScholesInputs, greeks, implied_volatility, option_expiry_at, price, time_to_expiry, value_option
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
                                   post_event_volatility_verified=True,
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
                                   post_event_volatility_verified=True,
                                   per_contract_fees=Decimal("1"), max_quote_age_ms=5000, now=received)
        self.assertEqual(decision.reason_codes, (ReasonCode.STALE_UNDERLYING,))

    def test_unverified_post_event_scenario_cannot_approve_option(self):
        now = datetime(2026, 9, 19, 10, 0, tzinfo=timezone.utc)
        thesis = Thesis(symbol="NVDA", view=View.BEAT, expected_move_pct=Decimal("0.08"),
                        max_loss=Decimal("1000"), event_at=datetime(2026, 9, 20, 20, 5, tzinfo=timezone.utc),
                        user_timezone="Africa/Lagos")
        underlying = UnderlyingQuote(symbol="NVDA.US", price=Decimal("100"), observed_at=now,
                                     source_timestamp=now)
        option = OptionQuote(symbol="NVDA261002C100000.US", underlying_symbol="NVDA.US",
                             direction=Direction.CALL, strike=Decimal("100"), expiry=date(2026, 10, 2),
                             contract_multiplier=Decimal("100"), bid=Decimal("2"), ask=Decimal("2.5"),
                             observed_at=now, source_timestamp=now)
        decision = evaluate_option(thesis=thesis, underlying=underlying, option=option,
                                   paired_straddle_move_pct=None, risk_free_rate=Decimal("0.03"),
                                   dividend_yield=Decimal("0"), post_event_volatility=None,
                                   post_event_volatility_verified=False, per_contract_fees=Decimal("1"),
                                   max_quote_age_ms=5000, now=now)
        self.assertEqual(decision.reason_codes, (ReasonCode.UNVERIFIED_ASSUMPTION,))

    def test_fees_are_per_contract_in_breakeven_and_scenario_pnl(self):
        now = datetime(2026, 9, 19, 10, 0, tzinfo=timezone.utc)
        inputs = BlackScholesInputs(Decimal("100"), Decimal("100"), Decimal("7") / Decimal("365"), Decimal("0.03"))
        ask = price(inputs, Direction.CALL, Decimal("0.35"))
        underlying = UnderlyingQuote(symbol="NVDA.US", price=Decimal("100"), observed_at=now,
                                     source_timestamp=now)
        option = OptionQuote(symbol="NVDA261002C100000.US", underlying_symbol="NVDA.US",
                             direction=Direction.CALL, strike=Decimal("100"), expiry=date(2026, 10, 2),
                             contract_multiplier=Decimal("100"), bid=ask - Decimal("0.01"), ask=ask,
                             observed_at=now, source_timestamp=now)
        valuation = value_option(underlying, option, datetime(2026, 9, 19, 20, 5, tzinfo=timezone.utc),
                                 Decimal("0.03"), Decimal("0"), Decimal("0.30"), None,
                                 Decimal("0.08"), Decimal("5"))
        expected_breakeven = option.strike + ask + Decimal("0.05")
        expected_pnl = (valuation.scenario_value_after_event - ask) * Decimal("100") - Decimal("5")
        self.assertEqual(valuation.breakeven_price, expected_breakeven)
        self.assertEqual(valuation.scenario_pnl, expected_pnl)

    def test_time_to_expiry_uses_intraday_expiry_boundary(self):
        valuation_at = datetime(2026, 9, 19, 15, 0, tzinfo=timezone.utc)
        expiry = date(2026, 9, 21)
        expected_seconds = (option_expiry_at(expiry) - valuation_at).total_seconds()
        expected = Decimal(str(expected_seconds)) / Decimal(365 * 24 * 60 * 60)
        self.assertEqual(time_to_expiry(valuation_at, expiry), expected)

    def test_ledger_requires_registration_before_outcome(self):
        with TemporaryDirectory() as temp:
            ledger = Ledger(Path(temp) / "ledger.jsonl")
            with self.assertRaises(LedgerError):
                ledger.outcome("missing", {"result": "unknown"})
            entry = ledger.register({"decision_id": "d1", "status": "refuse", "reason_codes": ["stale_option"]})
            self.assertEqual(entry["sequence"], 1)
            ledger.outcome("d1", {"result": "refused"})
            self.assertEqual(len(ledger.verify()), 2)

    def test_ledger_refuses_to_append_after_tampering(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "ledger.jsonl"
            ledger = Ledger(path)
            ledger.register({"decision_id": "d1", "status": "refuse"})
            path.write_bytes(path.read_bytes().replace(b'"status":"refuse"', b'"status":"act"'))
            with self.assertRaises(LedgerError):
                ledger.append("marker", {"reason": "must halt"})


if __name__ == "__main__":
    unittest.main()
