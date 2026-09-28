"""Small, ledger-backed Costco forward-run brief for the report surface."""
from __future__ import annotations

import html
import json
from datetime import timezone
from pathlib import Path

from .reconciliation import FrozenThesis, verify_frozen_thesis


def load_costco_thesis(root: Path) -> FrozenThesis | None:
    config_path = root / "config" / "costco_run.json"
    artifact = "evidence/costco/frozen_thesis.json"
    if config_path.exists():
        artifact = json.loads(config_path.read_text(encoding="utf-8")).get("frozen_thesis_path", artifact)
    path = root / artifact
    if not path.exists():
        return None
    thesis = FrozenThesis.model_validate_json(path.read_text(encoding="utf-8"))
    if not verify_frozen_thesis(thesis):
        raise ValueError("Costco frozen thesis hash does not verify")
    return thesis


CONFIRMED_ATTR = ' data-s="c"'


def outcome_label(row: dict, attribution_ids: set[str] = frozenset()) -> str:
    """Name an unscored claim by what happened, not as a gap."""
    if row["scored"]:
        return row["status"].replace("_", " ")
    reason = row["reason"].casefold()
    if row["claim_id"] in attribution_ids or "attribution" in reason:
        return "NOT ATTRIBUTED"
    if "consensus" in reason or "benchmark" in reason:
        return "NO FAIR BENCHMARK"
    return row["status"].replace("_", " ")


def _attribution_ids(root: Path) -> set[str]:
    thesis = load_costco_thesis(root)
    return {claim.claim_id for claim in thesis.claims
            if claim.comparison.value == "EXPLICIT_ATTRIBUTION"} if thesis else set()


def _evidence(root: Path, name: str) -> dict | None:
    path = root / "evidence" / "costco" / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _pct(value: float) -> str:
    return f"{value:+.2f}%".replace("-", "−")


def costco_headline(root: Path) -> dict | None:
    """Landing-page facts for the recorded Costco run, or None while pending."""
    capture = _evidence(root, "capture_summary.json")
    reconciliation = _evidence(root, "post_event/reconciliation.json")
    if not capture or not reconciliation:
        return None
    tally = reconciliation["reconciliation"]
    addendum = reconciliation.get("addendum") or {}
    extra = {row["claim_id"]: row for row in addendum.get("claims", [])}
    return {
        "peak": _pct(capture["reaction"]["max_pct"]),
        "trigger": f"{capture['reaction']['trigger_pct']:.0f}%",
        "decision": "HOLD" if not capture["reaction"]["trigger_crossed"] else "REVIEW",
        "slots": f"{capture['slots']['complete']}/{capture['slots']['expected']}",
        "scored": f"{tally['scored_confirmed']} of {tally['scored_total']}",
        "orders": str(capture["orders"]),
        "run_status": capture["run_status"],
        "hash": reconciliation["frozen_thesis_sha256"][:8],
        "claims": [(row["text"], (extra[row["claim_id"]]["status"] + "*") if row["claim_id"] in extra
                    else outcome_label(row, _attribution_ids(root))) for row in tally["claims"]],
        "addendum_scored": (f"{addendum['scored_confirmed']} of {addendum['scored_total']}"
                            if addendum else ""),
    }


def costco_report_summary(root: Path) -> dict[str, str] | None:
    thesis = load_costco_thesis(root)
    if thesis is None:
        return None
    frozen_at = thesis.frozen_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    capture = _evidence(root, "capture_summary.json")
    reaction = capture["reaction"] if capture else None
    return {
        "symbol": "COST",
        "token": "RCOSTUSDT",
        "date": "24 SEP 2026",
        "baseline": f"${reaction['baseline_close']:,.2f}" if reaction else "—",
        "observed": f"${reaction['max_close']:,.2f}" if reaction else "—",
        "move": _pct(reaction["max_pct"]) if reaction else "—",
        "budget": f"${thesis.risk_budget_usdt:,.2f}",
        "status": f"RUN {capture['run_status']} · HELD" if capture else "THESIS FROZEN · CAPTURE PENDING",
        "frozen_at": frozen_at,
        "hash": thesis.sha256,
    }


def render_costco_morning_brief(root: Path) -> str | None:
    thesis = load_costco_thesis(root)
    if thesis is None:
        return None
    capture = _evidence(root, "capture_summary.json")
    reconciliation = _evidence(root, "post_event/reconciliation.json")
    results = {row["claim_id"]: row for row in reconciliation["reconciliation"]["claims"]} if reconciliation else {}
    addendum = (reconciliation or {}).get("addendum") or {}
    extra = {row["claim_id"]: row for row in addendum.get("claims", [])}
    rows: list[str] = []
    for claim in thesis.claims:
        result = results.get(claim.claim_id)
        if claim.claim_id in extra:
            row = extra[claim.claim_id]
            status = f"{row['status']} · ADDENDUM"
            detail = f"Frozen rules: {result['reason'] if result else 'not addressed'}. Addendum: {row['reason']}."
        elif result:
            status = outcome_label(result, _attribution_ids(root))
            detail = result["reason"]
            if result.get("current_value_text"):
                detail += f" ({result['current_value_text']} vs {result['comparison_value_text']})"
        else:
            status = "NO FAIR BENCHMARK" if not claim.scoreable else "AWAITING RELEASE"
            detail = claim.unscored_reason or "No issuer release has been captured yet."
        rows.append(
            "<tr>"
            f"<td>{html.escape(claim.text)}</td>"
            f"<td><strong{CONFIRMED_ATTR if status == 'CONFIRMED' else ''}>{html.escape(status)}</strong></td>"
            f"<td>{html.escape(detail)}</td>"
            "</tr>"
        )
    qwen = (reconciliation or {}).get("qwen_release_check") or {}
    qwen_note = (f" Qwen cross-check (candidate only): {qwen['schema_valid_runs']} of {qwen['runs']} live runs returned "
                 f"valid facts; {qwen['runs_matching_human_selection']} matched the quarter figures. It consistently "
                 "cited the 52-week membership fees instead, which is why the model never scores."
                 if qwen.get("runs") else "")
    if reconciliation:
        tally = reconciliation["reconciliation"]
        context = reconciliation["unscored_context"]["derived_gross_margin_pct_of_net_sales"]
        released = reconciliation["issuer_release_timestamp"]["value"]
        score_note = (f"Scored: {tally['scored_confirmed']} of {tally['scored_total']} confirmed against "
                      f"<a href=\"{html.escape(reconciliation['source']['url'])}\">Costco's 8-K Exhibit 99.1</a> "
                      f"(accepted {html.escape(released)}, an upper bound on release time). Unscored context: "
                      f"gross margin derived from net sales fell from {context['q4_fy2025']}% to "
                      f"{context['q4_fy2026']}%, but the release states no margin figure verbatim; "
                      "the release does not mention freight."
                      + (f" With the disclosed post-release addendum ({addendum['rule']}, added {addendum['added']}): "
                         f"{addendum['scored_confirmed']} of {addendum['scored_total']} confirmed, using Costco's own "
                         "Exhibit 99.2 statement of the margin change." if addendum else "")
                      + qwen_note)
    else:
        score_note = (f"Scored: 0 of {len([claim for claim in thesis.claims if claim.scoreable])} before the release. "
                      "The snapshot contains no claim-resolving public evidence at freeze.")
    thesis_section = f'''<section class="section costco-brief"><div class="section-intro"><div class="eyebrow"><b></b> 1 · Your thesis</div><h2>COSTCO · Q4 FY2026</h2><p>Frozen at {html.escape(thesis.frozen_at.astimezone(timezone.utc).isoformat())}. Hash <code>{html.escape(thesis.sha256)}</code>. The claim set was explicitly human-approved; the unavailable Qwen attempt did not supply claims.</p></div><div class="card"><table class="claim-table"><thead><tr><th>Claim</th><th>Status</th><th>Evidence rule</th></tr></thead><tbody>{''.join(rows)}</tbody></table><p class="small">{score_note}</p></div></section>'''
    decision = '''<section class="section human-decision"><div class="section-intro"><div class="eyebrow"><b></b> 5 · Your decision</div><h2>Human review only</h2><p>This control records that you reviewed the brief in this browser. It never places a Costco order; the forward-run configuration explicitly allows no live orders.</p></div><button class="button primary" type="button" data-human-review>Mark brief reviewed</button><span class="small" data-human-review-status>Not reviewed</span></section>'''
    if not capture:
        return thesis_section + '''
<section class="section"><div class="section-intro"><div class="eyebrow"><b></b> 2 · The market</div><h2>Capture pending</h2><p>The event window has not produced a verified Costco result yet. Required depth will come from the proven public UTA Reality-token order-book route; protected-route `40025` responses remain optional provenance.</p></div><div class="report-summary"><article><span>Pre-close baseline</span><strong>—</strong></article><article><span>Largest move</span><strong>—</strong></article><article><span>Trigger</span><strong>3.00%</strong></article><article><span>Spread / depth</span><strong>—</strong></article></div></section>
<section class="section"><div class="section-intro"><div class="eyebrow"><b></b> 3 · Market quality</div><h2>Not measured</h2><p>Visible depth, two-sidedness, and candle/book/fill provenance will be reported only from the continuous event capture.</p></div></section>
<section class="section"><div class="section-intro"><div class="eyebrow"><b></b> 4 · Reverb's recommendation</div><h2>REFUSE</h2><p>Deterministic reason: the issuer timestamp and required event-window candles and public order-book interval are not available yet, so no Costco event decision can be produced.</p></div></section>
''' + decision
    r = capture["reaction"]
    slots = capture["slots"]
    book = capture["public_book"]
    crossed = "crossed" if r["trigger_crossed"] else "did not cross"
    return thesis_section + f'''
<section class="section"><div class="section-intro"><div class="eyebrow"><b></b> 2 · The market</div><h2>{_pct(r["max_pct"])} peak, trigger not reached</h2><p>RCOSTUSDT one-minute candles, {slots["complete"]} of {slots["expected"]} slots with {slots["gaps"]} gaps. Baseline is the {html.escape(r["baseline_rule"])}. Peak at {html.escape(r["max_at"])}, low {_pct(r["min_pct"])} at {html.escape(r["min_at"])}, last {_pct(r["last_pct"])}.</p></div><div class="report-summary"><article><span>Pre-close baseline</span><strong>${r["baseline_close"]:,.2f}</strong></article><article><span>Largest move</span><strong>{_pct(r["max_pct"])}</strong></article><article><span>Trigger</span><strong>{r["trigger_pct"]:.2f}%</strong></article><article><span>Spread / depth</span><strong>Not measured</strong></article></div></section>
<section class="section"><div class="section-intro"><div class="eyebrow"><b></b> 3 · Market quality</div><h2>Depth not visible</h2><p>All {book["snapshots"]} public order-book snapshots returned successfully with {book["with_visible_levels"]} visible levels, while RCOST traded throughout. {html.escape(capture["event_time_spread"])}. Later runs also record the ticker's best bid and ask.</p></div></section>
<section class="section"><div class="section-intro"><div class="eyebrow"><b></b> 4 · Reverb's recommendation</div><h2>HOLD</h2><p>Deterministic reason: the largest move {crossed} the {r["trigger_pct"]:.0f}% trigger, so Reverb held and did not act. Run status {html.escape(capture["run_status"])}: {html.escape(capture["run_status_reason"])} Orders: {capture["orders"]}.</p></div></section>
''' + decision
