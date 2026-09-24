from pathlib import Path
import json
from decimal import Decimal
import unittest

from reverb.replay import load_replay_snapshot, render_replay_html, render_replay_report


class ReplayTests(unittest.TestCase):
    def test_real_capture_uses_production_trigger_and_holds_below_threshold(self):
        root = Path(__file__).resolve().parents[1]
        engine = json.loads((root / "config" / "engine.json").read_text())
        replay_config = json.loads((root / "config" / "replay.json").read_text())
        self.assertEqual(Decimal(replay_config["trigger_pct"]), Decimal(engine["reaction_trigger_pct"]))
        snapshot = load_replay_snapshot(root)
        self.assertEqual(snapshot.action["status"], "hold")
        self.assertEqual(snapshot.refusal["status"], "hold")
        self.assertEqual(snapshot.arithmetic["rows"], "90")
        self.assertEqual(snapshot.arithmetic["trigger_pct"], "0.03")

    def test_demo_and_report_are_explicitly_paper_only(self):
        root = Path(__file__).resolve().parents[1]
        snapshot = load_replay_snapshot(root)
        page = render_replay_html(snapshot)
        report = render_replay_report(snapshot)
        self.assertIn("No order was submitted", page)
        self.assertIn("did not act", page.lower())
        self.assertIn("No order was submitted", report)
        self.assertIn("3.00%", report)


if __name__ == "__main__":
    unittest.main()
