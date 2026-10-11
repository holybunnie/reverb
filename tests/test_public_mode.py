import importlib.util
import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = "https://reverb.example"


def load_server():
    spec = importlib.util.spec_from_file_location("reverb_server_public", ROOT / "scripts" / "reverb_server.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RateLimiterTests(unittest.TestCase):
    def test_per_visitor_and_total_limits(self):
        limiter = load_server().RateLimiter(per_visitor=2, visitor_window_s=3600, total=3, total_window_s=86400)
        self.assertIsNone(limiter.allow("a"))
        self.assertIsNone(limiter.allow("a"))
        self.assertIn("per-visitor", limiter.allow("a"))
        self.assertIsNone(limiter.allow("b"))
        self.assertIn("daily limit", limiter.allow("c"))


class PublicModeTests(unittest.TestCase):
    def setUp(self):
        self.server_module = load_server()
        self.server_module.PUBLIC_ORIGIN = ORIGIN
        # No Qwen key: an allowed extraction reaches the handler and reports 503, never a call.
        self.server_module.optional_qwen_client = lambda: None
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), self.server_module.Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def call(self, path, *, body=None, visitor="203.0.113.7", origin=ORIGIN):
        headers = {"Content-Type": "application/json"}
        if visitor:
            headers["X-Real-IP"] = visitor
        if origin:
            headers["Origin"] = origin
        data = json.dumps(body).encode() if body is not None else None
        try:
            with urlopen(Request(self.base + path, data=data, headers=headers), timeout=10) as response:
                return response.status, json.loads(response.read() or b"{}")
        except HTTPError as error:
            return error.code, json.loads(error.read() or b"{}")

    def extract_body(self):
        return {"symbol": "STZ", "event_date": "2026-10-06", "calendar_event_id": "x", "thesis_text": "Beer sales grow."}

    def test_owner_only_actions_are_refused_to_visitors(self):
        for path in ("/api/thesis", "/api/react", "/api/language/view"):
            status, body = self.call(path, body={})
            self.assertEqual(status, 403, path)
            self.assertEqual(body["status"], "local_only")

    def test_desk_routes_are_open_to_same_origin_visitors_only(self):
        status, _ = self.call("/api/thesis/extract", body=self.extract_body())
        self.assertEqual(status, 503)  # allowed through; no Qwen key in tests
        status, body = self.call("/api/thesis/extract", body=self.extract_body(), origin="https://evil.example")
        self.assertEqual(status, 403)
        self.assertEqual(body["status"], "forbidden")

    def test_bad_context_input_is_rejected_before_any_data_call(self):
        status, _ = self.call("/api/events/context?symbol=STZ;&date=2026-10-06", origin=None)
        self.assertEqual(status, 400)

    def test_extraction_is_capped_per_visitor(self):
        statuses = [self.call("/api/thesis/extract", body=self.extract_body())[0] for _ in range(6)]
        self.assertEqual(statuses[:5], [503] * 5)
        self.assertEqual(statuses[5], 429)
        # Another visitor still has their own allowance.
        self.assertEqual(self.call("/api/thesis/extract", body=self.extract_body(), visitor="198.51.100.9")[0], 503)

    def test_public_route_list_excludes_owner_actions(self):
        self.assertIn("/api/events/context", self.server_module.PUBLIC_ROUTES)
        self.assertNotIn("/api/thesis", self.server_module.PUBLIC_ROUTES)
        self.assertNotIn("/api/react", self.server_module.PUBLIC_ROUTES)

    def test_public_events_page_says_it_is_a_public_demo(self):
        with urlopen(Request(self.base + "/events", headers={"X-Real-IP": "203.0.113.7"}), timeout=30) as response:
            page = response.read().decode()
        self.assertIn("PUBLIC DEMO", page)
        self.assertIn("Up to 5 extractions per visitor per hour", page)


class LocalModeTests(unittest.TestCase):
    def test_without_public_origin_visitor_headers_grant_nothing(self):
        module = load_server()
        module.PUBLIC_ORIGIN = None
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), module.Handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            request = Request(f"http://127.0.0.1:{httpd.server_address[1]}/api/thesis", data=b"{}",
                              headers={"Content-Type": "application/json", "Origin": "https://evil.example"})
            with self.assertRaises(HTTPError) as caught:
                urlopen(request, timeout=10)
            self.assertEqual(caught.exception.code, 403)
        finally:
            httpd.shutdown()
            httpd.server_close()


if __name__ == "__main__":
    unittest.main()
