from __future__ import annotations

import html
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .preview import PreviewSnapshot
from .costco_report import costco_report_summary, render_costco_morning_brief


ROOT = Path(__file__).resolve().parents[1]


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
                "refusal": "—", "risk_fill": "0", "trigger": "—"}
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
            "trigger": percent(arithmetic.get("trigger_pct")),
            "action": money(arithmetic.get("action_order_notional"), 3), "refusal": money(arithmetic.get("refusal_order_notional")),
            "risk_fill": f"{fill:.1f}"}


def layout(*, title: str, page: str, body: str, static: bool = False, description: str = "Write down what you believe before earnings. Reverb checks it against the release and market reaction; you decide.") -> str:
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
<section class="landing-hero"><div class="orbital" aria-hidden="true"><span></span><span></span><span></span></div><div class="hero-copy reveal"><div class="eyebrow"><b></b> Overnight earnings desk</div><h1>Know what you believed.<br><em>See what survived.</em></h1><p>Write down your view before the report. Reverb checks it against what the company said, measures the token-market reaction, and leaves you a sourced morning brief. You make the decision.</p><div class="hero-actions"><a class="button primary magnetic" href="{route('events', static)}">Prepare a thesis <span>↗</span></a><a class="button ghost" href="{route('demo', static)}"><span class="play">▶</span> Open verified replay</a></div><div class="trust-row"><span><i class="live-dot"></i> Claims frozen before scoring</span><span>Source-linked facts</span><span>Human decides</span></div></div>
<aside class="event-orbit reveal delay-1"><div class="glass event-preview"><div class="event-preview-top"><span>COSTCO FORWARD RUN</span><span class="verified-pill">24 SEP · READ ONLY</span></div><div class="event-symbol">COST</div><p>RCOSTUSDT · Q4 FY2026</p><div class="event-move"><span>Registered thesis</span><strong>$100 max risk</strong></div><div class="wave"><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i></div><div class="event-foot"><span>Trigger 3.00%</span><span>Human confirmation only</span></div></div></aside></section>
<section class="proof-strip"><div><strong>{snapshot.online_reality}</strong><span>online Reality pairs in latest checked capture</span></div><div><strong>RCOSTUSDT</strong><span>forward event under observation</span></div><div><strong>3%</strong><span>production reaction threshold</span></div><div><strong>YOU</strong><span>make the final decision</span></div></section>
<section class="story" id="how"><div class="section-intro reveal"><div class="eyebrow"><b></b> Your overnight research desk</div><h2>Most tools report the quarter. Reverb remembers your view before it.</h2><p>A post-mortem is useful only when the thesis was frozen first—and when public facts are not mistaken for a prediction.</p></div><div class="steps"><article class="step reveal"><span>01</span><div class="step-icon target"></div><h3>Write it down</h3><p>Put your earnings view into plain language. Review and confirm the extracted claims before the timestamped record is frozen.</p></article><article class="step reveal delay-1"><span>02</span><div class="step-icon pulse-icon"></div><h3>Check what changed</h3><p>Facts already public are marked known and excluded. New release facts must match their cited source; deterministic code reconciles the claims.</p></article><article class="step reveal delay-2"><span>03</span><div class="step-icon receipt"></div><h3>Decide with receipts</h3><p>See the measured market reaction, market quality, and Reverb's recommendation in the morning. No order without your explicit confirmation.</p></article></div></section>
<section class="refusal-section"><div class="refusal-copy reveal"><div class="eyebrow"><b></b> Human-confirmed, never automatic</div><h2>Analysis is not an order.</h2><p>Reverb presents a deterministic recommendation with its arithmetic and source evidence. The final action stays with you; any supported execution is a separate, explicit Agent Hub handoff.</p><a class="text-link" href="{route('report', static)}">Inspect the morning brief <span>→</span></a></div><div class="refusal-card glass reveal delay-1"><div class="decision-stamp">FORWARD</div><span>Costco · event capture pending</span><strong>RCOSTUSDT</strong><p>The Costco workflow records the issuer timestamp, public UTA order book, reaction, and thesis reconciliation. A required capture gap stays incomplete.</p><div class="math-line"><i style="--w:72%"></i><i style="--w:48%"></i></div><small>NVIDIA's 3% replay remains the secondary verification</small></div></section>
<section class="closing-cta reveal"><div><span class="eyebrow"><b></b> Before the next report</span><h2>Make your view testable. Keep the decision yours.</h2></div><a class="button primary magnetic" href="{route('events', static)}">Open the thesis desk <span>↗</span></a></section>'''
    return layout(title="Overnight earnings desk", page="home", body=body, static=static)


def render_workspace(snapshot: PreviewSnapshot, replay: Any | None, *, static: bool = False, risk: str | None = None, timezone_name: str | None = None) -> str:
    r = {k: html.escape(v) for k, v in replay_view(replay, timezone_name).items()}
    body = f'''<section class="product-shell"><aside class="side-nav"><span class="side-label">CONTROL ROOM</span><a class="active" href="{route('app', static)}">Overview</a><a href="{route('events', static)}">Events</a><a href="{route('report', static)}">Reports</a><a href="{route('connect', static)}">Connection</a><div class="side-status"><i class="live-dot"></i><div><strong>Agent online</strong><span>Research mode</span></div></div></aside>
<div class="workspace"><div class="workspace-head reveal"><div><span class="eyebrow"><b></b> Control room</span><h1>Good evening.</h1><p>Live event decisions are stored locally. No order is sent from this dashboard.</p></div><div class="clock" data-clock data-zone="{html.escape(timezone_label(timezone_name))}">--:--:--<small>{html.escape(timezone_label(timezone_name))}</small></div></div>
<div class="status-grid reveal delay-1"><article class="mini-stat"><span>Reality universe</span><strong>{snapshot.online_reality}</strong><small>from checked public evidence</small></article><article class="mini-stat"><span>Spot transport</span><strong class="green">VERIFIED</strong><small>one manually approved fill</small></article><article class="mini-stat"><span>Options path</span><strong class="amber">BLOCKED</strong><small>account entitlement</small></article><article class="mini-stat"><span>Risk cap</span><strong data-risk-label>{html.escape(risk or r['budget'])}</strong><small>stored locally</small></article></div>
<section class="workspace-card waiting-card reveal delay-2" data-waiting-state><div class="card-heading"><div><span class="overline">YOUR NEXT EVENT</span><h2 data-waiting-title>No event selected</h2></div><span class="verified-pill" data-waiting-status>LOCAL WORKSPACE</span></div><p class="waiting-empty" data-waiting-empty>Choose a company from the current earnings week to save a thesis and start a countdown.</p><div data-waiting-details hidden><div class="event-columns"><div><span>Event time</span><strong data-waiting-local>—</strong></div><div><span>New York</span><strong data-waiting-ny>—</strong></div><div><span>Time source</span><strong data-waiting-basis>—</strong></div><div><span>Risk budget</span><strong data-waiting-budget>—</strong></div></div><div class="countdown-row"><span>Time to event</span><strong data-countdown>—</strong></div><div class="waiting-actions"><button class="button ghost" type="button" data-monitor-reaction>Check price reaction</button><a class="button primary" href="{route('report', static)}">Open morning report</a></div><p class="monitor-result" data-monitor-result aria-live="polite"></p></div></section>
<section class="workspace-card event-focus reveal"><div class="card-heading"><div><span class="overline">VERIFIED HISTORICAL EVENT</span><h2>{r['symbol']} <small>{r['token']}</small></h2></div><span class="verified-pill">LEDGER VERIFIED</span></div><div class="event-columns"><div><span>Event date</span><strong>{r['date']}</strong></div><div><span>New York</span><strong>{r['ny']}</strong></div><div><span>Your time</span><strong>{r['local']}</strong></div><div><span>Observed move</span><strong class="negative">{r['move']}</strong></div></div><div class="signal-track"><i></i><span>Close</span><span>Results</span><span>First crossing</span></div><div class="card-actions"><a class="button primary" href="{route('demo', static)}">Open full replay</a><a class="button ghost" href="{route('events', static)}">Find an upcoming event</a></div></section>
<section class="workspace-card quick-setup reveal"><div class="card-heading"><div><span class="overline">LOCAL PREFERENCES</span><h2>Set your guardrails</h2></div><span class="save-state" data-save-state>Saved on this device</span></div><form class="preference-form" data-preferences><label>Risk budget (USDT)<input name="risk" inputmode="decimal" min="1" step="0.01" value="{html.escape(risk or '')}" placeholder="50.00"></label><label>Timezone<input name="timezone" value="{html.escape(timezone_name or 'Africa/Lagos')}" placeholder="Africa/Lagos"></label><button class="button primary" type="submit">Save preferences</button></form></section></div></section>'''
    return layout(title="Control room", page="app", body=body, static=static)


def _render_events_legacy(snapshot: PreviewSnapshot, replay: Any | None, *, static: bool = False) -> str:
    live = "false" if static else "true"
    status = ("The hosted Pages view is read-only. Open the verified replay, or run Reverb locally to search the live earnings calendar."
              if static else "Loading this week's earnings from the configured calendar and Bitget's public Reality market.")
    body = f'''<section class="inner-hero reveal"><span class="eyebrow"><b></b> Event discovery</span><h1>Choose what<br>you want to watch.</h1><p>Search the current earnings week, review the time source, then register your direction and risk budget. A saved decision is not an order.</p></section><section class="event-builder" data-event-builder data-live-events="{live}"><div class="search-panel workspace-card reveal delay-1"><label class="search-box"><span>⌕</span><input type="search" data-event-search placeholder="Search company or ticker" autocomplete="off" aria-label="Search this week's earnings" {"disabled" if static else ""}></label><div class="filter-row"><span class="chip active" data-calendar-badge>{"STATIC PREVIEW" if static else "CURRENT EARNINGS WEEK"}</span><button class="chip" type="button" data-refresh-events {"hidden" if static else ""}>Refresh</button></div><p class="events-status" data-events-status aria-live="polite">{status}</p><div class="events-list" data-events-list></div><div class="empty-search" data-empty-search hidden>No current-week event matches that search.</div></div>
<div class="thesis-panel workspace-card reveal delay-2"><div class="card-heading"><div><span class="overline">THESIS BUILDER</span><h2>Your view, bounded.</h2></div><span class="step-count">LOCAL ONLY</span></div><div class="selected-event-summary" data-selected-event-summary>No event selected. Choose one from the current-week list.</div><form data-thesis-form><fieldset><legend>Direction</legend><div class="segmented"><label><input type="radio" name="direction" value="beat" checked><span>↑ Beats</span></label><label><input type="radio" name="direction" value="miss"><span>↓ Misses</span></label><label><input type="radio" name="direction" value="watch"><span>○ Watch only</span></label></div></fieldset><div class="form-grid"><label>Your expected move (%)<input required name="move" type="number" inputmode="decimal" min="0.1" max="99.9" step="0.1" placeholder="6.0"><small>Saved with your thesis; the spot-only path does not validate it against an options market.</small></label><label>Maximum risk (USDT)<input required name="budget" type="number" inputmode="decimal" min="0.01" step="0.01" placeholder="25.00"></label></div><label>Describe your view <textarea name="view" maxlength="500" placeholder="What would need to be true for your view to be right?"></textarea></label><div class="deterministic-note"><i>◆</i><p><strong>The engine decides; Qwen does not.</strong> Qwen may classify or explain words only. Prices, size, freshness, and risk checks are deterministic.</p></div><button class="button primary wide" type="submit" data-submit-thesis {"disabled" if static else ""}>Review and save thesis <span>→</span></button></form><div class="decision-preview" data-decision-preview hidden><div class="decision-icon" data-decision-icon>✓</div><span data-decision-status>PRE-REGISTERED</span><h3 data-decision-title>Decision saved</h3><p data-decision-copy></p><ul class="decision-arithmetic" data-decision-arithmetic></ul><div class="preview-actions"><button class="button ghost" type="button" data-edit-thesis>Edit thesis</button><a class="button primary" href="{route('app', static)}">Go to waiting room</a></div></div></div></section><section class="public-events-note" data-static-note {"" if static else "hidden"}><strong>Public preview</strong><p>The published Pages build has no server-side account or live API. This screen does not invent upcoming events. Use the verified replay, or run the local app to search and register a live calendar event.</p><a class="button primary" href="{route('demo', static)}">Open verified replay</a></section>'''
    return layout(title="Events", page="events", body=body, static=static)


def render_events(snapshot: PreviewSnapshot, replay: Any | None, *, static: bool = False) -> str:
    live = "false" if static else "true"
    status = ("The hosted Pages view is read-only. Run Reverb locally to search the live calendar and review claim extraction."
              if static else "Loading the current earnings week and Reality-token availability…")
    body = f'''<section class="inner-hero reveal"><span class="eyebrow"><b></b> Event discovery</span><h1>Write your view<br>before the results.</h1><p>Search the earnings week, select an event, and put your thesis in your own words. Qwen proposes claim labels for review; it does not grade them or make a trading decision.</p></section>
<section class="event-builder" data-event-builder data-live-events="{live}">
<div class="search-panel workspace-card reveal delay-1"><label class="search-box"><span>⌕</span><input type="search" data-event-search placeholder="Search company or ticker" autocomplete="off" aria-label="Search this week's earnings" {"disabled" if static else ""}></label><div class="filter-row"><span class="chip active" data-calendar-badge>{"STATIC PREVIEW" if static else "CURRENT EARNINGS WEEK"}</span><button class="chip" type="button" data-refresh-events {"hidden" if static else ""}>Refresh</button></div><p class="events-status" data-events-status aria-live="polite">{status}</p><div class="events-list" data-events-list></div><div class="empty-search" data-empty-search hidden>No current-week event matches that search.</div></div>
<div class="thesis-panel workspace-card reveal delay-2"><div class="card-heading"><div><span class="overline">THESIS BUILDER</span><h2>Make the view testable.</h2></div><span class="step-count">LOCAL ONLY</span></div><div class="selected-event-summary" data-selected-event-summary>No event selected. Choose one from the current-week list.</div>
<form data-thesis-form><fieldset><legend>Your broad view</legend><div class="segmented"><label><input type="radio" name="direction" value="beat" checked><span>↑ Above expectations</span></label><label><input type="radio" name="direction" value="miss"><span>↓ Below expectations</span></label><label><input type="radio" name="direction" value="watch"><span>○ Research only</span></label></div></fieldset><div class="form-grid"><label>Expected market move (%)<input required name="move" type="number" inputmode="decimal" min="0.1" max="99.9" step="0.1" placeholder="3.0"><small>This is your stated view, not a forecast from Reverb.</small></label><label>Maximum risk budget (USDT)<input required name="budget" type="number" inputmode="decimal" min="0.01" step="0.01" placeholder="100.00"></label></div><label>Your thesis in plain language <textarea required name="view" maxlength="2000" placeholder="Example: I think Costco beats on EPS and membership fee growth stays strong, but margins disappoint because of freight costs. I'd put $100 at risk at most."></textarea></label><details class="scoring-notes"><summary>How the Costco example is checked</summary><ul><li>Membership-fee income: compare the reported quarter with the same quarter a year earlier.</li><li>Gross margin: compare the same reported measure year over year.</li><li>Freight: score attribution only if Costco explicitly links it to margin or cost of sales.</li><li>EPS: keep it visible but unscored unless a source, value, timestamp, and matching reported/adjusted basis are frozen first.</li></ul></details><div class="deterministic-note"><i>◆</i><p><strong>Qwen suggests; you confirm; code reconciles.</strong> Extracted claims are a draft until reviewed. This step neither freezes a preregistration nor places an order.</p></div><button class="button primary wide" type="submit" data-submit-thesis {"disabled" if static else ""}>Extract claims for review <span>→</span></button></form>
<div class="decision-preview claim-review" data-decision-preview hidden><div class="decision-icon" data-decision-icon>✎</div><span data-decision-status>CANDIDATE CLAIMS · NOT FROZEN</span><h3 data-decision-title>Review what you meant</h3><p data-decision-copy></p><ul class="claim-review-list" data-claims-review></ul><p class="claim-review-note">Confirm every claim below. If one is wrong or missing, revise your wording and extract again. This saves a local draft only; it does not freeze the thesis or send an order.</p><div class="preview-actions"><button class="button ghost" type="button" data-edit-thesis>Revise thesis</button><button class="button primary" type="button" data-confirm-claims>Confirm claims and save draft</button></div><p class="events-status" data-claim-save-status aria-live="polite"></p></div></div></section>
<section class="public-events-note" data-static-note {"" if static else "hidden"}><strong>Public preview</strong><p>The hosted Pages view has no server-side account or live Qwen key. It does not invent upcoming events. Run Reverb locally to search the calendar and review thesis claims.</p><a class="button primary" href="{route('demo', static)}">Open verified replay</a></section>'''
    return layout(title="Events", page="events", body=body, static=static)


def render_report_page(snapshot: PreviewSnapshot, replay: Any | None, report_html: str | None, *, static: bool = False) -> str:
    costco = costco_report_summary(ROOT)
    if costco is not None:
        r = {key: html.escape(value) for key, value in costco.items()}
        report = render_costco_morning_brief(ROOT) or '<div class="empty-state">No Costco brief is available.</div>'
        body = f'''<section class="inner-hero report-hero reveal"><span class="eyebrow"><b></b> Morning report</span><h1>What survived.<br>What remains unknown.</h1><p>The Costco forward brief keeps the frozen thesis separate from the unrecorded event result. Every populated number must come from the capture ledger.</p><div class="report-meta"><span>{r['symbol']} · {r['token']} · {r['date']}</span><span class="verified-pill">{r['status']}</span></div></section><section class="report-summary reveal delay-1"><article><span>Baseline</span><strong>{r['baseline']}</strong></article><article><span>First crossing</span><strong>{r['observed']}</strong></article><article><span>Observed move</span><strong>{r['move']}</strong></article><article><span>Risk budget</span><strong>{r['budget']}</strong></article></section><section class="report-stage reveal delay-2">{report}</section><section class="report-disclaimer"><strong>Forward evidence, not performance.</strong><p>The Costco event result is still pending. If a required interval or issuer timestamp is missing, the run remains `INCOMPLETE`; no order is submitted.</p><a href="{route('preview', static)}">Inspect source evidence →</a></section>'''
    else:
        r = {k: html.escape(v) for k, v in replay_view(replay, "Africa/Lagos").items()}
        report = report_html or '<div class="empty-state">No checked report is available.</div>'
        body = f'''<section class="inner-hero report-hero reveal"><span class="eyebrow"><b></b> Morning report</span><h1>What happened.<br>What Reverb refused.</h1><p>Action and refusal receive equal space. Every number below regenerates from the verified replay ledger.</p><div class="report-meta"><span>{r['symbol']} · {r['date']}</span><span class="verified-pill">LEDGER VERIFIED</span></div></section><section class="report-summary reveal delay-1"><article><span>Baseline</span><strong>{r['baseline']}</strong></article><article><span>First crossing</span><strong>{r['observed']}</strong></article><article><span>Observed move</span><strong class="negative">{r['move']}</strong></article><article><span>Risk budget</span><strong>{r['budget']}</strong></article></section><section class="report-stage reveal delay-2">{report}</section><section class="report-disclaimer"><strong>Recorded evidence, not performance.</strong><p>This is one historical event replay. It is not a live fill, a backtest, or a profitability claim.</p><a href="{route('preview', static)}">Inspect source evidence →</a></section>'''
    return layout(title="Morning report", page="report", body=body, static=static)


def render_connect(*, static: bool = False) -> str:
    body = f'''<section class="inner-hero reveal"><span class="eyebrow"><b></b> Local connection</span><h1>Your keys stay<br>on your machine.</h1><p>The hosted experience needs no credentials. The local app reads public market data from Bitget; supported order execution uses Agent Hub on your device. Automatic earnings orders are currently disabled.</p></section><section class="permission-boundary reveal delay-1"><div>◆</div><p><strong>Permission boundary</strong>Read and trade only. Reverb never requests withdrawal or transfer permission.</p></section><section class="connect-steps"><article class="workspace-card reveal"><span>01</span><h2>Create or edit the key</h2><p>Open Bitget API Management and use Unified account Trade permission.</p></article><article class="workspace-card reveal delay-1"><span>02</span><h2>Keep dangerous scopes off</h2><p>Leave P2P, Wallet, Withdraw, and Transfer disabled.</p></article><article class="workspace-card reveal delay-2"><span>03</span><h2>Store it locally</h2><p>Put the API key, secret, and passphrase in the ignored <code>.env</code>.</p></article><article class="workspace-card reveal delay-3"><span>04</span><h2>Verify read-only</h2><p>Run <code>./.venv/bin/python scripts/account_check.py</code>. No order is submitted.</p></article></section><div class="connect-cta"><a class="button primary" href="https://github.com/holybunnie/reverb#how-to-run-the-current-build">Open setup guide ↗</a><a class="button ghost" href="{route('app', static)}">Back to workspace</a></div>'''
    return layout(title="Connect locally", page="connect", body=body, static=static)
