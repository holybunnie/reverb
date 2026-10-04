import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVENTS = sorted(p.stem for p in (ROOT / "config/events").glob("*.json"))


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class EventConfigTests(unittest.TestCase):
    def test_every_event_is_approved_read_only_and_cites_frozen_sources(self):
        freeze = load("event_freeze")
        self.assertTrue(EVENTS)
        for event_id in EVENTS:
            config, _ = freeze.load_config(event_id)
            self.assertIs(config["live_orders_allowed"], False)
            documents, _ = freeze.load_sources(event_id)
            references = freeze.build_references(config, documents)
            claims = {c["claim_id"]: c for c in config["claims"]}
            for reference in references:
                self.assertIn(reference.value_text, reference.citation.excerpt)
                self.assertEqual(reference.unit, claims[reference.claim_id]["unit"])
            for claim in claims.values():
                if claim["comparison"] in {"ABOVE_REFERENCE", "BELOW_REFERENCE"}:
                    self.assertIn(claim["claim_id"], {r.claim_id for r in references}, event_id)

    def test_frozen_events_still_verify(self):
        from reverb.reconciliation import FrozenThesis, verify_frozen_thesis
        for path in (ROOT / "evidence/events").glob("*/frozen_thesis.json"):
            self.assertTrue(verify_frozen_thesis(FrozenThesis.model_validate(json.loads(path.read_text()))), path)


if __name__ == "__main__":
    unittest.main()
