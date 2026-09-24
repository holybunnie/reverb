"""Small, ledger-backed Costco forward-run brief for the report surface."""
from __future__ import annotations

import html
from datetime import timezone
from pathlib import Path

from .reconciliation import FrozenThesis, verify_frozen_thesis


def load_costco_thesis(root: Path) -> FrozenThesis | None:
    path = root / "evidence" / "costco" / "frozen_thesis.json"
    if not path.exists():
        return None
    thesis = FrozenThesis.model_validate_json(path.read_text(encoding="utf-8"))
    if not verify_frozen_thesis(thesis):
        raise ValueError("Costco frozen thesis hash does not verify")
    return thesis


def costco_report_summary(root: Path) -> dict[str, str] | None:
    thesis = load_costco_thesis(root)
    if thesis is None:
        return None
    frozen_at = thesis.frozen_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return {
        "symbol": "COST",
        "token": "RCOSTUSDT",
        "date": "24 SEP 2026",
        "baseline": "—",
        "observed": "—",
        "move": "—",
        "budget": f"${thesis.risk_budget_usdt:,.2f}",
        "status": "THESIS FROZEN · CAPTURE PENDING",
        "frozen_at": frozen_at,
        "hash": thesis.sha256,
    }


def render_costco_morning_brief(root: Path) -> str | None:
    thesis = load_costco_thesis(root)
    if thesis is None:
        return None
    rows: list[str] = []
    for claim in thesis.claims:
        status = "UNSCORED" if not claim.scoreable else "AWAITING RELEASE"
        reason = claim.unscored_reason or "No issuer release has been captured yet."
        rows.append(
            "<tr>"
            f"<td>{html.escape(claim.text)}</td>"
            f"<td><strong>{html.escape(status)}</strong></td>"
            f"<td>{html.escape(reason)}</td>"
            "</tr>"
        )
    return f'''<section class="section costco-brief"><div class="section-intro"><div class="eyebrow"><b></b> 1 · Your thesis</div><h2>COSTCO · Q4 FY2026</h2><p>Frozen at {html.escape(thesis.frozen_at.astimezone(timezone.utc).isoformat())}. Hash <code>{html.escape(thesis.sha256)}</code>. The claim set was explicitly human-approved; the unavailable Qwen attempt did not supply claims.</p></div><div class="card"><table class="claim-table"><thead><tr><th>Claim</th><th>Status</th><th>Evidence rule</th></tr></thead><tbody>{''.join(rows)}</tbody></table><p class="small">Scored: 0 of {len([claim for claim in thesis.claims if claim.scoreable])} before the release. The snapshot contains no claim-resolving public evidence at freeze.</p></div></section>
<section class="section"><div class="section-intro"><div class="eyebrow"><b></b> 2 · The market</div><h2>Capture pending</h2><p>The event window has not produced a verified Costco result yet. The diagnostic `40025` response is not substituted for the required raw Reality book.</p></div><div class="report-summary"><article><span>Pre-close baseline</span><strong>—</strong></article><article><span>Largest move</span><strong>—</strong></article><article><span>Trigger</span><strong>3.00%</strong></article><article><span>Spread / depth</span><strong>—</strong></article></div></section>
<section class="section"><div class="section-intro"><div class="eyebrow"><b></b> 3 · Market quality</div><h2>Not measured</h2><p>Visible depth, two-sidedness, and candle/book/fill provenance will be reported only from the continuous event capture. Public diagnostics cannot fill that gap.</p></div></section>
<section class="section"><div class="section-intro"><div class="eyebrow"><b></b> 4 · Reverb's recommendation</div><h2>REFUSE</h2><p>Deterministic reason: the issuer timestamp and required raw Reality-book interval are not available, so no Costco event decision can be produced.</p></div></section>
<section class="section human-decision"><div class="section-intro"><div class="eyebrow"><b></b> 5 · Your decision</div><h2>Human review only</h2><p>This control records that you reviewed the incomplete brief in this browser. It never places a Costco order; the forward-run configuration explicitly allows no live orders.</p></div><button class="button primary" type="button" data-human-review>Mark brief reviewed</button><span class="small" data-human-review-status>Not reviewed</span></section>'''
