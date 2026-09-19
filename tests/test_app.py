from pathlib import Path
import unittest

from reverb.app import render_app_html, render_connection_html
from reverb.preview import load_preview_snapshot


class AppTests(unittest.TestCase):
    def test_consumer_surface_keeps_risk_cap_visible_and_does_not_invent_event(self):
        snapshot = load_preview_snapshot(Path(__file__).resolve().parents[1])
        page = render_app_html(snapshot, risk_budget="50", timezone_name="Africa/Lagos")
        self.assertIn("$50.00 maximum loss", page)
        self.assertIn("Africa/Lagos", page)
        self.assertIn("No event is being invented", page)
        self.assertNotIn("implied volatility", page.lower())

    def test_connection_surface_is_local_only_and_excludes_dangerous_scopes(self):
        page = render_connection_html()
        self.assertIn("Unified account trade, read and write", page)
        self.assertIn("Unified account management, read-only", page)
        self.assertIn("Withdraw and Transfer unchecked", page)
        self.assertIn(".env", page)
        self.assertNotIn("name=\"api_key\"", page)

    def test_invalid_timezone_does_not_get_displayed_as_verified(self):
        snapshot = load_preview_snapshot(Path(__file__).resolve().parents[1])
        page = render_app_html(snapshot, timezone_name="not/a-timezone")
        self.assertIn("Timezone unavailable", page)
