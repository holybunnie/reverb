from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from reverb.language import decision_with_narration, interpret_view_and_record
from reverb.ledger import Ledger
from reverb.errors import DataUnavailable
from reverb.qwen import QwenNarration, QwenViewInterpretation


class FakeQwen:
    def interpret_view(self, text):
        return QwenViewInterpretation(
            view="beat", provider="bitget-qwen", model="test-model",
            input_sha256="input", output_sha256="output",
        )

    def narrate(self, decision):
        return QwenNarration(
            text="Reverb refused because the required input was unavailable.",
            provider="bitget-qwen", model="test-model",
            input_sha256="ignored", output_sha256="narrated",
        )


class FailingQwen:
    def narrate(self, decision):
        raise DataUnavailable("language endpoint unavailable")


class LanguageTests(unittest.TestCase):
    def test_plain_language_view_is_recorded_separately_from_decision(self):
        with TemporaryDirectory() as temp:
            ledger = Ledger(Path(temp) / "ledger.jsonl")
            view = interpret_view_and_record(text="looks strong", ledger=ledger, qwen=FakeQwen())
            self.assertEqual(view.value, "beat")
            record = ledger.verify()[0]
            self.assertEqual(record["kind"], "view_interpretation")
            self.assertNotIn("looks strong", str(record))

    def test_narration_is_attached_without_changing_decision(self):
        with TemporaryDirectory() as temp:
            ledger = Ledger(Path(temp) / "ledger.jsonl")
            decision = {"decision_id": "d1", "status": "refuse", "reason_codes": ["data_unavailable"]}
            result = decision_with_narration(decision=decision, ledger=ledger, qwen=FakeQwen())
            self.assertEqual(result["status"], "refuse")
            self.assertEqual(result["narration"]["provider"], "bitget-qwen")
            self.assertEqual(ledger.verify()[0]["kind"], "narration")

    def test_qwen_failure_is_recorded_before_deterministic_fallback(self):
        with TemporaryDirectory() as temp:
            ledger = Ledger(Path(temp) / "ledger.jsonl")
            decision = {"decision_id": "d2", "status": "refuse", "reason_codes": ["data_unavailable"]}
            result = decision_with_narration(decision=decision, ledger=ledger, qwen=FailingQwen())
            self.assertEqual(result["narration"]["provider"], "deterministic-template")
            self.assertEqual([row["kind"] for row in ledger.verify()], ["language_failure", "narration"])


if __name__ == "__main__":
    unittest.main()
