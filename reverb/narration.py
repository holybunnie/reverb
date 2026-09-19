from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .ledger import Ledger
from .qwen import QwenClient, QwenNarration


@dataclass(frozen=True)
class Narration:
    text: str
    provider: str
    model: str | None
    input_sha256: str
    output_sha256: str
    created_at: datetime


def _deterministic_text(decision: dict[str, Any]) -> str:
    status = str(decision.get("status", "unknown")).upper()
    reasons = decision.get("reason_codes") or []
    if reasons:
        reason_text = ", ".join(str(reason).replace("_", " ") for reason in reasons)
        return f"Reverb recorded a {status} decision. It did not override the safety gate: {reason_text}."
    return f"Reverb recorded a {status} decision from the deterministic engine."


def narrate_and_record(*, decision: dict[str, Any], ledger: Ledger,
                       qwen: QwenClient | None = None) -> Narration:
    serialized = json.dumps(decision, sort_keys=True, separators=(",", ":"), allow_nan=False)
    input_hash = hashlib.sha256(serialized.encode()).hexdigest()
    qwen_result: QwenNarration | None = qwen.narrate(decision) if qwen is not None else None
    text = qwen_result.text if qwen_result is not None else _deterministic_text(decision)
    output_hash = hashlib.sha256(text.encode()).hexdigest()
    result = Narration(
        text=text, provider=qwen_result.provider if qwen_result else "deterministic-template",
        model=qwen_result.model if qwen_result else None, input_sha256=input_hash,
        output_sha256=output_hash, created_at=datetime.now(timezone.utc),
    )
    ledger.append("narration", {
        "decision_id": decision.get("decision_id"), "text": result.text,
        "provider": result.provider, "model": result.model,
        "input_sha256": result.input_sha256, "output_sha256": result.output_sha256,
    })
    return result
