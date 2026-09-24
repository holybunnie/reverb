"""Timestamped, append-only capture for a scheduled Reality-token event."""
from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4

import httpx

from .errors import BitgetAPIError
from .ledger import Ledger


# The public UTA v3 SPOT order-book route is the proven Reality-token depth
# source used by the successful EXNIGHT capture. The account-scoped Reality
# routes remain useful provenance when the account is whitelisted, but a 40025
# response from them must not invalidate an otherwise complete market capture.
REQUIRED_ENDPOINTS = ("candles", "public_orderbook")
OPTIONAL_ENDPOINTS = ("public_fills", "reality_orderbook", "reality_fills")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("recording timestamps must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def exchange_timestamps(endpoint: str, response_body: bytes) -> list[str]:
    """Extract only documented/obvious exchange-time fields, preserving values."""
    try:
        payload = json.loads(response_body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return []
    if not isinstance(payload, dict) or payload.get("code") != "00000":
        return []
    data = payload.get("data")
    if endpoint == "candles" and isinstance(data, list):
        return [str(row[0]) for row in data if isinstance(row, list) and row and row[0] not in (None, "")]
    if endpoint in {"public_orderbook", "reality_orderbook"} and isinstance(data, dict):
        value = data.get("ts") or data.get("timestamp")
        return [str(value)] if value not in (None, "") else []
    if endpoint in {"public_fills", "reality_fills"} and isinstance(data, list):
        stamps = []
        for row in data:
            if not isinstance(row, dict):
                continue
            value = next((row.get(key) for key in ("ts", "timestamp", "tradeTime", "fillTime")
                          if row.get(key) not in (None, "")), None)
            if value is not None:
                stamps.append(str(value))
        return stamps
    return []


def exchange_response_timestamp(response_body: bytes) -> str | None:
    try:
        payload = json.loads(response_body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    value = payload.get("requestTime")
    return str(value) if value not in (None, "") else None


class CaptureTrace:
    """Capture status/body/timestamps via HTTP hooks without recording headers."""

    def __init__(self):
        self._items: list[dict[str, Any]] = []
        self._lock = Lock()

    def on_request(self, request: httpx.Request) -> None:
        request_id = str(uuid4())
        request.extensions["reverb_capture_id"] = request_id
        request.extensions["reverb_sent_at"] = iso_utc(utc_now())
        request.extensions["reverb_started"] = time.monotonic()
        with self._lock:
            self._items.append({
                "request_id": request_id,
                "url": str(request.url),
                "method": request.method,
                "sent_at": request.extensions["reverb_sent_at"],
                "received_at": None,
                "elapsed_ms": None,
                "status": None,
                "body": None,
            })

    def on_response(self, response: httpx.Response) -> None:
        request = response.request
        request_id = request.extensions.get("reverb_capture_id")
        body = response.read()
        with self._lock:
            item = next((row for row in reversed(self._items) if row["request_id"] == request_id), None)
            if item is None:
                return
            item.update({
                "received_at": iso_utc(utc_now()),
                "elapsed_ms": round((time.monotonic() - request.extensions["reverb_started"]) * 1000),
                "status": response.status_code,
                "body": body,
            })

    def mark(self) -> int:
        with self._lock:
            return len(self._items)

    def since(self, mark: int) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(row) for row in self._items[mark:]]


class EventRecorder:
    def __init__(self, *, directory: Path, config: dict[str, Any], config_bytes: bytes,
                 client: Any, trace: CaptureTrace, symbol: str):
        directory.mkdir(parents=True, exist_ok=False)
        self.directory = directory
        self.config = config
        self.config_sha256 = hashlib.sha256(config_bytes).hexdigest()
        self.ledger = Ledger(directory / "ledger.jsonl")
        self.client = client
        self.trace = trace
        self.symbol = symbol
        self._body_number = 0
        (directory / "config.json").write_bytes(config_bytes)
        self.ledger.append("recording_start", {
            "started_at": iso_utc(utc_now()),
            "config_sha256": self.config_sha256,
            "symbol": symbol,
            "required_endpoints": list(REQUIRED_ENDPOINTS),
            "optional_endpoints": list(OPTIONAL_ENDPOINTS),
            "write_capability": False,
        })

    def _call(self, endpoint: str, slot_at: datetime, method):
        mark = self.trace.mark()
        result = None
        error_type = None
        error_code = None
        http_status = None
        try:
            result = method()
        except BitgetAPIError as exc:
            error_type = type(exc).__name__
            error_code = exc.code
            http_status = exc.status
        except Exception as exc:
            # Never print or persist arbitrary exception messages; some HTTP
            # clients include request metadata in them.
            error_type = type(exc).__name__
        traces = self.trace.since(mark)
        response = traces[-1] if traces else None
        payload = None
        body_path = None
        body_hash = None
        source_stamps: list[str] = []
        exchange_response_at = None
        if response and isinstance(response.get("body"), bytes):
            payload = response["body"]
            self._body_number += 1
            body_name = f"{self._body_number:05d}-{endpoint}.body"
            path = self.directory / body_name
            with path.open("xb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            body_path = body_name
            body_hash = hashlib.sha256(payload).hexdigest()
            source_stamps = exchange_timestamps(endpoint, payload)
            exchange_response_at = exchange_response_timestamp(payload)
            http_status = response.get("status")
        success = error_type is None and http_status is not None and 200 <= http_status < 300
        record = self.ledger.append("capture_attempt", {
            "slot_at": iso_utc(slot_at),
            "endpoint": endpoint,
            "url": response.get("url") if response else None,
            "request_sent_at": response.get("sent_at") if response else None,
            "response_received_at": response.get("received_at") if response else iso_utc(utc_now()),
            "exchange_timestamps": source_stamps,
            "exchange_response_timestamp": exchange_response_at,
            "http_status": http_status,
            "bitget_code": error_code,
            "error_type": error_type,
            "body": body_path,
            "body_sha256": body_hash,
            "success": success,
        })
        return {"endpoint": endpoint, "success": success, "record_hash": record["hash"],
                "exchange_timestamps": source_stamps,
                "exchange_response_timestamp": exchange_response_at,
                "result_present": result is not None}

    def capture_slot(self, slot_at: datetime) -> dict[str, Any]:
        outcomes = [
            self._call("candles", slot_at,
                       lambda: self.client.candles(self.symbol, interval="1m", candle_type="market", limit=100)),
            self._call("public_orderbook", slot_at,
                       lambda: self.client.orderbook(self.symbol, limit=50)),
            self._call("public_fills", slot_at,
                       lambda: self.client.public_fills(self.symbol, limit=100)),
            self._call("reality_orderbook", slot_at,
                       lambda: self.client.reality_orderbook(self.symbol)),
            self._call("reality_fills", slot_at,
                       lambda: self.client.reality_fills(self.symbol, limit=100)),
        ]
        required = [row for row in outcomes if row["endpoint"] in REQUIRED_ENDPOINTS]
        complete = len(required) == len(REQUIRED_ENDPOINTS) and all(
            row["success"] and bool(row["exchange_response_timestamp"])
            and bool(row["exchange_timestamps"])
            for row in required
        )
        marker = self.ledger.append("capture_slot", {
            "slot_at": iso_utc(slot_at),
            "complete": complete,
            "required_endpoints": list(REQUIRED_ENDPOINTS),
            "optional_endpoints": list(OPTIONAL_ENDPOINTS),
            "endpoint_results": outcomes,
        })
        return {"slot_at": iso_utc(slot_at), "complete": complete,
                "ledger_hash": marker["hash"], "endpoint_results": outcomes}

    def finish(self, *, expected_slots: int, end_at: datetime, interrupted: bool = False) -> dict[str, Any]:
        rows = self.ledger.verify()
        slots = [row["payload"] for row in rows if row["kind"] == "capture_slot"]
        gaps = [row["payload"] for row in rows if row["kind"] == "capture_gap"]
        complete_slots = sum(bool(row["complete"]) for row in slots)
        status = "COMPLETE" if (
            not interrupted and len(slots) == expected_slots and complete_slots == expected_slots and not gaps
        ) else "INCOMPLETE"
        end = self.ledger.append("recording_complete", {
            "ended_at": iso_utc(utc_now()),
            "planned_end_at": iso_utc(end_at),
            "status": status,
            "expected_slots": expected_slots,
            "captured_slots": len(slots),
            "complete_slots": complete_slots,
            "gap_count": len(gaps),
            "interrupted": interrupted,
            "ledger_head_before_completion": rows[-1]["hash"] if rows else None,
        })
        return {"status": status, "expected_slots": expected_slots,
                "captured_slots": len(slots), "complete_slots": complete_slots,
                "gap_count": len(gaps), "ledger_head": end["hash"]}
