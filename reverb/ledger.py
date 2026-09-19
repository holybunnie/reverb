from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .errors import LedgerError


GENESIS = "0" * 64


def canonical(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class Ledger:
    """Append-only hash chain for registrations, refusals, orders, and outcomes."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _last(self) -> tuple[int, str]:
        if not self.path.exists():
            return 0, GENESIS
        lines = self.path.read_bytes().splitlines()
        if not lines:
            return 0, GENESIS
        last = json.loads(lines[-1])
        return int(last["sequence"]), str(last["hash"])

    def append(self, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not kind or not isinstance(payload, dict):
            raise LedgerError("ledger entries need a kind and object payload")
        sequence, previous = self._last()
        record = {"sequence": sequence + 1, "previous": previous, "kind": kind,
                  "created_at": datetime.now(timezone.utc).isoformat(), "payload": payload}
        record["hash"] = sha256(canonical(record))
        with self.path.open("ab") as stream:
            stream.write(canonical(record) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        return record

    def verify(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        records = []
        previous = GENESIS
        for expected, line in enumerate(self.path.read_bytes().splitlines(), 1):
            try:
                record = json.loads(line)
                claimed = record.pop("hash")
                if record["sequence"] != expected or record["previous"] != previous or sha256(canonical(record)) != claimed:
                    raise LedgerError(f"ledger hash mismatch at sequence {expected}")
                record["hash"] = claimed
                records.append(record)
                previous = claimed
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise LedgerError(f"malformed ledger at sequence {expected}: {exc}") from exc
        return records

    def register(self, decision: dict[str, Any]) -> dict[str, Any]:
        if decision.get("status") not in {"act", "refuse", "hold"}:
            raise LedgerError("registration requires a structured decision status")
        return self.append("pre_registration", decision)

    def outcome(self, decision_id: str, outcome: dict[str, Any]) -> dict[str, Any]:
        if not decision_id or not outcome:
            raise LedgerError("outcome requires decision_id and payload")
        existing = [r for r in self.verify() if r["kind"] == "pre_registration" and r["payload"].get("decision_id") == decision_id]
        if not existing:
            raise LedgerError("cannot append an outcome without a pre-registration")
        return self.append("outcome", {"decision_id": decision_id, **outcome})
