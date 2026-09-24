"""Run Qwen's local Costco claim-extraction path; it never freezes or grades."""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from reverb.env import load_local_env  # noqa: E402
from reverb.errors import ReverbError  # noqa: E402
from reverb.ledger import Ledger  # noqa: E402
from reverb.qwen import QwenClient, QwenCredentials  # noqa: E402


def _input_sha256(config: dict) -> str:
    serialized = json.dumps({
        "thesis_text": config.get("thesis_text"),
        "approved_comparison_rules": config.get("approved_comparison_rules", {}),
    }, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _append_attempt(config: dict, *, status: str, error_type: str | None = None,
                    provider: str | None = None, model: str | None = None,
                    input_sha256: str | None = None, output_sha256: str | None = None,
                    claims: list[dict] | None = None) -> None:
    Ledger(ROOT / "evidence" / "qwen" / "ledger.jsonl").append("costco_thesis_extraction", {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "provider": provider,
        "model": model,
        "input_sha256": input_sha256 or _input_sha256(config),
        "output_sha256": output_sha256,
        "error_type": error_type,
        "claims": claims or [],
        "outcome_statuses_assigned": False,
        "frozen": False,
        "bitget_account_calls": False,
        "order_calls": False,
    })


def main() -> int:
    load_local_env(ROOT)
    try:
        config = json.loads((ROOT / "config" / "costco_run.json").read_text(encoding="utf-8"))
        credentials = QwenCredentials.from_env()
    except (OSError, ValueError, ReverbError) as exc:
        if "config" in locals():
            _append_attempt(config, status="unavailable", error_type=type(exc).__name__)
        print(f"QWEN THESIS CHECK HALTED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    with QwenClient(credentials) as qwen:
        try:
            result = qwen.extract_thesis(
                config["thesis_text"],
                approved_rule_definitions=config["approved_comparison_rules"],
            )
        except ReverbError as exc:
            _append_attempt(
                config,
                status="unavailable",
                error_type=type(exc).__name__,
                provider="bitget-qwen",
                model=credentials.model,
            )
            print(f"QWEN THESIS CHECK HALTED: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 2

    claims = [claim.model_dump(mode="json") for claim in result.extraction.claims]
    record = Ledger(ROOT / "evidence" / "qwen" / "ledger.jsonl").append(
        "costco_thesis_extraction", {
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "status": "candidate_only_requires_human_review",
            "provider": result.provider,
            "model": result.model,
            "input_sha256": result.input_sha256,
            "output_sha256": result.output_sha256,
            "claims": claims,
            "outcome_statuses_assigned": False,
            "frozen": False,
            "bitget_account_calls": False,
            "order_calls": False,
        })
    print(f"Candidate extraction: provider={result.provider} model={result.model}; not frozen or scored.")
    for claim in result.extraction.claims:
        print(f"- {claim.claim_id}: {claim.text} [{claim.variable}; {claim.comparison.value}; {claim.claim_type.value}]")
    print(f"Sanitized Qwen ledger entry: {record['hash']}")
    print("Review every candidate; no status, market call, or order was produced.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
