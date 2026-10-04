import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

from reverb.walkthrough import render_walkthrough_html, walkthrough_data

ROOT = Path(__file__).resolve().parents[1]
THESES = ["evidence/costco/frozen_thesis.json", "evidence/costco/frozen_thesis_v2.json"]


class WalkthroughTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = walkthrough_data()
        cls.page = render_walkthrough_html(cls.data)

    def test_numbers_match_committed_evidence(self):
        summary = json.loads((ROOT / "evidence/costco/capture_summary.json").read_text())
        recon = json.loads((ROOT / "evidence/costco/post_event/reconciliation.json").read_text())
        market = self.data["market"]
        reaction = summary["reaction"]
        for key in ("baseline_close", "max_pct", "max_at", "max_close", "trigger_pct"):
            self.assertEqual(market[{"baseline_close": "baseline"}.get(key, key)], reaction[key])
        closes = dict(market["closes"])
        self.assertEqual(closes[reaction["baseline_at"]], reaction["baseline_close"])
        self.assertEqual(max(closes.values()), reaction["max_close"])
        self.assertEqual(market["book"]["with_visible_levels"], 0)
        self.assertEqual(self.data["decision"]["orders"], summary["orders"])
        self.assertEqual(self.data["frozen"]["sha256"], recon["frozen_thesis_sha256"])
        verdicts = {v["id"]: v for v in self.data["verdicts"]}
        self.assertEqual(verdicts["c2"]["values"], ["1,850", "1,724"])
        self.assertEqual(verdicts["c3"]["addendum"]["values"][0], "-11 bps")
        self.assertEqual(self.data["qwen_check"]["matching"], 0)

    def test_highlights_are_exact_source_offsets(self):
        for verdict in self.data["verdicts"]:
            for evidence in filter(None, [verdict.get("evidence"), (verdict.get("addendum") or {}).get("evidence")]):
                text = (ROOT / evidence["file"]).read_text(encoding="utf-8")
                self.assertEqual(text[evidence["start"]:evidence["end"]], evidence["match"])

    def test_embedded_data_round_trips_and_page_is_offline_except_links(self):
        embedded = re.search(r'<script id="data" type="application/json">(.*?)</script>', self.page, re.S).group(1)
        self.assertEqual(json.loads(embedded.replace("<\\/", "</")), json.loads(json.dumps(self.data)))
        self.assertNotRegex(self.page, r"fetch\(|<script src=|<link [^>]*href=\"http")
        for phrase in ("HOLD", "never places an order", "not a claim that the strategy is profitable", "recorded on"):
            self.assertIn(phrase, self.page)

    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_js_canonicalisation_matches_python_hash(self):
        script = re.search(r"(function canonical\(v\) \{.*?\n\})", self.page, re.S).group(1)
        for path in THESES:
            thesis = json.loads((ROOT / path).read_text())
            expected = thesis.pop("sha256")
            js = script + ("\nconst c=require('crypto');const b=" + json.dumps(thesis) +
                           ";process.stdout.write(c.createHash('sha256').update(canonical(b)).digest('hex'));")
            out = subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout
            self.assertEqual(out, expected, path)


if __name__ == "__main__":
    unittest.main()
