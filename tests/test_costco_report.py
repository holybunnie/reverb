from pathlib import Path
import unittest

from reverb.costco_report import costco_report_summary, render_costco_morning_brief


ROOT = Path(__file__).resolve().parents[1]


class CostcoReportTests(unittest.TestCase):
    def test_frozen_costco_brief_is_integrated_and_incomplete_until_capture(self):
        summary = costco_report_summary(ROOT)
        page = render_costco_morning_brief(ROOT)
        self.assertIsNotNone(summary)
        self.assertIsNotNone(page)
        self.assertEqual(summary["token"], "RCOSTUSDT")
        self.assertEqual(summary["status"], "THESIS FROZEN · CAPTURE PENDING")
        self.assertIn("EPS above consensus", page)
        self.assertIn("UNSCORED", page)
        self.assertIn("REFUSE", page)
        self.assertIn("public order-book interval", page)
        self.assertIn("data-human-review", page)
        self.assertNotIn("NVIDIA", page)


if __name__ == "__main__":
    unittest.main()
