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

from reverb.app import render_app_html, render_connection_html  # noqa: E402
from reverb.ledger import Ledger  # noqa: E402
from reverb.preview import load_preview_snapshot, render_preview_html  # noqa: E402
from reverb.report import morning_report  # noqa: E402


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
            snapshot = load_preview_snapshot(ROOT)
            if route in {"/", "/preview", "/demo"}:
                self._send(200, "text/html; charset=utf-8", render_preview_html(snapshot).encode())
                return
            if route == "/app":
                query = parse_qs(urlsplit(self.path).query)
                risk_budget = query.get("risk", [None])[0]
                timezone_name = query.get("timezone", [None])[0]
                ledger_path = Path(os.getenv("REVERB_LEDGER_PATH", str(ROOT / "data" / "private" / "ledger.jsonl")))
                report = morning_report(Ledger(ledger_path)) if ledger_path.exists() else None
                self._send(200, "text/html; charset=utf-8",
                           render_app_html(snapshot, risk_budget=risk_budget, timezone_name=timezone_name,
                                           morning_report_html=report).encode())
                return
            if route == "/connect":
                self._send(200, "text/html; charset=utf-8", render_connection_html().encode())
                return
            if route == "/api/preview":
                self._send(200, "application/json; charset=utf-8", json.dumps(snapshot.as_dict(), sort_keys=True).encode())
                return
            if route == "/health":
                self._send(200, "application/json; charset=utf-8", b'{"status":"ok","credentials_required":false}')
                return
            self._send(404, "text/plain; charset=utf-8", b"not found\n")
        except Exception as exc:  # the server must report a failed evidence path, never a fake page
            self._send(503, "application/json; charset=utf-8", json.dumps({
                "status": "unavailable", "error_type": type(exc).__name__, "message": str(exc)
            }).encode())

    def log_message(self, format: str, *args: object) -> None:
        sys.stderr.write("reverb-preview: " + format % args + "\n")


def main() -> int:
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
