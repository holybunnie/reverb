from pathlib import Path
import unittest

from reverb.demo import load_demo_snapshot, render_demo_html


class DemoTests(unittest.TestCase):
    def test_demo_replays_verified_capture_without_credentials(self):
        root = Path(__file__).resolve().parents[1]
        snapshot = load_demo_snapshot(root)
        self.assertEqual(snapshot.gate_status, "BLOCKED")
        self.assertGreater(snapshot.online_reality, 0)
        self.assertTrue(snapshot.samples)
        payload = snapshot.as_dict()
        self.assertFalse(payload["credentials_required"])
        self.assertFalse(payload["earnings_event"])

    def test_demo_page_labels_its_limits(self):
        root = Path(__file__).resolve().parents[1]
        page = render_demo_html(load_demo_snapshot(root))
        self.assertIn("not an earnings event", page)
        self.assertIn("Feasibility gate", page)
        self.assertIn("BLOCKED", page)

