from pathlib import Path
import unittest

from reverb.app import (render_app_html, render_connection_html, render_events_html,
                        render_landing_html, render_report_html)
from reverb.preview import load_preview_snapshot
from reverb.replay import load_replay_snapshot, render_replay_report


class AppTests(unittest.TestCase):
    def test_consumer_surface_keeps_risk_cap_visible_and_does_not_invent_event(self):
        snapshot = load_preview_snapshot(Path(__file__).resolve().parents[1])
        page = render_app_html(snapshot, risk_budget="50", timezone_name="Africa/Lagos")
        self.assertIn('data-risk-label>50', page)
        self.assertIn("Africa/Lagos", page)
        self.assertNotIn("implied volatility", page.lower())
        self.assertIn("Set your guardrails", page)

    def test_connection_surface_is_local_only_and_excludes_dangerous_scopes(self):
        page = render_connection_html()
        self.assertIn("Unified account Trade permission", page)
        self.assertIn("Leave P2P, Wallet, Withdraw, and Transfer disabled", page)
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
        self.assertIn("NVDA", page)
        self.assertIn("VERIFIED HISTORICAL EVENT", page)
        self.assertIn('/reverb/demo/', page)
        css = (root / "reverb" / "static" / "styles.css").read_text()
        self.assertIn("prefers-reduced-motion", css)

    def test_landing_and_product_pages_are_separate(self):
        root = Path(__file__).resolve().parents[1]
        preview = load_preview_snapshot(root)
        replay = load_replay_snapshot(root)
        landing = render_landing_html(preview, replay_snapshot=replay, static_demo=True)
        events = render_events_html(preview, replay_snapshot=replay, static_demo=True)
        report = render_report_html(preview, replay_snapshot=replay,
                                    morning_report_html=render_replay_report(replay), static_demo=True)
        self.assertIn("Know what you believed", landing)
        self.assertIn("COSTCO FORWARD RUN", landing)
        self.assertIn("RCOSTUSDT", landing)
        self.assertNotIn("THESIS BUILDER", landing)
        self.assertIn("THESIS BUILDER", events)
        self.assertIn("data-claims-review", events)
        self.assertIn("does not freeze", events)
        self.assertIn("Morning report", report)
        self.assertIn("COSTCO · Q4 FY2026", report)
        self.assertIn("REFUSE", report)
        self.assertIn("data-human-review", report)
        self.assertNotIn("NVIDIA", report)

    def test_event_workflow_uses_local_live_api_instead_of_a_replay_card(self):
        root = Path(__file__).resolve().parents[1]
        preview = load_preview_snapshot(root)
        replay = load_replay_snapshot(root)
        local_page = render_events_html(preview, replay_snapshot=replay)
        hosted_page = render_events_html(preview, replay_snapshot=replay, static_demo=True)
        self.assertIn('data-live-events="true"', local_page)
        self.assertIn("same reported measure year over year", local_page)
        self.assertIn("matching reported/adjusted basis", local_page)
        self.assertIn("explicitly links it to margin or cost of sales", local_page)
        self.assertIn("/api/events", (root / "reverb" / "static" / "app.js").read_text())
        self.assertNotIn('data-search="nvidia nvda"', local_page.lower())
        self.assertIn("STATIC PREVIEW", hosted_page)
        self.assertIn("does not invent upcoming events", hosted_page)
