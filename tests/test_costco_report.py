from pathlib import Path
import unittest

from reverb.costco_report import costco_report_summary, render_costco_morning_brief


ROOT = Path(__file__).resolve().parents[1]


class CostcoReportTests(unittest.TestCase):
    def test_costco_brief_reports_recorded_capture_and_reconciliation(self):
        summary = costco_report_summary(ROOT)
        page = render_costco_morning_brief(ROOT)
        self.assertIsNotNone(summary)
        self.assertIsNotNone(page)
        self.assertEqual(summary["token"], "RCOSTUSDT")
        self.assertEqual(summary["status"], "RUN COMPLETE · HELD")
        self.assertEqual(summary["move"], "+1.17%")
        self.assertIn("EPS above consensus", page)
        self.assertIn("NO FAIR BENCHMARK", page)
        self.assertIn("NOT ATTRIBUTED", page)
        self.assertIn("CONFIRMED", page)
        self.assertIn("Scored: 1 of 1", page)
        self.assertIn("HOLD", page)
        self.assertIn("did not cross", page)
        self.assertIn("No quoted depth", page)
        self.assertIn("data-human-review", page)
        self.assertNotIn("NVIDIA", page)


if __name__ == "__main__":
    unittest.main()
