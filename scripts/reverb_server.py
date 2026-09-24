"""Serve Reverb's credential-free live evidence preview locally."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from reverb.app import (  # noqa: E402
    render_app_html, render_connection_html, render_events_html,
    render_landing_html, render_report_html,
)
from reverb.errors import DataUnavailable, LedgerError  # noqa: E402
from reverb.env import load_local_env  # noqa: E402
from reverb.bitget import BitgetClient  # noqa: E402
from reverb.calendar import EarningsCalendar  # noqa: E402
from reverb.config import EngineConfig, load_config  # noqa: E402
from reverb.language import (extract_thesis_and_record, interpret_view_and_record,
                             optional_qwen_client)  # noqa: E402
from reverb.ledger import Ledger  # noqa: E402
from reverb.preview import load_preview_snapshot, render_preview_html  # noqa: E402
from reverb.report import morning_report  # noqa: E402
from reverb.replay import load_replay_snapshot, render_replay_html, render_replay_report  # noqa: E402
from reverb.service import DecisionService  # noqa: E402


def _ledger_path() -> Path:
    return Path(os.getenv("REVERB_LEDGER_PATH", str(ROOT / "data" / "private" / "ledger.jsonl")))


def _service(*, calendar: EarningsCalendar | None = None) -> DecisionService:
    loaded = load_config(ROOT / "config" / "engine.json", EngineConfig)
    return DecisionService(
        BitgetClient(), loaded.value, Ledger(_ledger_path()),
        calendar=calendar, engine_config_sha256=loaded.sha256,
    )


def _decimal_field(document: dict, name: str) -> Decimal:
    value = document.get(name)
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        raise ValueError(f"{name} must be a decimal value")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{name} must be a decimal value") from exc
    if not result.is_finite():
        raise ValueError(f"{name} must be finite")
    return result


def _local_report_or_replay(replay):
    path = _ledger_path()
    if path.exists():
        ledger = Ledger(path)
        records = ledger.verify()
        if any(row.get("kind") == "pre_registration" for row in records):
            return morning_report(ledger)
    return render_replay_report(replay) if replay is not None else None


class Handler(BaseHTTPRequestHandler):
    server_version = "ReverbPreview/0.1"

    def _send(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _local_request(self) -> bool:
        if self.client_address[0] not in {"127.0.0.1", "::1"}:
            return False
        origin = self.headers.get("Origin")
        if origin:
            host = urlsplit(origin).hostname
            if host not in {"localhost", "127.0.0.1", "::1"}:
                return False
        return True

    def _read_json(self, maximum: int = 8192) -> dict:
        if self.headers.get_content_type() != "application/json":
            raise ValueError("content type must be application/json")
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > maximum:
            raise ValueError(f"request body must be between 1 and {maximum} bytes")
        document = json.loads(self.rfile.read(length))
        if not isinstance(document, dict):
            raise ValueError("request body must be a JSON object")
        return document

    def do_GET(self) -> None:  # noqa: N802
        route = urlsplit(self.path).path
        try:
            if route.startswith("/assets/"):
                name = route.removeprefix("/assets/")
                if name not in {"styles.css", "app.js"}:
                    self._send(404, "text/plain; charset=utf-8", b"not found\n")
                    return
                body = (ROOT / "reverb" / "static" / name).read_bytes()
                kind = "text/css; charset=utf-8" if name.endswith(".css") else "text/javascript; charset=utf-8"
                self._send(200, kind, body)
                return
            if route == "/demo":
                replay = load_replay_snapshot(ROOT)
                self._send(200, "text/html; charset=utf-8", render_replay_html(replay).encode())
                return
            if route == "/api/events":
                if not self._local_request():
                    self._send(403, "application/json; charset=utf-8", b'{"status":"local_only"}')
                    return
                query = parse_qs(urlsplit(self.path).query)
                user_timezone = query.get("timezone", ["Africa/Lagos"])[0]
                if len(user_timezone) > 100:
                    raise ValueError("timezone is too long")
                with _service(calendar=EarningsCalendar()) as service:
                    result = service.earnings_this_week(user_timezone=user_timezone).model_dump(mode="json")
                if result.get("decision") is None:
                    self._send(503, "application/json; charset=utf-8",
                               json.dumps({"status": "unavailable", "result": result}, sort_keys=True).encode())
                else:
                    self._send(200, "application/json; charset=utf-8",
                               json.dumps({"status": "ok", "result": result}, sort_keys=True).encode())
                return
            snapshot = load_preview_snapshot(ROOT)
            if route == "/preview":
                self._send(200, "text/html; charset=utf-8", render_preview_html(snapshot).encode())
                return
            replay = None
            try:
                replay = load_replay_snapshot(ROOT)
            except (DataUnavailable, LedgerError, OSError, ValueError):
                replay = None
            if route == "/":
                self._send(200, "text/html; charset=utf-8",
                           render_landing_html(snapshot, replay_snapshot=replay).encode())
                return
            if route == "/app":
                query = parse_qs(urlsplit(self.path).query)
                risk_budget = query.get("risk", [None])[0]
                timezone_name = query.get("timezone", [None])[0]
                report = _local_report_or_replay(replay)
                self._send(200, "text/html; charset=utf-8",
                           render_app_html(snapshot, risk_budget=risk_budget, timezone_name=timezone_name,
                                           morning_report_html=report, replay_snapshot=replay).encode())
                return
            if route == "/events":
                self._send(200, "text/html; charset=utf-8",
                           render_events_html(snapshot, replay_snapshot=replay).encode())
                return
            if route == "/report":
                report = _local_report_or_replay(replay)
                self._send(200, "text/html; charset=utf-8",
                           render_report_html(snapshot, replay_snapshot=replay,
                                              morning_report_html=report).encode())
                return
            if route == "/connect":
                self._send(200, "text/html; charset=utf-8", render_connection_html().encode())
                return
            if route == "/api/preview":
                self._send(200, "application/json; charset=utf-8", json.dumps(snapshot.as_dict(), sort_keys=True).encode())
                return
            if route == "/api/demo":
                replay = load_replay_snapshot(ROOT)
                self._send(200, "application/json; charset=utf-8", json.dumps(replay.as_dict(), sort_keys=True).encode())
                return
            if route == "/health":
                self._send(200, "application/json; charset=utf-8", b'{"status":"ok","credentials_required":false}')
                return
            self._send(404, "text/plain; charset=utf-8", b"not found\n")
        except Exception as exc:  # the server must report a failed evidence path, never a fake page
            self._send(503, "application/json; charset=utf-8", json.dumps({
                "status": "unavailable", "error_type": type(exc).__name__, "message": str(exc)
            }).encode())

    def do_POST(self) -> None:  # noqa: N802
        route = urlsplit(self.path).path
        if route not in {"/api/language/view", "/api/thesis/extract", "/api/thesis", "/api/react"}:
            self._send(404, "text/plain; charset=utf-8", b"not found\n")
            return
        if not self._local_request():
            self._send(403, "application/json; charset=utf-8", b'{"status":"local_only"}')
            return
        try:
            if route == "/api/language/view":
                document = self._read_json(4096)
                view_text = document.get("view")
                if not isinstance(view_text, str) or not view_text.strip() or len(view_text) > 500:
                    raise ValueError("view must be a non-empty string of at most 500 characters")
                qwen = optional_qwen_client()
                if qwen is None:
                    self._send(503, "application/json; charset=utf-8",
                               b'{"status":"unavailable","message":"Local Qwen key is not configured"}')
                    return
                ledger = Ledger(_ledger_path())
                try:
                    result = interpret_view_and_record(text=view_text, ledger=ledger, qwen=qwen)
                finally:
                    qwen.close()
                self._send(200, "application/json; charset=utf-8", json.dumps({
                    "status": "classified", "view": result.value,
                    "scope": "direction_only", "trade_decision": False,
                }, sort_keys=True).encode())
                return

            if route == "/api/thesis/extract":
                document = self._read_json(8192)
                allowed = {"symbol", "event_date", "calendar_event_id", "thesis_text"}
                if set(document) - allowed:
                    raise ValueError("request contains unsupported fields")
                for field in ("symbol", "event_date", "calendar_event_id", "thesis_text"):
                    if not isinstance(document.get(field), str) or not document[field].strip():
                        raise ValueError(f"{field} is required")
                if len(document["symbol"]) > 20 or len(document["calendar_event_id"]) > 256:
                    raise ValueError("event identity is invalid")
                thesis_text = document["thesis_text"].strip()
                if len(thesis_text) > 2000:
                    raise ValueError("thesis_text must be at most 2000 characters")
                qwen = optional_qwen_client()
                if qwen is None:
                    self._send(503, "application/json; charset=utf-8",
                               b'{"status":"unavailable","message":"Local Qwen key is not configured"}')
                    return
                approved_rules = {}
                if document["symbol"].upper() == "COST":
                    config = json.loads((ROOT / "config" / "costco_run.json").read_text(encoding="utf-8"))
                    approved_rules = config["approved_comparison_rules"]
                ledger = Ledger(_ledger_path())
                try:
                    extracted = extract_thesis_and_record(
                        text=thesis_text, approved_rule_definitions=approved_rules,
                        ledger=ledger, qwen=qwen,
                    )
                finally:
                    qwen.close()
                result = {
                    "claims": [claim.model_dump(mode="json") for claim in extracted.extraction.claims],
                    "provider": extracted.provider, "model": extracted.model,
                    "input_sha256": extracted.input_sha256,
                    "output_sha256": extracted.output_sha256,
                    "requires_user_confirmation": True,
                    "outcome_statuses_assigned": False,
                    "frozen": False,
                }
                self._send(200, "application/json; charset=utf-8",
                           json.dumps({"status": "candidate_claims", "result": result}, sort_keys=True).encode())
                return

            if route == "/api/thesis":
                document = self._read_json()
                allowed = {"symbol", "event_date", "calendar_event_id", "direction",
                            "expected_move_percent", "max_loss", "user_timezone", "view_text"}
                if set(document) - allowed:
                    raise ValueError("request contains unsupported fields")
                for field in ("symbol", "event_date", "calendar_event_id", "direction", "user_timezone"):
                    if not isinstance(document.get(field), str) or not document[field].strip():
                        raise ValueError(f"{field} is required")
                if len(document["symbol"]) > 20 or len(document["calendar_event_id"]) > 256:
                    raise ValueError("event identity is invalid")
                if len(document["user_timezone"]) > 100:
                    raise ValueError("timezone is too long")
                view_text = document.get("view_text", "")
                if not isinstance(view_text, str) or len(view_text) > 500:
                    raise ValueError("view_text must be at most 500 characters")
                direction = document["direction"].lower()
                if direction == "watch":
                    expected_move_pct = None
                    max_loss = None
                else:
                    expected_move_pct = _decimal_field(document, "expected_move_percent") / Decimal("100")
                    max_loss = _decimal_field(document, "max_loss")
                    if expected_move_pct <= 0 or expected_move_pct >= 1 or max_loss <= 0:
                        raise ValueError("expected move must be 0–100% and risk budget must be positive")
                calendar = EarningsCalendar()
                try:
                    matches = [event for event in calendar.this_week()
                               if event.symbol == document["symbol"].upper()
                               and event.event_date.isoformat() == document["event_date"]
                               and event.source_id == document["calendar_event_id"]]
                    if len(matches) != 1:
                        self._send(409, "application/json; charset=utf-8",
                                   b'{"status":"stale_event","message":"Refresh the event list; the selected event no longer matches this week\'s calendar."}')
                        return
                    with _service(calendar=calendar) as service:
                        calendar = None  # service owns and closes this calendar
                        result = service.prepare_spot_position(
                            event=matches[0], direction=direction,
                            expected_move_pct=expected_move_pct, max_loss=max_loss,
                            user_timezone=document["user_timezone"], view_text=view_text,
                        ).model_dump(mode="json")
                finally:
                    if calendar is not None:
                        calendar.close()
                self._send(200, "application/json; charset=utf-8",
                           json.dumps({"status": "registered", "result": result}, sort_keys=True).encode())
                return

            document = self._read_json(2048)
            decision_id = document.get("decision_id")
            if not isinstance(decision_id, str) or not decision_id or len(decision_id) > 80:
                raise ValueError("decision_id is required")
            ledger = Ledger(_ledger_path())
            registrations = [row["payload"] for row in ledger.verify()
                             if row.get("kind") == "pre_registration"
                             and row.get("payload", {}).get("decision_id") == decision_id
                             and row.get("payload", {}).get("tool") == "spot_position"]
            if len(registrations) != 1:
                self._send(404, "application/json; charset=utf-8",
                           b'{"status":"not_found","message":"No local spot thesis with that id exists."}')
                return
            registration = registrations[0]
            details = registration.get("decision")
            if not isinstance(details, dict) or not isinstance(details.get("event_at_utc"), str):
                raise LedgerError("registered spot thesis has no validated event timestamp")
            event_at = datetime.fromisoformat(details["event_at_utc"].replace("Z", "+00:00"))
            if event_at.tzinfo is None:
                raise LedgerError("registered spot thesis timestamp is not timezone-aware")
            with _service() as service:
                result = service.react(symbol=registration["symbol"], event_at=event_at,
                                       user_timezone=str(details.get("user_timezone", "Africa/Lagos")))
            reaction = result.model_dump(mode="json")
            ledger.append("reaction_monitor", {"decision_id": decision_id, "result": reaction,
                                                "orders_submitted": False})
            reaction_details = reaction.get("decision")
            if (datetime.now(timezone.utc) >= event_at.astimezone(timezone.utc) + timedelta(minutes=30)
                    and isinstance(reaction_details, dict)
                    and reaction_details.get("baseline_price") is not None
                    and reaction_details.get("observed_price") is not None):
                records = ledger.verify()
                if not any(row.get("kind") == "outcome"
                           and row.get("payload", {}).get("decision_id") == decision_id for row in records):
                    ledger.outcome(decision_id, {
                        "result": "reaction evidence recorded; no live order submitted",
                        "reaction_decision_id": reaction.get("decision_id"),
                        "reaction_status": reaction.get("status"),
                        "move_pct": reaction.get("arithmetic", {}).get("move_pct"),
                        "orders_submitted": False,
                    })
            self._send(200, "application/json; charset=utf-8",
                       json.dumps({"status": "observed", "result": reaction}, sort_keys=True).encode())
        except (ValueError, TypeError, InvalidOperation, json.JSONDecodeError) as exc:
            self._send(422, "application/json; charset=utf-8", json.dumps({
                "status": "invalid_request", "message": str(exc)
            }, sort_keys=True).encode())
        except Exception as exc:
            self._send(503, "application/json; charset=utf-8", json.dumps({
                "status": "unavailable", "error_type": type(exc).__name__, "message": str(exc)
            }).encode())

    def log_message(self, format: str, *args: object) -> None:
        sys.stderr.write("reverb-preview: " + format % args + "\n")


def main() -> int:
    load_local_env(ROOT)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Reverb live preview: http://{args.host}:{args.port}/preview", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
