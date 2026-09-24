from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest

import httpx

from reverb.bitget import BitgetClient, Credentials
from reverb.ledger import Ledger
from reverb.recording import CaptureTrace, EventRecorder, exchange_response_timestamp, exchange_timestamps


NOW = datetime(2026, 9, 24, 19, 30, tzinfo=timezone.utc)
STAMP = "1790278200000"


class RecordingTests(unittest.TestCase):
    def _client(self, *, blocked=False):
        candle = {"code": "00000", "requestTime": STAMP, "data": [[STAMP, "900", "901", "899", "900", "1", "900", "1", "1"]]}
        book = {"code": "00000", "requestTime": STAMP, "data": {"ts": STAMP, "bids": [["899", "2"]], "asks": [["901", "3"]]}}
        reality = {"code": "00000", "requestTime": STAMP, "data": {
            "symbol": "RCOSTUSDT", "ts": STAMP, "b": [["899", "2"]], "a": [["901", "3"]],
        }}
        fills = {"code": "00000", "requestTime": STAMP, "data": [
            {"execId": "fill-1", "price": "900", "size": "1", "ts": STAMP},
        ]}

        def handler(request):
            if request.url.path.endswith("/market/candles"):
                return httpx.Response(200, json=candle)
            if request.url.path.endswith("/market/orderbook"):
                return httpx.Response(200, json=book)
            if request.url.path.endswith("/market/fills"):
                return httpx.Response(200, json=fills)
            if request.url.path.endswith("/account/reality-orderbook") and blocked:
                return httpx.Response(400, json={"code": "40014", "msg": "not authorized", "data": {}})
            if request.url.path.endswith("/account/reality-orderbook"):
                return httpx.Response(200, json=reality)
            if request.url.path.endswith("/account/reality-fills"):
                return httpx.Response(200, json=fills)
            raise AssertionError(f"unexpected request {request.url.path}")

        trace = CaptureTrace()
        transport = httpx.MockTransport(handler)
        client_http = httpx.Client(transport=transport, event_hooks={
            "request": [trace.on_request], "response": [trace.on_response],
        })
        client = BitgetClient(credentials=Credentials("local-test-key", "local-test-secret", "local-pass"),
                              client=client_http)
        return client, trace

    def test_snapshot_preserves_exchange_and_receipt_times_and_hashes(self):
        with TemporaryDirectory() as temp:
            directory = Path(temp) / "capture"
            client, trace = self._client()
            recorder = EventRecorder(directory=directory, config={"symbol": "RCOSTUSDT"},
                                     config_bytes=b'{"symbol":"RCOSTUSDT"}\n', client=client,
                                     trace=trace, symbol="RCOSTUSDT")
            try:
                result = recorder.capture_slot(NOW)
                records = recorder.ledger.verify()
            finally:
                client.close()
        self.assertTrue(result["complete"])
        self.assertEqual({row["endpoint"] for row in result["endpoint_results"]}, {
            "candles", "public_orderbook", "public_fills", "reality_orderbook", "reality_fills",
        })
        attempts = [row["payload"] for row in records if row["kind"] == "capture_attempt"]
        self.assertEqual(len(attempts), 5)
        self.assertTrue(all(row["request_sent_at"] and row["response_received_at"] for row in attempts))
        self.assertTrue(all(row["exchange_response_timestamp"] == STAMP for row in attempts))
        self.assertTrue(all(row["body"] and row["body_sha256"] for row in attempts))
        self.assertNotIn("local-test-secret", str(records))

    def test_private_reality_book_error_is_optional_when_public_depth_arrives(self):
        with TemporaryDirectory() as temp:
            directory = Path(temp) / "capture"
            client, trace = self._client(blocked=True)
            recorder = EventRecorder(directory=directory, config={"symbol": "RCOSTUSDT"},
                                     config_bytes=b'{"symbol":"RCOSTUSDT"}\n', client=client,
                                     trace=trace, symbol="RCOSTUSDT")
            try:
                result = recorder.capture_slot(NOW)
                attempts = [row["payload"] for row in recorder.ledger.verify()
                            if row["kind"] == "capture_attempt"]
            finally:
                client.close()
        reality = next(row for row in attempts if row["endpoint"] == "reality_orderbook")
        self.assertTrue(result["complete"])
        self.assertEqual(reality["http_status"], 400)
        self.assertEqual(reality["bitget_code"], "40014")
        self.assertIsNotNone(reality["body_sha256"])

    def test_public_orderbook_error_keeps_slot_incomplete(self):
        with TemporaryDirectory() as temp:
            directory = Path(temp) / "capture"
            client, trace = self._client()
            original_request = client._request

            def with_required_book_blocked(method, path, *args, **kwargs):
                if path.endswith("/market/orderbook"):
                    from reverb.errors import BitgetAPIError
                    raise BitgetAPIError(400, "40014", "not authorized")
                return original_request(method, path, *args, **kwargs)

            client._request = with_required_book_blocked
            recorder = EventRecorder(directory=directory, config={"symbol": "RCOSTUSDT"},
                                     config_bytes=b'{"symbol":"RCOSTUSDT"}\n', client=client,
                                     trace=trace, symbol="RCOSTUSDT")
            try:
                result = recorder.capture_slot(NOW)
            finally:
                client.close()
        self.assertFalse(result["complete"])

    def test_private_fills_access_is_optional(self):
        with TemporaryDirectory() as temp:
            directory = Path(temp) / "capture"
            client, trace = self._client()
            original_request = client._request

            def with_optional_fills_blocked(method, path, *args, **kwargs):
                if path.endswith("/account/reality-fills"):
                    from reverb.errors import BitgetAPIError
                    raise BitgetAPIError(400, "40014", "not authorized")
                return original_request(method, path, *args, **kwargs)

            client._request = with_optional_fills_blocked
            recorder = EventRecorder(directory=directory, config={"symbol": "RCOSTUSDT"},
                                     config_bytes=b'{"symbol":"RCOSTUSDT"}\n', client=client,
                                     trace=trace, symbol="RCOSTUSDT")
            try:
                result = recorder.capture_slot(NOW)
            finally:
                client.close()
        self.assertTrue(result["complete"])
        fills = next(row for row in result["endpoint_results"] if row["endpoint"] == "reality_fills")
        self.assertFalse(fills["success"])

    def test_exchange_time_extractors_preserve_timestamp_text(self):
        body = json.dumps({"code": "00000", "requestTime": STAMP,
                           "data": [[STAMP, "1", "1", "1", "1"]]}).encode()
        self.assertEqual(exchange_timestamps("candles", body), [STAMP])
        self.assertEqual(exchange_response_timestamp(body), STAMP)

    def test_short_capture_cannot_be_reported_complete(self):
        with TemporaryDirectory() as temp:
            directory = Path(temp) / "capture"
            client, trace = self._client()
            recorder = EventRecorder(directory=directory, config={"symbol": "RCOSTUSDT"},
                                     config_bytes=b'{"symbol":"RCOSTUSDT"}\n', client=client,
                                     trace=trace, symbol="RCOSTUSDT")
            try:
                recorder.capture_slot(NOW)
                summary = recorder.finish(expected_slots=2, end_at=NOW, interrupted=False)
            finally:
                client.close()
        self.assertEqual(summary["status"], "INCOMPLETE")
        self.assertEqual(summary["captured_slots"], 1)


if __name__ == "__main__":
    unittest.main()
