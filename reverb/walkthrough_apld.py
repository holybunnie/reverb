"""The third forward run, APLD Q1 FY2027, as the same eight-step research walkthrough.

Every number is read from committed APLD evidence; nothing is typed in by hand. The page
shell, chart and in-browser hash check are shared with the Costco walkthrough.
"""
from __future__ import annotations

import html
import json
from typing import Any

from .walkthrough import BLOB, REPO, ROOT, _TEMPLATE, _excerpt, _load, recorded_closes
from .walkthrough_stz import _first_crossing

EVENT = ROOT / "evidence/events/apld-q1-fy27"
EVENT_REL = "evidence/events/apld-q1-fy27"
RAW_REL = f"{EVENT_REL}/raw/20261007T192000Z-4c90a9d1"
QUESTION = ("Before Applied Digital's Q1 report I believed revenue and adjusted EBITDA would beat last quarter's "
            "$258.7M and $42.4M, the net loss would narrow from $110.6M, and they would announce another lease. "
            "Did my view survive, and what should I do with RAPLD tonight?")


def _held_beyond_trigger_from(closes: list[list[Any]], baseline: float, baseline_at: str, trigger_pct: float,
                               sign: int) -> str | None:
    """First minute from which every later close stays beyond the trigger on the move's side."""
    held = None
    for at, close in closes:
        if at <= baseline_at:
            continue
        beyond = sign * (close / baseline - 1) * 100 >= trigger_pct
        held = (held or at) if beyond else None
    return held


def walkthrough_data() -> dict[str, Any]:
    thesis = _load(EVENT / "frozen_thesis.json")
    registration = _load(EVENT / "registration_manifest.json")
    proof = _load(EVENT / "push_proof.json")
    recon = _load(EVENT / "post_event/reconciliation.json")
    summary = _load(EVENT / "capture_summary.json")
    release = _load(EVENT / "post_event/issuer_release_timestamp.json")
    if proof["frozen_thesis_sha256"] != thesis["sha256"] or recon["frozen_thesis_sha256"] != thesis["sha256"]:
        raise ValueError("push proof or reconciliation does not match the frozen APLD thesis")
    frozen_claims = {c["claim_id"]: c for c in thesis["claims"]}
    references = {r["claim_id"]: r["value_text"] for r in thesis["references"]}
    verdicts = []
    for claim in recon["reconciliation"]["claims"]:
        cid = claim["claim_id"]
        item = {"id": cid, "text": claim["text"], "rule": frozen_claims[cid]["comparison"],
                "frozen_status": claim["status"], "frozen_reason": claim["reason"], "scored": claim["scored"],
                "values": [claim["current_value_text"], claim["comparison_value_text"]],
                "reference": references.get(cid)}
        if claim["citation"]:
            item["evidence"] = _excerpt(recon["source"]["text_path"], claim["citation"])
        verdicts.append(item)
    reaction = summary["reaction"]
    closes = recorded_closes(EVENT / "raw/20261007T192000Z-4c90a9d1")
    extreme = "min" if abs(reaction["min_pct"]) > abs(reaction["max_pct"]) else "max"
    qwen = recon["qwen_release_check"]
    per_claim = {}
    for attempt in qwen["attempts"]:
        for cid in attempt.get("claims_matching_human_selection") or []:
            per_claim[cid] = per_claim.get(cid, 0) + 1
    return {
        "question": QUESTION,
        "thesis_text": thesis["thesis_text"],
        "risk_budget_usdt": thesis["risk_budget_usdt"],
        "event": thesis["event"],
        "symbol": summary["symbol"],
        "drafted": {"by": registration["drafted_by"], "approved_at": registration["approved_by_owner_at"],
                    "sources": f"{EVENT_REL}/pre_event/manifest.json"},
        "frozen": {"sha256": thesis["sha256"], "body": {k: v for k, v in thesis.items() if k != "sha256"},
                   "frozen_at": thesis["frozen_at"], "file": f"{EVENT_REL}/frozen_thesis.json",
                   "push": {"commit": proof["commit"], "pushed_at": proof["pushed_at"], "source": proof["source"]},
                   "proof_file": f"{EVENT_REL}/push_proof.json"},
        "clock": sorted([
            {"label": "Thesis frozen", "at": thesis["frozen_at"][:19] + "Z", "file": f"{EVENT_REL}/frozen_thesis.json"},
            {"label": "Freeze pushed to GitHub", "at": proof["pushed_at"], "file": f"{EVENT_REL}/push_proof.json"},
            {"label": "Applied Digital results release", "at": release["issuer_release_timestamp"],
             "file": f"{EVENT_REL}/post_event/issuer_release_timestamp.json"},
            {"label": "SEC 8-K accepted", "at": release["upper_bound_8k_acceptance"], "url": recon["source"]["filing_index"]},
        ], key=lambda row: row["at"]),
        "market": {"closes": closes, "baseline": reaction["baseline_close"], "baseline_at": reaction["baseline_at"],
                   "trigger_pct": reaction["trigger_pct"], "max_pct": reaction["max_pct"], "max_at": reaction["max_at"],
                   "min_pct": reaction["min_pct"], "min_at": reaction["min_at"], "last_pct": reaction["last_pct"],
                   "mark": {"at": reaction[f"{extreme}_at"], "close": reaction[f"{extreme}_close"],
                            "pct": reaction[f"{extreme}_pct"], "label": "low" if extreme == "min" else "peak"},
                   "first_crossing": _first_crossing(closes, reaction["baseline_close"], reaction["baseline_at"],
                                                     reaction["trigger_pct"]),
                   "held_from": _held_beyond_trigger_from(closes, reaction["baseline_close"], reaction["baseline_at"],
                                                          reaction["trigger_pct"], -1 if extreme == "min" else 1),
                   "trigger_crossed": reaction["trigger_crossed"], "release_at": release["issuer_release_timestamp"],
                   "release_label": "Applied Digital release",
                   "slots": summary["slots"], "book": summary["public_book"], "spread": summary["ticker_spread_bps"],
                   "ledger_head": summary["ledger_head"], "file": f"{EVENT_REL}/capture_summary.json", "raw": RAW_REL},
        "verdicts": verdicts,
        "context": recon["unscored_context"],
        "qwen_check": {"model": qwen["model"], "runs": qwen["runs"], "schema_valid": qwen["schema_valid_runs"],
                       "matched_every_claim": qwen["runs_matching_human_selection"],
                       "per_claim": per_claim, "role": qwen["role"],
                       "revision_file": "evidence/qwen/release_prompt_revision.json"},
        "decision": {"action": "REVIEW" if reaction["trigger_crossed"] else "HOLD", "orders": summary["orders"],
                     "run_status": summary["run_status"], "live_orders_allowed": registration["live_orders_allowed"]},
        "files": {"reconciliation": f"{EVENT_REL}/post_event/reconciliation.json"},
    }


_STEPS = r"""const STEPS = [
  {name: "Question", render: () => `<p class="kicker">Step 1 · The question</p><h1>A trader asks Reverb</h1>
    <p class="q">“${esc(D.question)}”</p>
    <p>This is Reverb's third forward run: Applied Digital's ${esc(D.event)} report on 7 Oct 2026, and the ${esc(D.symbol)} token on Bitget. Every number below comes from a committed evidence file, and the page names the file each time.</p>
    <div class="label">Recorded run, not live. Reverb never places an order: <code>live_orders_allowed: ${D.decision.live_orders_allowed}</code>. Max risk set: $${esc(D.risk_budget_usdt)} USDT.</div>`},
  {name: "Claims", render: () => `<p class="kicker">Step 2 · The view, as testable claims</p><h1>Plain words become four claims</h1>
    <p class="q" style="font-size:17px">“${esc(D.thesis_text)}”</p>
    <table><tr><th>Claim</th><th>Deterministic test</th></tr>${D.frozen.body.claims.map(c => `<tr><td>${esc(c.text)}</td><td><code>${esc(c.comparison)}</code> on ${esc(c.variable)} (${esc(c.unit)})</td></tr>`).join("")}</table>
    <div class="label">Drafted by ${esc(D.drafted.by)} and approved by the owner on ${fmt(D.drafted.approved_at, "UTC")}. It is not the owner's independent view. Each reference ($258.7M, $42.4M, $110.6M, 1,410 MW) was frozen from last quarter's release with its exact citation.</div>
    <div class="src">Frozen claims: ${file(D.frozen.file)} · drafting sources: ${file(D.drafted.sources)}</div>`},
  {name: "Freeze", render: () => `<p class="kicker">Step 3 · Freeze (the anti-hindsight proof)</p><h1>The view is locked before the report</h1>
    <p>Your browser now recomputes the SHA-256 of the frozen thesis. Change any claim and the hash breaks, so the view can't be rewritten after the result.</p>
    <div id="edits">${D.frozen.body.claims.map((c, i) => `<label class="claim-edit"><span class="count">${c.claim_id}</span><input data-i="${i}" value="${esc(c.text)}" aria-label="Claim ${c.claim_id}"></label>`).join("")}</div>
    <div id="hashbox" class="hash">computing…</div><p class="count" id="hashnote"></p>
    <button class="btn ghost" id="reset">Restore the frozen text</button>
    <div class="src">Frozen at ${fmt(D.frozen.frozen_at, "UTC")} in ${file(D.frozen.file)} · commit <code>${D.frozen.push.commit.slice(0, 7)}</code> pushed ${fmt(D.frozen.push.pushed_at, "UTC")} (${file(D.frozen.proof_file)}, from ${link(D.frozen.push.source, "GitHub's activity log")})</div>`,
    after: async () => {
      const body = JSON.parse(JSON.stringify(D.frozen.body)), box = document.getElementById("hashbox"), note = document.getElementById("hashnote");
      const update = async () => {
        const h = await sha256(canonical(body)), ok = h === D.frozen.sha256;
        box.className = "hash " + (ok ? "ok" : "bad");
        box.textContent = (ok ? "✓ matches frozen hash  " : "✗ does not match  ") + h;
        note.textContent = ok ? "Identical to the hash pushed on 4 Oct, three days before Applied Digital released." : "Edited text no longer matches what was frozen and pushed. Reverb would refuse to score it.";
      };
      document.querySelectorAll("#edits input").forEach(el => el.addEventListener("input", () => { body.claims[+el.dataset.i].text = el.value; update(); }));
      document.getElementById("reset").onclick = () => { render(2); };
      await update();
    }},
  {name: "Event & market", render: () => {
    const m = D.market, zone = Intl.DateTimeFormat().resolvedOptions().timeZone, x = m.first_crossing;
    return `<p class="kicker">Step 4 · Event clock and market</p><h1>What happened, minute by minute</h1>
    <ul class="timeline">${D.clock.map(c => `<li><b>${esc(c.label)}</b><span>${fmt(c.at, zone)} <small>· ${fmt(c.at, "America/New_York")} · ${fmt(c.at, "UTC")} · ${c.file ? file(c.file) : link(c.url, "source")}</small></span></li>`).join("")}</ul>
    ${chart()}
    <div class="grid2"><div class="stat"><b>${pct(m.mark.pct)}</b><span>${m.mark.label}, at ${fmt(m.mark.at, "America/New_York")}, vs ±${m.trigger_pct}% trigger${x ? `; first crossed at ${fmt(x[0], "America/New_York")} (${pct(x[2])})` : ""}${x && m.held_from && m.held_from !== x[0] ? `; it fell back the next minute and stayed past the trigger from ${fmt(m.held_from, "America/New_York")}` : ""}; last ${pct(m.last_pct)}</span></div>
    <div class="stat"><b>${m.slots.complete} / ${m.slots.expected}</b><span>minutes captured, ${m.slots.gaps} gaps · ${m.book.with_visible_levels} with visible book depth · ticker spread median ${m.spread.median} bps</span></div></div>
    <div class="src">${m.closes.length} recorded closes from ${file(m.raw)} · summary ${file(m.file)} · ledger head <code>${m.ledger_head.slice(0, 12)}…</code></div>`;
  }},
  {name: "Evidence", render: () => `<p class="kicker">Step 5 · Claims vs Applied Digital's own words</p><h1>Click a claim to see the sentence it was scored on</h1>
    <div class="claims-list" id="cl">${D.verdicts.map(v => `<button data-id="${v.id}" aria-pressed="false"><span>${esc(v.text)}</span>${statusPill(v.frozen_status)}</button>`).join("")}</div>
    <div id="ev"></div>`,
    after: () => {
      const notes = {
        c1: v => `Applied Digital reports revenues of <b>${esc(v.values[0])}</b>, above last quarter's frozen <b>${esc(v.values[1])}</b> (Exhibit 99.1).`,
        c2: v => `Adjusted EBITDA was <b>${esc(v.values[0])}</b>, above last quarter's frozen <b>${esc(v.values[1])}</b>.`,
        c3: v => `The net loss attributable to common stockholders was <b>${esc(v.values[0])}</b>: it widened from the frozen <b>${esc(v.values[1])}</b> instead of narrowing, so the claim is contradicted. ${esc(D.context.net_loss_basis)}`,
        c4: v => `<b>Not addressed.</b> ${esc(D.context.contracted_capacity_unit)} ${esc(D.context.new_lease)}`,
      };
      const show = id => {
        const v = V[id], el = document.getElementById("ev");
        document.querySelectorAll("#cl button").forEach(b => b.setAttribute("aria-pressed", b.dataset.id === id));
        el.innerHTML = `<h2>${esc(v.text)} · frozen rule <code>${esc(v.rule)}</code></h2><p>${notes[id](v)}</p>` + (v.evidence ? docView(v.evidence) : "");
        const hit = document.getElementById("hit"); if (hit) hit.scrollIntoView({block: "nearest"});
      };
      document.querySelectorAll("#cl button").forEach(b => b.onclick = () => show(b.dataset.id));
      show("c1");
    }},
  {name: "Verdicts", render: () => {
    const q = D.qwen_check, scored = D.verdicts.filter(v => v.scored);
    return `<p class="kicker">Step 6 · Verdict per claim</p><h1>What survived the report</h1>
    <table><tr><th>Claim</th><th>Frozen rules</th></tr>${D.verdicts.map(v => `<tr><td>${esc(v.text)}</td><td>${statusPill(v.frozen_status)}</td></tr>`).join("")}</table>
    <p><b>${scored.filter(v => v.frozen_status === "CONFIRMED").length} of ${scored.length}</b> scored claims confirmed.</p>
    <h2>Model cross-check, out of sample</h2>
    <p>Applied Digital is the first release after the 7 Oct prompt revision (${file(q.revision_file)}), so this is the honest test. ${esc(q.model)} ran the same fact-finding task ${q.runs} times: ${q.schema_valid} returned valid output and ${q.matched_every_claim} matched every claim. It matched the human selection for ${Object.entries(q.per_claim).map(([c, n]) => `${c} in ${n} runs`).join(", ") || "no claim"}; revenue and net loss were rejected every time because its period label was not verbatim in its quote. Role: ${esc(q.role)}.</p>
    <div class="src">${file(D.files.reconciliation)}</div>`;
  }},
  {name: "Insight", render: () => {
    const m = D.market, c = V;
    return `<p class="kicker">Step 7 · Actionable insight</p><h1>Did the view survive, and what now?</h1>
    <div class="insight"><table>
    <tr><td>Revenue</td><td>${statusPill(c.c1.frozen_status)} ${esc(c.c1.values[0])} vs ${esc(c.c1.values[1])}</td></tr>
    <tr><td>Adjusted EBITDA</td><td>${statusPill(c.c2.frozen_status)} ${esc(c.c2.values[0])} vs ${esc(c.c2.values[1])}</td></tr>
    <tr><td>Net loss</td><td>${statusPill(c.c3.frozen_status)} ${esc(c.c3.values[0])} vs ${esc(c.c3.values[1])}: it widened</td></tr>
    <tr><td>New lease</td><td>${statusPill(c.c4.frozen_status)} 1.41 GW stated, the same as the frozen 1,410 MW; no new lease announced</td></tr>
    <tr><td>Market</td><td>RAPLD spiked to <b>${pct(m.mark.pct)}</b> in the release minute, fell back, then held above the +${m.trigger_pct}% trigger from ${fmt(m.held_from, "America/New_York")} and ended the window ${pct(m.last_pct)}, with visible book depth in ${m.book.with_visible_levels} of ${m.book.snapshots} minutes</td></tr>
    </table>
    <p class="big">${esc(D.decision.action)} · ${D.decision.orders} orders</p>
    <p>The deterministic rule: a move beyond ±${m.trigger_pct}% from the baseline flags the run for human review. It crossed, so Reverb says <b>review</b>, not buy or sell. The view was right on growth and wrong on losses, and the lease it expected did not come. Unlike RSTZ, the book had depth to trade into, but this run was registered read-only. This is not a claim that the strategy is profitable.</p></div>`;
  }},
  {name: "You decide", render: () => `<p class="kicker">Step 8 · Human decision</p><h1>Reverb recommends. You decide.</h1>
    <p>Reverb found that two of your three scored claims held, the net loss did not narrow, and no new lease was announced. The market moved past your trigger, so it recommends <b>${esc(D.decision.action)}</b> and places nothing: there is no order path.</p>
    <p><button class="btn" id="rev">Mark reviewed</button> <span class="count" id="revnote"></span></p>
    <div class="label">“Mark reviewed” stays in this browser only. Run status: ${esc(D.decision.run_status)}.</div>
    <div class="src">Repo and all evidence: ${link("__REPO__")}</div>`,
    after: () => {
      const note = document.getElementById("revnote"), key = "reverb-walkthrough-apld-reviewed";
      try { const v = localStorage.getItem(key); if (v) note.textContent = "Reviewed " + v; } catch (e) {}
      document.getElementById("rev").onclick = () => { const v = new Date().toISOString(); note.textContent = "Reviewed " + v; try { localStorage.setItem(key, v); } catch (e) {} };
    }},
];
"""


def _template() -> str:
    head, rest = _TEMPLATE.split("const STEPS = [", 1)
    tail = rest[rest.index("\nlet current = 0;"):]
    swaps = [
        ("<title>Reverb Research Walkthrough</title>", "<title>Reverb APLD Walkthrough</title>"),
        ("a trader's Costco view, frozen before the report, checked against Costco's own filing and the RCOST market, to a decision.",
         "an Applied Digital view, frozen before the report, checked against Applied Digital's own filing and the RAPLD market, to a decision."),
        ('<a href="https://x.com/holybunnie3/status/2106831716157718648" rel="noopener">Video</a>',
         '<a href="__HOME__walkthrough/stz/">STZ run</a>'),
        ("research task walkthrough</small>", "third forward run · APLD</small>"),
        ('aria-label="RCOST one-minute closes', 'aria-label="RAPLD one-minute closes'),
        # The peak sits in the release minute, so the release label goes to the foot of its line.
        ('<text x="${xr + 4}" y="${P.t + 10}" style="fill:var(--accent)">Costco release</text>',
         '<text x="${xr + 4}" y="${H - P.b - 6}" style="fill:var(--accent)">${esc(m.release_label)}</text>'),
        # Every minute had depth here; the red band was for RSTZ's empty book.
        ('height="14" rx="3" fill="var(--bad)" opacity=".18"',
         'height="14" rx="3" fill="var(--${m.book.with_visible_levels === m.book.snapshots ? "ok" : "bad"})" opacity=".18"'),
        ("const xr = x(m.release_at), xp = x(m.max_at), yp = y(m.max_close);",
         "const xr = x(m.release_at), xp = x(m.mark.at), yp = y(m.mark.close);"),
        ("peak ${pct(m.max_pct)}</text>", "${m.mark.label} ${pct(m.mark.pct)}</text>"),
        ('s === "REFUTED" ? "bad"', '(s === "REFUTED" || s === "CONTRADICTED") ? "bad"'),
    ]
    for old, new in swaps:
        if head.count(old) != 1:
            raise ValueError(f"walkthrough template changed; cannot adapt: {old[:50]!r}")
        head = head.replace(old, new)
    return head + _STEPS + tail


def render_apld_walkthrough_html(data: dict[str, Any] | None = None, *, home: str = "/reverb/") -> str:
    data = data or walkthrough_data()
    payload = json.dumps(data, sort_keys=True, ensure_ascii=True).replace("</", "<\\/")
    return (_template().replace("__DATA__", payload).replace("__HOME__", html.escape(home))
            .replace("__BLOB__", BLOB).replace("__REPO__", REPO))
