from datetime import datetime
from decimal import Decimal
import json
from pathlib import Path
import unittest
from zoneinfo import ZoneInfo

from reverb.replay import load_replay_snapshot


ROOT = Path(__file__).resolve().parents[1]


class ReadmeEvidenceTests(unittest.TestCase):
    def test_published_replay_numbers_match_verified_replay_capture(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        replay = load_replay_snapshot(ROOT)
        arithmetic = replay.arithmetic
        move_percent = (Decimal(arithmetic["move_pct"]) * 100).quantize(Decimal("0.01"))
        displayed_move = f"{move_percent}%".replace("-", "−")
        observed = datetime.fromisoformat(arithmetic["observed_at"].replace("Z", "+00:00"))
        event_time = observed.astimezone(ZoneInfo("America/New_York")).strftime("%H:%M ET")
        self.assertIn(f"{arithmetic['rows']} contiguous one-minute Reality candles", readme)
        self.assertIn("`$" + arithmetic["baseline"] + "`", readme)
        self.assertIn(f"`{displayed_move}` at `{event_time}`", readme)
        trigger = Decimal(arithmetic["trigger_pct"]) * 100
        self.assertIn(f"`{trigger.normalize()}%`", readme)
        self.assertIn("so Reverb held and did not act", readme)
        self.assertIn("| Orders in the replay | `0` |", readme)

    def test_published_runtime_costco_eligibility_matches_raw_stock_info(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        directory = ROOT / "evidence" / "runs" / "20260923T115045.662310Z-11d40a83"
        body = json.loads((directory / "004-stock-info.body").read_text(encoding="utf-8"))
        ledger = [json.loads(line) for line in (directory / "ledger.jsonl").read_text().splitlines()]
        row = next(item for item in body["data"] if item["symbol"] == "RCOSTUSDT")
        capture = next(item for item in ledger if item.get("kind") == "http" and item.get("name") == "stock-info")
        self.assertIn("after_hours", row["tradingPeriod"])
        self.assertEqual(row["weekendTradable"], "no")
        self.assertIn("`RCOSTUSDT`", readme)
        self.assertIn("`weekendTradable: no`", readme)
        self.assertEqual(capture["body_sha256"], "862ee9420ffe8729586ae93f490396d0067a24c2e049c1c36dcec1f54cba8450")

    def test_published_qwen_status_matches_sanitized_evidence(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        ledger = [json.loads(line) for line in (ROOT / "evidence" / "qwen" / "ledger.jsonl").read_text().splitlines()]
        verified = [item["payload"] for item in ledger
                    if item.get("kind") == "qwen_live_check" and item.get("payload", {}).get("status") == "verified"]
        self.assertTrue(verified)
        self.assertIn("Qwen live check", readme)
        self.assertTrue(all(not item.get("order_calls") and not item.get("bitget_account_calls") for item in verified))


if __name__ == "__main__":
    unittest.main()
