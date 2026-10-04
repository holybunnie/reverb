import importlib.util
import json
import unittest
from pathlib import Path

from reverb.ledger import Ledger

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "evidence/costco/raw/20260924T072322Z-1239ae49"


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CostcoRawCaptureTests(unittest.TestCase):
    def test_published_ledger_verifies_to_recorded_head(self):
        rows = Ledger(RAW / "ledger.jsonl").verify()
        self.assertEqual(rows[-1]["hash"], json.loads((ROOT / "evidence/costco/capture_summary.json").read_text())["ledger_head"])

    def test_summary_rebuilds_byte_identically_from_published_raw(self):
        summary = load("costco_capture_summary")
        self.assertEqual(summary.render(RAW), (ROOT / "evidence/costco/capture_summary.json").read_text(encoding="utf-8"))

    def test_published_raw_passes_secret_scan(self):
        self.assertEqual(load("costco_publish_raw").scan_tree(RAW), {})

    def test_account_scoped_bodies_are_withheld_by_hash(self):
        self.assertFalse(list(RAW.glob("*-reality_*.body")))
        withheld = (RAW / "WITHHELD.md").read_text(encoding="utf-8")
        for line in (RAW / "ledger.jsonl").read_text(encoding="utf-8").splitlines():
            payload = json.loads(line)["payload"]
            if payload.get("endpoint", "").startswith("reality_") and payload.get("body"):
                self.assertIn(payload["body_sha256"], withheld)

    def test_secret_scan_catches_account_fields(self):
        scan = load("costco_publish_raw").scan_text
        self.assertTrue(scan('{"uid": "123"}'))
        self.assertTrue(scan("ACCESS-SIGN: abc"))
        self.assertFalse(scan('{"code":"00000","data":[["1790272260000","896.1"]]}'))


if __name__ == "__main__":
    unittest.main()
