from datetime import datetime, timezone
import unittest

import httpx

from reverb.bitget import BitgetClient
from reverb.errors import ConfigurationError, DataUnavailable


class BitgetMarketTests(unittest.TestCase):
    def test_history_candles_uses_bounded_market_request(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["path"] = request.url.path
            captured["query"] = dict(request.url.params)
            return httpx.Response(200, json={"code": "00000", "msg": "success", "data": []})

        client = BitgetClient(client=httpx.Client(transport=httpx.MockTransport(handler)))
        try:
            rows = client.history_candles(
                "RNVDAUSDT", start_time=datetime(2026, 9, 18, 19, 5, tzinfo=timezone.utc),
                end_time=datetime(2026, 9, 18, 20, 5, tzinfo=timezone.utc),
            )
        finally:
            client.close()
        self.assertEqual(rows, [])
        self.assertEqual(captured["path"], "/api/v3/market/history-candles")
        self.assertEqual(captured["query"]["type"], "market")
        self.assertEqual(captured["query"]["limit"], "100")
        self.assertEqual(captured["query"]["startTime"], "1789758300000")
        self.assertEqual(captured["query"]["endTime"], "1789761900000")

    def test_history_candles_rejects_range_over_ninety_days(self):
        client = BitgetClient(client=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200))))
        try:
            with self.assertRaises(ConfigurationError):
                client.history_candles(
                    "RNVDAUSDT", start_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
                    end_time=datetime(2026, 4, 2, tzinfo=timezone.utc),
                )
        finally:
            client.close()

    def test_non_object_json_is_a_data_halt(self):
        client = BitgetClient(client=httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=["not", "an", "object"]))
        ))
        try:
            with self.assertRaises(DataUnavailable):
                client.instruments()
        finally:
            client.close()


if __name__ == "__main__":
    unittest.main()
