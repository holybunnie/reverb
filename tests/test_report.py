from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from reverb.ledger import Ledger
from reverb.report import morning_report


class ReportTests(unittest.TestCase):
    def test_refusal_report_includes_ledger_backed_arithmetic(self):
        with TemporaryDirectory() as temp:
            ledger = Ledger(Path(temp) / "ledger.jsonl")
            ledger.register({
                "decision_id": "decision-refusal",
                "status": "refuse",
                "reason_codes": ["market_expects_larger_move"],
                "arithmetic": {
                    "market_implied_move_pct": "0.1200",
                    "thesis_expected_move_pct": "0.0800",
                    "comparison": "market >= thesis",
                },
            })
            page = morning_report(ledger)

        self.assertIn("Arithmetic recorded before the decision", page)
        self.assertIn("Market implied move pct", page)
        self.assertIn("0.1200", page)
        self.assertIn("market &gt;= thesis", page)


if __name__ == "__main__":
    unittest.main()
