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
            scored = (registration.parent / "post_event/reconciliation.json").exists()
            self.assertEqual(runs[data["event_id"]]["result"] is not None, scored)

    def test_page_embeds_data_and_makes_no_network_calls(self):
        page = render_runs_html()
        self.assertNotRegex(page, r"fetch\(|<script src=")
        embedded = re.search(r'<script id="data" type="application/json">(.*?)</script>', page, re.S).group(1)
        self.assertEqual(len(json.loads(embedded)), len(runs_data()))

    def test_every_scored_run_links_to_a_built_walkthrough(self):
        for run in runs_data():
            if run["result"] is None:
                continue
            self.assertTrue(run["walkthrough"], run["id"])
            self.assertIn(run["walkthrough"], ("walkthrough/", "walkthrough/stz/", "walkthrough/apld/"))


if __name__ == "__main__":
    unittest.main()


class StzWalkthroughTests(unittest.TestCase):
    def test_stz_walkthrough_reads_committed_evidence_and_makes_no_network_calls(self):
        from reverb.walkthrough_stz import render_stz_walkthrough_html, walkthrough_data
        data = walkthrough_data()
        self.assertEqual(data["decision"], {"action": "REVIEW", "orders": 0, "run_status": "COMPLETE",
                                            "live_orders_allowed": False})
        self.assertEqual([v["frozen_status"] for v in data["verdicts"]],
                         ["CONFIRMED", "CONTRADICTED", "CONFIRMED", "NOT_ADDRESSED"])
        self.assertEqual([c["at"] for c in data["clock"]], sorted(c["at"] for c in data["clock"]))
        page = render_stz_walkthrough_html()
        self.assertNotRegex(page, r"fetch\(|<script src=|Costco release</text>")


class ApldWalkthroughTests(unittest.TestCase):
    def test_apld_walkthrough_reads_committed_evidence_and_makes_no_network_calls(self):
        from reverb.walkthrough_apld import render_apld_walkthrough_html, walkthrough_data
        data = walkthrough_data()
        self.assertEqual(data["decision"], {"action": "REVIEW", "orders": 0, "run_status": "COMPLETE",
                                            "live_orders_allowed": False})
        self.assertEqual([v["frozen_status"] for v in data["verdicts"]],
                         ["CONFIRMED", "CONFIRMED", "CONTRADICTED", "NOT_ADDRESSED"])
        self.assertEqual([c["at"] for c in data["clock"]], sorted(c["at"] for c in data["clock"]))
        page = render_apld_walkthrough_html()
        self.assertNotRegex(page, r"fetch\(|<script src=|Costco release</text>|RSTZ one-minute")


class BitgetCrossCheckTests(unittest.TestCase):
    def test_every_run_carries_the_committed_bitget_calendar_check(self):
        crosscheck = json.loads((ROOT / "evidence/bitget-data/release_crosscheck.json").read_text())
        committed = {item["run"]: item for item in crosscheck["runs"]}
        for run in runs_data():
            self.assertIn(run["id"], committed)
            self.assertEqual(run["bitget_check"]["status"], committed[run["id"]]["status"])
            self.assertEqual(run["files"]["bitget"], "evidence/bitget-data/release_crosscheck.json")

    def test_committed_crosscheck_recomputes_from_its_raw_rows(self):
        import hashlib
        import importlib.util
        spec = importlib.util.spec_from_file_location("crosscheck", ROOT / "scripts/bitget_data_crosscheck.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        committed = json.loads(module.OUTPUT.read_text())
        for item in committed["runs"]:
            raw = ROOT / item["raw_path"]
            self.assertEqual(hashlib.sha256(raw.read_bytes()).hexdigest(), item["raw_sha256"])
            recomputed = module.compare_run(item["run"], json.loads(raw.read_text()),
                                            committed["calendar_match_window_days"])
            self.assertEqual(recomputed, {k: v for k, v in item.items() if k not in {"raw_path", "raw_sha256"}})
