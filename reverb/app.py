"""HTML entry points for Reverb's public and local product surfaces."""
from __future__ import annotations

from typing import Any

from .preview import PreviewSnapshot
from .web import render_connect, render_events, render_landing, render_report_page, render_workspace


def render_landing_html(snapshot: PreviewSnapshot, *, replay_snapshot: Any | None = None,
                        static_demo: bool = False) -> str:
    return render_landing(snapshot, replay_snapshot, static=static_demo)


def render_app_html(snapshot: PreviewSnapshot, *, risk_budget: str | None = None,
                    timezone_name: str | None = None, morning_report_html: str | None = None,
                    replay_snapshot: Any | None = None, static_demo: bool = False) -> str:
    del morning_report_html
    return render_workspace(snapshot, replay_snapshot, static=static_demo,
                            risk=risk_budget, timezone_name=timezone_name)


def render_events_html(snapshot: PreviewSnapshot, *, replay_snapshot: Any | None = None,
                       static_demo: bool = False) -> str:
    return render_events(snapshot, replay_snapshot, static=static_demo)


def render_report_html(snapshot: PreviewSnapshot, *, replay_snapshot: Any | None = None,
                       morning_report_html: str | None = None, static_demo: bool = False) -> str:
    return render_report_page(snapshot, replay_snapshot, morning_report_html, static=static_demo)


def render_connection_html(*, static_demo: bool = False) -> str:
    return render_connect(static=static_demo)
