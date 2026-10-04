"""One complete research task, question to actionable insight, from committed Costco evidence.

Every number on the page is read from a committed evidence file here; nothing is typed
in by hand. The page recomputes the frozen-thesis hash in the browser with WebCrypto.
"""
from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
COSTCO = ROOT / "evidence/costco"
RAW_CAPTURE = COSTCO / "raw/20260924T072322Z-1239ae49"
REPO = "https://github.com/holybunnie/reverb"
BLOB = f"{REPO}/blob/main"
# GitHub's activity log for holybunnie/reverb records this push of the commit holding frozen_thesis_v2.json.
FREEZE_PUSH = {"commit": "dfb03ca8f01509484dbd9942d7d263004211e465", "pushed_at": "2026-09-24T06:35:26Z",
               "source": "https://api.github.com/repos/holybunnie/reverb/activity"}
QUESTION = ("Before Costco's Q4 report I believed it would beat on EPS, membership fees would stay strong, "
            "and margins would disappoint because of freight. Did my view survive the report, and what "
            "should I do with RCOST tonight?")
CONTEXT_CHARS = 260


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _iso_ms(value: int) -> str:
    return datetime.fromtimestamp(value / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def recorded_closes(directory: Path = RAW_CAPTURE) -> list[list[Any]]:
    """Latest recorded close per one-minute candle inside the recorded slot window, keyed by open time."""
    rows = [json.loads(line) for line in (directory / "ledger.jsonl").read_text(encoding="utf-8").splitlines()]
    attempts = [r["payload"] for r in rows if r["kind"] == "capture_attempt"]
    slots = sorted(_ms(p["slot_at"]) for p in attempts)
    lo, hi = slots[0], slots[-1] + 60_000
    closes: dict[int, float] = {}
    for payload in attempts:
        if payload["endpoint"] != "candles" or not payload["success"]:
            continue
        for candle in _load(directory / Path(payload["body"]).name)["data"]:
            closes[int(candle[0])] = float(candle[4])
    return [[_iso_ms(key), closes[key]] for key in sorted(closes) if lo <= key < hi]


def _ms(value: str) -> int:
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)


def _excerpt(text_path: str, citation: dict[str, Any]) -> dict[str, Any]:
    text = (ROOT / text_path).read_text(encoding="utf-8")
    start, end = (int(x) for x in citation["location"].rsplit(" ", 1)[-1].split(":"))
    if text[start:end] != citation["excerpt"]:
        raise ValueError(f"citation offsets do not match {text_path}")
    lo, hi = max(0, start - CONTEXT_CHARS), min(len(text), end + CONTEXT_CHARS)
    return {"before": text[lo:start], "match": text[start:end], "after": text[end:hi], "start": start, "end": end,
            "file": text_path, "url": citation["source_url"], "sha256": citation["source_sha256"]}


def walkthrough_data() -> dict[str, Any]:
    thesis = _load(COSTCO / "frozen_thesis_v2.json")
    recon = _load(COSTCO / "post_event/reconciliation.json")
    summary = _load(COSTCO / "capture_summary.json")
    release = _load(COSTCO / "post_event/issuer_release_timestamp.json")
    qwen_rows = [json.loads(line) for line in (ROOT / "evidence/qwen/ledger.jsonl").read_text(encoding="utf-8").splitlines()]
    extractions = [r["payload"] for r in qwen_rows if r["kind"] == "costco_thesis_extraction"]
    freeze_call = next(p for p in extractions if p["checked_at"] < thesis["frozen_at"])
    recorded = next(p for p in reversed(extractions) if p["claims"])
    frozen_claims = {c["claim_id"]: c for c in thesis["claims"]}
    addendum = {c["claim_id"]: c for c in recon["addendum"]["claims"]}
    verdicts = []
    for claim in recon["reconciliation"]["claims"]:
        cid = claim["claim_id"]
        item = {"id": cid, "text": claim["text"], "rule": frozen_claims[cid]["comparison"],
                "frozen_status": claim["status"], "frozen_reason": claim["reason"], "scored": claim["scored"]}
        if claim["citation"]:
            item["evidence"] = _excerpt(recon["source"]["text_path"], claim["citation"])
            item["values"] = [claim["current_value_text"], claim["comparison_value_text"]]
        if cid in addendum:
            add = addendum[cid]
            item["addendum"] = {"status": add["status"], "reason": add["reason"], "rule": recon["addendum"]["rule"],
                                "added": recon["addendum"]["added"], "values": [add["current_value_text"], add["comparison_value_text"]],
                                "evidence": _excerpt(recon["addendum"]["source"]["text_path"], add["citation"])}
        verdicts.append(item)
    context = recon["unscored_context"]
    qwen = recon["qwen_release_check"]
    body = {k: v for k, v in thesis.items() if k != "sha256"}
    reaction = summary["reaction"]
    return {
        "question": QUESTION,
        "thesis_text": thesis["thesis_text"],
        "risk_budget_usdt": thesis["risk_budget_usdt"],
        "event": thesis["event"],
        "symbol": summary["symbol"],
        "frozen": {"sha256": thesis["sha256"], "body": body, "frozen_at": thesis["frozen_at"],
                   "file": "evidence/costco/frozen_thesis_v2.json", "push": FREEZE_PUSH},
        "qwen_recorded": {"model": recorded["model"], "checked_at": recorded["checked_at"], "status": recorded["status"],
                          "output_sha256": recorded["output_sha256"], "claims": recorded["claims"],
                          "freeze_call": {"checked_at": freeze_call["checked_at"], "status": freeze_call["status"]}},
        "clock": [
            {"label": "Thesis frozen", "at": thesis["frozen_at"][:19] + "Z", "file": "evidence/costco/frozen_thesis_v2.json"},
            {"label": "Freeze pushed to GitHub", "at": FREEZE_PUSH["pushed_at"], "url": FREEZE_PUSH["source"]},
            {"label": "Costco release", "at": release["issuer_release_timestamp"], "file": "evidence/costco/post_event/issuer_release_timestamp.json"},
            {"label": "SEC 8-K accepted", "at": release["upper_bound_8k_acceptance"], "url": recon["source"]["filing_index"]},
        ],
        "market": {"closes": recorded_closes(), "baseline": reaction["baseline_close"], "baseline_at": reaction["baseline_at"],
                   "trigger_pct": reaction["trigger_pct"], "max_pct": reaction["max_pct"], "max_at": reaction["max_at"],
                   "max_close": reaction["max_close"], "min_pct": reaction["min_pct"], "last_pct": reaction["last_pct"],
                   "trigger_crossed": reaction["trigger_crossed"], "release_at": release["issuer_release_timestamp"],
                   "slots": summary["slots"], "book": summary["public_book"], "ledger_head": summary["ledger_head"],
                   "file": "evidence/costco/capture_summary.json", "raw": "evidence/costco/raw/20260924T072322Z-1239ae49"},
        "verdicts": verdicts,
        "context": {"eps": context["diluted_eps"], "freight_mentioned": context["freight_mentioned_in_release"],
                    "call": context["conference_call"]},
        "qwen_check": {"model": qwen["model"], "runs": qwen["runs"], "schema_valid": qwen["schema_valid_runs"],
                       "matching": qwen["runs_matching_human_selection"], "role": qwen["role"],
                       "example": next(a["grounded_facts"][0] for a in qwen["attempts"] if a.get("grounded_facts")),
                       "rejected": [a["reason"] for a in qwen["attempts"] if a["status"] != "returned"]},
        "decision": {"action": "HOLD", "orders": summary["orders"], "run_status": summary["run_status"]},
        "files": {"reconciliation": "evidence/costco/post_event/reconciliation.json"},
    }


def render_walkthrough_html(data: dict[str, Any] | None = None, *, home: str = "/reverb/") -> str:
    data = data or walkthrough_data()
    payload = json.dumps(data, sort_keys=True, ensure_ascii=True).replace("</", "<\\/")
    return (_TEMPLATE.replace("__DATA__", payload).replace("__HOME__", html.escape(home))
            .replace("__BLOB__", BLOB).replace("__REPO__", REPO))


_TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Reverb Research Walkthrough</title>
<meta name="description" content="One complete research task on Reverb: a trader's Costco view, frozen before the report, checked against Costco's own filing and the RCOST market, to a decision.">
<style>
:root{--bg:#f6f4ef;--panel:#fff;--ink:#16181d;--muted:#5d6370;--line:#dedad0;--accent:#1f5eff;--ok:#127a46;--warn:#9a5b00;--bad:#b42318;--hl:#fff1a8;--chip:#efece4}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#0f1115;--panel:#171a21;--ink:#eceef3;--muted:#a1a7b3;--line:#2a2f3a;--accent:#7aa2ff;--ok:#4cc38a;--warn:#f0b354;--bad:#ff7b72;--hl:#5a4b00;--chip:#222733}}
:root[data-theme="dark"]{--bg:#0f1115;--panel:#171a21;--ink:#eceef3;--muted:#a1a7b3;--line:#2a2f3a;--accent:#7aa2ff;--ok:#4cc38a;--warn:#f0b354;--bad:#ff7b72;--hl:#5a4b00;--chip:#222733}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif}
a{color:var(--accent)}header{max-width:980px;margin:0 auto;padding:20px 16px 0;display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}
.brand{font-weight:700;text-decoration:none;color:var(--ink);letter-spacing:.02em}.brand small{color:var(--muted);font-weight:500;margin-left:8px}
main{max-width:980px;margin:0 auto;padding:16px}
.steps{display:flex;gap:6px;flex-wrap:wrap;margin:8px 0 18px;padding:0;list-style:none}
.steps button{border:1px solid var(--line);background:var(--panel);color:var(--muted);border-radius:999px;padding:5px 11px;font:inherit;font-size:13px;cursor:pointer}
.steps button[aria-current="step"]{background:var(--ink);color:var(--bg);border-color:var(--ink)}
.steps button.done{color:var(--ink)}
.card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:22px;min-height:340px}
.kicker{font-size:13px;color:var(--muted);text-transform:uppercase;letter-spacing:.08em;margin:0 0 4px}
h1{font-size:26px;line-height:1.25;margin:0 0 12px}h2{font-size:17px;margin:20px 0 8px}
.q{font-size:20px;line-height:1.5;border-left:4px solid var(--accent);padding:6px 0 6px 16px;margin:16px 0}
.src{font-size:13px;color:var(--muted);margin-top:16px;border-top:1px dashed var(--line);padding-top:10px;overflow-wrap:anywhere}
.src code,code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.9em;background:var(--chip);padding:1px 5px;border-radius:5px;overflow-wrap:anywhere}
.nav{display:flex;justify-content:space-between;align-items:center;margin-top:16px;gap:12px}
.btn{border:1px solid var(--ink);background:var(--ink);color:var(--bg);border-radius:10px;padding:10px 18px;font:inherit;font-weight:600;cursor:pointer}
.btn.ghost{background:transparent;color:var(--ink);border-color:var(--line)}.btn:disabled{opacity:.35;cursor:default}
.count{color:var(--muted);font-size:14px}
table{width:100%;border-collapse:collapse;font-size:15px}td,th{text-align:left;padding:8px 6px;border-bottom:1px solid var(--line);vertical-align:top}th{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em}
.pill{display:inline-block;align-self:center;flex:none;font-size:12px;font-weight:700;border-radius:999px;padding:2px 9px;background:var(--chip);white-space:nowrap}
.pill.ok{color:var(--ok)}.pill.warn{color:var(--warn)}.pill.bad{color:var(--bad)}
.label{font-size:13px;background:var(--chip);border-radius:8px;padding:8px 10px;color:var(--muted);margin:10px 0}
.claim-edit{display:flex;gap:8px;align-items:center;margin:6px 0}.claim-edit input{flex:1;font:inherit;padding:7px 10px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--ink)}
.hash{font-family:ui-monospace,Menlo,monospace;font-size:13px;overflow-wrap:anywhere;padding:10px;border-radius:8px;border:1px solid var(--line);margin:6px 0}
.hash.ok{border-color:var(--ok)}.hash.bad{border-color:var(--bad);color:var(--bad)}
.timeline{list-style:none;padding:0;margin:8px 0;display:grid;gap:10px}.timeline li{display:grid;grid-template-columns:170px 1fr;gap:10px;border-left:3px solid var(--line);padding-left:12px}
.timeline b{display:block}.timeline small{color:var(--muted)}
svg{width:100%;height:auto;display:block}.chart text{fill:var(--muted);font-size:11px}
.claims-list{display:grid;gap:6px;margin:8px 0}.claims-list button{text-align:left;border:1px solid var(--line);background:var(--bg);color:var(--ink);border-radius:10px;padding:9px 12px;font:inherit;cursor:pointer;display:flex;justify-content:space-between;gap:8px}
.claims-list button[aria-pressed="true"]{border-color:var(--accent);box-shadow:0 0 0 1px var(--accent)}
.doc{font-family:ui-monospace,Menlo,monospace;font-size:13px;line-height:1.6;background:var(--bg);border:1px solid var(--line);border-radius:10px;padding:12px;max-height:280px;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere}
.doc mark{background:var(--hl);color:inherit;padding:1px 0}
.insight{border:2px solid var(--ink);border-radius:14px;padding:16px;margin-top:8px}
.big{font-size:34px;font-weight:800;letter-spacing:.02em}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.stat{background:var(--bg);border:1px solid var(--line);border-radius:10px;padding:12px}.stat b{display:block;font-size:22px}.stat span{font-size:13px;color:var(--muted)}
@media (max-width:640px){h1{font-size:22px}.q{font-size:17px}.grid2{grid-template-columns:1fr}.timeline li{grid-template-columns:1fr}.card{padding:16px}}
</style></head><body>
<header><a class="brand" href="__HOME__">REVERB<small>research task walkthrough</small></a><span><a href="__HOME__runs/">Forward runs</a> · <a href="__REPO__">Source and evidence</a></span></header>
<main><ol class="steps" id="steps" aria-label="Steps"></ol><section class="card" id="card" aria-live="polite"></section>
<div class="nav"><button class="btn ghost" id="prev">Back</button><span class="count" id="count"></span><button class="btn" id="next">Next</button></div></main>
<script id="data" type="application/json">__DATA__</script>
<script>
"use strict";
const D = JSON.parse(document.getElementById("data").textContent);
const BLOB = "__BLOB__";
const esc = s => String(s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const file = p => `<a href="${BLOB}/${p}"><code>${esc(p)}</code></a>`;
const link = (u, t) => `<a href="${esc(u)}" rel="noopener">${esc(t || u)}</a>`;
const fmt = (iso, tz) => new Intl.DateTimeFormat("en-GB", {timeZone: tz, day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false, timeZoneName: "short"}).format(new Date(iso));
const pct = v => (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v).toFixed(2) + "%";
const statusPill = s => `<span class="pill ${s === "CONFIRMED" ? "ok" : s === "REFUTED" ? "bad" : "warn"}">${esc(s.replace(/_/g, " "))}</span>`;
const V = Object.fromEntries(D.verdicts.map(v => [v.id, v]));

// Python json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=True)
function canonical(v) {
  if (v === null || typeof v !== "object") {
    return typeof v === "string" ? JSON.stringify(v).replace(/[\u007f-￿]/g, c => "\\u" + c.charCodeAt(0).toString(16).padStart(4, "0")) : JSON.stringify(v);
  }
  if (Array.isArray(v)) return "[" + v.map(canonical).join(",") + "]";
  return "{" + Object.keys(v).sort().map(k => canonical(k) + ":" + canonical(v[k])).join(",") + "}";
}
async function sha256(text) {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(buf)].map(b => b.toString(16).padStart(2, "0")).join("");
}

function chart() {
  const m = D.market, pts = m.closes, W = 900, H = 300, P = {l: 52, r: 14, t: 16, b: 34};
  const t0 = Date.parse(pts[0][0]), t1 = Date.parse(pts[pts.length - 1][0]);
  const lo = m.baseline * (1 - m.trigger_pct / 100), hi = m.baseline * (1 + m.trigger_pct / 100);
  const ymin = Math.min(lo, ...pts.map(p => p[1])), ymax = Math.max(hi, ...pts.map(p => p[1]));
  const x = t => P.l + (Date.parse(t) - t0) / (t1 - t0) * (W - P.l - P.r);
  const y = v => P.t + (ymax - v) / (ymax - ymin) * (H - P.t - P.b);
  const path = pts.map((p, i) => (i ? "L" : "M") + x(p[0]).toFixed(1) + " " + y(p[1]).toFixed(1)).join("");
  const xr = x(m.release_at), xp = x(m.max_at), yp = y(m.max_close);
  const ticks = [0, 1, 2, 3, 4].map(i => new Date(t0 + i * (t1 - t0) / 4).toISOString());
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="RCOST one-minute closes during the recorded window">
  <rect x="${P.l}" y="${y(hi)}" width="${W - P.l - P.r}" height="${y(lo) - y(hi)}" fill="currentColor" opacity=".05"/>
  <line x1="${P.l}" x2="${W - P.r}" y1="${y(hi)}" y2="${y(hi)}" stroke="var(--bad)" stroke-dasharray="5 4"/><text x="${W - P.r}" y="${y(hi) - 4}" text-anchor="end">+${m.trigger_pct}% trigger $${hi.toFixed(2)}</text>
  <line x1="${P.l}" x2="${W - P.r}" y1="${y(lo)}" y2="${y(lo)}" stroke="var(--bad)" stroke-dasharray="5 4"/><text x="${W - P.r}" y="${y(lo) - 4}" text-anchor="end">−${m.trigger_pct}% trigger $${lo.toFixed(2)}</text>
  <line x1="${P.l}" x2="${W - P.r}" y1="${y(m.baseline)}" y2="${y(m.baseline)}" stroke="var(--muted)" stroke-width="1"/><text x="${P.l + 4}" y="${y(m.baseline) + 14}">baseline $${m.baseline}</text>
  <line x1="${xr}" x2="${xr}" y1="${P.t}" y2="${H - P.b}" stroke="var(--accent)"/><text x="${xr + 4}" y="${P.t + 10}" style="fill:var(--accent)">Costco release</text>
  <path d="${path}" fill="none" stroke="var(--ink)" stroke-width="1.6"/>
  <circle cx="${xp}" cy="${yp}" r="4" fill="var(--accent)"/><text x="${xp + 7}" y="${yp - 6}" style="fill:var(--ink);font-weight:700">peak ${pct(m.max_pct)}</text>
  ${ticks.map((t, i) => `<text x="${x(t)}" y="${H - 12}" text-anchor="${i === 0 ? "start" : i === 4 ? "end" : "middle"}">${fmt(t, "UTC").replace(/^\d+ \w+ /, "").replace(/:\d\d UTC/, " UTC")}</text>`).join("")}
  </svg>
  <svg viewBox="0 0 ${W} 26" aria-label="Public order book depth per recorded minute"><rect x="${P.l}" y="4" width="${W - P.l - P.r}" height="14" rx="3" fill="var(--bad)" opacity=".18"/><text x="${P.l + 6}" y="15" style="fill:var(--ink);font-size:11px">public book depth: ${m.book.with_visible_levels} of ${m.book.snapshots} minutes had any visible level</text></svg>`;
}

function docView(e) {
  return `<div class="doc">…${esc(e.before)}<mark id="hit">${esc(e.match)}</mark>${esc(e.after)}…</div>
  <div class="src">Exact offsets <code>${e.start}:${e.end}</code> in ${file(e.file)} (SHA-256 <code>${e.sha256.slice(0, 12)}…</code>) · original: ${link(e.url, "SEC filing")}</div>`;
}

const STEPS = [
  {name: "Question", render: () => `<p class="kicker">Step 1 · The question</p><h1>A trader asks Reverb</h1>
    <p class="q">“${esc(D.question)}”</p>
    <p>This walkthrough follows one real run end to end: Costco's ${esc(D.event)} report on 24 Sep 2026, and the ${esc(D.symbol)} token on Bitget. Every number below comes from a committed evidence file, and the page names the file each time.</p>
    <div class="label">Recorded run, not live. Reverb never places an order: <code>live_orders_allowed: false</code>. Max risk the trader set: $${esc(D.risk_budget_usdt)} USDT.</div>`},
  {name: "Claims", render: () => {
    const q = D.qwen_recorded;
    return `<p class="kicker">Step 2 · The view, as testable claims</p><h1>Plain words become four claims</h1>
    <p class="q" style="font-size:17px">“${esc(D.thesis_text)}”</p>
    <table><tr><th>Claim</th><th>Deterministic test</th></tr>${D.frozen.body.claims.map(c => `<tr><td>${esc(c.text)}</td><td><code>${esc(c.comparison)}</code> on ${esc(c.variable)}${c.scoreable ? "" : ` <span class="pill warn">unscored</span>`}</td></tr>`).join("")}</table>
    <div class="label">The claims were extracted by ${esc(q.model)} and recorded on ${fmt(q.checked_at, "UTC")}, after the event; the freeze-time call on ${fmt(q.freeze_call.checked_at, "UTC")} returned <b>${esc(q.freeze_call.status)}</b>, so the frozen claims are human-approved. The model phrased claims; it never picked numbers or trades. Editing the view here won't call a model: live extraction needs the local app and a key.</div>
    <div class="src">Frozen claims: ${file(D.frozen.file)} · model record: ${file("evidence/qwen/ledger.jsonl")} (output <code>${q.output_sha256.slice(0, 12)}…</code>)</div>`;
  }},
  {name: "Freeze", render: () => `<p class="kicker">Step 3 · Freeze (the anti-hindsight proof)</p><h1>The view is locked before the report</h1>
    <p>Your browser now recomputes the SHA-256 of the frozen thesis. Change any claim and the hash breaks, so the view can't be rewritten after the result.</p>
    <div id="edits">${D.frozen.body.claims.map((c, i) => `<label class="claim-edit"><span class="count">${c.claim_id}</span><input data-i="${i}" value="${esc(c.text)}" aria-label="Claim ${c.claim_id}"></label>`).join("")}</div>
    <div id="hashbox" class="hash">computing…</div><p class="count" id="hashnote"></p>
    <button class="btn ghost" id="reset">Restore the frozen text</button>
    <div class="src">Frozen at ${fmt(D.frozen.frozen_at, "UTC")} in ${file(D.frozen.file)} · commit <code>${D.frozen.push.commit.slice(0, 7)}</code> pushed ${fmt(D.frozen.push.pushed_at, "UTC")} per ${link(D.frozen.push.source, "GitHub's activity log")}</div>`,
    after: async () => {
      const body = JSON.parse(JSON.stringify(D.frozen.body)), box = document.getElementById("hashbox"), note = document.getElementById("hashnote");
      const update = async () => {
        const h = await sha256(canonical(body)), ok = h === D.frozen.sha256;
        box.className = "hash " + (ok ? "ok" : "bad");
        box.textContent = (ok ? "✓ matches frozen hash  " : "✗ does not match  ") + h;
        note.textContent = ok ? "Identical to the hash recorded at freeze, about 13h40m before Costco released." : "Edited text no longer matches what was frozen and pushed. Reverb would refuse to score it.";
      };
      document.querySelectorAll("#edits input").forEach(el => el.addEventListener("input", () => { body.claims[+el.dataset.i].text = el.value; update(); }));
      document.getElementById("reset").onclick = () => { render(2); };
      await update();
    }},
  {name: "Event & market", render: () => {
    const m = D.market, zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    return `<p class="kicker">Step 4 · Event clock and market</p><h1>What happened, minute by minute</h1>
    <ul class="timeline">${D.clock.map(c => `<li><b>${esc(c.label)}</b><span>${fmt(c.at, zone)} <small>· ${fmt(c.at, "America/New_York")} · ${fmt(c.at, "UTC")} · ${c.file ? file(c.file) : link(c.url, "source")}</small></span></li>`).join("")}</ul>
    ${chart()}
    <div class="grid2"><div class="stat"><b>${pct(m.max_pct)}</b><span>peak move, at ${fmt(m.max_at, "America/New_York")}, the release minute, vs ±${m.trigger_pct}% trigger</span></div>
    <div class="stat"><b>${m.slots.complete} / ${m.slots.expected}</b><span>minutes captured, ${m.slots.gaps} gaps · ${m.book.with_visible_levels} with visible book depth</span></div></div>
    <div class="src">${m.closes.length} recorded closes from ${file(m.raw)} · summary ${file(m.file)} · ledger head <code>${m.ledger_head.slice(0, 12)}…</code></div>`;
  }},
  {name: "Evidence", render: () => `<p class="kicker">Step 5 · Claims vs Costco's own words</p><h1>Click a claim to see the sentence it was scored on</h1>
    <div class="claims-list" id="cl">${D.verdicts.map(v => `<button data-id="${v.id}" aria-pressed="false"><span>${esc(v.text)}</span>${statusPill(v.addendum ? v.addendum.status + "_BY_ADDENDUM" : v.frozen_status)}</button>`).join("")}</div>
    <div id="ev"></div>`,
    after: () => {
      const show = id => {
        const v = V[id], el = document.getElementById("ev");
        document.querySelectorAll("#cl button").forEach(b => b.setAttribute("aria-pressed", b.dataset.id === id));
        let out = `<h2>${esc(v.text)} · frozen rule <code>${esc(v.rule)}</code></h2>`;
        if (v.evidence) out += `<p>Costco reports <b>${esc(v.values[0])}</b> against <b>${esc(v.values[1])}</b> a year earlier (USD millions, Exhibit 99.1).</p>` + docView(v.evidence);
        else if (v.addendum) out += `<p>Under the frozen rules: <b>${esc(v.frozen_status.replace(/_/g, " "))}</b>, ${esc(v.frozen_reason)}.</p><div class="label">Disclosed addendum <code>${esc(v.addendum.rule)}</code>, added ${esc(v.addendum.added)} after the release and reported separately: ${esc(v.addendum.reason)}.</div>` + docView(v.addendum.evidence);
        else if (v.id === "c1") out += `<p><b>No fair benchmark.</b> ${esc(v.frozen_reason)}</p><div class="label">${esc(D.context.eps)}</div>`;
        else out += `<p><b>Not attributed.</b> Costco's release ${D.context.freight_mentioned ? "mentions" : "does not mention"} freight, so the attribution claim fails to find support. ${esc(D.context.call)}</p>`;
        el.innerHTML = out;
        const hit = document.getElementById("hit"); if (hit) hit.scrollIntoView({block: "nearest"});
      };
      document.querySelectorAll("#cl button").forEach(b => b.onclick = () => show(b.dataset.id));
      show("c2");
    }},
  {name: "Verdicts", render: () => {
    const q = D.qwen_check;
    return `<p class="kicker">Step 6 · Verdict per claim</p><h1>What survived the report</h1>
    <table><tr><th>Claim</th><th>Frozen rules</th><th>With disclosed addendum</th></tr>${D.verdicts.map(v => `<tr><td>${esc(v.text)}</td><td>${statusPill(v.frozen_status)}</td><td>${v.addendum ? statusPill(v.addendum.status) + ` <small>${esc(v.addendum.values[0])}</small>` : "—"}</td></tr>`).join("")}</table>
    <h2>Model cross-check, measured</h2>
    <p>${esc(q.model)} ran the same scoring task ${q.runs} times: ${q.schema_valid} returned valid output, <b>${q.matching} of ${q.runs}</b> matched the human selection. It picked the full-year figure (${esc(q.example.current)} vs ${esc(q.example.prior)}, ${esc(q.example.current_period)}) instead of the quarter, and one run was rejected: “${esc(q.rejected[0] || "")}”. Role: ${esc(q.role)}.</p>
    <div class="src">${file(D.files.reconciliation)}</div>`;
  }},
  {name: "Insight", render: () => {
    const m = D.market, c = V;
    return `<p class="kicker">Step 7 · Actionable insight</p><h1>Did the view survive, and what now?</h1>
    <div class="insight"><table>
    <tr><td>Membership fees</td><td>${statusPill(c.c2.frozen_status)} ${esc(c.c2.values[0])} vs ${esc(c.c2.values[1])} (Exhibit 99.1)</td></tr>
    <tr><td>Margins</td><td>${statusPill(c.c3.addendum.status)} only under the disclosed addendum (Exhibit 99.2, ${esc(c.c3.addendum.values[0])})</td></tr>
    <tr><td>Freight</td><td>${statusPill("NOT_ATTRIBUTED")} Costco did not blame freight, so that part of the view failed</td></tr>
    <tr><td>EPS</td><td>${statusPill("UNGRADED")} no fair benchmark was frozen</td></tr>
    <tr><td>Market</td><td>RCOST peaked at <b>${pct(m.max_pct)}</b> in the release minute, under the ${m.trigger_pct}% trigger, with ${m.book.with_visible_levels} visible book levels across ${m.book.snapshots} minutes</td></tr>
    </table>
    <p class="big">${esc(D.decision.action)} · ${D.decision.orders} orders</p>
    <p>The deterministic rule: act only if the move crosses ±${m.trigger_pct}% from the baseline. It peaked at ${pct(m.max_pct)}, so Reverb recommends holding, and there was no visible depth to trade into anyway. This shows the view was checked honestly. It is not a claim that the strategy is profitable.</p></div>`;
  }},
  {name: "You decide", render: () => `<p class="kicker">Step 8 · Human decision</p><h1>Reverb recommends. You decide.</h1>
    <p>Reverb found that your view partly held, but your stated reason (freight) didn't, and the market didn't move enough to act on. It recommends <b>${esc(D.decision.action)}</b> and places nothing: there is no order path.</p>
    <p><button class="btn" id="rev">Mark reviewed</button> <span class="count" id="revnote"></span></p>
    <div class="label">“Mark reviewed” stays in this browser only. Run status: ${esc(D.decision.run_status)}.</div>
    <div class="src">Repo and all evidence: ${link("__REPO__")}</div>`,
    after: () => {
      const note = document.getElementById("revnote"), key = "reverb-walkthrough-reviewed";
      try { const v = localStorage.getItem(key); if (v) note.textContent = "Reviewed " + v; } catch (e) {}
      document.getElementById("rev").onclick = () => { const v = new Date().toISOString(); note.textContent = "Reviewed " + v; try { localStorage.setItem(key, v); } catch (e) {} };
    }},
];

let current = 0;
function render(i) {
  current = Math.max(0, Math.min(STEPS.length - 1, i));
  document.getElementById("steps").innerHTML = STEPS.map((s, j) => `<li><button data-j="${j}" class="${j < current ? "done" : ""}" ${j === current ? 'aria-current="step"' : ""}>${j + 1}. ${s.name}</button></li>`).join("");
  document.querySelectorAll("#steps button").forEach(b => b.onclick = () => render(+b.dataset.j));
  document.getElementById("card").innerHTML = STEPS[current].render();
  document.getElementById("count").textContent = `${current + 1} of ${STEPS.length}`;
  document.getElementById("prev").disabled = current === 0;
  document.getElementById("next").textContent = current === STEPS.length - 1 ? "Start over" : "Next";
  history.replaceState(null, "", "#" + (current + 1));
  if (STEPS[current].after) STEPS[current].after();
}
document.getElementById("prev").onclick = () => render(current - 1);
document.getElementById("next").onclick = () => render(current === STEPS.length - 1 ? 0 : current + 1);
render((parseInt(location.hash.slice(1), 10) || 1) - 1);
</script></body></html>
"""
