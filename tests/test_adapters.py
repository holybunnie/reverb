from datetime import datetime, timezone
from decimal import Decimal
import unittest

from reverb.adapters import option_expiry, parse_option_quote, parse_rtoken_ticker
from reverb.errors import DataUnavailable


class AdapterTests(unittest.TestCase):
    def test_option_expiry_accepts_both_documented_shapes(self):
        self.assertEqual(option_expiry("20261016").isoformat(), "2026-10-16")
        self.assertEqual(option_expiry("261016").isoformat(), "2026-10-16")

    def test_option_quote_preserves_missing_bid_ask(self):
        quote = parse_option_quote({
            "symbol": "NVDA261016C180000.US", "underlyingSymbol": "NVDA.US", "direction": "C",
            "strikePrice": "180", "expiryDate": "20261016", "contractMultipier": "100",
            "lastDone": "4.20", "impliedVolatility": "0.75", "timestamp": "1789810000000",
            "tradeStatus": "1",
        }, observed_at=datetime(2026, 9, 19, tzinfo=timezone.utc))
        self.assertEqual(quote.contract_multiplier, Decimal("100"))
        self.assertIsNone(quote.bid)
        self.assertIsNone(quote.ask)
        self.assertFalse(quote.executable)

    def test_rtoken_ticker_requires_price(self):
        with self.assertRaises(DataUnavailable):
            parse_rtoken_ticker({"symbol": "RNVDAUSDT", "ts": "1789810000000"})


if __name__ == "__main__":
    unittest.main()
