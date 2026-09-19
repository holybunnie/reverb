from pathlib import Path
import unittest

from reverb.preview import load_preview_snapshot, render_preview_html


class PreviewTests(unittest.TestCase):
    def test_preview_replays_verified_capture_without_credentials(self):
        root = Path(__file__).resolve().parents[1]
        snapshot = load_preview_snapshot(root)
        self.assertEqual(snapshot.gate_status, "BLOCKED")
        self.assertGreater(snapshot.online_reality, 0)
        self.assertTrue(snapshot.samples)
        payload = snapshot.as_dict()
        self.assertFalse(payload["credentials_required"])
        self.assertFalse(payload["earnings_event"])

    def test_preview_page_labels_its_limits(self):
        root = Path(__file__).resolve().parents[1]
        page = render_preview_html(load_preview_snapshot(root))
        self.assertIn("not an earnings event", page)
        self.assertIn("Feasibility gate", page)
        self.assertIn("BLOCKED", page)
