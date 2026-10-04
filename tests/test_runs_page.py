import json
import re
import unittest
from pathlib import Path

from reverb.runs_page import render_runs_html, runs_data

ROOT = Path(__file__).resolve().parents[1]


class RunsPageTests(unittest.TestCase):
    def test_every_registered_event_has_a_card_matching_its_frozen_hash(self):
        runs = {r["id"]: r for r in runs_data()}
        for registration in (ROOT / "evidence/events").glob("*/registration_manifest.json"):
            data = json.loads(registration.read_text())
            self.assertEqual(runs[data["event_id"]]["frozen_sha256"], data["frozen_thesis_sha256"])
            self.assertIsNone(runs[data["event_id"]]["result"])

    def test_page_embeds_data_and_makes_no_network_calls(self):
        page = render_runs_html()
        self.assertNotRegex(page, r"fetch\(|<script src=")
        embedded = re.search(r'<script id="data" type="application/json">(.*?)</script>', page, re.S).group(1)
        self.assertEqual(len(json.loads(embedded)), len(runs_data()))


if __name__ == "__main__":
    unittest.main()
