from __future__ import annotations

import html
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .preview import PreviewSnapshot


def _risk_label(value: str | None) -> str:
    if not value:
        return "Set your risk budget"
    try:
        amount = Decimal(value)
    except InvalidOperation:
        return "Risk budget unavailable"
    if not amount.is_finite() or amount <= 0:
        return "Risk budget unavailable"
    return f"${amount:,.2f} maximum loss"


def _timezone_label(value: str | None) -> str:
    if not value:
        return "Choose your timezone"
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        return "Timezone unavailable"
    return value


def render_app_html(snapshot: PreviewSnapshot, *, risk_budget: str | None = None,
                    timezone_name: str | None = None) -> str:
    risk = html.escape(_risk_label(risk_budget))
    timezone_display = html.escape(_timezone_label(timezone_name))
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Reverb — earnings watch</title>
<style>
:root {{ color-scheme:dark; --bg:#0b1016; --panel:#151d26; --line:#2a3947; --text:#f3f7f8; --muted:#9cadb9; --mint:#75e6d4; --gold:#f2c66f; --red:#ff928d; }}
* {{ box-sizing:border-box; }} body {{ margin:0; background:var(--bg); color:var(--text); font:16px/1.5 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }} main {{ max-width:620px; margin:auto; padding:22px 16px 54px; }}
header {{ display:flex; justify-content:space-between; align-items:center; gap:16px; margin-bottom:30px; }} .brand {{ font-weight:800; letter-spacing:-.04em; font-size:24px; }} .cap {{ color:var(--gold); font-size:12px; text-align:right; }}
.eyebrow {{ color:var(--mint); font-size:12px; font-weight:700; letter-spacing:.12em; text-transform:uppercase; }} h1 {{ font-size:42px; line-height:1; letter-spacing:-.055em; margin:12px 0 14px; }} h2 {{ font-size:22px; margin:0 0 8px; }} p {{ color:var(--muted); margin:0 0 16px; }}
.stack {{ display:grid; gap:12px; }} .card {{ background:var(--panel); border:1px solid var(--line); border-radius:18px; padding:18px; }} .step {{ display:flex; gap:14px; }} .num {{ min-width:28px; height:28px; border:1px solid var(--mint); color:var(--mint); border-radius:50%; display:grid; place-items:center; font-weight:700; }} .status {{ display:inline-flex; border-radius:999px; padding:3px 10px; font-size:12px; font-weight:700; background:#3b2d17; color:var(--gold); }}
.risk {{ color:var(--gold); font-weight:700; }} .muted {{ color:var(--muted); font-size:14px; }} .divider {{ height:1px; background:var(--line); margin:25px 0; }} .small {{ font-size:13px; color:var(--muted); }} a {{ color:var(--mint); }} code {{ color:var(--mint); }}
</style></head><body><main>
<header><div class="brand">Reverb</div><div class="cap">{risk}<br>{timezone_display}</div></header>
<div class="eyebrow">Your earnings watch</div>
<h1>Go to bed. Wake up to the reasoning.</h1>
<p>Reverb watches the company event, uses a defined budget, and records what it did. It will show you a refusal just as clearly as an action.</p>
<section class="stack">
<div class="card"><div class="step"><div class="num">1</div><div><h2>Connect your account</h2><p>Keys stay on your device. Reverb only needs permission to read and place trades. It never asks to withdraw or transfer money.</p><a class="status" href="/connect">See the local connection steps</a></div></div></div>
<div class="card"><div class="step"><div class="num">2</div><div><h2>Set the amount</h2><p>How much are you willing to lose on one earnings bet? The cap stays visible on every screen.</p><div class="risk">{risk}</div></div></div></div>
<div class="card"><div class="step"><div class="num">3</div><div><h2>Choose your timezone</h2><p>Your event time is shown beside New York time, so nobody has to do the midnight math.</p><div class="muted">{timezone_display}</div></div></div></div>
</section>
<div class="divider"></div>
<section><div class="eyebrow">This week</div><h2>No event is being invented</h2><p>The current public evidence capture contains no validated earnings calendar or account-specific options intersection. Reverb is waiting instead of showing a made-up company.</p><div class="card"><span class="status">Gate {html.escape(snapshot.gate_status)}</span><p class="small">{snapshot.online_reality} online Reality instruments were observed in the capture. That does not prove 24/7 eligibility or an options match.</p></div></section>
<div class="divider"></div>
<section><div class="eyebrow">Morning report</div><h2>Nothing to hide</h2><p>There is no recorded trade or refusal for this account yet. Once an event is authorized, the report will show the pre-registration, outcome, and the arithmetic behind any refusal.</p><p class="small">This page is driven by the same structured decisions used by the MCP tools. It does not expose raw market data.</p></section>
<footer class="small">Capture {html.escape(snapshot.run_id)} · <a href="/preview">view the evidence</a></footer>
</main></body></html>"""


def render_connection_html() -> str:
    return """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Reverb — connect locally</title>
<style>
:root { color-scheme:dark; --bg:#0b1016; --panel:#151d26; --line:#2a3947; --text:#f3f7f8; --muted:#9cadb9; --mint:#75e6d4; --gold:#f2c66f; --red:#ff928d; }
* { box-sizing:border-box; } body { margin:0; background:var(--bg); color:var(--text); font:16px/1.5 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; } main { max-width:680px; margin:auto; padding:22px 16px 54px; }
a { color:var(--mint); } .brand { font-weight:800; letter-spacing:-.04em; font-size:24px; margin-bottom:34px; } .eyebrow { color:var(--mint); font-size:12px; font-weight:700; letter-spacing:.12em; text-transform:uppercase; } h1 { font-size:42px; line-height:1; letter-spacing:-.055em; margin:12px 0 14px; } h2 { font-size:21px; margin:0 0 8px; } p { color:var(--muted); margin:0 0 12px; } .stack { display:grid; gap:12px; margin-top:26px; } .card { background:var(--panel); border:1px solid var(--line); border-radius:18px; padding:18px; } .step { display:flex; gap:14px; } .num { min-width:28px; height:28px; border:1px solid var(--mint); color:var(--mint); border-radius:50%; display:grid; place-items:center; font-weight:700; } .warning { border-left:3px solid var(--gold); padding:12px 14px; background:#211c13; color:#e9d9af; margin-top:20px; } code { color:var(--mint); } .small { color:var(--muted); font-size:13px; margin-top:24px; }
</style></head><body><main>
<div class="brand">Reverb</div>
<div class="eyebrow">Before you connect</div>
<h1>Your keys stay on your machine.</h1>
<p>The hosted surface never asks for a key. The real connection runs locally, so your credentials go directly to Bitget and nowhere else.</p>
<div class="warning"><strong>Permission boundary:</strong> Reverb may read your account and place trades. It never requests withdrawal or transfer permission.</div>
<section class="stack">
<div class="card"><div class="step"><div class="num">1</div><div><h2>Open Bitget API Management</h2><p>On Bitget, open Personal Center → API Management → Create New API. Use a passphrase you can keep safe; Bitget shows the secret once.</p></div></div></div>
<div class="card"><div class="step"><div class="num">2</div><div><h2>Choose only the required scopes</h2><p>Select Unified account trade, read and write, and Unified account management, read-only. Leave Withdraw and Transfer unchecked.</p></div></div></div>
<div class="card"><div class="step"><div class="num">3</div><div><h2>Store the values locally</h2><p>Put the API key, secret, and passphrase in your ignored local <code>.env</code> file. Never paste them into this page, a chat, a ticket, or a screenshot.</p></div></div></div>
<div class="card"><div class="step"><div class="num">4</div><div><h2>Verify without placing an order</h2><p>Run <code>./.venv/bin/python scripts/account_check.py</code>. Reverb checks read access, trade permission, management access, and account settings. It does not submit an order. Live order submission, when enabled, goes through your local Agent Hub command.</p></div></div></div>
</section>
<p class="small"><a href="/app">Back to the earnings watch</a> · If the check fails, fix the key or IP binding locally; do not send the secret to Reverb.</p>
</main></body></html>"""
