from datetime import datetime, timezone
import unittest
from unittest.mock import patch

import httpx

from reverb.bitget import BitgetClient, Credentials
from reverb.errors import ConfigurationError, DataUnavailable


class BitgetMarketTests(unittest.TestCase):
    def test_data_credentials_are_separate_and_preferred_when_complete(self):
        with patch.dict("os.environ", {
            "BITGET_API_KEY": "trade-key",
            "BITGET_SECRET_KEY": "trade-secret",
            "BITGET_PASSPHRASE": "trade-passphrase",
            "BITGET_DATA_API_KEY": "read-key",
            "BITGET_DATA_SECRET_KEY": "read-secret",
            "BITGET_DATA_PASSPHRASE": "read-passphrase",
        }, clear=True):
            credentials = Credentials.from_env(prefix="BITGET_DATA", fallback_prefix="BITGET")
        self.assertEqual(credentials, Credentials("read-key", "read-secret", "read-passphrase"))

    def test_bitget_read_credentials_are_preferred_over_existing_trade_key(self):
        with patch.dict("os.environ", {
            "BITGET_API_KEY": "trade-key",
            "BITGET_SECRET_KEY": "trade-secret",
            "BITGET_PASSPHRASE": "trade-passphrase",
            "BITGET_READ_API_KEY": "read-key",
            "BITGET_READ_SECRET_KEY": "read-secret",
            "BITGET_READ_PASSPHRASE": "read-passphrase",
        }, clear=True):
            credentials = Credentials.from_env_priority("BITGET_READ", "BITGET_DATA", "BITGET")
        self.assertEqual(credentials, Credentials("read-key", "read-secret", "read-passphrase"))

    def test_data_credentials_fall_back_to_existing_key_only_when_unset(self):
        with patch.dict("os.environ", {
            "BITGET_API_KEY": "trade-key",
            "BITGET_SECRET_KEY": "trade-secret",
            "BITGET_PASSPHRASE": "trade-passphrase",
        }, clear=True):
            credentials = Credentials.from_env(prefix="BITGET_DATA", fallback_prefix="BITGET")
        self.assertEqual(credentials, Credentials("trade-key", "trade-secret", "trade-passphrase"))

    def test_partial_data_credentials_halt_instead_of_using_trade_key(self):
        with patch.dict("os.environ", {
            "BITGET_API_KEY": "trade-key",
            "BITGET_SECRET_KEY": "trade-secret",
            "BITGET_PASSPHRASE": "trade-passphrase",
            "BITGET_DATA_API_KEY": "read-key",
        }, clear=True):
            with self.assertRaises(ConfigurationError):
                Credentials.from_env(prefix="BITGET_DATA", fallback_prefix="BITGET")

    def test_reality_raw_orderbook_uses_private_whitelisted_endpoint(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["path"] = request.url.path
            captured["symbol"] = request.url.params["symbol"]
            captured["has_auth"] = bool(request.headers.get("ACCESS-SIGN"))
            return httpx.Response(200, json={"code": "00000", "data": {
                "symbol": "RCOSTUSDT", "a": [["900", "2"]], "b": [["899", "3"]], "ts": "1789990000000"
            }})

        client = BitgetClient(credentials=Credentials("local-test", "local-test-secret", "local-pass"),
                              client=httpx.Client(transport=httpx.MockTransport(handler)))
        try:
            book = client.reality_orderbook("RCOSTUSDT")
        finally:
            client.close()
        self.assertEqual(captured, {"path": "/api/v3/account/reality-orderbook",
                                    "symbol": "RCOSTUSDT", "has_auth": True})
        self.assertEqual(book["ts"], "1789990000000")

    def test_reality_fills_uses_private_whitelisted_endpoint(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["path"] = request.url.path
            captured["limit"] = request.url.params["limit"]
            captured["has_auth"] = bool(request.headers.get("ACCESS-SIGN"))
            return httpx.Response(200, json={"code": "00000", "data": [
                {"execId": "one", "price": "900", "size": "1", "side": "buy", "ts": "1789990000000"}
            ]})

        client = BitgetClient(credentials=Credentials("local-test", "local-test-secret", "local-pass"),
                              client=httpx.Client(transport=httpx.MockTransport(handler)))
        try:
            fills = client.reality_fills("RCOSTUSDT")
        finally:
            client.close()
        self.assertEqual(captured, {"path": "/api/v3/account/reality-fills", "limit": "100", "has_auth": True})
        self.assertEqual(fills[0]["execId"], "one")

    def test_public_market_fills_are_a_distinct_unauthenticated_route(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["path"] = request.url.path
            captured["query"] = dict(request.url.params)
            captured["has_auth"] = "ACCESS-SIGN" in request.headers
            return httpx.Response(200, json={"code": "00000", "data": [
                {"execId": "public-1", "price": "900", "size": "1", "ts": "1789990000000"}
            ]})

        client = BitgetClient(client=httpx.Client(transport=httpx.MockTransport(handler)))
        try:
            fills = client.public_fills("RCOSTUSDT")
        finally:
            client.close()
        self.assertEqual(captured, {"path": "/api/v3/market/fills", "query": {
            "category": "SPOT", "symbol": "RCOSTUSDT", "limit": "100",
        }, "has_auth": False})
        self.assertEqual(fills[0]["execId"], "public-1")

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
