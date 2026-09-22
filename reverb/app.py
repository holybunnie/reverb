from __future__ import annotations

import html
from datetime import datetime
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


def _money(value: Any, *, places: int = 2) -> str:
    try:
        amount = Decimal(str(value))
    except (ArithmeticError, InvalidOperation, TypeError, ValueError):
        return "—"
    if not amount.is_finite():
        return "—"
    return f"${amount:,.{places}f}"


def _percent(value: Any) -> str:
    try:
        amount = Decimal(str(value)) * 100
    except (ArithmeticError, InvalidOperation, TypeError, ValueError):
        return "—"
    if not amount.is_finite():
        return "—"
    return f"{amount:+.2f}%"


def _route(path: str, *, static_demo: bool) -> str:
    return f"./{path.strip('/')}/" if static_demo else path


def _replay_view(replay_snapshot: Any | None, timezone_name: str | None) -> dict[str, str]:
    if replay_snapshot is None:
        return {
            "symbol": "WAITING",
            "token": "No verified live event",
            "date": "Calendar unresolved",
            "ny_time": "—",
            "local_time": "—",
            "observed_time": "—",
            "baseline": "—",
            "move": "—",
            "budget": "—",
            "action_notional": "—",
            "refusal_notional": "—",
            "risk_fill": "0",
            "mode": "Live gate blocked",
        }
    arithmetic = replay_snapshot.arithmetic
    event = datetime.fromisoformat(replay_snapshot.event_at)
    local_zone = ZoneInfo(timezone_name) if timezone_name and _timezone_label(timezone_name) == timezone_name else ZoneInfo("UTC")
    ny = event.astimezone(ZoneInfo("America/New_York"))
    local = event.astimezone(local_zone)
    observed_raw = arithmetic.get("observed_at")
    observed = datetime.fromisoformat(observed_raw).astimezone(ZoneInfo("America/New_York")) if observed_raw else None
    try:
        budget = Decimal(str(arithmetic.get("risk_budget")))
        action = Decimal(str(arithmetic.get("action_order_notional")))
        fill = max(Decimal("0"), min(Decimal("100"), action / budget * 100)) if budget > 0 else Decimal("0")
    except (ArithmeticError, InvalidOperation, TypeError, ValueError):
        fill = Decimal("0")
    return {
        "symbol": str(replay_snapshot.symbol),
        "token": str(replay_snapshot.token_symbol),
        "date": ny.strftime("%d %b %Y").upper(),
        "ny_time": ny.strftime("%H:%M ET"),
        "local_time": local.strftime("%H:%M %Z"),
        "observed_time": observed.strftime("%H:%M ET") if observed else "—",
        "baseline": _money(arithmetic.get("baseline")),
        "move": _percent(arithmetic.get("move_pct")),
        "budget": _money(arithmetic.get("risk_budget")),
        "action_notional": _money(arithmetic.get("action_order_notional"), places=3),
        "refusal_notional": _money(arithmetic.get("refusal_order_notional")),
        "risk_fill": f"{fill:.1f}",
        "mode": "Verified historical replay",
    }


def render_app_html(
    snapshot: PreviewSnapshot,
    *,
    risk_budget: str | None = None,
    timezone_name: str | None = None,
    morning_report_html: str | None = None,
    replay_snapshot: Any | None = None,
    static_demo: bool = False,
) -> str:
    risk = html.escape(_risk_label(risk_budget))
    timezone_display = html.escape(_timezone_label(timezone_name))
    replay = {key: html.escape(value) for key, value in _replay_view(replay_snapshot, timezone_name).items()}
    home_href = "./" if static_demo else "/app"
    demo_href = html.escape(_route("/demo", static_demo=static_demo))
    preview_href = html.escape(_route("/preview", static_demo=static_demo))
    connect_href = "https://github.com/holybunnie/reverb#connect-bitget-locally" if static_demo else "/connect"
    settings = "" if static_demo else f"""
    <form method="get" action="/app" class="settings-panel" id="settings">
      <label><span>Risk budget</span><input name="risk" inputmode="decimal" placeholder="50" value="{html.escape(risk_budget or '')}"></label>
      <label><span>Timezone</span><input name="timezone" placeholder="Africa/Lagos" value="{html.escape(timezone_name or '')}"></label>
      <button type="submit">Update dashboard</button>
    </form>
    <section class="language-panel" aria-labelledby="language-title">
      <div><div class="label">Optional Qwen layer</div><h3 id="language-title">Say the view naturally.</h3><p>Qwen classifies direction only. It cannot choose a contract, size, price, or trade.</p></div>
      <form id="thesis-form"><label><span>Your earnings view</span><input id="thesis-view" maxlength="500" placeholder="I expect NVIDIA to report stronger results"></label><button type="submit">Classify view</button></form>
      <p class="small" id="thesis-result" role="status">Runs locally when <code>BITGET_QWEN_API_KEY</code> is configured.</p>
    </section>
    <script>
    (() => {{
      const form = document.getElementById('thesis-form');
      const result = document.getElementById('thesis-result');
      form.addEventListener('submit', async (event) => {{
        event.preventDefault();
        result.textContent = 'Classifying direction…';
        try {{
          const response = await fetch('/api/language/view', {{method:'POST', headers:{{'Content-Type':'application/json'}}, body:JSON.stringify({{view:document.getElementById('thesis-view').value}})}});
          const payload = await response.json();
          if (!response.ok) throw new Error(payload.message || 'Language layer unavailable');
          result.textContent = `Direction: ${{payload.view.replace('_', ' ')}}. No trade decision was made.`;
        }} catch (error) {{ result.textContent = error.message; }}
      }});
    }})();
    </script>"""
    report = morning_report_html or '<div class="empty-report"><span>○</span><p>No registered decision exists for this account yet.</p></div>'
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#090b0d"><meta name="color-scheme" content="dark">
<title>Reverb — earnings control room</title>
<style>
@property --ring {{ syntax:"<percentage>"; inherits:false; initial-value:0%; }}
:root {{ --ink:#090b0d; --ink-2:#101418; --panel:rgba(20,25,29,.82); --panel-strong:#171c20; --line:rgba(255,255,255,.09); --text:#f4f6f2; --muted:#8f9a98; --acid:#c8ff5a; --cyan:#67e7d1; --amber:#ffc767; --rose:#ff7d84; --shadow:0 28px 80px rgba(0,0,0,.34); color-scheme:dark; }}
* {{ box-sizing:border-box; }} html {{ scroll-behavior:smooth; }} body {{ margin:0; min-height:100vh; overflow-x:hidden; background:var(--ink); color:var(--text); font:15px/1.55 Inter,ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
body::before {{ content:""; position:fixed; inset:-25%; z-index:-2; background:radial-gradient(circle at 18% 16%,rgba(103,231,209,.12),transparent 23%),radial-gradient(circle at 82% 18%,rgba(200,255,90,.08),transparent 22%),radial-gradient(circle at 60% 92%,rgba(255,125,132,.06),transparent 24%); animation:ambient 18s ease-in-out infinite alternate; }}
body::after {{ content:""; position:fixed; inset:0; z-index:-1; pointer-events:none; opacity:.23; background-image:linear-gradient(rgba(255,255,255,.025) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.025) 1px,transparent 1px); background-size:44px 44px; mask-image:linear-gradient(to bottom,black,transparent 78%); }}
a {{ color:inherit; text-decoration:none; }} .shell {{ width:min(1180px,calc(100% - 36px)); margin:auto; padding:18px 0 64px; }}
.topbar {{ position:sticky; top:14px; z-index:20; display:flex; align-items:center; justify-content:space-between; gap:20px; min-height:58px; padding:10px 12px 10px 18px; border:1px solid var(--line); border-radius:18px; background:rgba(10,13,15,.76); box-shadow:0 12px 40px rgba(0,0,0,.22); backdrop-filter:blur(22px); }}
.brand {{ display:flex; align-items:center; gap:10px; font-size:18px; font-weight:780; letter-spacing:-.04em; }} .brand-mark {{ width:19px; height:19px; position:relative; border:1px solid rgba(200,255,90,.5); border-radius:50%; }} .brand-mark::before,.brand-mark::after {{ content:""; position:absolute; inset:4px; border-radius:50%; background:var(--acid); box-shadow:0 0 18px rgba(200,255,90,.7); }} .brand-mark::after {{ inset:-1px; background:transparent; border:1px solid var(--acid); animation:ping 2.6s ease-out infinite; }}
.nav {{ display:flex; align-items:center; gap:6px; }} .nav a {{ color:var(--muted); padding:8px 11px; border-radius:10px; transition:.25s ease; }} .nav a:hover,.nav a:focus-visible {{ color:var(--text); background:rgba(255,255,255,.06); }} .mode-pill {{ display:inline-flex; align-items:center; gap:7px; margin-left:5px; padding:8px 11px; border:1px solid rgba(200,255,90,.18); border-radius:999px; color:var(--acid); background:rgba(200,255,90,.06); font-size:12px; font-weight:700; }} .mode-pill i {{ width:6px; height:6px; border-radius:50%; background:var(--acid); box-shadow:0 0 12px var(--acid); animation:pulse 2s ease-in-out infinite; }}
.hero {{ display:grid; grid-template-columns:minmax(0,1.45fr) minmax(300px,.55fr); gap:32px; align-items:end; padding:82px 6px 34px; }} .kicker {{ display:flex; align-items:center; gap:10px; color:var(--cyan); font-size:11px; font-weight:760; letter-spacing:.14em; text-transform:uppercase; }} .kicker::before {{ content:""; width:28px; height:1px; background:currentColor; }} h1 {{ max-width:830px; margin:17px 0 18px; font-size:clamp(49px,7.4vw,92px); line-height:.91; letter-spacing:-.07em; font-weight:760; }} h1 em {{ color:var(--muted); font-style:normal; }} .lede {{ max-width:680px; margin:0; color:#aeb7b4; font-size:clamp(17px,2vw,20px); }}
.hero-actions {{ display:flex; flex-wrap:wrap; gap:10px; margin-top:28px; }} .button {{ display:inline-flex; align-items:center; justify-content:center; gap:9px; min-height:45px; padding:0 16px; border:1px solid var(--line); border-radius:12px; background:rgba(255,255,255,.035); font-weight:700; transition:transform .25s ease,border-color .25s ease,background .25s ease; }} .button.primary {{ border-color:transparent; background:var(--acid); color:#11150c; }} .button:hover {{ transform:translateY(-2px); border-color:rgba(255,255,255,.22); }} .hero-note {{ align-self:end; padding:17px 0 3px 22px; border-left:1px solid var(--line); color:var(--muted); font-size:13px; }} .hero-note strong {{ display:block; color:var(--text); margin-bottom:5px; font-size:14px; }}
.dashboard {{ display:grid; grid-template-columns:1.55fr .75fr; gap:14px; }} .card {{ position:relative; overflow:hidden; border:1px solid var(--line); border-radius:22px; background:linear-gradient(145deg,rgba(25,31,35,.94),rgba(14,18,21,.88)); box-shadow:var(--shadow); }} .card::after {{ content:""; position:absolute; inset:0; pointer-events:none; background:linear-gradient(110deg,transparent 35%,rgba(255,255,255,.035) 50%,transparent 65%); transform:translateX(-120%); transition:transform .8s ease; }} .card:hover::after {{ transform:translateX(120%); }}
.event-card {{ min-height:390px; padding:26px; }} .card-top {{ display:flex; align-items:flex-start; justify-content:space-between; gap:18px; }} .label {{ color:var(--muted); font-size:11px; font-weight:720; letter-spacing:.12em; text-transform:uppercase; }} .recorded {{ display:inline-flex; align-items:center; gap:7px; padding:6px 9px; border-radius:999px; background:rgba(103,231,209,.08); color:var(--cyan); font-size:11px; font-weight:720; }} .ticker {{ margin-top:30px; font-size:clamp(60px,10vw,112px); line-height:.8; letter-spacing:-.075em; font-weight:790; }} .token {{ margin-top:13px; color:var(--muted); }}
.move {{ color:var(--rose); font-size:30px; letter-spacing:-.04em; font-weight:740; text-align:right; }} .move small {{ display:block; margin-top:2px; color:var(--muted); font-size:11px; letter-spacing:.08em; text-transform:uppercase; }}
.timeline {{ position:absolute; left:26px; right:26px; bottom:25px; display:grid; grid-template-columns:repeat(3,1fr); gap:0; padding-top:22px; }} .timeline::before {{ content:""; position:absolute; left:8px; right:8px; top:7px; height:1px; background:linear-gradient(90deg,var(--muted),var(--cyan),var(--acid)); opacity:.45; }} .timeline::after {{ content:""; position:absolute; top:4px; left:0; width:7px; height:7px; border-radius:50%; background:var(--acid); box-shadow:0 0 16px var(--acid); animation:travel 5s ease-in-out infinite; }} .moment {{ position:relative; color:var(--muted); font-size:12px; }} .moment::before {{ content:""; position:absolute; top:-19px; left:0; width:5px; height:5px; border-radius:50%; background:#697370; }} .moment:nth-child(2) {{ text-align:center; }} .moment:nth-child(2)::before {{ left:50%; }} .moment:last-child {{ text-align:right; }} .moment:last-child::before {{ left:auto; right:0; background:var(--acid); box-shadow:0 0 12px rgba(200,255,90,.65); }} .moment strong {{ display:block; color:var(--text); font-size:13px; }}
.side-stack {{ display:grid; grid-template-rows:1fr 1fr; gap:14px; }} .risk-card,.system-card {{ padding:22px; min-height:188px; }} .risk-layout {{ display:flex; align-items:center; justify-content:space-between; gap:16px; margin-top:17px; }} .ring {{ --ring:calc({replay['risk_fill']} * 1%); width:104px; aspect-ratio:1; flex:0 0 auto; display:grid; place-items:center; border-radius:50%; background:conic-gradient(var(--acid) var(--ring),rgba(255,255,255,.075) 0); animation:ring-in 1.2s .45s both ease-out; }} .ring::before {{ content:""; width:78px; aspect-ratio:1; border-radius:50%; background:var(--panel-strong); box-shadow:inset 0 0 0 1px var(--line); }} .ring-copy {{ position:absolute; text-align:center; font-size:11px; color:var(--muted); }} .ring-copy strong {{ display:block; color:var(--text); font-size:19px; }} .risk-copy strong {{ display:block; font-size:26px; letter-spacing:-.04em; }} .risk-copy span {{ color:var(--muted); font-size:12px; }}
.system-row {{ display:flex; align-items:center; justify-content:space-between; gap:16px; padding:11px 0; border-bottom:1px solid var(--line); }} .system-row:last-child {{ border-bottom:0; padding-bottom:0; }} .system-row span {{ color:var(--muted); font-size:12px; }} .system-row strong {{ font-size:12px; }} .blocked {{ color:var(--amber); }} .verified {{ color:var(--cyan); }}
.section {{ margin-top:58px; }} .section-head {{ display:flex; align-items:end; justify-content:space-between; gap:20px; margin-bottom:17px; }} .section-head h2 {{ margin:5px 0 0; font-size:clamp(29px,4vw,45px); line-height:1; letter-spacing:-.05em; }} .section-head p {{ max-width:430px; margin:0; color:var(--muted); font-size:13px; }}
.report-grid {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:14px; }} .decision {{ min-height:250px; padding:22px; border:1px solid var(--line); border-radius:22px; background:var(--panel); box-shadow:var(--shadow); }} .decision-head {{ display:flex; justify-content:space-between; gap:14px; align-items:center; }} .decision-head strong {{ padding:5px 9px; border-radius:999px; font-size:10px; letter-spacing:.1em; }} .decision-head span {{ color:var(--muted); font-size:12px; }} .action {{ border-top:2px solid var(--cyan); }} .refusal {{ border-top:2px solid var(--rose); }} .action .decision-head strong {{ color:var(--cyan); background:rgba(103,231,209,.09); }} .refusal .decision-head strong {{ color:var(--rose); background:rgba(255,125,132,.09); }} .decision p {{ color:var(--muted); }} .decision p b {{ color:var(--text); }} .decision ul {{ padding:13px 0 0; margin:13px 0 0; list-style:none; border-top:1px solid var(--line); }} .decision li {{ display:flex; justify-content:space-between; gap:20px; padding:7px 0; color:var(--text); font-size:12px; }} .decision li span {{ color:var(--muted); }} .report-note {{ grid-column:1/-1; margin:0 2px; }}
.readiness {{ display:grid; grid-template-columns:1fr 1fr; gap:14px; }} .readiness-card {{ padding:24px; }} .readiness-card h3 {{ margin:13px 0 7px; font-size:22px; letter-spacing:-.03em; }} .readiness-card p {{ margin:0; color:var(--muted); }} .metric {{ display:flex; justify-content:space-between; gap:16px; margin-top:22px; padding-top:15px; border-top:1px solid var(--line); }} .metric strong {{ font-size:28px; letter-spacing:-.04em; }} .metric span {{ max-width:150px; color:var(--muted); font-size:11px; text-align:right; }}
.settings-panel {{ display:grid; grid-template-columns:1fr 1fr auto; gap:10px; margin-top:14px; padding:16px; border:1px solid var(--line); border-radius:18px; background:rgba(255,255,255,.025); }} .settings-panel label span {{ display:block; margin-bottom:5px; color:var(--muted); font-size:11px; }} input,button {{ min-height:42px; border:1px solid var(--line); border-radius:10px; color:var(--text); background:var(--ink-2); font:inherit; }} input {{ width:100%; padding:0 11px; }} button {{ align-self:end; padding:0 15px; border-color:transparent; background:var(--acid); color:#11150c; font-weight:760; cursor:pointer; }}
.language-panel {{ display:grid; grid-template-columns:1fr 1.2fr; gap:22px; margin-top:14px; padding:22px; border:1px solid var(--line); border-radius:18px; background:rgba(103,231,209,.035); }} .language-panel h3 {{ margin:6px 0; font-size:22px; }} .language-panel p {{ margin:0; color:var(--muted); }} .language-panel form {{ display:grid; grid-template-columns:1fr auto; gap:10px; align-items:end; }} .language-panel label span {{ display:block; margin-bottom:5px; color:var(--muted); font-size:11px; }} .language-panel > .small {{ grid-column:2; }}
.empty-report {{ grid-column:1/-1; min-height:180px; display:grid; place-items:center; align-content:center; color:var(--muted); border:1px dashed var(--line); border-radius:20px; text-align:center; }} .empty-report span {{ font-size:30px; color:var(--amber); }}
.small {{ font-size:12px; color:var(--muted); }} footer {{ display:flex; justify-content:space-between; gap:18px; margin-top:64px; padding:22px 2px 0; border-top:1px solid var(--line); color:var(--muted); font-size:11px; }} code {{ color:var(--cyan); }}
.reveal {{ opacity:0; transform:translateY(18px); animation:enter .7s cubic-bezier(.22,1,.36,1) forwards; }} .delay-1 {{ animation-delay:.08s; }} .delay-2 {{ animation-delay:.16s; }} .delay-3 {{ animation-delay:.24s; }}
@keyframes enter {{ to {{ opacity:1; transform:none; }} }} @keyframes ambient {{ to {{ transform:translate3d(3%,-2%,0) scale(1.04); }} }} @keyframes ping {{ 0% {{ transform:scale(.7); opacity:.9; }} 75%,100% {{ transform:scale(1.8); opacity:0; }} }} @keyframes pulse {{ 50% {{ opacity:.42; transform:scale(.78); }} }} @keyframes travel {{ 0%,15% {{ left:0; opacity:0; }} 25% {{ opacity:1; }} 75% {{ opacity:1; }} 85%,100% {{ left:calc(100% - 7px); opacity:0; }} }} @keyframes ring-in {{ from {{ --ring:0%; }} }}
@media(max-width:850px) {{ .hero {{ grid-template-columns:1fr; padding-top:60px; }} .hero-note {{ display:none; }} .dashboard {{ grid-template-columns:1fr; }} .side-stack {{ grid-template-columns:1fr 1fr; grid-template-rows:auto; }} .event-card {{ min-height:370px; }} }}
@media(max-width:620px) {{ .shell {{ width:min(100% - 22px,1180px); }} .topbar {{ top:8px; }} .nav a {{ display:none; }} .hero {{ padding:48px 3px 26px; }} h1 {{ font-size:52px; }} .side-stack,.report-grid,.readiness,.language-panel {{ grid-template-columns:1fr; }} .language-panel form {{ grid-template-columns:1fr; }} .language-panel > .small {{ grid-column:1; }} .card-top {{ gap:9px; }} .ticker {{ font-size:76px; }} .event-card {{ min-height:390px; padding:20px; }} .timeline {{ left:20px; right:20px; }} .section {{ margin-top:46px; }} .section-head {{ display:block; }} .section-head p {{ margin-top:10px; }} .settings-panel {{ grid-template-columns:1fr; }} footer {{ display:block; }} footer span {{ display:block; margin-top:7px; }} }}
@media(prefers-reduced-motion:reduce) {{ *,*::before,*::after {{ animation-duration:.001ms!important; animation-iteration-count:1!important; scroll-behavior:auto!important; transition-duration:.001ms!important; }} }}
</style></head><body><div class="shell">
<header class="topbar reveal"><a class="brand" href="{home_href}"><span class="brand-mark" aria-hidden="true"></span>reverb</a><nav class="nav" aria-label="Primary"><a href="{demo_href}">Replay</a><a href="{preview_href}">Evidence</a><a href="{html.escape(connect_href)}">Connect</a><span class="mode-pill"><i aria-hidden="true"></i>paper replay</span></nav></header>
<main>
<section class="hero reveal delay-1"><div><div class="kicker">Earnings control room</div><h1>The market closed. <em>Reverb stayed awake.</em></h1><p class="lede">A risk-capped agent for the moment earnings land—built to act, hold, or refuse, then show its work in the morning.</p><div class="hero-actions"><a class="button primary" href="{demo_href}">Open verified replay <span>↗</span></a><a class="button" href="{preview_href}">Inspect evidence</a></div></div><aside class="hero-note"><strong>No account required</strong>The public surface is a recorded replay. It cannot place an order and never asks for credentials.</aside></section>
<section class="dashboard reveal delay-2" aria-label="Recorded earnings dashboard">
  <article class="card event-card"><div class="card-top"><div><div class="label">Recorded earnings window</div><div class="ticker">{replay['symbol']}</div><div class="token">{replay['token']} · {replay['date']} · {replay['local_time']} local</div></div><div><div class="recorded">● {replay['mode']}</div><div class="move">{replay['move']}<small>from {replay['baseline']} baseline</small></div></div></div><div class="timeline"><div class="moment"><strong>16:00 ET</strong>Market close</div><div class="moment"><strong>{replay['ny_time']}</strong>Results released</div><div class="moment"><strong>{replay['observed_time']}</strong>Signal recorded</div></div></article>
  <div class="side-stack"><article class="card risk-card"><div class="label">Budget discipline</div><div class="risk-layout"><div class="ring"><div class="ring-copy"><strong>{replay['risk_fill']}%</strong>used</div></div><div class="risk-copy"><span>Maximum loss</span><strong>{replay['budget']}</strong><span>{replay['action_notional']} paper intent</span></div></div></article><article class="card system-card"><div class="label">System state</div><div class="system-row"><span>Feasibility gate</span><strong class="blocked">{html.escape(snapshot.gate_status)}</strong></div><div class="system-row"><span>Replay ledger</span><strong class="verified">VERIFIED</strong></div><div class="system-row"><span>Orders submitted</span><strong>NONE</strong></div></article></div>
</section>
{settings}
<section class="section reveal delay-3"><div class="section-head"><div><div class="kicker">Morning report</div><h2>Action and refusal,<br>side by side.</h2></div><p>A refusal gets the same visual weight as an action. That is the product’s credibility, not an edge case.</p></div><div class="report-grid">{report}</div></section>
<section class="section readiness"><article class="card readiness-card"><div class="label">Live readiness</div><h3>No event is being invented</h3><p>The live calendar, account eligibility, and executable options intersection remain gated. Reverb waits instead of filling the dashboard with synthetic data.</p><div class="metric"><strong>{snapshot.online_reality}</strong><span>online Reality instruments observed; not proof of a tradeable options match</span></div></article><article class="card readiness-card"><div class="label">User guardrail</div><h3>{risk}</h3><p>Your cap remains visible before any future live decision. Current dashboard timezone: {timezone_display}.</p><div class="metric"><strong>{replay['refusal_notional']}</strong><span>oversized replay intent refused against a {replay['budget']} budget</span></div></article></section>
</main>
<footer><div>Reverb · earnings decisions with receipts</div><span>Capture <code>{html.escape(snapshot.run_id)}</code> · ledger <code>{html.escape(snapshot.ledger_head[:12])}…</code></span></footer>
</div></body></html>"""


def render_connection_html() -> str:
    return """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark"><title>Reverb — connect locally</title>
<style>
:root { color-scheme:dark; --bg:#090b0d; --panel:#151a1e; --line:rgba(255,255,255,.1); --text:#f4f6f2; --muted:#95a09d; --acid:#c8ff5a; --cyan:#67e7d1; --amber:#ffc767; }
* { box-sizing:border-box; } body { margin:0; min-height:100vh; background:radial-gradient(circle at 20% 0,rgba(103,231,209,.11),transparent 28%),var(--bg); color:var(--text); font:15px/1.55 Inter,ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; } main { width:min(760px,calc(100% - 30px)); margin:auto; padding:24px 0 70px; }
a { color:inherit; } .brand { display:flex; align-items:center; gap:9px; font-size:19px; font-weight:800; letter-spacing:-.04em; text-decoration:none; } .dot { width:12px; height:12px; border-radius:50%; background:var(--acid); box-shadow:0 0 18px rgba(200,255,90,.7); } .eyebrow { margin-top:70px; color:var(--cyan); font-size:11px; font-weight:750; letter-spacing:.14em; text-transform:uppercase; } h1 { max-width:660px; margin:13px 0 17px; font-size:clamp(44px,8vw,72px); line-height:.93; letter-spacing:-.065em; } .lede { max-width:630px; color:var(--muted); font-size:18px; }
.boundary { margin:28px 0 14px; padding:16px 18px; border:1px solid rgba(255,199,103,.2); border-radius:16px; color:#ebd8af; background:rgba(255,199,103,.06); } .stack { display:grid; gap:11px; } .card { display:grid; grid-template-columns:36px 1fr; gap:15px; padding:19px; border:1px solid var(--line); border-radius:18px; background:rgba(21,26,30,.86); } .num { width:32px; height:32px; display:grid; place-items:center; border:1px solid rgba(200,255,90,.32); border-radius:50%; color:var(--acid); font-weight:750; } h2 { margin:2px 0 6px; font-size:19px; } p { margin:0; color:var(--muted); } code { color:var(--cyan); } .small { margin-top:24px; color:var(--muted); font-size:12px; } .small a { color:var(--cyan); }
@media(prefers-reduced-motion:no-preference) { .card { opacity:0; transform:translateY(10px); animation:in .55s ease forwards; } .card:nth-child(2) { animation-delay:.07s; } .card:nth-child(3) { animation-delay:.14s; } .card:nth-child(4) { animation-delay:.21s; } @keyframes in { to { opacity:1; transform:none; } } }
</style></head><body><main>
<a class="brand" href="/app"><span class="dot"></span>reverb</a><div class="eyebrow">Local connection</div><h1>Your keys never touch the hosted app.</h1><p class="lede">The public demo needs no account. Live account access runs on your machine and sends authenticated requests directly to Bitget.</p>
<div class="boundary"><strong>Permission boundary:</strong> Reverb may read the account and place trades. It never requests withdrawal or transfer permission.</div>
<section class="stack">
<div class="card"><div class="num">1</div><div><h2>Open API Management</h2><p>On Bitget, open Personal Center → API Management and edit the existing key or create one. Keep its secret and passphrase off-screen.</p></div></div>
<div class="card"><div class="num">2</div><div><h2>Select Unified account</h2><p>Choose the Unified account permission. If Bitget exposes a read/write choice, trading needs read and write. There is no separate Stock+ checkbox on this API-key screen. Leave P2P, Wallet, Withdraw, and Transfer off.</p></div></div>
<div class="card"><div class="num">3</div><div><h2>Store it locally</h2><p>Put the API key, secret, and passphrase in the ignored local <code>.env</code>. Never paste them into the hosted page, chat, ticket, or screenshot.</p></div></div>
<div class="card"><div class="num">4</div><div><h2>Verify without trading</h2><p>Run <code>./.venv/bin/python scripts/account_check.py</code>. It performs read-only checks and submits no order.</p></div></div>
</section><p class="small"><a href="/app">← Back to dashboard</a> · A failed protected route does not prove which account or product entitlement is missing.</p>
</main></body></html>"""
