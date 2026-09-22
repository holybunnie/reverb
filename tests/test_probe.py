import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SPEC = importlib.util.spec_from_file_location("reverb_probe", Path(__file__).parents[1] / "scripts" / "probe.py")
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


class ProbeTests(unittest.TestCase):
    def test_reality_requires_first_party_identity_and_online_status(self):
        rows = [
            {"symbol": "RGOODUSDT", "baseCoin": "rGOOD", "symbolType": "stock", "isReality": "yes", "status": "online"},
            {"symbol": "RNOUSDT", "baseCoin": "rNO", "symbolType": "stock", "isReality": "no", "status": "online"},
            {"symbol": "RMAINTUSDT", "baseCoin": "rMAINT", "symbolType": "stock", "isReality": "yes", "status": "offline"},
        ]
        self.assertEqual([r["baseCoin"] for r in probe.reality(rows)], ["rGOOD"])

    def test_continuous_symbols_require_weekend_and_after_hours(self):
        rows = [
            {"symbol": "RGOODUSDT", "weekendTradable": "yes", "tradingPeriod": ["regular", "after_hours"]},
            {"symbol": "RNOWEEKENDUSDT", "weekendTradable": "no", "tradingPeriod": ["regular", "after_hours"]},
            {"symbol": "RNOAFTERUSDT", "weekendTradable": "yes", "tradingPeriod": ["regular"]},
        ]
        self.assertEqual(probe.continuously_traded_symbols(rows), {"RGOODUSDT"})

    def test_book_metrics_marks_old_exchange_timestamp_stale(self):
        record = {"received_at": "2026-09-19T10:00:05+00:00"}
        data = {"ts": "1789804799000", "b": [[100, 2]], "a": [[101, 3]]}
        metric = probe.book_metrics(data, record, {"max_book_age_ms": 5000, "max_future_skew_ms": 1000})
        self.assertEqual(metric["status"], "STALE")
        self.assertGreater(float(metric["spread_bps"]), 0)

    def test_book_metrics_clamps_tolerated_future_clock_skew(self):
        record = {"received_at": "2026-09-19T10:00:00+00:00"}
        data = {"ts": "1789812000500", "b": [[100, 2]], "a": [[101, 3]]}
        metric = probe.book_metrics(data, record, {"max_book_age_ms": 5000, "max_future_skew_ms": 1000})
        self.assertEqual(metric["status"], "FRESH")
        self.assertEqual(metric["age_ms"], 0)

    def test_hash_chain_and_body_hash_are_checked(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            config = b'{"x":1}'
            (directory / "config.json").write_bytes(config)
            evidence = probe.Evidence(directory)
            evidence.append({"kind": "start", "config_sha256": probe.digest(config), "at": probe.utc_now()})
            body = b'{"code":"00000","data":[]}'
            (directory / "001-body.body").write_bytes(body)
            evidence.append({"kind": "http", "name": "test", "body": "001-body.body", "body_sha256": probe.digest(body), "error": None, "status": 200})
            evidence.append({"kind": "complete", "failures": [], "at": probe.utc_now()})
            self.assertEqual(probe.verify(directory)[-1]["kind"], "complete")


if __name__ == "__main__":
    unittest.main()
