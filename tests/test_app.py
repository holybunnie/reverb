from pathlib import Path
import unittest

from reverb.app import render_app_html, render_connection_html
from reverb.preview import load_preview_snapshot
from reverb.replay import load_replay_snapshot, render_replay_report


class AppTests(unittest.TestCase):
    def test_consumer_surface_keeps_risk_cap_visible_and_does_not_invent_event(self):
        snapshot = load_preview_snapshot(Path(__file__).resolve().parents[1])
        page = render_app_html(snapshot, risk_budget="50", timezone_name="Africa/Lagos")
        self.assertIn("$50.00 maximum loss", page)
        self.assertIn("Africa/Lagos", page)
        self.assertIn("No event is being invented", page)
        self.assertNotIn("implied volatility", page.lower())
        self.assertIn("/api/language/view", page)
        self.assertIn("Say the view naturally", page)

    def test_connection_surface_is_local_only_and_excludes_dangerous_scopes(self):
        page = render_connection_html()
        self.assertIn("Select Unified account", page)
        self.assertIn("no separate Stock+ checkbox", page)
        self.assertIn("Leave P2P, Wallet, Withdraw, and Transfer off", page)
        self.assertIn(".env", page)
        self.assertNotIn("name=\"api_key\"", page)

    def test_invalid_timezone_does_not_get_displayed_as_verified(self):
        snapshot = load_preview_snapshot(Path(__file__).resolve().parents[1])
        page = render_app_html(snapshot, timezone_name="not/a-timezone")
        self.assertIn("Timezone unavailable", page)

    def test_public_dashboard_uses_verified_replay_and_respects_reduced_motion(self):
        root = Path(__file__).resolve().parents[1]
        preview = load_preview_snapshot(root)
        replay = load_replay_snapshot(root)
        page = render_app_html(
            preview,
            risk_budget="50",
            timezone_name="Africa/Lagos",
            morning_report_html=render_replay_report(replay),
            replay_snapshot=replay,
            static_demo=True,
        )
        self.assertIn("The market closed", page)
        self.assertIn("NVDA", page)
        self.assertIn("Verified historical replay", page)
        self.assertIn("prefers-reduced-motion", page)
        self.assertIn('./demo/', page)
        self.assertNotIn('action="/app"', page)
        self.assertNotIn("/api/language/view", page)
