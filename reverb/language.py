from __future__ import annotations

import os
from typing import Any

from .errors import ReverbError
from .ledger import Ledger
from .models import View
from .narration import narrate_and_record
from .qwen import QwenClient, QwenCredentials


def optional_qwen_client() -> QwenClient | None:
    """Return the local Qwen client only when its key is configured."""
    if not (os.getenv("QWEN_API_KEY") or os.getenv("BITGET_QWEN_API_KEY")):
        return None
    return QwenClient(QwenCredentials.from_env())


def interpret_view_and_record(*, text: str, ledger: Ledger, qwen: QwenClient) -> View:
    """Use Qwen only to classify direction and record its auditable output."""
    result = qwen.interpret_view(text)
    ledger.append("view_interpretation", {
        "view": result.view,
        "provider": result.provider,
        "model": result.model,
        "input_sha256": result.input_sha256,
        "output_sha256": result.output_sha256,
    })
    return View(result.view)


def extract_thesis_and_record(*, text: str, approved_rule_definitions: dict[str, str],
                              ledger: Ledger, qwen: QwenClient):
    """Record a candidate extraction without freezing or grading the thesis."""
    result = qwen.extract_thesis(text, approved_rule_definitions=approved_rule_definitions)
    ledger.append("thesis_claim_extraction", {
        "claims": [claim.model_dump(mode="json") for claim in result.extraction.claims],
        "input_sha256": result.input_sha256,
        "output_sha256": result.output_sha256,
        "provider": result.provider,
        "model": result.model,
        "requires_user_confirmation": True,
        "outcome_statuses_assigned": False,
        "decision_or_order": False,
    })
    return result


def decision_with_narration(*, decision: dict[str, Any], ledger: Ledger,
                            qwen: QwenClient | None) -> dict[str, Any]:
    """Attach presentation-only prose without changing the engine decision."""
    try:
        narration = narrate_and_record(decision=decision, ledger=ledger, qwen=qwen)
    except ReverbError as exc:
        # Language is presentation-only. Record the failure loudly, then keep
        # the deterministic decision usable with deterministic prose.
        ledger.append("language_failure", {
            "decision_id": decision.get("decision_id"),
            "stage": "narration",
            "error_type": type(exc).__name__,
        })
        narration = narrate_and_record(decision=decision, ledger=ledger, qwen=None)
    return {
        **decision,
        "narration": {
            "text": narration.text,
            "provider": narration.provider,
            "model": narration.model,
            "input_sha256": narration.input_sha256,
            "output_sha256": narration.output_sha256,
        },
    }
