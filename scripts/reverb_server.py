"""Serve Reverb's credential-free live evidence preview locally."""
from __future__ import annotations

import argparse
import json
import os
import sys
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
from reverb.language import interpret_view_and_record, optional_qwen_client  # noqa: E402
from reverb.ledger import Ledger  # noqa: E402
from reverb.preview import load_preview_snapshot, render_preview_html  # noqa: E402
from reverb.report import morning_report  # noqa: E402
from reverb.replay import load_replay_snapshot, render_replay_html, render_replay_report  # noqa: E402


class Handler(BaseHTTPRequestHandler):
    server_version = "ReverbPreview/0.1"

    def _send(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

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
                ledger_path = Path(os.getenv("REVERB_LEDGER_PATH", str(ROOT / "data" / "private" / "ledger.jsonl")))
                report = morning_report(Ledger(ledger_path)) if ledger_path.exists() else None
                if report is None:
                    report = render_replay_report(replay) if replay is not None else None
                self._send(200, "text/html; charset=utf-8",
                           render_app_html(snapshot, risk_budget=risk_budget, timezone_name=timezone_name,
                                           morning_report_html=report, replay_snapshot=replay).encode())
                return
            if route == "/events":
                self._send(200, "text/html; charset=utf-8",
                           render_events_html(snapshot, replay_snapshot=replay).encode())
                return
            if route == "/report":
                report = render_replay_report(replay) if replay is not None else None
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
        if route != "/api/language/view":
            self._send(404, "text/plain; charset=utf-8", b"not found\n")
            return
        if self.client_address[0] not in {"127.0.0.1", "::1"}:
            self._send(403, "application/json; charset=utf-8", b'{"status":"local_only"}')
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 4096:
                raise ValueError("request body must be between 1 and 4096 bytes")
            document = json.loads(self.rfile.read(length))
            view_text = document.get("view") if isinstance(document, dict) else None
            if not isinstance(view_text, str) or not view_text.strip() or len(view_text) > 500:
                raise ValueError("view must be a non-empty string of at most 500 characters")
            qwen = optional_qwen_client()
            if qwen is None:
                self._send(503, "application/json; charset=utf-8",
                           b'{"status":"unavailable","message":"Local Qwen key is not configured"}')
                return
            ledger = Ledger(Path(os.getenv("REVERB_LEDGER_PATH", str(ROOT / "data" / "private" / "ledger.jsonl"))))
            try:
                result = interpret_view_and_record(text=view_text, ledger=ledger, qwen=qwen)
            finally:
                qwen.close()
            self._send(200, "application/json; charset=utf-8", json.dumps({
                "status": "classified", "view": result.value,
                "scope": "direction_only", "trade_decision": False,
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
