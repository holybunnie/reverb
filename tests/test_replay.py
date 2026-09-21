from pathlib import Path
import unittest

from reverb.replay import load_replay_snapshot, render_replay_html, render_replay_report


class ReplayTests(unittest.TestCase):
    def test_real_capture_regenerates_action_and_budget_refusal(self):
        snapshot = load_replay_snapshot(Path(__file__).resolve().parents[1])
        self.assertEqual(snapshot.action["status"], "act")
        self.assertEqual(snapshot.refusal["status"], "refuse")
        self.assertIn("risk_budget_exceeded", snapshot.refusal["reason_codes"])
        self.assertEqual(snapshot.arithmetic["rows"], "90")
        self.assertEqual(snapshot.arithmetic["trigger_pct"], "0.02")

    def test_demo_and_report_are_explicitly_paper_only(self):
        root = Path(__file__).resolve().parents[1]
        snapshot = load_replay_snapshot(root)
        page = render_replay_html(snapshot)
        report = render_replay_report(snapshot)
        self.assertIn("No order was submitted", page)
        self.assertIn("risk budget", page.lower())
        self.assertIn("No order was submitted", report)
        self.assertIn("203.94", page)


if __name__ == "__main__":
    unittest.main()
