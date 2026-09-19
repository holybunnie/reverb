from pathlib import Path
import unittest

from reverb.app import render_app_html
from reverb.demo import load_demo_snapshot


class AppTests(unittest.TestCase):
    def test_consumer_surface_keeps_risk_cap_visible_and_does_not_invent_event(self):
        snapshot = load_demo_snapshot(Path(__file__).resolve().parents[1])
        page = render_app_html(snapshot, risk_budget="50", timezone_name="Africa/Lagos")
        self.assertIn("$50.00 maximum loss", page)
        self.assertIn("Africa/Lagos", page)
        self.assertIn("No event is being invented", page)
        self.assertNotIn("implied volatility", page.lower())

