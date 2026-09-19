from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from reverb.bitget import BitgetClient
from reverb.config import EngineConfig, load_config
from reverb.ledger import Ledger
from reverb.models import DecisionStatus, ReasonCode
from reverb.service import DecisionService


class ServiceInputTests(unittest.TestCase):
    def test_malformed_tool_input_is_a_recorded_refusal(self):
        with TemporaryDirectory() as temp:
            engine = load_config(Path("config/engine.json"), EngineConfig).value
            ledger = Ledger(Path(temp) / "ledger.jsonl")
            with DecisionService(BitgetClient(), engine, ledger) as service:
                result = service.input_refusal(
                    tool="position_for", symbol="NVDA", field="event_at",
                    error=ValueError("timezone required"),
                )
            self.assertEqual(result.status, DecisionStatus.REFUSE)
            self.assertEqual(result.reason_codes, (ReasonCode.INVALID_INPUT,))
            records = ledger.verify()
            self.assertEqual(records[0]["kind"], "pre_registration")
            self.assertEqual(records[0]["payload"]["reason_codes"], [ReasonCode.INVALID_INPUT.value])


if __name__ == "__main__":
    unittest.main()
