import json
import subprocess
import unittest
from decimal import Decimal
from unittest.mock import Mock

from reverb.agent_hub import AgentHubExecutor
from reverb.errors import AgentHubError, ConfigurationError, DataUnavailable


class AgentHubTests(unittest.TestCase):
    def _executor(self, stdout, returncode=0, stderr=""):
        runner = Mock(return_value=subprocess.CompletedProcess(
            args=[], returncode=returncode, stdout=stdout, stderr=stderr))
        return AgentHubExecutor(executable="bgc", runner=runner), runner

    def test_order_is_sent_to_agent_hub_with_no_raw_endpoint(self):
        executor, runner = self._executor(json.dumps({"data": {"orderId": "hub-order-1"}}))

        response = executor.place_reality_limit(
            symbol="RNVDAUSDT", side="buy", quantity=Decimal("1"),
            price=Decimal("105.10"), client_oid="oid-1",
        )

        self.assertEqual(response["orderId"], "hub-order-1")
        command = runner.call_args.args[0]
        self.assertEqual(command[0], "bgc")
        self.assertEqual(command[1:5], ["order", "--action", "place", "--category"])
        self.assertIn("SPOT", command)
        self.assertIn("RNVDAUSDT", command)
        self.assertFalse(any(part.startswith("/api/") for part in command))
        self.assertFalse(runner.call_args.kwargs["shell"])

    def test_agent_hub_failure_does_not_fallback(self):
        executor, _ = self._executor(
            "", returncode=1,
            stderr=json.dumps({"error": {"type": "PERMISSION_DENIED", "message": "private"}}),
        )
        with self.assertRaisesRegex(AgentHubError, "PERMISSION_DENIED"):
            executor.place_reality_limit(
                symbol="RNVDAUSDT", side="buy", quantity=Decimal("1"),
                price=Decimal("105"), client_oid="oid-1",
            )

    def test_malformed_agent_hub_result_halts(self):
        executor, _ = self._executor(json.dumps({"data": {}}))
        with self.assertRaises(DataUnavailable):
            executor.place_reality_limit(
                symbol="RNVDAUSDT", side="buy", quantity=Decimal("1"),
                price=Decimal("105"), client_oid="oid-1",
            )

    def test_non_finite_order_values_are_rejected(self):
        executor, _ = self._executor(json.dumps({"data": {"orderId": "hub-order-1"}}))
        with self.assertRaises(ConfigurationError):
            executor.place_reality_limit(
                symbol="RNVDAUSDT", side="buy", quantity=Decimal("NaN"),
                price=Decimal("105"), client_oid="oid-1",
            )

    def test_available_quote_uses_read_only_agent_hub_max_open(self):
        executor, runner = self._executor(json.dumps({"data": {"available": "5.997001"}}))
        available = executor.available_quote_for_limit(
            symbol="RCAPRUSDT", side="buy", price=Decimal("9.07"))
        self.assertEqual(available, Decimal("5.997001"))
        command = runner.call_args.args[0]
        self.assertEqual(command[1:4], ["--read-only", "order", "--action"])


if __name__ == "__main__":
    unittest.main()
