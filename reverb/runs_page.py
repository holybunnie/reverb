"""Forward-run board: one card per registered event, built only from committed evidence.

Before an event's window the card shows the frozen thesis, its hash and the
GitHub push time; the countdown and status are computed in the viewer's browser
from the registered window. Results appear only once a reconciliation file is
committed; until then the card says the run is awaiting scoring.
"""
from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BLOB = "https://github.com/holybunnie/reverb/blob/main"


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def runs_data() -> list[dict[str, Any]]:
    costco = _load(ROOT / "evidence/costco/capture_summary.json")
    costco_recon = _load(ROOT / "evidence/costco/post_event/reconciliation.json")
    frozen, addendum = costco_recon["reconciliation"], costco_recon["addendum"]
    runs: list[dict[str, Any]] = [{
        "id": "costco-q4-fy26", "event": "Costco Q4 FY2026", "symbol": costco["symbol"],
        "window": ["2026-09-24T19:30:00Z", "2026-09-25T00:00:00Z"], "frozen_sha256": _load(
            ROOT / "evidence/costco/frozen_thesis_v2.json")["sha256"],
        "pushed_at": "2026-09-24T06:35:26Z", "thesis": _load(ROOT / "evidence/costco/frozen_thesis_v2.json")["thesis_text"],
        "claims": [c["text"] for c in _load(ROOT / "evidence/costco/frozen_thesis_v2.json")["claims"]],
        "drafted": "Owner-supplied thesis; claims human-approved", "files": {"frozen": "evidence/costco/frozen_thesis_v2.json",
                                                   "result": "evidence/costco/post_event/reconciliation.json"},
        "result": f"Peak {costco['reaction']['max_pct']:+.2f}% vs {costco['reaction']['trigger_pct']:.0f}% trigger · "
                  f"HOLD, {costco['orders']} orders · thesis {frozen['scored_confirmed']}/{frozen['scored_total']} confirmed "
                  f"({addendum['scored_confirmed']}/{addendum['scored_total']} with a disclosed addendum) · run {costco['run_status']}",
        "walkthrough": True,
    }]
    for directory in sorted((ROOT / "evidence/events").iterdir()):
        registration_path = directory / "registration_manifest.json"
        if not registration_path.exists():
            continue
        registration = _load(registration_path)
        thesis = _load(ROOT / registration["frozen_thesis_path"])
        proof = _load(directory / "push_proof.json")
        if proof["frozen_thesis_sha256"] != thesis["sha256"] or registration["frozen_thesis_sha256"] != thesis["sha256"]:
            raise ValueError(f"push proof or registration does not match the frozen thesis for {directory.name}")
        reconciliation = directory / "post_event/reconciliation.json"
        summary_path = directory / "capture_summary.json"
        result = None
        if reconciliation.exists() and summary_path.exists():
            summary, scored = _load(summary_path), _load(reconciliation)["reconciliation"]
            reaction = summary["reaction"]
            move = max((reaction["max_pct"], reaction["min_pct"]), key=abs)
            result = (f"Move {move:+.2f}% vs {reaction['trigger_pct']:.0f}% trigger · {summary['orders']} orders (read-only) · "
                      f"thesis {scored['scored_confirmed']}/{scored['scored_total']} confirmed · run {summary['run_status']}")
        runs.append({
            "id": registration["event_id"], "event": registration["event"], "symbol": registration["token_symbol"],
            "window": registration["window"], "frozen_sha256": thesis["sha256"], "pushed_at": proof["pushed_at"],
            "thesis": thesis["thesis_text"], "claims": [c["text"] for c in thesis["claims"]],
            "drafted": f"Drafted by {registration['drafted_by'].split(' from ')[0]}, approved by the owner "
                       f"({registration['approved_by_owner_at'][:16].replace('T', ' ')} UTC)",
            "files": {"frozen": registration["frozen_thesis_path"],
                      "sources": f"evidence/events/{directory.name}/pre_event/manifest.json",
                      **({"result": str(reconciliation.relative_to(ROOT))} if reconciliation.exists() else {})},
            "result": result, "walkthrough": False,
        })
    return sorted(runs, key=lambda run: run["window"][0])


def render_runs_html(runs: list[dict[str, Any]] | None = None, *, home: str = "/reverb/") -> str:
    payload = json.dumps(runs or runs_data(), sort_keys=True, ensure_ascii=True).replace("</", "<\\/")
    return _TEMPLATE.replace("__DATA__", payload).replace("__HOME__", html.escape(home)).replace("__BLOB__", BLOB)


_TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Reverb Forward Runs</title>
<meta name="description" content="Every Reverb forward run: thesis frozen and pushed before the earnings release, then recorded and scored against the issuer's own filing.">
<style>
:root{--bg:#f6f4ef;--panel:#fff;--ink:#16181d;--muted:#5d6370;--line:#dedad0;--accent:#1f5eff;--ok:#127a46;--warn:#9a5b00;--chip:#efece4}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#0f1115;--panel:#171a21;--ink:#eceef3;--muted:#a1a7b3;--line:#2a2f3a;--accent:#7aa2ff;--ok:#4cc38a;--warn:#f0b354;--chip:#222733}}
:root[data-theme="dark"]{--bg:#0f1115;--panel:#171a21;--ink:#eceef3;--muted:#a1a7b3;--line:#2a2f3a;--accent:#7aa2ff;--ok:#4cc38a;--warn:#f0b354;--chip:#222733}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif}
a{color:var(--accent)}header,main{max-width:1040px;margin:0 auto;padding:16px}header{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;align-items:center;padding-top:20px}
.brand{font-weight:700;text-decoration:none;color:var(--ink)}.brand small{color:var(--muted);font-weight:500;margin-left:8px}
h1{font-size:26px;margin:4px 0 6px}.lede{color:var(--muted);margin:0 0 18px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:14px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:18px;display:flex;flex-direction:column;gap:8px}
.top{display:flex;justify-content:space-between;gap:8px;align-items:center}.sym{font-weight:800;font-size:20px}
.pill{font-size:12px;font-weight:700;border-radius:999px;padding:3px 10px;background:var(--chip);white-space:nowrap}.pill.ok{color:var(--ok)}.pill.warn{color:var(--warn)}.pill.live{color:var(--accent)}
.count{font-size:22px;font-weight:700}.muted{color:var(--muted);font-size:14px}
blockquote{margin:0;border-left:3px solid var(--line);padding-left:10px;font-size:15px}
ul{margin:0;padding-left:18px;font-size:15px}code{font-family:ui-monospace,Menlo,monospace;font-size:12.5px;background:var(--chip);padding:1px 5px;border-radius:5px;overflow-wrap:anywhere}
.links{font-size:14px;display:flex;gap:12px;flex-wrap:wrap;margin-top:auto;padding-top:6px;border-top:1px dashed var(--line)}
</style></head><body>
<header><a class="brand" href="__HOME__">REVERB<small>forward runs</small></a><a href="__HOME__walkthrough/">Walk through the Costco run</a></header>
<main><h1>Forward runs</h1><p class="lede">Each thesis is frozen and pushed to GitHub before the company reports. The page never fills in a result that isn't committed; times are shown in your time zone.</p>
<div class="grid" id="grid"></div></main>
<script id="data" type="application/json">__DATA__</script>
<script>
"use strict";
const RUNS = JSON.parse(document.getElementById("data").textContent), BLOB = "__BLOB__";
const esc = s => String(s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const when = iso => new Intl.DateTimeFormat(undefined, {weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZoneName: "short"}).format(new Date(iso));
function span(ms) { const m = Math.floor(ms / 60000), d = Math.floor(m / 1440), h = Math.floor(m % 1440 / 60); return (d ? d + "d " : "") + h + "h " + (m % 60) + "m"; }
function status(r) {
  const now = Date.now(), start = Date.parse(r.window[0]), end = Date.parse(r.window[1]);
  if (r.result) return ["ok", "Scored", ""];
  if (now < start) return ["warn", "Locked", "recording starts in " + span(start - now)];
  if (now < end) return ["live", "Recording", "window closes in " + span(end - now)];
  return ["warn", "Awaiting scoring", "window closed " + when(r.window[1])];
}
function render() {
  document.getElementById("grid").innerHTML = RUNS.map(r => {
    const [cls, label, sub] = status(r);
    return `<article class="card"><div class="top"><span class="sym">${esc(r.symbol)}</span><span class="pill ${cls}">${label}</span></div>
    <div><b>${esc(r.event)}</b></div>${sub ? `<div class="count">${esc(sub)}</div>` : ""}
    <div class="muted">Window ${when(r.window[0])} → ${when(r.window[1])}</div>
    <blockquote>${esc(r.thesis)}</blockquote><ul>${r.claims.map(c => `<li>${esc(c)}</li>`).join("")}</ul>
    ${r.result ? `<div><b>${esc(r.result)}</b></div>` : ""}
    <div class="muted">${esc(r.drafted)}</div>
    <div class="muted">Frozen hash <code>${esc(r.frozen_sha256.slice(0, 16))}…</code> pushed ${when(r.pushed_at)}</div>
    <div class="links"><a href="${BLOB}/${esc(r.files.frozen)}">Frozen thesis</a>${r.files.sources ? `<a href="${BLOB}/${esc(r.files.sources)}">Pre-event sources</a>` : ""}${r.files.result ? `<a href="${BLOB}/${esc(r.files.result)}">Scoring</a>` : ""}${r.walkthrough ? `<a href="__HOME__walkthrough/">Walkthrough</a>` : ""}</div></article>`;
  }).join("");
}
render(); setInterval(render, 30000);
</script></body></html>
"""
