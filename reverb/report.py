from __future__ import annotations

import html
from typing import Any

from .ledger import Ledger


def morning_report(ledger: Ledger) -> str:
    """Render only ledger-backed decisions and outcomes for the consumer app."""
    records = ledger.verify()
    outcomes = {
        str(row["payload"].get("decision_id")): row["payload"]
        for row in records
        if row.get("kind") == "outcome" and row.get("payload", {}).get("decision_id")
    }
    registrations = [row["payload"] for row in records if row.get("kind") == "pre_registration"]
    if not registrations:
        return "<p class=\"small\">No registered event decision exists yet.</p>"
    blocks: list[str] = []
    for decision in registrations[-5:]:
        decision_id = str(decision.get("decision_id", "unknown"))
        status = html.escape(str(decision.get("status", "unknown")).upper())
        reasons = decision.get("reason_codes") or []
        reason_text = ", ".join(html.escape(str(value).replace("_", " ")) for value in reasons)
        outcome = outcomes.get(decision_id)
        outcome_text = "Outcome not appended yet."
        if outcome is not None:
            outcome_text = "Outcome: " + html.escape(str(outcome.get("result", "recorded")))
        blocks.append(
            f"<div class=\"card\"><strong>{status}</strong>"
            f"<p class=\"small\">Decision {html.escape(decision_id)}</p>"
            f"<p>{reason_text or 'The deterministic engine recorded an executable or held decision.'}</p>"
            f"<p class=\"small\">{outcome_text}</p></div>"
        )
    return "".join(blocks)
