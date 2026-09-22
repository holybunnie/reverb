"""Build the credential-free static Pages artifact from verified replay evidence."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from reverb.errors import DataUnavailable, LedgerError  # noqa: E402
from reverb.app import (  # noqa: E402
    render_app_html, render_connection_html, render_events_html,
    render_landing_html, render_report_html,
)
from reverb.preview import load_preview_snapshot, render_preview_html  # noqa: E402
from reverb.replay import load_replay_snapshot, render_replay_html, render_replay_report  # noqa: E402


def main() -> int:
    try:
        replay = load_replay_snapshot(ROOT)
        preview = load_preview_snapshot(ROOT)
    except (DataUnavailable, LedgerError, OSError, ValueError) as exc:
        print(f"REVERB HALTED: cannot build static demo: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    site = ROOT / "site"
    site.mkdir(parents=True, exist_ok=True)
    landing = render_landing_html(preview, replay_snapshot=replay, static_demo=True)
    dashboard = render_app_html(
        preview,
        risk_budget=str(replay.arithmetic["risk_budget"]),
        timezone_name="Africa/Lagos",
        morning_report_html=render_replay_report(replay),
        replay_snapshot=replay,
        static_demo=True,
    )
    (site / "index.html").write_text(landing, encoding="utf-8")
    (site / "app").mkdir(exist_ok=True)
    (site / "app" / "index.html").write_text(dashboard, encoding="utf-8")
    (site / "events").mkdir(exist_ok=True)
    (site / "events" / "index.html").write_text(
        render_events_html(preview, replay_snapshot=replay, static_demo=True), encoding="utf-8")
    (site / "report").mkdir(exist_ok=True)
    (site / "report" / "index.html").write_text(
        render_report_html(preview, replay_snapshot=replay,
                           morning_report_html=render_replay_report(replay), static_demo=True), encoding="utf-8")
    (site / "connect").mkdir(exist_ok=True)
    (site / "connect" / "index.html").write_text(
        render_connection_html(static_demo=True), encoding="utf-8")
    (site / "demo").mkdir(exist_ok=True)
    page = render_replay_html(replay)
    (site / "demo" / "index.html").write_text(
        page.replace('href="preview"', 'href="../preview"'),
        encoding="utf-8",
    )
    (site / "preview").mkdir(exist_ok=True)
    (site / "preview" / "index.html").write_text(render_preview_html(preview), encoding="utf-8")
    assets = site / "assets"
    assets.mkdir(exist_ok=True)
    source_assets = ROOT / "reverb" / "static"
    for name in ("styles.css", "app.js"):
        (assets / name).write_bytes((source_assets / name).read_bytes())
    print(f"Static demo written to {site}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
