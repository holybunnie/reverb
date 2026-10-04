"""Freeze an owner-approved event thesis from config/events/<event_id>.json.

Reads only committed, hash-identified pre-event sources under
evidence/events/<event_id>/pre_event/, freezes the reference values the thesis
compares against, and writes the immutable thesis plus its registration
manifest. Costco keeps its own script and paths.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from reverb.reconciliation import (  # noqa: E402
    Citation,
    FrozenReference,
    ThesisClaim,
    build_knowledge_snapshot,
    freeze_thesis,
    source_text_sha256,
    verify_frozen_thesis,
)


def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def load_config(event_id: str) -> tuple[dict, str]:
    raw = (ROOT / "config" / "events" / f"{event_id}.json").read_bytes()
    config = json.loads(raw)
    if config.get("event_id") != event_id:
        raise ValueError("config event_id does not match its file name")
    if config.get("live_orders_allowed") is not False:
        raise ValueError("an event registration must set live_orders_allowed to false")
    if not config.get("approved_by_owner_at") or not config.get("approval_text"):
        raise ValueError("no owner approval is recorded; an unapproved thesis is never frozen")
    return config, hashlib.sha256(raw).hexdigest()


def load_sources(event_id: str) -> tuple[dict[str, str], dict]:
    directory = ROOT / "evidence" / "events" / event_id / "pre_event"
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    for item in manifest["sources"]:
        if hashlib.sha256((ROOT / item["file"]).read_bytes()).hexdigest() != item["sha256"]:
            raise ValueError(f"raw source hash mismatch: {item['file']}")
    documents = {}
    for path in sorted(directory.glob("*.txt")):
        text = path.read_text(encoding="utf-8")
        documents[source_text_sha256(text)] = text
    return documents, manifest


def build_references(config: dict, documents: dict[str, str]) -> tuple[FrozenReference, ...]:
    references = []
    for row in config["references"]:
        text = (ROOT / row["text_path"]).read_text(encoding="utf-8")
        offset = text.find(row["excerpt"])
        if offset < 0 or text.count(row["excerpt"]) != 1:
            raise ValueError(f"reference excerpt for {row['claim_id']} is not unique in {row['text_path']}")
        citation = Citation(
            source_url=row["source_url"], published_at=row["published_at"], captured_at=row["captured_at"],
            source_sha256=source_text_sha256(text), excerpt=row["excerpt"],
            location=f"{row['text_path']} normalized text offsets {offset}:{offset + len(row['excerpt'])}",
        )
        references.append(FrozenReference(claim_id=row["claim_id"], value_text=row["value_text"],
                                          unit=row["unit"], citation=citation))
    return tuple(references)


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()


def freeze(event_id: str, frozen_at: datetime, *, require_clean: bool) -> int:
    config, config_sha256 = load_config(event_id)
    if frozen_at >= datetime.fromisoformat(config["window_start"].replace("Z", "+00:00")):
        print("EVENT FREEZE HALTED: the capture window has already opened.", file=sys.stderr)
        return 2
    if require_clean and git("status", "--porcelain"):
        print("EVENT FREEZE HALTED: commit the code, config and sources before freezing.", file=sys.stderr)
        return 2
    documents, manifest = load_sources(event_id)
    claims = tuple(ThesisClaim.model_validate(row) for row in config["claims"])
    references = build_references(config, documents)
    snapshot = build_knowledge_snapshot(claims=claims, evidence=(), frozen_at=frozen_at, source_documents=documents)
    commit = git("rev-parse", "HEAD")
    frozen = freeze_thesis(
        event=config["event"], thesis_text=config["thesis_text"], claims=claims,
        confirmed_claim_ids={claim.claim_id for claim in claims}, knowledge_snapshot=snapshot,
        references=references, risk_budget_usdt=config["risk_budget_usdt"],
        reaction_trigger_pct=config["reaction_trigger_pct"], baseline_method=config["baseline_method"],
        capture_plan=config["capture_plan"], code_commit=commit, frozen_at=frozen_at, source_documents=documents,
    )
    if not verify_frozen_thesis(frozen):
        raise ValueError("new frozen thesis failed its own hash check")
    out = ROOT / "evidence" / "events" / event_id
    destination, registration_path = out / "frozen_thesis.json", out / "registration_manifest.json"
    if destination.exists() or registration_path.exists():
        print("EVENT FREEZE HALTED: frozen artifacts already exist; refusing overwrite.", file=sys.stderr)
        return 2
    destination.write_text(json.dumps(frozen.model_dump(mode="json"), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    registration = {
        "event_id": event_id, "event": config["event"], "token_symbol": config["token_symbol"],
        "frozen_thesis_path": str(destination.relative_to(ROOT)), "frozen_thesis_sha256": frozen.sha256,
        "frozen_at": iso_utc(frozen_at), "code_commit": commit,
        "config_path": f"config/events/{event_id}.json", "config_sha256": config_sha256,
        "drafted_by": config["drafted_by"], "approved_by_owner_at": config["approved_by_owner_at"],
        "approval_text": config["approval_text"], "claims_approved_by_human": True, "model_candidate_used": False,
        "live_orders_allowed": False, "window": [config["window_start"], config["window_end"]],
        "pre_event_sources": manifest["sources"],
        "knowledge_snapshot_statuses": [{"claim_id": i.claim_id, "status": i.status.value, "reason": i.reason}
                                        for i in snapshot.items],
    }
    registration_path.write_text(json.dumps(registration, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Frozen thesis: {destination.relative_to(ROOT)}\nThesis hash: {frozen.sha256}\nCode commit: {commit}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event", required=True)
    parser.add_argument("--frozen-at", help="aware ISO timestamp; defaults to now")
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args()
    frozen_at = (datetime.fromisoformat(args.frozen_at.replace("Z", "+00:00")) if args.frozen_at
                 else datetime.now(timezone.utc))
    if frozen_at.tzinfo is None:
        parser.error("--frozen-at must include a timezone")
    return freeze(args.event, frozen_at, require_clean=not args.allow_dirty)


if __name__ == "__main__":
    raise SystemExit(main())
