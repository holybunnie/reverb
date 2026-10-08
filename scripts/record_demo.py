"""Record Reverb's under-three-minute demo: what it is, who it is for, and what it has shown.

One headless Chromium session films four surfaces: evidence-built title scenes
(rendered from committed files into a local page), the deployed landing page,
the live local thesis desk (a real calendar call and a real Qwen extraction),
and the deployed Applied Digital walkthrough. Every narration line is
synthesised first with Piper and each beat is held until its line ends. Spoken
numbers are checked against the evidence before anything is recorded, and the
live Qwen beat picks between pre-synthesised lines based on what Qwen actually
returned and how long it took, so the voice never describes a result the
screen does not show. The recording is refused if it would run past 3:00.

The published cut (8 Oct) was edited after recording: the voice moved 1.25 s
earlier, because on the loaded VPS the browser video started later than the
recorder's clock (measured from caption onsets, which then varied by ±0.35 s),
and three silent black or loading stretches were shortened (1.6 s, 8.9 s, 1.6 s).
No spoken line was cut.

    python scripts/record_demo.py --voice en_US-ryan-high.onnx [--desk http://127.0.0.1:8791]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from reverb.runs_page import runs_data  # noqa: E402
from reverb.walkthrough import walkthrough_data as costco_data  # noqa: E402
from reverb.walkthrough_apld import walkthrough_data as apld_data  # noqa: E402

SITE = "https://holybunnie.github.io/reverb/"
NAME = "reverb-demo"
LIMIT_SECONDS = 180.0
TAIL = 0.45
DELTA_VIEW = ("I think Delta grows total revenue year over year on premium cabins, "
              "but fuel costs push operating margin below last year. I'd put $100 at risk at most.")


def _load(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def film_data() -> dict:
    """Everything the title scenes show, read from committed evidence and checked here."""
    apld = apld_data()
    m, v = apld["market"], {x["id"]: x for x in apld["verdicts"]}
    capture = {"COST": _load("evidence/costco/capture_summary.json"),
               "STZ": _load("evidence/events/stz-q2-fy27/capture_summary.json"),
               "APLD": _load("evidence/events/apld-q1-fy27/capture_summary.json")}
    recon = {"COST": _load("evidence/costco/post_event/reconciliation.json"),
             "STZ": _load("evidence/events/stz-q2-fy27/post_event/reconciliation.json"),
             "APLD": _load("evidence/events/apld-q1-fy27/post_event/reconciliation.json")}
    names = {"COST": "Costco Q4 FY26", "STZ": "Constellation Q2 FY27", "APLD": "Applied Digital Q1 FY27"}
    runs = []
    for ticker in ("COST", "STZ", "APLD"):
        c, r = capture[ticker], recon[ticker]["reconciliation"]
        move = max((c["reaction"]["max_pct"], c["reaction"]["min_pct"]), key=abs)
        runs.append({"ticker": ticker, "name": names[ticker], "move": f"{move:+.2f}%",
                     "scored": f"{r['scored_confirmed']} of {r['scored_total']}",
                     "decision": "REVIEW" if c["reaction"]["trigger_crossed"] else "HOLD",
                     "minutes": f"{c['slots']['complete']}/{c['slots']['expected']}", "gaps": c["slots"]["gaps"],
                     "book": f"{c['public_book']['with_visible_levels']}/{c['public_book']['snapshots']}",
                     "orders": c["orders"]})
    before = {"Costco": costco_data()["qwen_check"],
              "Constellation": _load("evidence/events/stz-q2-fy27/post_event/qwen_check_before_fix.json")}
    after = {"Costco": _load("evidence/costco/post_event/qwen_recheck_2026-10-07-r2.json"),
             "Constellation": _load("evidence/events/stz-q2-fy27/post_event/qwen_recheck_2026-10-07-r2.json")}
    qwen = [
        {"group": "Before the fix", "rows": [
            {"label": "Costco", "n": before["Costco"]["matching"], "of": before["Costco"]["runs"]},
            {"label": "Constellation", "n": before["Constellation"]["runs_matching_human_selection"],
             "of": before["Constellation"]["runs"]}]},
        {"group": "After the fix, same reports (in-sample)", "rows": [
            {"label": "Costco", "n": after["Costco"]["runs_matching_every_claim"], "of": after["Costco"]["runs"]},
            {"label": "Constellation", "n": after["Constellation"]["runs_matching_every_claim"], "of": after["Constellation"]["runs"]}]},
        {"group": "A report it had never seen", "rows": [
            {"label": "Applied Digital", "n": apld["qwen_check"]["matched_every_claim"], "of": apld["qwen_check"]["runs"]}]},
    ]
    return {
        "thesis": apld["thesis_text"], "hash": apld["frozen"]["sha256"],
        "frozen_at": apld["frozen"]["frozen_at"], "pushed_at": apld["frozen"]["push"]["pushed_at"],
        "commit": apld["frozen"]["push"]["commit"][:7],
        "release_at": m["release_at"], "closes": m["closes"], "baseline": m["baseline"],
        "trigger": m["trigger_pct"], "peak": round(m["mark"]["pct"], 2), "peak_at": m["mark"]["at"],
        "verdicts": [
            {"ok": True, "text": "Revenue beats last quarter", "fact": f"{v['c1']['values'][0]} vs {v['c1']['values'][1]}"},
            {"ok": True, "text": "Adjusted EBITDA beats last quarter", "fact": f"{v['c2']['values'][0]} vs {v['c2']['values'][1]}"},
            {"ok": False, "text": "Net loss narrows", "fact": f"widened to {v['c3']['values'][0]}"},
        ],
        "statuses": [v[c]["frozen_status"] for c in ("c1", "c2", "c3", "c4")],
        "runs": runs, "qwen": qwen, "decision": apld["decision"],
    }


def check_spoken_numbers(f: dict) -> None:
    """Every value the narration speaks must match the evidence, or nothing is recorded."""
    q = {(g["group"], r["label"]): (r["n"], r["of"]) for g in f["qwen"] for r in g["rows"]}
    expected = {
        "freeze date": (f["frozen_at"][:10], "2026-10-04"),
        "release": (f["release_at"], "2026-10-07T20:27:00Z"),
        "peak": (f["peak"], 4.75),
        "trigger": (f["trigger"], 3.0),
        "apld statuses": (f["statuses"], ["CONFIRMED", "CONFIRMED", "CONTRADICTED", "NOT_ADDRESSED"]),
        "net loss": (f["verdicts"][2]["fact"], "widened to $221.0 million"),
        "runs": ([(r["ticker"], r["scored"], r["decision"], r["minutes"], r["gaps"], r["orders"]) for r in f["runs"]],
                 [("COST", "1 of 1", "HOLD", "270/270", 0, 0), ("STZ", "2 of 3", "REVIEW", "270/270", 0, 0),
                  ("APLD", "2 of 3", "REVIEW", "270/270", 0, 0)]),
        "qwen out of sample": (q[("A report it had never seen", "Applied Digital")], (0, 5)),
        "qwen before": ((q[("Before the fix", "Costco")], q[("Before the fix", "Constellation")]), ((0, 5), (0, 5))),
        "decision": ((f["decision"]["action"], f["decision"]["orders"]), ("REVIEW", 0)),
    }
    wrong = {k: a for k, (a, b) in expected.items() if a != b}
    if wrong:
        raise SystemExit(f"narration would contradict the evidence: {wrong}")


FILM = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Reverb</title><style>
@font-face{font-family:'Inter Tight';font-weight:400 800;src:url(__FONTS__/inter-tight-latin.woff2) format('woff2')}
@font-face{font-family:'JetBrains Mono';font-weight:400 600;src:url(__FONTS__/jetbrains-mono-latin.woff2) format('woff2')}
:root{--bg:#0a0b0d;--panel:#111317;--line:rgba(255,255,255,.09);--text:#f3f4f6;--muted:#8d929c;--accent:#ff6b2c;--mint:#4fdca0;--red:#ff5a67;--amber:#ffc15e}
*{box-sizing:border-box}html,body{margin:0;height:100%;background:var(--bg);color:var(--text);font-family:'Inter Tight',sans-serif;overflow:hidden}
body:before{content:"";position:fixed;inset:0;background:linear-gradient(rgba(255,255,255,.025) 1px,transparent 1px) 0 0/100% 64px,linear-gradient(90deg,rgba(255,255,255,.025) 1px,transparent 1px) 0 0/64px 100%;pointer-events:none}
.mono{font-family:'JetBrains Mono',monospace}
section{position:fixed;inset:0;display:flex;flex-direction:column;justify-content:center;padding:0 110px;opacity:0;transition:opacity .5s}
section.on{opacity:1}
.kicker{font:500 13px 'JetBrains Mono';letter-spacing:.16em;color:var(--accent);text-transform:uppercase;display:flex;align-items:center;gap:12px}
.kicker:before{content:"";width:28px;height:1px;background:var(--accent)}
.thesis{font-size:38px;line-height:1.3;font-weight:500;letter-spacing:-.02em;max-width:1000px;margin:26px 0 34px;min-height:200px}
.thesis .cur{display:inline-block;width:3px;height:36px;background:var(--accent);vertical-align:-6px;margin-left:3px;animation:b 1s steps(1) infinite}@keyframes b{50%{opacity:0}}
.lock{display:flex;gap:14px;opacity:0;transform:translateY(10px);transition:.6s}.lock.on{opacity:1;transform:none}
.pill{border:1px solid var(--line);background:var(--panel);border-radius:6px;padding:12px 16px;font:500 15px 'JetBrains Mono';color:var(--muted)}
.pill b{color:var(--text);font-weight:600}.pill.ok{border-color:rgba(79,220,160,.4)}.pill.ok b{color:var(--mint)}
.clocks{display:grid;grid-template-columns:1fr 1fr;gap:40px;margin-top:30px}
.clock{border-top:1px solid var(--line);padding-top:24px;opacity:0;transform:translateY(14px);transition:.7s}.clock.on{opacity:1;transform:none}
.clock .t{font:600 128px/1 'Inter Tight';letter-spacing:-.05em}.clock .t.night{color:var(--accent)}
.clock .w{font:500 15px 'JetBrains Mono';color:var(--muted);letter-spacing:.1em;margin-top:14px;text-transform:uppercase}
.sub{font-size:24px;color:var(--muted);margin-top:34px;opacity:0;transition:.6s .3s}.sub.on{opacity:1}
.split{display:grid;grid-template-columns:1fr 1.15fr;gap:54px;align-items:center;margin-top:26px}
.verdict{display:flex;gap:18px;align-items:center;padding:20px 0;border-bottom:1px solid var(--line);opacity:0;transform:translateX(-16px);transition:.5s}.verdict.on{opacity:1;transform:none}
.mark{width:44px;height:44px;border-radius:50%;display:grid;place-items:center;font-size:24px;font-weight:700;flex:none}
.mark.ok{background:rgba(79,220,160,.12);color:var(--mint)}.mark.no{background:rgba(255,90,103,.13);color:var(--red)}
.verdict b{display:block;font-size:24px;font-weight:600;letter-spacing:-.015em}.verdict span{font:500 15px 'JetBrains Mono';color:var(--muted)}
.chart{position:relative}.chart svg{width:100%;height:auto;overflow:visible}
.chart .line{fill:none;stroke:var(--text);stroke-width:2.2;stroke-linejoin:round}
.chart .peak{font:600 30px 'Inter Tight';fill:var(--accent)}.chart .lab{font:500 13px 'JetBrains Mono';fill:var(--muted)}
.brand{display:flex;align-items:center;gap:22px}.bars{display:flex;gap:7px;align-items:center}.bars i{width:9px;border-radius:2px;background:var(--accent);display:block}
.word{font:700 132px/1 'Inter Tight';letter-spacing:-.06em}
.tag{font-size:54px;font-weight:600;letter-spacing:-.04em;line-height:1.08;margin-top:36px}.tag em{font-style:normal;color:var(--accent)}
.runs{display:grid;grid-template-columns:repeat(3,1fr);gap:18px;margin-top:30px}
.run{border:1px solid var(--line);background:var(--panel);border-radius:8px;padding:26px;opacity:0;transform:translateY(16px);transition:.6s}.run.on{opacity:1;transform:none}
.run h3{font:700 44px/1 'Inter Tight';letter-spacing:-.04em;margin:0}.run small{display:block;color:var(--muted);font-size:15px;margin:8px 0 18px}
.row{display:flex;justify-content:space-between;padding:10px 0;border-top:1px solid var(--line);font:500 15px 'JetBrains Mono';color:var(--muted)}.row b{color:var(--text)}
.dec{font:700 30px 'Inter Tight';letter-spacing:-.02em;margin-top:16px}.dec.hold{color:var(--mint)}.dec.review{color:var(--amber)}
.totals{margin-top:26px;font:500 16px 'JetBrains Mono';color:var(--muted);opacity:0;transition:.6s}.totals.on{opacity:1}.totals b{color:var(--text)}
.groups{display:grid;grid-template-columns:repeat(3,1fr);gap:26px;margin-top:34px}
.group{opacity:0;transform:translateY(14px);transition:.6s}.group.on{opacity:1;transform:none}
.group h4{font:500 13px 'JetBrains Mono';letter-spacing:.08em;text-transform:uppercase;color:var(--muted);margin:0 0 16px;min-height:34px}
.q{margin-bottom:18px}.q div{display:flex;justify-content:space-between;font-size:18px;margin-bottom:8px}.q b{font-family:'JetBrains Mono'}
.track{height:12px;border-radius:6px;background:rgba(255,255,255,.06);overflow:hidden}.fill{height:100%;width:0;border-radius:6px;transition:width 1.1s cubic-bezier(.2,.7,.2,1)}
.h1{font-size:62px;font-weight:700;letter-spacing:-.045em;line-height:1.02;margin:22px 0 0}
.note{font-size:21px;color:var(--muted);margin-top:30px;max-width:980px;opacity:0;transition:.6s}.note.on{opacity:1}
.lines div{font:700 92px/1.08 'Inter Tight';letter-spacing:-.05em;opacity:0;transform:translateY(16px);transition:.6s}.lines div.on{opacity:1;transform:none}.lines div:last-child{color:var(--accent)}
.foot{display:flex;gap:34px;margin-top:46px;font:500 18px 'JetBrains Mono';color:var(--muted);opacity:0;transition:.6s}.foot.on{opacity:1}.foot b{color:var(--text);font-weight:500}
</style></head><body>
<section id="thesis"><div class="kicker">My view · Applied Digital Q1 FY27</div><div class="thesis" id="tt"><span class="cur"></span></div>
<div class="lock" id="lock"><span class="pill">frozen <b id="fz"></b></span><span class="pill">sha-256 <b id="hs"></b></span><span class="pill ok">pushed to GitHub <b id="cm"></b></span></div></section>
<section id="clock"><div class="kicker">Applied Digital reports</div><div class="clocks">
<div class="clock" id="c1"><div class="t">16:27</div><div class="w">New York · Wed 7 Oct · after the close</div></div>
<div class="clock" id="c2"><div class="t night">04:27</div><div class="w">Singapore · Thu 8 Oct · while you sleep</div></div></div>
<div class="sub" id="csub">The RAPLD token keeps trading. Nobody is watching.</div></section>
<section id="verdict"><div class="kicker">The next morning</div><div class="split"><div id="vlist"></div>
<div class="chart"><svg id="svg" viewBox="0 0 640 360"></svg></div></div></section>
<section id="title"><div class="brand"><div class="bars"><i style="height:34px"></i><i style="height:62px"></i><i style="height:44px"></i></div><div class="word">reverb</div></div>
<div class="tag">Know what you believed.<br><em>See what survived.</em></div></section>
<section id="runs"><div class="kicker">Three live runs · views frozen before the report</div><div class="runs" id="rl"></div><div class="totals" id="tot"></div></section>
<section id="measure"><div class="kicker">Measuring the model, not just the market</div><div class="h1">Qwen runs that matched every fact</div>
<div class="groups" id="gl"></div><div class="note" id="qn">Code checks every value against the filing and assigns every score. The model proposes; it never grades.</div></section>
<section id="close"><div class="lines"><div>Model proposes.</div><div>Code verifies.</div><div>You decide.</div></div>
<div class="foot" id="ft"><span><b>holybunnie.github.io/reverb</b></span><span>github.com/holybunnie/reverb</span><span>#BitgetHackathon</span></div></section>
<script id="data" type="application/json">__DATA__</script>
<script>
const D = JSON.parse(document.getElementById("data").textContent), $ = id => document.getElementById(id);
const fmt = iso => iso.slice(8,10) + " Oct " + iso.slice(11,16) + " UTC";
const esc = s => String(s).replace(/[&<>]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));
function show(id){ document.querySelectorAll("section").forEach(s => s.classList.toggle("on", s.id === id)); }
function later(ms, f){ setTimeout(f, ms); }
const scenes = {
  thesis(){ show("thesis"); const t = $("tt"), text = D.thesis; let i = 0;
    const tick = setInterval(() => { i += 2; t.innerHTML = esc(text.slice(0, i)) + '<span class="cur"></span>'; if (i >= text.length) clearInterval(tick); }, 22); },
  lock(){ $("fz").textContent = fmt(D.frozen_at); $("hs").textContent = D.hash.slice(0, 16) + "…"; $("cm").textContent = D.commit + " · " + fmt(D.pushed_at); $("lock").classList.add("on"); },
  clock(){ show("clock"); later(200, () => $("c1").classList.add("on")); later(1300, () => $("c2").classList.add("on")); later(2400, () => $("csub").classList.add("on")); },
  verdict(){ show("verdict");
    $("vlist").innerHTML = D.verdicts.map(v => `<div class="verdict"><div class="mark ${v.ok ? "ok" : "no"}">${v.ok ? "✓" : "✗"}</div><div><b>${esc(v.text)}</b><span>${esc(v.fact)}</span></div></div>`).join("");
    [...document.querySelectorAll(".verdict")].forEach((el, i) => later(300 + i * 650, () => el.classList.add("on")));
    const W = 640, H = 330, xs = D.closes.map(c => Date.parse(c[0])), ys = D.closes.map(c => c[1]);
    const x0 = Math.min(...xs), x1 = Math.max(...xs), lo = D.baseline * 0.985, hi = D.baseline * (1 + D.peak / 100) * 1.012;
    const X = t => (t - x0) / (x1 - x0) * W, Y = v => H - (v - lo) / (hi - lo) * (H - 20);
    const pts = D.closes.map(c => `${X(Date.parse(c[0])).toFixed(1)},${Y(c[1]).toFixed(1)}`).join(" ");
    const trig = D.baseline * (1 + D.trigger / 100), rel = X(Date.parse(D.release_at)), pk = D.closes.find(c => c[0] === D.peak_at);
    $("svg").innerHTML = `<line x1="0" x2="${W}" y1="${Y(D.baseline)}" y2="${Y(D.baseline)}" stroke="rgba(255,255,255,.25)"/>
      <line x1="0" x2="${W}" y1="${Y(trig)}" y2="${Y(trig)}" stroke="#ff6b2c" stroke-dasharray="5 6" opacity=".7"/>
      <text class="lab" x="${W}" y="${Y(trig) - 8}" text-anchor="end">+${D.trigger}% trigger</text>
      <text class="lab" x="0" y="${Y(D.baseline) + 20}">baseline at the close</text>
      <line x1="${rel}" x2="${rel}" y1="0" y2="${H}" stroke="rgba(255,107,44,.45)"/>
      <polyline class="line" id="pl" points="${pts}"/>
      <circle id="pc" cx="${X(Date.parse(pk[0]))}" cy="${Y(pk[1])}" r="6" fill="#ff6b2c" opacity="0"/>
      <text id="pt" class="peak" x="${X(Date.parse(pk[0])) + 14}" y="${Y(pk[1]) + 6}" opacity="0">+${D.peak.toFixed(2)}%</text>`;
    const pl = $("pl"), len = pl.getTotalLength(); pl.style.strokeDasharray = len; pl.style.strokeDashoffset = len;
    pl.getBoundingClientRect(); pl.style.transition = "stroke-dashoffset 3.2s cubic-bezier(.3,.6,.3,1)"; pl.style.strokeDashoffset = 0;
    later(1500, () => { $("pc").setAttribute("opacity", 1); $("pt").setAttribute("opacity", 1); }); },
  title(){ show("title"); },
  runs(){ show("runs");
    $("rl").innerHTML = D.runs.map(r => `<div class="run"><h3>${r.ticker}</h3><small>${esc(r.name)}</small>
      <div class="row">claims confirmed<b>${r.scored}</b></div><div class="row">largest move<b>${r.move}</b></div>
      <div class="row">minutes captured<b>${r.minutes}</b></div><div class="row">order-book depth<b>${r.book}</b></div>
      <div class="row">orders<b>${r.orders}</b></div><div class="dec ${r.decision.toLowerCase()}">${r.decision}</div></div>`).join("");
    [...document.querySelectorAll(".run")].forEach((el, i) => later(250 + i * 700, () => el.classList.add("on")));
    const total = D.runs.reduce((a, r) => a + Number(r.minutes.split("/")[0]), 0), gaps = D.runs.reduce((a, r) => a + r.gaps, 0);
    $("tot").innerHTML = `<b>${total}</b> one-minute slots captured · <b>${gaps}</b> gaps · <b>0</b> orders · every number links to raw data in the repo`;
    later(2600, () => $("tot").classList.add("on")); },
  measure(){ show("measure");
    $("gl").innerHTML = D.qwen.map(g => `<div class="group"><h4>${esc(g.group)}</h4>${g.rows.map(r => `<div class="q"><div><span>${esc(r.label)}</span><b>${r.n} / ${r.of}</b></div><div class="track"><div class="fill" data-w="${r.n / r.of * 100}" style="background:${r.n / r.of >= .8 ? "var(--mint)" : "var(--red)"}"></div></div></div>`).join("")}</div>`).join("");
    [...document.querySelectorAll(".group")].forEach((el, i) => later(300 + i * 1300, () => { el.classList.add("on"); el.querySelectorAll(".fill").forEach(f => later(250, () => f.style.width = Math.max(f.dataset.w, 1.5) + "%")); }));
    later(4300, () => $("qn").classList.add("on")); },
  close(){ show("close"); [...document.querySelectorAll(".lines div")].forEach((el, i) => later(150 + i * 700, () => el.classList.add("on"))); later(2400, () => $("ft").classList.add("on")); },
};
window.scene = name => scenes[name]();
</script></body></html>"""


OVERLAY_INIT = """(() => {
  const css = `#rv-cap{position:fixed;left:50%;bottom:30px;transform:translateX(-50%);max-width:82%;z-index:2147483646;
    background:rgba(10,11,13,.86);color:#f3f4f6;font:600 21px/1.4 'Inter Tight',system-ui,sans-serif;padding:11px 20px;border-radius:10px;
    border:1px solid rgba(255,255,255,.09);text-align:center;transition:opacity .25s}
    #rv-cap:empty{opacity:0}
    #rv-fade{position:fixed;inset:0;background:#0a0b0d;z-index:2147483647;pointer-events:none;transition:opacity .35s}
    #rv-spot{position:fixed;z-index:2147483645;pointer-events:none;border:2px solid #ff6b2c;border-radius:10px;
      box-shadow:0 0 0 200vmax rgba(5,6,8,.58);opacity:0;transition:all .45s cubic-bezier(.3,.7,.3,1)}
    body{transition:transform .9s cubic-bezier(.3,.7,.3,1)}`;
  const add = () => {
    if (document.getElementById("rv-fade")) return;
    const style = document.createElement("style"); style.textContent = css; document.documentElement.append(style);
    const fade = document.createElement("div"); fade.id = "rv-fade"; document.documentElement.append(fade);
    window.addEventListener("load", () => setTimeout(() => fade.style.opacity = 0, 120));
  };
  if (document.documentElement) add(); else document.addEventListener("readystatechange", add, {once: true});
})();"""

HELPERS = """window.rv = {
  cap(text){ let el = document.getElementById("rv-cap"); if (!el) { el = document.createElement("div"); el.id = "rv-cap"; document.documentElement.append(el); } el.textContent = text; },
  out(){ const f = document.getElementById("rv-fade"); if (f) f.style.opacity = 1; },
  spot(sel, pad = 10){ const el = typeof sel === "string" ? document.querySelector(sel) : sel; if (!el) return false;
    let s = document.getElementById("rv-spot"); if (!s) { s = document.createElement("div"); s.id = "rv-spot"; document.documentElement.append(s); }
    const r = el.getBoundingClientRect(); Object.assign(s.style, {left: r.left - pad + "px", top: r.top - pad + "px", width: r.width + 2 * pad + "px", height: r.height + 2 * pad + "px", opacity: 1}); return true; },
  unspot(){ const s = document.getElementById("rv-spot"); if (s) s.style.opacity = 0; },
  push(sel, scale = 1.3){ const el = document.querySelector(sel); if (!el) return false; const r = el.getBoundingClientRect();
    document.body.style.transformOrigin = `${r.left + r.width / 2 + scrollX}px ${r.top + r.height / 2 + scrollY}px`; document.body.style.transform = `scale(${scale})`; return true; },
  pull(){ document.body.style.transform = "none"; },
  center(sel, offset = 0){ const el = document.querySelector(sel); if (!el) return false; const r = el.getBoundingClientRect();
    scrollBy({top: r.top + r.height / 2 - innerHeight / 2 + offset, behavior: "smooth"}); return true; },
};"""


class Take:
    """One continuous recording; each beat speaks one line and holds until it ends."""

    def __init__(self, page: Page | None, clips: dict[str, tuple[Path, float]] | None) -> None:
        self.page, self.clips = page, clips
        self.start = time.monotonic()
        self.lines: list[str] = []
        self.spoken: list[tuple[float, Path]] = []
        self.cues: list[tuple[float, float, str]] = []
        self.plan: list[tuple[str, float]] = []
        self.transitions = 0
        self.live: dict = {}

    def now(self) -> float:
        return time.monotonic() - self.start

    def beat(self, caption: str, say: str, action=None, *, hold: float = 0.0, variants: list[str] | None = None) -> None:
        if self.page is None:
            self.lines.extend(variants or [say])
            self.plan.append((max(variants or [say], key=len), hold))
            return
        begin = self.now()
        self.page.evaluate("t => rv.cap(t)", caption)
        clip, length = self.clips[say]
        self.spoken.append((begin, clip))
        if action:
            action()
        remaining = max(hold, length + TAIL) - (self.now() - begin)
        if remaining > 0:
            self.page.wait_for_timeout(int(remaining * 1000))
        self.cues.append((begin, self.now(), caption))

    def go(self, url: str) -> None:
        self.transitions += 1
        if self.page is None:
            return
        self.page.evaluate("rv.cap(''); rv.out()")
        self.page.wait_for_timeout(380)
        self.page.goto(url, wait_until="networkidle")
        self.page.evaluate(HELPERS)
        self.page.wait_for_timeout(450)

    def scene(self, name: str) -> None:
        if self.page is not None:
            self.page.evaluate("n => scene(n)", name)


def script(take: Take, film_url: str, desk: str, f: dict) -> None:
    page = take.page
    live = take.live
    live.update({"count": 0, "seconds": 0.0, "narrowed": None})

    take.go(film_url)
    take.scene("thesis")
    take.beat("On 4 October I wrote down what I believed about Applied Digital…",
              "On October fourth, I wrote down what I believed about Applied Digital.", hold=4.6)
    take.beat("…then locked it, and pushed the proof to GitHub.",
              "Then I locked it, and pushed the proof to GitHub.", lambda: take.scene("lock"))
    take.scene("clock")
    take.beat("Three days later they reported: 4:27 pm in New York, 4:27 am in Singapore.",
              "Three days later, they reported. Four twenty seven in the afternoon in New York. Four twenty seven in the morning in Singapore.", hold=4.2)
    take.scene("verdict")
    take.beat("Two of my claims held. One didn't. The token jumped almost 5%.",
              "Two of my claims held. One didn't. And the token jumped almost five percent.", hold=4.4)
    take.scene("title")
    take.beat("I built Reverb so a view can't be rewritten after the fact.",
              "I built Ree-verb, so a view can't be rewritten after the fact.")

    take.go(SITE)
    take.beat("After earnings, everyone's memory improves. AI makes it worse: it always sounds right afterwards.",
              "After earnings, everyone's memory improves. A I makes it worse. It always sounds right, after the fact.",
              (lambda: page.evaluate("rv.spot('.landing-hero h1', 14)")) if page else None)
    take.beat("Reverb is for Bitget traders holding tokenized US stocks through reports that land in their night.",
              "Ree-verb is for Bitget traders who hold tokenized U S stocks through reports that land in their night.",
              (lambda: page.evaluate("rv.unspot(); rv.spot('.landing-hero .hero-copy > p', 12)")) if page else None)

    take.go(desk + "/events/")
    if page is not None:
        page.wait_for_selector(".event-result", timeout=60000)
        events = page.evaluate("fetch('/api/events').then(r => r.json()).then(b => b.result.decision.events)")
        delta = [e for e in events if e["symbol"] == "DAL"]
        if not delta or delta[0]["token_status"] == "missing" or delta[0]["event_at_utc"] != "unresolved":
            raise SystemExit(f"Delta is not an unresolved-time event with a Reality token this week: {delta}")
        live["count"] = len(events)
        live["tokens"] = sum(e["token_status"] != "missing" for e in events)
    take.beat(f"Live: {live['count'] or 'N'} companies report this week; {live.get('tokens', 'M')} have a Reality token.",
              "This is the desk, running live. It pulls this week's earnings calendar, and checks every company for a Reality token.",
              (lambda: page.evaluate("rv.spot('.search-panel', 8)")) if page else None)

    def pick() -> None:
        page.evaluate("rv.unspot()")
        page.locator("[data-event-search]").press_sequentially("Delta", delay=90)
        page.wait_for_timeout(300)
        page.locator(".event-result").first.click()
        page.wait_for_timeout(250)
        page.evaluate("rv.spot('[data-selected-event-summary]', 8)")
    take.beat("I pick Delta. The calendar has no release time, so Reverb says so instead of guessing.",
              "I pick Delta. The calendar has no release time, so Ree-verb says so, instead of guessing.",
              pick if page else None)

    def write() -> None:
        page.evaluate("rv.unspot()")
        page.fill('input[name="move"]', "3")
        page.fill('input[name="budget"]', "100")
        page.evaluate("rv.center('textarea[name=view]', 120)")
        page.wait_for_timeout(500)
        page.locator('textarea[name="view"]').press_sequentially(DELTA_VIEW, delay=26)
    take.beat("I write my view the way I'd say it.", "I write my view, the way I'd say it.", write if page else None)

    def extract() -> None:
        page.evaluate("rv.center('[data-submit-thesis]')")
        page.wait_for_timeout(500)
        began = time.monotonic()
        with page.expect_response(lambda r: "/api/thesis/extract" in r.url, timeout=120000) as response:
            page.click("[data-submit-thesis]")
        claims = response.value.json()["result"]["claims"]
        page.wait_for_selector("[data-claims-review] li", timeout=10000)
        live["seconds"] = time.monotonic() - began
        live["narrowed"] = next((i for i, c in enumerate(claims)
                                 if "revenue" in c["variable"].lower() and "premium" in c["variable"].lower()), None)
        page.evaluate("rv.center('[data-claims-review]')")
    take.beat("Qwen turns it into testable claims.", "Then Kwen turns it into testable claims.", extract if page else None)

    seconds = [f"{n} second{'s' if n > 1 else ''}." for n in range(1, 13)]
    caught = [f"Back in {s} But it narrowed my revenue claim to premium cabin revenue. I didn't say that. "
              "So nothing is frozen until I've confirmed every line." for s in seconds]
    clean = [f"Back in {s} Each claim reads back what I meant, and nothing is frozen until I've confirmed every line."
             for s in seconds]
    n = max(1, min(12, round(live["seconds"]))) if page else 1
    if page is not None and live["seconds"] > 12.4:
        raise SystemExit(f"Qwen took {live['seconds']:.1f}s; re-run rather than narrate a time that is not true")

    def review() -> None:
        if live["narrowed"] is not None:
            item = f"[data-claims-review] li:nth-child({live['narrowed'] + 1})"
            page.evaluate("s => rv.spot(s, 8)", item)
            page.wait_for_timeout(5200)
            page.evaluate("rv.unspot()")
            for i in range(page.locator("[data-claims-review] li").count()):
                if i != live["narrowed"]:
                    page.locator("[data-claims-review] li input").nth(i).check()
        else:
            page.wait_for_timeout(2500)
            for box in page.locator("[data-claims-review] li input").all():
                box.check()
                page.wait_for_timeout(400)
    if page is not None and live["narrowed"] is not None:
        line, cap = caught[n - 1], f"Back in {n}s. But it narrowed my revenue claim to premium-cabin revenue. I didn't say that, so nothing freezes until I confirm every line."
    elif page is not None:
        line, cap = clean[n - 1], f"Back in {n}s. Each claim reads back what I meant; nothing freezes until I confirm every line."
    else:
        line, cap = caught[0], ""
    take.beat(cap, line, review if page else None, variants=caught + clean)

    take.go(SITE + "walkthrough/apld/#3")

    def tamper() -> None:
        page.evaluate("rv.center('#edits', 40)")
        page.wait_for_timeout(700)
        box = page.locator("#edits input").nth(3)
        box.click()
        box.press("End")
        for _ in range(len("1,410 MW")):
            box.press("Backspace")
            page.wait_for_timeout(35)
        box.type("500 MW", delay=70)
        page.wait_for_timeout(300)
        page.evaluate("rv.spot('#hashnote', 8)")
    take.beat("Once confirmed, the view is hashed and pushed before the report. Change one claim and the hash breaks.",
              "Once confirmed, the view is hashed, and pushed before the report. Change one claim, and the hash breaks.",
              tamper if page else None)
    if page is not None:
        page.evaluate("rv.unspot()")
        page.click("#reset")
        page.click("#next")
        page.wait_for_timeout(500)
    take.beat("A recorder captures the token every minute: 270 minutes, no gaps. Release time from the company's own feed.",
              "During the event, a recorder pulls the token every minute. Two hundred seventy minutes, no gaps. "
              "The release time comes from the company's own feed.",
              (lambda: (page.evaluate("rv.center('svg.chart', 30)"), page.wait_for_timeout(900),
                        page.evaluate("rv.spot('svg.chart', 6)"))) if page else None)
    if page is not None:
        page.evaluate("rv.unspot()")
        page.click("#next")
        page.wait_for_timeout(500)
    take.beat("In the morning, code checks every claim against the company's exact words. Revenue ✓ Adjusted EBITDA ✓",
              "In the morning, code checks every claim against the company's exact words. Revenue, confirmed. Adjusted EBITDA, confirmed.",
              (lambda: (page.evaluate("rv.spot('#hit', 6)"), page.wait_for_timeout(3000), page.evaluate("rv.unspot()"),
                        page.click('#cl button[data-id="c2"]'), page.wait_for_timeout(300),
                        page.evaluate("rv.spot('#hit', 6)"))) if page else None)

    def loss() -> None:
        page.evaluate("rv.unspot()")
        page.click('#cl button[data-id="c3"]')
        page.wait_for_timeout(350)
        page.evaluate("rv.spot('#hit', 6)")
    take.beat("Net loss narrowing? Wrong. It doubled, to $221.0M.",
              "Net loss narrowing? Wrong. It doubled, to two hundred twenty one million.", loss if page else None)
    if page is not None:
        page.evaluate("rv.unspot()")
        for _ in range(2):
            page.click("#next")
            page.wait_for_timeout(350)
    take.beat("The token crossed my 3% trigger, so Reverb says REVIEW. It never places the order. I decide.",
              "The token crossed my three percent trigger, so Ree-verb says review. It never places the order. I decide.",
              (lambda: (page.evaluate("rv.center('.big', 40)"), page.wait_for_timeout(700),
                        page.evaluate("rv.spot('.big', 10)"))) if page else None)

    take.go(film_url)
    take.scene("runs")
    take.beat("Three live runs. Costco under the trigger. Constellation 2 of 3, wrong on the reason. Applied Digital 2 of 3.",
              "I've run this live three times. Costco stayed under the trigger. Constellation, two of three, and wrong on the reason. "
              "Applied Digital, two of three. Eight hundred ten minutes captured. Zero gaps.", hold=5)
    take.scene("measure")
    take.beat("I measure the model too. After the fix, on a report it had never seen, Qwen still missed. That's published.",
              "I measure the model too. I fixed my prompt, and froze the fix before Applied Digital. "
              "On a report it had never seen, Kwen still missed. That's published, and it's why the model never scores.", hold=6)
    take.scene("close")
    take.beat("", "The model proposes. Code verifies. You decide. Ree-verb. Built for the Bitget A I Hackathon.", hold=4.5)


def synthesise(lines: list[str], voice: Path, directory: Path) -> dict[str, tuple[Path, float]]:
    directory.mkdir(parents=True, exist_ok=True)
    clips = {}
    for line in dict.fromkeys(lines):
        path = directory / (hashlib.sha256(line.encode()).hexdigest()[:16] + ".wav")
        if not path.exists():
            subprocess.run([sys.executable, "-m", "piper", "-m", str(voice), "-f", str(path), "--length-scale", "1.0",
                            "--sentence-silence", "0.25"], input=line, text=True, check=True, capture_output=True)
        length = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                       str(path)], capture_output=True, text=True, check=True).stdout)
        clips[line] = (path, length)
    return clips


def _ts(seconds: float, sep: str = ",") -> str:
    ms = int(round(seconds * 1000))
    return f"{ms // 3_600_000:02d}:{ms // 60_000 % 60:02d}:{ms // 1000 % 60:02d}{sep}{ms % 1000:03d}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--voice", type=Path, required=True, help="Piper .onnx voice")
    parser.add_argument("--desk", default="http://127.0.0.1:8791", help="local reverb_server.py with a Qwen key")
    parser.add_argument("--out", type=Path, default=ROOT / "data/private/recordings")
    parser.add_argument("--plan", action="store_true", help="synthesise and report the spoken length only")
    args = parser.parse_args()
    if not shutil.which("ffmpeg"):
        raise SystemExit("ffmpeg is required")
    f = film_data()
    check_spoken_numbers(f)
    work = args.out / "_demo"
    voice_dir = args.out / "_demo_voice"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    film = work / "film.html"
    film.write_text(FILM.replace("__FONTS__", (ROOT / "reverb/static/fonts").as_uri())
                    .replace("__DATA__", json.dumps(f).replace("</", "<\\/")), encoding="utf-8")

    planner = Take(None, None)
    script(planner, film.as_uri(), args.desk, f)
    clips = synthesise(planner.lines, args.voice, voice_dir)
    if args.plan:
        beats = sum(max(hold, clips[say][1] + TAIL) for say, hold in planner.plan)
        estimate = beats + planner.transitions * 1.6 + 6.0  # page loads, typing overrun, live call
        print(json.dumps({"beats": len(planner.plan), "spoken_and_held": round(beats, 1), "estimate": round(estimate, 1),
                          "per_beat": [round(max(h, clips[s][1] + TAIL), 1) for s, h in planner.plan]}))
        return

    size = {"width": 1280, "height": 720}
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--disable-dev-shm-usage"])
        context = browser.new_context(viewport=size, record_video_dir=str(work), record_video_size=size,
                                      device_scale_factor=1, color_scheme="dark", timezone_id="Asia/Singapore")
        context.add_init_script(OVERLAY_INIT)
        video_start = time.monotonic()
        page = context.new_page()
        page.goto(film.as_uri(), wait_until="load")
        page.evaluate(HELPERS)
        take = Take(page, clips)
        script(take, film.as_uri(), args.desk, f)
        page.wait_for_timeout(600)
        lead = take.start - video_start
        context.close()
        browser.close()

    webm = next(work.glob("*.webm"))
    mp4 = args.out / f"{NAME}.mp4"
    command = ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{lead:.3f}", "-i", str(webm)]
    for _, clip in take.spoken:
        command += ["-i", str(clip)]
    delays = "".join(f"[{i}:a]adelay={int(begin * 1000)}:all=1[a{i}];" for i, (begin, _) in enumerate(take.spoken, 1))
    mix = "".join(f"[a{i}]" for i in range(1, len(take.spoken) + 1))
    command += ["-filter_complex", f"{delays}{mix}amix=inputs={len(take.spoken)}:normalize=0,loudnorm=I=-16:TP=-1.5[aout]",
                "-map", "0:v", "-map", "[aout]", "-c:a", "aac", "-b:a", "160k", "-ar", "48000",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast", "-threads", "1", "-crf", "20",
                "-movflags", "+faststart", str(mp4)]
    subprocess.run(command, check=True)
    duration = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(mp4)],
                                    capture_output=True, text=True, check=True).stdout)
    (args.out / f"{NAME}.srt").write_text("".join(
        f"{i}\n{_ts(a)} --> {_ts(b)}\n{text}\n\n" for i, (a, b, text) in enumerate((c for c in take.cues if c[2]), 1)), encoding="utf-8")
    (args.out / f"{NAME}-narration.txt").write_text(
        "\n".join(next(k for k, v in clips.items() if v[0] == clip) for _, clip in take.spoken) + "\n", encoding="utf-8")
    shutil.rmtree(work)
    print(json.dumps({"mp4": str(mp4), "seconds": round(duration, 1), "events": take.live.get("count"), "with_token": take.live.get("tokens"),
                      "qwen_seconds": round(take.live.get("seconds", 0), 1), "qwen_narrowed_revenue": take.live.get("narrowed") is not None}, indent=1))
    if duration > LIMIT_SECONDS:
        raise SystemExit(f"demo runs {duration:.1f}s, over the {LIMIT_SECONDS:.0f}s limit; tighten the script")


if __name__ == "__main__":
    main()
