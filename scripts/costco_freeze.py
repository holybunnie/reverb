"""Capture Costco pre-event sources and create the immutable thesis artifact."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from reverb.reconciliation import (  # noqa: E402
    Citation,
    KnowledgeEvidence,
    ThesisClaim,
    build_knowledge_snapshot,
    freeze_thesis,
    source_text_sha256,
    verify_frozen_thesis,
)


SOURCE_URLS = {
    "august_sales": "https://investor.costco.com/news/news-details/2026/Costco-Wholesale-Corporation-Reports-August-Sales-Results/default.aspx",
    "events_page": "https://investor.costco.com/events-and-presentations/default.aspx?lv=true",
}


def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def capture_sources() -> int:
    directory = ROOT / "evidence" / "costco" / "pre_event"
    directory.mkdir(parents=True, exist_ok=True)
    manifest = []
    try:
        with httpx.Client(
            timeout=30.0,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; Reverb evidence capture/1.0)",
                "Accept": "text/html,application/xhtml+xml",
            },
        ) as client:
            for source_id, url in SOURCE_URLS.items():
                captured_at = datetime.now(timezone.utc)
                response = client.get(url)
                response.raise_for_status()
                body = response.content
                body_path = directory / f"{source_id}.body"
                if body_path.exists():
                    raise RuntimeError(f"refusing to overwrite {body_path}")
                body_path.write_bytes(body)
                text = body.decode("utf-8", errors="replace")
                manifest.append({
                    "source_id": source_id,
                    "source_url": url,
                    "captured_at": iso_utc(captured_at),
                    "http_status": response.status_code,
                    "content_type": response.headers.get("content-type"),
                    "body_path": str(body_path.relative_to(ROOT)),
                    "body_sha256": hashlib.sha256(body).hexdigest(),
                    "text_sha256": source_text_sha256(text),
                    "bytes": len(body),
                })
    except (httpx.HTTPError, OSError, RuntimeError) as exc:
        print(f"COSTCO SOURCE CAPTURE HALTED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    manifest_path = directory / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Captured {len(manifest)} Costco pre-event source documents to {directory}")
    for item in manifest:
        print(f"- {item['source_id']}: {item['text_sha256']}")
    return 0


def register_existing_sources() -> int:
    """Register a deliberately labelled normalized extract without calling the site."""
    directory = ROOT / "evidence" / "costco" / "pre_event"
    bodies = sorted(directory.glob("*.body"))
    if not bodies:
        print("COSTCO SOURCE REGISTRATION HALTED: no existing source bodies", file=sys.stderr)
        return 2
    manifest = []
    for body_path in bodies:
        body = body_path.read_bytes()
        text = body.decode("utf-8", errors="replace")
        source_id = body_path.stem
        manifest.append({
            "source_id": source_id,
            "source_url": SOURCE_URLS.get(source_id),
            "captured_at": iso_utc(datetime.now(timezone.utc)),
            "capture_mode": "normalized_web_extract",
            "raw_http_capture": False,
            "body_path": str(body_path.relative_to(ROOT)),
            "body_sha256": hashlib.sha256(body).hexdigest(),
            "text_sha256": source_text_sha256(text),
            "bytes": len(body),
        })
    manifest_path = directory / "manifest.json"
    if manifest_path.exists():
        print("COSTCO SOURCE REGISTRATION HALTED: refusing to overwrite manifest", file=sys.stderr)
        return 2
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Registered {len(manifest)} labelled normalized source extract(s)")
    return 0


def load_source_documents() -> tuple[dict[str, str], list[dict]]:
    manifest_path = ROOT / "evidence" / "costco" / "pre_event" / "manifest.json"
    if not manifest_path.exists():
        return {}, []
    manifest = read_json(manifest_path)
    documents: dict[str, str] = {}
    for item in manifest:
        body = (ROOT / item["body_path"]).read_bytes()
        text = body.decode("utf-8", errors="replace")
        digest = source_text_sha256(text)
        if digest != item["text_sha256"]:
            raise ValueError(f"source text hash mismatch for {item['source_id']}")
        documents[digest] = text
    return documents, manifest


def load_knowledge_evidence(source_documents: dict[str, str]) -> tuple[KnowledgeEvidence, ...]:
    path = ROOT / "config" / "costco_knowledge_evidence.json"
    rows = read_json(path)
    evidence = tuple(KnowledgeEvidence.model_validate(row) for row in rows)
    for item in evidence:
        if item.citation.source_sha256 not in source_documents:
            raise ValueError(f"knowledge evidence source is not in the captured source set: {item.claim_id}")
    return evidence


def current_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
        capture_output=True, text=True,
    )
    return result.stdout.strip()


def latest_qwen_attempt() -> dict | None:
    path = ROOT / "evidence" / "qwen" / "ledger.jsonl"
    if not path.exists():
        return None
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    for row in reversed(rows):
        if row.get("kind") == "costco_thesis_extraction":
            return {"hash": row.get("hash"), **row.get("payload", {})}
    return None


def freeze(frozen_at: datetime, *, require_clean: bool, revision: str | None = None) -> int:
    config = read_json(ROOT / "config" / "costco_run.json")
    review = read_json(ROOT / "config" / "costco_claims.json")
    claims = tuple(ThesisClaim.model_validate(row) for row in review["claims"])
    source_documents, source_manifest = load_source_documents()
    evidence = load_knowledge_evidence(source_documents)
    snapshot = build_knowledge_snapshot(
        claims=claims, evidence=evidence, frozen_at=frozen_at,
        source_documents=source_documents,
    )
    status = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT,
                            check=True, capture_output=True, text=True).stdout.strip()
    if require_clean and status:
        print("COSTCO FREEZE HALTED: commit the code and reviewed claims before freezing.", file=sys.stderr)
        return 2
    commit = current_commit()
    frozen = freeze_thesis(
        event=config["event"], thesis_text=config["thesis_text"], claims=claims,
        confirmed_claim_ids={claim.claim_id for claim in claims},
        knowledge_snapshot=snapshot, references=(),
        risk_budget_usdt=config["risk_budget_usdt"],
        reaction_trigger_pct=config["reaction_trigger_pct"],
        baseline_method=config["baseline_method"], capture_plan=config["capture_plan"],
        code_commit=commit, frozen_at=frozen_at, source_documents=source_documents,
    )
    if not verify_frozen_thesis(frozen):
        raise ValueError("new frozen thesis failed its own hash check")
    suffix = f"_{revision}" if revision else ""
    destination = ROOT / "evidence" / "costco" / f"frozen_thesis{suffix}.json"
    manifest_path = ROOT / "evidence" / "costco" / f"registration_manifest{suffix}.json"
    if destination.exists() or manifest_path.exists():
        print("COSTCO FREEZE HALTED: frozen artifacts already exist; refusing overwrite.", file=sys.stderr)
        return 2
    body = json.dumps(frozen.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(body, encoding="utf-8")
    qwen = latest_qwen_attempt()
    registration = {
        "event": config["event"],
        "frozen_thesis_path": str(destination.relative_to(ROOT)),
        "frozen_thesis_sha256": frozen.sha256,
        "frozen_at": iso_utc(frozen_at),
        "code_commit": commit,
        "claims_approved_by_human": True,
        "approval_basis": review["approval_basis"],
        "model_candidate_used": False,
        "qwen_extraction_attempt": qwen,
        "pre_event_sources": source_manifest,
        "knowledge_snapshot_statuses": [
            {"claim_id": item.claim_id, "status": item.status.value, "reason": item.reason}
            for item in snapshot.items
        ],
        "source_documents_with_claim_evidence": len(evidence),
    }
    if revision:
        registration["supersedes"] = {
            "frozen_thesis_path": config.get("supersedes_frozen_thesis_path"),
            "frozen_thesis_sha256": config.get("supersedes_frozen_thesis_sha256"),
            "reason": config.get("supersession_reason"),
        }
    manifest_path.write_text(json.dumps(registration, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Frozen thesis: {destination.relative_to(ROOT)}")
    print(f"Thesis hash: {frozen.sha256}")
    print(f"Code commit: {commit}")
    for item in snapshot.items:
        print(f"- {item.claim_id}: {item.status.value} ({item.reason})")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture-sources", action="store_true")
    parser.add_argument("--register-existing-sources", action="store_true")
    parser.add_argument("--freeze", action="store_true")
    parser.add_argument("--frozen-at", help="aware ISO timestamp; defaults to the current UTC time")
    parser.add_argument("--allow-dirty", action="store_true",
                        help="allow local changes while recording the already committed code HEAD")
    parser.add_argument("--revision", choices=("v2",),
                        help="write a versioned registration while preserving the original freeze")
    args = parser.parse_args()
    if args.capture_sources:
        return capture_sources()
    if args.register_existing_sources:
        return register_existing_sources()
    if not args.freeze:
        parser.error("choose --capture-sources or --freeze")
    frozen_at = datetime.fromisoformat(args.frozen_at.replace("Z", "+00:00")) if args.frozen_at else datetime.now(timezone.utc)
    if frozen_at.tzinfo is None:
        parser.error("--frozen-at must include a timezone")
    return freeze(frozen_at, require_clean=not args.allow_dirty, revision=args.revision)


if __name__ == "__main__":
    raise SystemExit(main())
