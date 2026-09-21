from datetime import datetime, timezone
import unittest

import httpx

from reverb.bitget import BitgetClient, Credentials
from reverb.errors import ConfigurationError, DataUnavailable


class BitgetMarketTests(unittest.TestCase):
    def test_history_candles_uses_bounded_market_request(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["path"] = request.url.path
            captured["query"] = dict(request.url.params)
            return httpx.Response(200, json={"code": "00000", "msg": "success", "data": []})

        client = BitgetClient(credentials=Credentials("test-key", "test-secret", "test-pass"),
                              client=httpx.Client(transport=httpx.MockTransport(handler)))
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

    def test_option_quotes_enrich_last_trade_with_documented_depth(self):
        requests = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request.url.path)
            if request.url.path.endswith("/option-quote"):
                return httpx.Response(200, json={"code": "00000", "msg": "success", "data": {
                    "secuQuote": [{"symbol": "AAPL260925C100000.US", "lastDone": "2.5",
                                    "timestamp": "1789989000000", "tradeStatus": "1",
                                    "impliedVolatility": "0.4", "expiryDate": "20260925",
                                    "strikePrice": "100", "contractMultipier": "100",
                                    "direction": "C", "underlyingSymbol": "AAPL.US"}]
                }})
            if request.url.path.endswith("/depth"):
                return httpx.Response(200, json={"code": "00000", "msg": "success", "data": {
                    "asks": [{"position": 2, "price": "2.60", "volume": "5"},
                             {"position": 1, "price": "2.55", "volume": "2"}],
                    "bids": [{"position": 1, "price": "2.45", "volume": "3"}],
                }})
            return httpx.Response(404, json={"code": "404", "msg": "unexpected", "data": {}})

        client = BitgetClient(credentials=Credentials("test-key", "test-secret", "test-pass"),
                              client=httpx.Client(transport=httpx.MockTransport(handler)))
        try:
            rows = client.option_quotes(["AAPL260925C100000.US"])
        finally:
            client.close()
        self.assertEqual(rows[0]["bid"], "2.45")
        self.assertEqual(rows[0]["ask"], "2.55")
        self.assertEqual(requests, ["/api/v3/stockplus/market/option-quote", "/api/v3/stockplus/market/depth"])


if __name__ == "__main__":
    unittest.main()
