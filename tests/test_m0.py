from pathlib import Path
from tempfile import TemporaryDirectory
import json
import hashlib
import unittest

from reverb.m0 import gate_passed


class M0GateTests(unittest.TestCase):
    def test_missing_or_blocked_artifact_fails_closed(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            self.assertFalse(gate_passed(root))
            docs = root / "docs"
            docs.mkdir()
            (docs / "m0_gate.json").write_text(json.dumps({"schema_version": 1, "status": "BLOCKED"}))
            self.assertFalse(gate_passed(root))

    def test_pass_requires_all_answers_and_matching_evidence_hashes(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            docs = root / "docs"
            docs.mkdir()
            evidence = root / "evidence.json"
            evidence.write_text("verified evidence")
            digest = hashlib.sha256(evidence.read_bytes()).hexdigest()
            answers = {
                name: {"status": "VERIFIED", "evidence": [{"path": "evidence.json", "sha256": digest}]}
                for name in ("option_hours", "eligibility", "tradeable_intersection", "event_book")
            }
            (docs / "m0_gate.json").write_text(json.dumps({"schema_version": 1, "status": "PASSED", "answers": answers}))
            self.assertTrue(gate_passed(root))
            evidence.write_text("tampered evidence")
            self.assertFalse(gate_passed(root))


if __name__ == "__main__":
    unittest.main()
