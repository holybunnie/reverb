from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from reverb.ledger import Ledger
from reverb.narration import narrate_and_record


class NarrationTests(unittest.TestCase):
    def test_deterministic_narration_is_recorded_without_qwen(self):
        with TemporaryDirectory() as temp:
            ledger = Ledger(Path(temp) / "ledger.jsonl")
            result = narrate_and_record(
                decision={"decision_id": "decision-1", "status": "refuse", "reason_codes": ["stale_option"]},
                ledger=ledger,
            )
            self.assertEqual(result.provider, "deterministic-template")
            self.assertIn("REFUSE", result.text)
            records = ledger.verify()
            self.assertEqual(records[-1]["kind"], "narration")
            self.assertEqual(records[-1]["payload"]["decision_id"], "decision-1")

