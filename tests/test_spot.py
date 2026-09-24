from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import unittest

from reverb.models import UnderlyingQuote
from reverb.spot import calculate_long_limit_plan


ROOT = Path(__file__).resolve().parents[1]
CAPTURE = ROOT / "evidence" / "runs" / "20260922T014245.703699Z-92c20c78"


class SpotSizingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        instruments = json.loads((CAPTURE / "002-instruments.body").read_text())["data"]
        cls.instrument = next(row for row in instruments if row["symbol"] == "RNVDAUSDT")
        book = json.loads((CAPTURE / "010-book-RNVDAUSDT.body").read_text())["data"]
        record = next(
            json.loads(line) for line in (CAPTURE / "ledger.jsonl").read_text().splitlines()
            if json.loads(line).get("name") == "book-RNVDAUSDT"
        )
        stamp = datetime.fromtimestamp(int(book["ts"]) / 1000, timezone.utc)
        cls.quote = UnderlyingQuote(
            symbol="RNVDAUSDT",
            price=(Decimal(str(book["b"][0][0])) + Decimal(str(book["a"][0][0]))) / Decimal("2"),
            bid=Decimal(str(book["b"][0][0])),
            ask=Decimal(str(book["a"][0][0])),
            observed_at=datetime.fromisoformat(record["received_at"].replace("Z", "+00:00")),
            source_timestamp=stamp,
        )

    def test_size_uses_recorded_precision_and_never_exceeds_principal_budget(self):
        plan = calculate_long_limit_plan(
            risk_budget=Decimal("1000"), quote=self.quote, instrument=self.instrument,
        )
        self.assertTrue(plan.meets_exchange_minimum)
        self.assertLessEqual(plan.principal_notional, Decimal("1000"))
        self.assertEqual(plan.quantity.as_tuple().exponent, -int(self.instrument["quantityPrecision"]))
        self.assertEqual(plan.limit_price.as_tuple().exponent, -int(self.instrument["pricePrecision"]))
        self.assertGreaterEqual(plan.limit_price, self.quote.ask)

    def test_minimum_order_gate_refuses_budget_below_live_instrument_minimum(self):
        plan = calculate_long_limit_plan(
            risk_budget=Decimal("1"), quote=self.quote, instrument=self.instrument,
        )
        self.assertFalse(plan.meets_exchange_minimum)
        self.assertLess(plan.principal_notional, Decimal(str(self.instrument["minOrderAmount"])))


if __name__ == "__main__":
    unittest.main()
