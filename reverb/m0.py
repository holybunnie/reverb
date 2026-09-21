from __future__ import annotations

"""Machine-verifiable Milestone 0 gate.

The human-facing ``docs/m0.md`` is explanatory evidence.  Live execution must
not be unlocked by editing prose, so this module validates a separate JSON
artifact and the hashes of the evidence files it names.
"""

import hashlib
import json
from pathlib import Path
from typing import Any


REQUIRED_ANSWERS = (
    "option_hours",
    "eligibility",
    "tradeable_intersection",
    "event_book",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_evidence_path(root: Path, value: Any) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        return None
    path = (root / relative).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError:
        return None
    return path


def gate_passed(root: Path) -> bool:
    """Return true only for a complete, hash-verified gate artifact.

    Missing, malformed, blocked, or unverifiable artifacts all fail closed.
    This function intentionally does not infer a result from API availability.
    """
    artifact = root / "docs" / "m0_gate.json"
    try:
        document = json.loads(artifact.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return False
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        return False
    if document.get("status") != "PASSED":
        return False
    answers = document.get("answers")
    if not isinstance(answers, dict):
        return False
    for answer_name in REQUIRED_ANSWERS:
        answer = answers.get(answer_name)
        if not isinstance(answer, dict) or answer.get("status") != "VERIFIED":
            return False
        evidence = answer.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            return False
        for item in evidence:
            if not isinstance(item, dict):
                return False
            path = _safe_evidence_path(root, item.get("path"))
            claimed_hash = item.get("sha256")
            if path is None or not isinstance(claimed_hash, str) or len(claimed_hash) != 64:
                return False
            try:
                if _sha256(path) != claimed_hash:
                    return False
            except OSError:
                return False
    return True
