from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest
from unittest.mock import patch
import httpx

from reverb.language import decision_with_narration, extract_thesis_and_record, interpret_view_and_record
from reverb.ledger import Ledger
from reverb.errors import DataUnavailable
from reverb.qwen import QwenClient, QwenCredentials, QwenNarration, QwenViewInterpretation


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
    def test_hackathon_qwen_key_name_is_accepted(self):
        with patch.dict("os.environ", {"QWEN_API_KEY": "local-test-value"}, clear=True):
            credentials = QwenCredentials.from_env()
        self.assertEqual(credentials.api_key, "local-test-value")

    def test_hackathon_recommended_qwen_model_is_default(self):
        with patch.dict("os.environ", {"QWEN_API_KEY": "local-test-value"}, clear=True):
            credentials = QwenCredentials.from_env()
        self.assertEqual(credentials.model, "qwen3.8-max")

    def test_qwen_request_timeout_allows_slow_narration_response(self):
        credentials = QwenCredentials(api_key="local-test-value", base_url="https://example.invalid/v1",
                                      model="test-model")
        with patch("reverb.qwen.httpx.Client") as client:
            QwenClient(credentials)
        client.assert_called_once_with(timeout=120.0)

    def test_plain_language_view_is_recorded_separately_from_decision(self):
        with TemporaryDirectory() as temp:
            ledger = Ledger(Path(temp) / "ledger.jsonl")
            view = interpret_view_and_record(text="looks strong", ledger=ledger, qwen=FakeQwen())
            self.assertEqual(view.value, "beat")
            record = ledger.verify()[0]
            self.assertEqual(record["kind"], "view_interpretation")
            self.assertNotIn("looks strong", str(record))

    def test_thesis_extraction_only_records_candidate_claims_for_user_review(self):
        response_body = {"choices": [{"message": {"content": json.dumps({"claims": [{
            "claim_id": "c1", "text": "EPS above consensus", "variable": "EPS",
            "comparison": "ABOVE_REFERENCE", "claim_type": "QUARTER_FACT",
        }]})}}]}
        requests = []

        def handle(request):
            requests.append(request)
            return httpx.Response(200, json=response_body)

        transport = httpx.MockTransport(handle)
        client = QwenClient(QwenCredentials("local-test-value", "https://example.test/v1", "test-model"),
                            client=httpx.Client(transport=transport))
        with TemporaryDirectory() as temp:
            ledger = Ledger(Path(temp) / "ledger.jsonl")
            extracted = extract_thesis_and_record(
                text="I think earnings beat consensus.",
                approved_rule_definitions={"EPS beats consensus": "ABOVE_REFERENCE"},
                ledger=ledger, qwen=client,
            )
            rows = ledger.verify()
        client.close()
        self.assertEqual(extracted.extraction.claims[0].comparison.value, "ABOVE_REFERENCE")
        self.assertEqual(rows[0]["kind"], "thesis_claim_extraction")
        self.assertTrue(rows[0]["payload"]["requires_user_confirmation"])
        self.assertFalse(rows[0]["payload"]["outcome_statuses_assigned"])
        self.assertNotIn("status", rows[0]["payload"]["claims"][0])
        self.assertEqual(json.loads(requests[0].content)["max_tokens"], 512)

    def test_thesis_extraction_rejects_status_field_from_model(self):
        response_body = {"choices": [{"message": {"content": json.dumps({"claims": [{
            "claim_id": "c1", "text": "EPS beat", "variable": "EPS",
            "comparison": "ABOVE_REFERENCE", "claim_type": "QUARTER_FACT",
            "status": "CONFIRMED",
        }]})}}]}
        transport = httpx.MockTransport(lambda request: httpx.Response(200, json=response_body))
        client = QwenClient(QwenCredentials("local-test-value", "https://example.test/v1", "test-model"),
                            client=httpx.Client(transport=transport))
        try:
            with self.assertRaises(DataUnavailable):
                client.extract_thesis("EPS beat")
        finally:
            client.close()

    def test_qwen_release_fact_extraction_requires_source_grounding_and_no_status(self):
        release = "Adjusted diluted EPS was $5.55 per share."
        raw_fact = {"claim_id": "c1", "current_value_text": "$5.55",
                    "prior_value_text": None, "current_period_text": None,
                    "prior_period_text": None, "attribution_quote": None,
                    "excerpt": release}
        response_body = {"choices": [{"message": {"content": json.dumps({"facts": [raw_fact]})}}]}
        transport = httpx.MockTransport(lambda request: httpx.Response(200, json=response_body))
        client = QwenClient(QwenCredentials("local-test-value", "https://example.test/v1", "test-model"),
                            client=httpx.Client(transport=transport))
        claims = [{"claim_id": "c1", "text": "EPS beats consensus"}]
        try:
            result = client.extract_release_facts(release_text=release, claims=claims)
            self.assertEqual(result.extraction.facts[0].current_value_text, "$5.55")
        finally:
            client.close()

        raw_fact["current_value_text"] = "$5.56"
        bad_body = {"choices": [{"message": {"content": json.dumps({"facts": [raw_fact]})}}]}
        transport = httpx.MockTransport(lambda request: httpx.Response(200, json=bad_body))
        client = QwenClient(QwenCredentials("local-test-value", "https://example.test/v1", "test-model"),
                            client=httpx.Client(transport=transport))
        try:
            with self.assertRaisesRegex(DataUnavailable, "absent from its source"):
                client.extract_release_facts(release_text=release, claims=claims)
        finally:
            client.close()

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
