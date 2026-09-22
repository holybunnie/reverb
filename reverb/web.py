from __future__ import annotations

import html
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .preview import PreviewSnapshot


def route(path: str, static: bool) -> str:
    clean = path.strip("/")
    if not clean:
        return "/reverb/" if static else "/"
    if static:
        suffix = "" if "." in clean.rsplit("/", 1)[-1] else "/"
        return f"/reverb/{clean}{suffix}"
    return f"/{clean}"


def money(value: Any, places: int = 2) -> str:
    try:
        amount = Decimal(str(value))
    except (ArithmeticError, InvalidOperation, TypeError, ValueError):
        return "—"
    return f"${amount:,.{places}f}" if amount.is_finite() else "—"


def percent(value: Any) -> str:
    try:
        amount = Decimal(str(value)) * 100
    except (ArithmeticError, InvalidOperation, TypeError, ValueError):
        return "—"
    return f"{amount:+.2f}%" if amount.is_finite() else "—"


def timezone_label(value: str | None) -> str:
    if not value:
        return "Africa/Lagos"
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        return "Timezone unavailable"
    return value


def replay_view(replay: Any | None, timezone_name: str | None = None) -> dict[str, str]:
    if replay is None:
        return {"symbol": "—", "token": "No verified event", "date": "—", "ny": "—", "local": "—",
                "observed": "—", "baseline": "—", "move": "—", "budget": "—", "action": "—",
                "refusal": "—", "risk_fill": "0"}
    event = datetime.fromisoformat(replay.event_at)
    zone_name = timezone_label(timezone_name)
    zone = ZoneInfo(zone_name) if zone_name != "Timezone unavailable" else ZoneInfo("UTC")
    ny = event.astimezone(ZoneInfo("America/New_York"))
    local = event.astimezone(zone)
    arithmetic = replay.arithmetic
    observed_raw = arithmetic.get("observed_at")
    observed = datetime.fromisoformat(observed_raw).astimezone(ZoneInfo("America/New_York")) if observed_raw else None
    try:
        budget = Decimal(str(arithmetic["risk_budget"])); action = Decimal(str(arithmetic["action_order_notional"]))
        fill = max(Decimal("0"), min(Decimal("100"), action / budget * 100)) if budget else Decimal("0")
    except (KeyError, ArithmeticError, InvalidOperation, TypeError, ValueError):
        fill = Decimal("0")
    return {"symbol": str(replay.symbol), "token": str(replay.token_symbol), "date": ny.strftime("%d %b %Y").upper(),
            "ny": ny.strftime("%H:%M ET"), "local": local.strftime("%H:%M %Z"),
            "observed": observed.strftime("%H:%M ET") if observed else "—", "baseline": money(arithmetic.get("baseline")),
            "move": percent(arithmetic.get("move_pct")), "budget": money(arithmetic.get("risk_budget")),
            "action": money(arithmetic.get("action_order_notional"), 3), "refusal": money(arithmetic.get("refusal_order_notional")),
            "risk_fill": f"{fill:.1f}"}


def layout(*, title: str, page: str, body: str, static: bool = False, description: str = "Reverb watches earnings after the bell and shows every decision.") -> str:
    nav = [("How it works", "#how" if page == "home" else route("", static) + "#how"), ("Workspace", route("app", static)),
           ("Events", route("events", static)), ("Report", route("report", static)), ("Evidence", route("preview", static))]
    links = "".join(f'<a class="nav-link {"active" if page == key else ""}" href="{href}">{label}</a>'
                    for (label, href), key in zip(nav, ["how", "app", "events", "report", "preview"]))
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#07110f"><meta name="description" content="{html.escape(description)}"><meta name="color-scheme" content="dark">
<title>{html.escape(title)} · Reverb</title><link rel="stylesheet" href="{route('assets/styles.css', static)}"></head>
<body data-page="{page}"><div class="noise" aria-hidden="true"></div><header class="site-header"><a class="brand" href="{route('', static)}"><span class="brand-signal"><i></i><i></i><i></i></span><span>reverb</span></a><nav>{links}</nav><a class="header-cta" href="{route('app', static)}">Open workspace <span>↗</span></a><button class="menu" aria-label="Open navigation">Menu</button></header>
<main>{body}</main><footer><a class="brand footer-brand" href="{route('', static)}"><span class="brand-signal"><i></i><i></i><i></i></span><span>reverb</span></a><p>After-bell decisions with receipts.</p><div><a href="{route('demo', static)}">Verified replay</a><a href="{route('connect', static)}">Connect locally</a><a href="https://github.com/holybunnie/reverb">GitHub</a></div></footer>
<script src="{route('assets/app.js', static)}" defer></script></body></html>'''


def render_landing(snapshot: PreviewSnapshot, replay: Any | None, *, static: bool = False) -> str:
    r = {k: html.escape(v) for k, v in replay_view(replay, "Africa/Lagos").items()}
    body = f'''
<section class="landing-hero"><div class="orbital" aria-hidden="true"><span></span><span></span><span></span></div><div class="hero-copy reveal"><div class="eyebrow"><b></b> Earnings, after the bell</div><h1>The market closes.<br><em>Reverb keeps listening.</em></h1><p>An earnings agent that watches the move, respects your risk limit, and can refuse a bad setup—while you sleep.</p><div class="hero-actions"><a class="button primary magnetic" href="{route('app', static)}">Enter workspace <span>↗</span></a><a class="button ghost" href="{route('demo', static)}"><span class="play">▶</span> Watch verified replay</a></div><div class="trust-row"><span><i class="live-dot"></i> Agent Hub verified</span><span>Local-first keys</span><span>No withdrawal access</span></div></div>
<aside class="event-orbit reveal delay-1"><div class="glass event-preview"><div class="event-preview-top"><span>RECORDED EVENT</span><span class="verified-pill">VERIFIED</span></div><div class="event-symbol">{r['symbol']}</div><p>{r['token']} · {r['date']}</p><div class="event-move"><span>Observed move</span><strong>{r['move']}</strong></div><div class="wave"><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i></div><div class="event-foot"><span>{r['ny']}</span><span>{r['local']} Lagos</span></div></div></aside></section>
<section class="proof-strip"><div><strong>{snapshot.online_reality}</strong><span>Reality instruments observed</span></div><div><strong>24/7</strong><span>selected stock-token access</span></div><div><strong>1</strong><span>real Agent Hub fill</span></div><div><strong>0</strong><span>withdrawal permissions</span></div></section>
<section class="story" id="how"><div class="section-intro reveal"><div class="eyebrow"><b></b> Why Reverb</div><h2>The important part happens after everyone leaves.</h2><p>Earnings often arrive outside regular hours. Reverb turns that quiet gap into a controlled, explainable workflow.</p></div><div class="steps"><article class="step reveal"><span>01</span><div class="step-icon target"></div><h3>State the view</h3><p>Pick an event, direction, expected move, and the most you are willing to risk.</p></article><article class="step reveal delay-1"><span>02</span><div class="step-icon pulse-icon"></div><h3>Watch the reaction</h3><p>Fresh Bitget prices are measured against the pre-event baseline. Stale data stops the path.</p></article><article class="step reveal delay-2"><span>03</span><div class="step-icon receipt"></div><h3>Wake up to receipts</h3><p>Every action and refusal is recorded with its arithmetic, timing, and provenance.</p></article></div></section>
<section class="refusal-section"><div class="refusal-copy reveal"><div class="eyebrow"><b></b> Designed to say no</div><h2>A trading agent should not always trade.</h2><p>Reverb gives a refusal the same weight as an action. If the budget, freshness, session, or evidence fails, the decision stops there.</p><a class="text-link" href="{route('report', static)}">See the morning report <span>→</span></a></div><div class="refusal-card glass reveal delay-1"><div class="decision-stamp">REFUSED</div><span>Budget gate</span><strong>{r['refusal']}</strong><p>Requested notional exceeded the replay budget of {r['budget']}.</p><div class="math-line"><i style="--w:100%"></i><i style="--w:42%"></i></div><small>Arithmetic regenerated from the checked ledger</small></div></section>
<section class="closing-cta reveal"><div><span class="eyebrow"><b></b> The bell is only the beginning</span><h2>Be ready for the next earnings move.</h2></div><a class="button primary magnetic" href="{route('app', static)}">Open Reverb <span>↗</span></a></section>'''
    return layout(title="Earnings after the bell", page="home", body=body, static=static)


def render_workspace(snapshot: PreviewSnapshot, replay: Any | None, *, static: bool = False, risk: str | None = None, timezone_name: str | None = None) -> str:
    r = {k: html.escape(v) for k, v in replay_view(replay, timezone_name).items()}
    body = f'''<section class="product-shell"><aside class="side-nav"><span class="side-label">CONTROL ROOM</span><a class="active" href="{route('app', static)}">Overview</a><a href="{route('events', static)}">Events</a><a href="{route('report', static)}">Reports</a><a href="{route('connect', static)}">Connection</a><div class="side-status"><i class="live-dot"></i><div><strong>Agent online</strong><span>Research mode</span></div></div></aside>
<div class="workspace"><div class="workspace-head reveal"><div><span class="eyebrow"><b></b> Control room</span><h1>Good evening.</h1><p>One verified replay is ready. Live spot execution is locally guarded.</p></div><div class="clock" data-clock data-zone="{html.escape(timezone_label(timezone_name))}">--:--:--<small>{html.escape(timezone_label(timezone_name))}</small></div></div>
<div class="status-grid reveal delay-1"><article class="mini-stat"><span>Reality universe</span><strong>{snapshot.online_reality}</strong><small>observed online</small></article><article class="mini-stat"><span>Execution</span><strong class="green">VERIFIED</strong><small>Agent Hub spot path</small></article><article class="mini-stat"><span>Options path</span><strong class="amber">BLOCKED</strong><small>account entitlement</small></article><article class="mini-stat"><span>Risk cap</span><strong data-risk-label>{html.escape(risk or r['budget'])}</strong><small>stored locally</small></article></div>
<section class="workspace-card event-focus reveal delay-2"><div class="card-heading"><div><span class="overline">VERIFIED HISTORICAL EVENT</span><h2>{r['symbol']} <small>{r['token']}</small></h2></div><span class="verified-pill">LEDGER VERIFIED</span></div><div class="event-columns"><div><span>Event date</span><strong>{r['date']}</strong></div><div><span>New York</span><strong>{r['ny']}</strong></div><div><span>Your time</span><strong>{r['local']}</strong></div><div><span>Observed move</span><strong class="negative">{r['move']}</strong></div></div><div class="signal-track"><i></i><span>Close</span><span>Results</span><span>First crossing</span></div><div class="card-actions"><a class="button primary" href="{route('demo', static)}">Open full replay</a><a class="button ghost" href="{route('events', static)}">Build a thesis</a></div></section>
<section class="workspace-card quick-setup reveal"><div class="card-heading"><div><span class="overline">LOCAL PREFERENCES</span><h2>Set your guardrails</h2></div><span class="save-state" data-save-state>Saved on this device</span></div><form class="preference-form" data-preferences><label>Risk budget (USDT)<input name="risk" inputmode="decimal" min="1" step="0.01" value="{html.escape(risk or '')}" placeholder="50.00"></label><label>Timezone<input name="timezone" value="{html.escape(timezone_name or 'Africa/Lagos')}" placeholder="Africa/Lagos"></label><button class="button primary" type="submit">Save preferences</button></form></section></div></section>'''
    return layout(title="Control room", page="app", body=body, static=static)


def render_events(snapshot: PreviewSnapshot, replay: Any | None, *, static: bool = False) -> str:
    r = {k: html.escape(v) for k, v in replay_view(replay, "Africa/Lagos").items()}
    action_notional = html.escape(str(replay.arithmetic.get("action_order_notional", ""))) if replay else ""
    observed_move = html.escape(str(replay.arithmetic.get("move_pct", ""))) if replay else ""
    body = f'''<section class="inner-hero reveal"><span class="eyebrow"><b></b> Event discovery</span><h1>Find the earnings<br>moment that matters.</h1><p>Search the checked event set, then build a thesis with explicit direction, expected move, and risk.</p></section><section class="event-builder" data-event-builder data-action-notional="{action_notional}" data-observed-move="{observed_move}"><div class="search-panel workspace-card reveal delay-1"><label class="search-box"><span>⌕</span><input type="search" data-event-search placeholder="Search company or ticker" autocomplete="off"></label><div class="filter-row"><button class="chip active" type="button">Verified events</button><button class="chip" type="button" disabled>Live calendar requires local server</button></div><article class="event-result selected" data-event-card data-search="nvidia nvda"><div class="ticker-avatar">NV</div><div><strong>NVIDIA</strong><span>NVDA · {r['date']} · after close</span></div><div class="result-time"><strong>{r['ny']}</strong><span>{r['local']} Lagos</span></div><span class="verified-pill">REPLAY</span></article><div class="empty-search" data-empty-search>No checked event matches that search.</div></div>
<div class="thesis-panel workspace-card reveal delay-2"><div class="card-heading"><div><span class="overline">THESIS BUILDER</span><h2>Your view, bounded.</h2></div><span class="step-count">01 / 03</span></div><form data-thesis-form><fieldset><legend>Direction</legend><div class="segmented"><label><input type="radio" name="direction" value="beats" checked><span>↑ Beats</span></label><label><input type="radio" name="direction" value="misses"><span>↓ Misses</span></label><label><input type="radio" name="direction" value="watch"><span>○ Watch only</span></label></div></fieldset><div class="form-grid"><label>Expected move (%)<input required name="move" inputmode="decimal" min="0.1" max="100" step="0.1" placeholder="6.0"></label><label>Maximum risk (USDT)<input required name="budget" inputmode="decimal" min="1" step="0.01" placeholder="25.00"></label></div><label>Describe your view <textarea name="view" maxlength="500" placeholder="I expect stronger data-center revenue, but only want to act if the after-hours move confirms it."></textarea></label><div class="deterministic-note"><i>◆</i><p><strong>Qwen may interpret the words.</strong> Deterministic code supplies every price, size, threshold, and decision.</p></div><button class="button primary wide" type="submit">Review deterministic decision <span>→</span></button></form><div class="decision-preview" data-decision-preview hidden><div class="decision-icon">✓</div><span>THESIS SAVED LOCALLY</span><h3 data-decision-title>Watch NVDA earnings</h3><p data-decision-copy></p><div class="preview-actions"><button class="button ghost" type="button" data-edit-thesis>Edit thesis</button><a class="button primary" href="{route('app', static)}">Go to waiting room</a></div></div></div></section>'''
    return layout(title="Events", page="events", body=body, static=static)


def render_report_page(snapshot: PreviewSnapshot, replay: Any | None, report_html: str | None, *, static: bool = False) -> str:
    r = {k: html.escape(v) for k, v in replay_view(replay, "Africa/Lagos").items()}
    report = report_html or '<div class="empty-state">No checked report is available.</div>'
    body = f'''<section class="inner-hero report-hero reveal"><span class="eyebrow"><b></b> Morning report</span><h1>What happened.<br>What Reverb refused.</h1><p>Action and refusal receive equal space. Every number below regenerates from the verified replay ledger.</p><div class="report-meta"><span>{r['symbol']} · {r['date']}</span><span class="verified-pill">LEDGER VERIFIED</span></div></section><section class="report-summary reveal delay-1"><article><span>Baseline</span><strong>{r['baseline']}</strong></article><article><span>First crossing</span><strong>{r['observed']}</strong></article><article><span>Observed move</span><strong class="negative">{r['move']}</strong></article><article><span>Risk budget</span><strong>{r['budget']}</strong></article></section><section class="report-stage reveal delay-2">{report}</section><section class="report-disclaimer"><strong>Recorded evidence, not performance.</strong><p>This is one historical event replay. It is not a live fill, a backtest, or a profitability claim.</p><a href="{route('preview', static)}">Inspect source evidence →</a></section>'''
    return layout(title="Morning report", page="report", body=body, static=static)


def render_connect(*, static: bool = False) -> str:
    body = f'''<section class="inner-hero reveal"><span class="eyebrow"><b></b> Local connection</span><h1>Your keys stay<br>on your machine.</h1><p>The hosted experience needs no credentials. The real agent connects directly from your device to Bitget through Agent Hub.</p></section><section class="permission-boundary reveal delay-1"><div>◆</div><p><strong>Permission boundary</strong>Read and trade only. Reverb never requests withdrawal or transfer permission.</p></section><section class="connect-steps"><article class="workspace-card reveal"><span>01</span><h2>Create or edit the key</h2><p>Open Bitget API Management and use Unified account Trade permission.</p></article><article class="workspace-card reveal delay-1"><span>02</span><h2>Keep dangerous scopes off</h2><p>Leave P2P, Wallet, Withdraw, and Transfer disabled.</p></article><article class="workspace-card reveal delay-2"><span>03</span><h2>Store it locally</h2><p>Put the API key, secret, and passphrase in the ignored <code>.env</code>.</p></article><article class="workspace-card reveal delay-3"><span>04</span><h2>Verify read-only</h2><p>Run <code>./.venv/bin/python scripts/account_check.py</code>. No order is submitted.</p></article></section><div class="connect-cta"><a class="button primary" href="https://github.com/holybunnie/reverb#how-to-run-the-current-build">Open setup guide ↗</a><a class="button ghost" href="{route('app', static)}">Back to workspace</a></div>'''
    return layout(title="Connect locally", page="connect", body=body, static=static)
