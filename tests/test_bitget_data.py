from datetime import date, datetime, timezone
from decimal import Decimal
import json
import unittest

import httpx

from reverb.bitget_data import (
    BitgetDataClient, compare_release, event_context, normalize_symbol, parse_calendar,
    parse_consensus, parse_quote, select_consensus, session_of,
)
from reverb.errors import ConfigurationError, DataUnavailable


def calendar_row(symbol="STZ", period="2026-08-31", release="2026-10-06", filing="2026-10-07",
                 session="盘后", fiscal_year="2027"):
    return {"symbol": symbol, "period_ending": period, "fiscal_year": fiscal_year,
            "perf_briefing_fore_dsclsr_date": release, "perf_brief_dsclsr_date": release,
            "perf_report_dsclsr_date": filing, "is_trading_time": session}


def consensus_row(indicator="EPS", label="CurrentQtr.(Aug2026)", mean=3.55, scraped="2026-10-05",
                  symbol="STZ", analysts=19):
    return {"symbol": symbol, "fore_indicator_name": indicator, "report_period_scraped": label,
            "fore_mean": mean, "min_fore_value": mean - 0.3, "high_fore_value": mean + 0.3,
            "fore_org_num": analysts, "currency_unit": "USD", "scraped_date": scraped,
            "data_source": "雅虎财经"}


class ParsingTests(unittest.TestCase):
    def test_symbol_accepts_reverb_suffix_and_rejects_injection(self):
        self.assertEqual(normalize_symbol(" cost.us "), "COST")
        for bad in ("", "COST;DROP", "1ABC", "A" * 12):
            with self.assertRaises(ConfigurationError):
                normalize_symbol(bad)

    def test_calendar_merges_quarter_and_annual_rows_and_keeps_filing(self):
        rows = [
            calendar_row("COST", "2026-08-31", "2026-09-24", None),
            calendar_row("COST", "2026-08-30", "2026-09-24", "2026-10-07"),
            calendar_row("COST", "2026-05-10", "2026-05-28", "2026-06-03"),
            calendar_row("OTHER", "2026-08-31", "2026-09-24", None),
        ]
        releases = parse_calendar(rows, "COST")
        self.assertEqual([item.release_date for item in releases], [date(2026, 9, 24), date(2026, 5, 28)])
        self.assertEqual(releases[0].filing_date, date(2026, 10, 7))
        self.assertEqual(releases[0].session, "after_close")

    def test_unknown_session_label_is_unspecified_not_guessed(self):
        self.assertEqual(parse_calendar([calendar_row(session="")], "STZ")[0].session, "unspecified")
        self.assertEqual(parse_calendar([calendar_row(session="盘前")], "STZ")[0].session, "before_open")

    def test_malformed_calendar_date_halts(self):
        with self.assertRaises(DataUnavailable):
            parse_calendar([calendar_row(release="06/10/2026")], "STZ")

    def test_quote_change_is_converted_from_fraction_to_percent(self):
        quote = parse_quote([{"symbol": "STZ", "last_price": 122.6, "prev_close": 123.24,
                              "change_percent": -0.005193, "total_market_cap": 20746889372.0}], "STZ")
        self.assertEqual(quote.change_pct, Decimal("-0.5193000"))
        self.assertEqual(quote.last_price, Decimal("122.6"))

    def test_quote_missing_price_halts(self):
        with self.assertRaises(DataUnavailable):
            parse_quote([{"symbol": "STZ", "last_price": None, "prev_close": 1, "change_percent": 0}], "STZ")
        with self.assertRaises(DataUnavailable):
            parse_quote([], "STZ")

    def test_consensus_keeps_quarterly_eps_and_revenue_only(self):
        rows = [consensus_row(), consensus_row("Revenue", mean=2.54e9),
                consensus_row(label="CurrentYear(2027)"), consensus_row("EBITDA"),
                consensus_row(label="CurrentQtr.(Foo2026)")]
        estimates = parse_consensus(rows, "STZ")
        self.assertEqual([(item.indicator, item.quarter_end_month) for item in estimates],
                         [("EPS", "2026-08"), ("Revenue", "2026-08")])
        self.assertEqual(estimates[0].upstream_source, "Yahoo Finance")


class CrossCheckTests(unittest.TestCase):
    releases = parse_calendar([calendar_row(), calendar_row(period="2026-05-31", release="2026-06-30")], "STZ")

    def test_same_date_and_session_agree(self):
        result = compare_release(self.releases, expected_date=date(2026, 10, 6), window_days=7,
                                 issuer_release_at=datetime(2026, 10, 6, 20, 5, tzinfo=timezone.utc))
        self.assertEqual(result["status"], "agrees")
        self.assertEqual(result["issuer_session"], "after_close")
        self.assertEqual(result["session_status"], "agrees")
        self.assertEqual(result["period_ending"], "2026-08-31")

    def test_nearby_but_different_date_is_reported_as_differs(self):
        result = compare_release(self.releases, expected_date=date(2026, 10, 8), window_days=7)
        self.assertEqual(result["status"], "differs")
        self.assertEqual(result["difference_days"], -2)

    def test_session_mismatch_is_reported(self):
        result = compare_release(self.releases, expected_date=date(2026, 10, 6), window_days=7,
                                 issuer_release_at=datetime(2026, 10, 6, 11, 0, tzinfo=timezone.utc))
        self.assertEqual(result["issuer_session"], "before_open")
        self.assertEqual(result["session_status"], "differs")

    def test_release_outside_window_is_not_listed(self):
        result = compare_release(self.releases, expected_date=date(2026, 11, 20), window_days=7)
        self.assertEqual(result["status"], "not_listed")

    def test_session_boundaries_use_new_york_time(self):
        self.assertEqual(session_of(datetime(2026, 10, 6, 13, 29, tzinfo=timezone.utc)), "before_open")
        self.assertEqual(session_of(datetime(2026, 10, 6, 13, 30, tzinfo=timezone.utc)), "during_market")
        self.assertEqual(session_of(datetime(2026, 10, 6, 20, 0, tzinfo=timezone.utc)), "after_close")
        with self.assertRaises(ConfigurationError):
            session_of(datetime(2026, 10, 6, 20, 0))


class ConsensusSelectionTests(unittest.TestCase):
    def select(self, rows, *, today=date(2026, 10, 11), release=date(2026, 10, 6)):
        return select_consensus(parse_consensus(rows, "STZ"), period_ending=date(2026, 8, 31),
                                today=today, max_age_days=7, release_date=release)

    def test_newest_pre_release_row_per_indicator_is_current(self):
        result = self.select([consensus_row(mean=3.50, scraped="2026-10-01"),
                              consensus_row(mean=3.55, scraped="2026-10-05"),
                              consensus_row("Revenue", mean=2.54e9, scraped="2026-10-05")])
        self.assertEqual(result["status"], "current")
        self.assertEqual([(item["indicator"], item["mean"]) for item in result["estimates"]],
                         [("EPS", "3.55"), ("Revenue", "2540000000.0")])

    def test_scrape_on_or_after_release_is_never_an_expectation(self):
        result = self.select([consensus_row(scraped="2026-10-06"), consensus_row(scraped="2026-10-07")])
        self.assertEqual(result["status"], "post_release_only")
        self.assertEqual(result["estimates"], [])

    def test_old_scrape_is_stale_not_current(self):
        result = self.select([consensus_row(scraped="2026-07-04")])
        self.assertEqual(result["status"], "stale")
        self.assertEqual(result["newest_scrape"], "2026-07-04")

    def test_age_is_measured_at_the_release_for_past_events(self):
        # Scraped five days before a release that is now a month old: fresh at the release.
        result = self.select([consensus_row(scraped="2026-10-01")], today=date(2026, 11, 10))
        self.assertEqual(result["status"], "current")

    def test_other_quarters_are_not_used(self):
        result = self.select([consensus_row(label="CurrentQtr.(Nov2026)", scraped="2026-10-05")])
        self.assertEqual(result["status"], "not_listed")


def mcp_server(tool_bodies, seen=None):
    """A fake streamable-HTTP MCP server answering do_query from ``tool_bodies``."""
    def handle(request: httpx.Request) -> httpx.Response:
        message = json.loads(request.content)
        if seen is not None:
            seen.append((message.get("method"), request.headers.get("mcp-session-id")))
        if message["method"] == "initialize":
            body = {"jsonrpc": "2.0", "id": message["id"], "result": {"protocolVersion": "2025-03-26"}}
            return httpx.Response(200, headers={"content-type": "text/event-stream", "mcp-session-id": "s-1"},
                                  text=f"event: message\ndata: {json.dumps(body)}\n\n")
        if message["method"] == "notifications/initialized":
            return httpx.Response(202)
        entry = message["params"]["arguments"]["entry_id"]
        payload = tool_bodies[entry]
        body = {"jsonrpc": "2.0", "id": message["id"],
                "result": {"content": [{"type": "text", "text": json.dumps(payload)}], "isError": False}}
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
                              text=f"event: message\ndata: {json.dumps(body)}\n\n")
    return httpx.Client(transport=httpx.MockTransport(handle))


def ok(rows):
    return {"success": True, "status_code": 200, "data": {"results": rows}}


class ClientTests(unittest.TestCase):
    def test_session_is_opened_once_and_reused(self):
        seen = []
        client = BitgetDataClient(client=mcp_server({"equity_calendar": ok([calendar_row()])}, seen))
        client.releases("STZ")
        client.releases("STZ")
        self.assertEqual([method for method, _ in seen],
                         ["initialize", "notifications/initialized", "tools/call", "tools/call"])
        self.assertEqual(seen[-1][1], "s-1")

    def test_entries_outside_the_allow_list_are_refused_before_any_request(self):
        seen = []
        client = BitgetDataClient(client=mcp_server({}, seen))
        with self.assertRaises(ConfigurationError):
            client.query("crypto_whale_alerts", {})
        self.assertEqual(seen, [])

    def test_no_content_status_is_an_empty_answer(self):
        client = BitgetDataClient(client=mcp_server({"equity_calendar": {"success": True, "status_code": 204, "data": ""}}))
        self.assertEqual(client.releases("STZ"), ())

    def test_failed_query_halts(self):
        client = BitgetDataClient(client=mcp_server({"equity_price_quote": {"success": False, "status_code": 500}}))
        with self.assertRaises(DataUnavailable):
            client.quote("STZ")

    def test_http_failure_halts(self):
        client = BitgetDataClient(client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503))))
        with self.assertRaises(DataUnavailable):
            client.quote("STZ")

    def test_event_context_labels_each_part_and_survives_one_failure(self):
        client = BitgetDataClient(client=mcp_server({
            "equity_calendar": ok([calendar_row()]),
            "equity_price_quote": {"success": False, "status_code": 500},
            "equity_estimates_consensus": ok([consensus_row(scraped="2026-10-05")]),
        }))
        context = event_context(client, "STZ.US", event_date=date(2026, 10, 6),
                                 now=datetime(2026, 10, 5, 12, tzinfo=timezone.utc))
        self.assertEqual(context["symbol"], "STZ")
        self.assertEqual(context["source"], "bitget-mcp-server")
        self.assertEqual(context["calendar"]["status"], "agrees")
        self.assertEqual(context["quote"]["status"], "unavailable")
        self.assertEqual(context["consensus"]["status"], "current")

    def test_event_context_without_a_listed_release_does_not_guess_a_quarter(self):
        client = BitgetDataClient(client=mcp_server({
            "equity_calendar": ok([]),
            "equity_price_quote": ok([{"symbol": "STZ", "last_price": 1, "prev_close": 1, "change_percent": 0}]),
            "equity_estimates_consensus": ok([consensus_row()]),
        }))
        context = event_context(client, "STZ", event_date=date(2026, 10, 6),
                                now=datetime(2026, 10, 5, tzinfo=timezone.utc))
        self.assertEqual(context["calendar"]["status"], "not_listed")
        self.assertEqual(context["consensus"]["status"], "unavailable")
        self.assertEqual(context["quote"]["status"], "ok")


class ReverbMcpToolTests(unittest.TestCase):
    def load_server(self):
        import importlib.util
        from pathlib import Path
        spec = importlib.util.spec_from_file_location(
            "reverb_mcp_server", Path(__file__).resolve().parents[1] / "scripts" / "mcp_server.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_release_crosscheck_returns_the_comparison_only(self):
        server = self.load_server()
        fake = mcp_server({"equity_calendar": ok([calendar_row()])})
        server.BitgetDataClient = lambda: BitgetDataClient(client=fake)
        result = server.release_crosscheck("stz", "2026-10-06")
        self.assertEqual(result["status"], "agrees")
        self.assertEqual(result["source"], "bitget-mcp-server")
        self.assertNotIn("last_price", json.dumps(result))

    def test_release_crosscheck_refuses_bad_input_and_reports_outages(self):
        server = self.load_server()
        self.assertEqual(server.release_crosscheck("STZ;", "2026-10-06")["status"], "invalid")
        self.assertEqual(server.release_crosscheck("STZ", "06/10/2026")["status"], "invalid")
        down = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(503)))
        server.BitgetDataClient = lambda: BitgetDataClient(client=down)
        self.assertEqual(server.release_crosscheck("STZ", "2026-10-06")["status"], "unavailable")


if __name__ == "__main__":
    unittest.main()
