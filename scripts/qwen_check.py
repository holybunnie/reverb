"""Verify Reverb's optional Qwen language layer without touching Bitget trading APIs."""
from __future__ import annotations

import sys
from tempfile import TemporaryDirectory
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from reverb.env import load_local_env  # noqa: E402
from reverb.errors import DataUnavailable, ReverbError  # noqa: E402
from reverb.ledger import Ledger  # noqa: E402
from reverb.narration import narrate_and_record  # noqa: E402
from reverb.qwen import QwenClient, QwenCredentials  # noqa: E402
from reverb.replay import load_replay_snapshot  # noqa: E402


def main() -> int:
    load_local_env(ROOT)
    try:
        credentials = QwenCredentials.from_env()
    except ReverbError as exc:
        print(f"REVERB QWEN CLASSIFICATION HALTED: {exc}", file=sys.stderr)
        return 2

    with QwenClient(credentials) as qwen:
        try:
            view = qwen.interpret_view("I expect the company to report stronger results.")
        except ReverbError as exc:
            print(f"REVERB QWEN CLASSIFICATION HALTED: {exc}", file=sys.stderr)
            return 2
        print(f"Qwen ready: provider={view.provider} model={view.model} classification={view.view}")

        replay = load_replay_snapshot(ROOT)
        with TemporaryDirectory(prefix="reverb-qwen-check-") as temporary:
            ledger = Ledger(Path(temporary) / "ledger.jsonl")
            try:
                narrated = narrate_and_record(decision=replay.action, ledger=ledger, qwen=qwen)
            except ReverbError as exc:
                ledger.append("language_failure", {
                    "decision_id": replay.action.get("decision_id"),
                    "stage": "narration", "error_type": type(exc).__name__,
                    "reason": str(exc)[:200],
                })
                fallback = narrate_and_record(decision=replay.action, ledger=ledger, qwen=None)
                records = ledger.verify()
                if not any(row.get("kind") == "narration"
                           and row.get("payload", {}).get("provider") == "deterministic-template"
                           for row in records):
                    raise DataUnavailable("deterministic narration fallback was not recorded")
                print(f"Qwen narration not verified: {type(exc).__name__}: {exc}", file=sys.stderr)
                print(f"Deterministic fallback verified: provider={fallback.provider}")
                print("The check used a verified paper decision and a temporary hash-chained ledger.")
                print("No Bitget account endpoint or order path was called.")
                return 2
            records = ledger.verify()
            if (narrated.provider != "bitget-qwen"
                    or not any(row.get("kind") == "narration"
                               and row.get("payload", {}).get("provider") == "bitget-qwen"
                               for row in records)):
                raise DataUnavailable("Qwen narration was not recorded")
        print(f"Narration verified: provider={narrated.provider} model={narrated.model}")
        evidence = Ledger(ROOT / "evidence" / "qwen" / "ledger.jsonl").append("qwen_live_check", {
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "status": "verified",
            "provider": view.provider,
            "model": view.model,
            "classification_request_sha256": view.input_sha256,
            "classification_response_sha256": view.output_sha256,
            "narration_request_sha256": narrated.input_sha256,
            "narration_response_sha256": narrated.output_sha256,
            "bitget_account_calls": False,
            "order_calls": False,
        })
        print(f"Sanitized Qwen verification evidence appended: {evidence['hash']}")
        print("No Bitget account endpoint or order path was called.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
