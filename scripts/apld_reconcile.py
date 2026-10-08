"""Reconcile the frozen APLD Q1 FY2027 thesis against Applied Digital's own release.

Source: Exhibit 99.1 of Applied Digital's 7 October 2026 Form 8-K on SEC EDGAR, a
first-party issuer filing, as saved by event_post_capture.py (hash-checked here, not
refetched). Facts are hand-selected verbatim excerpts; no model supplies values. The
release time comes from Applied Digital's own press-release feed (explicit -0400
offset), recorded in issuer_release_timestamp.json.

The Qwen cross-check is the out-of-sample test of the 2026-10-07 prompt revision: the
script refuses to run it unless the prompt method still hashes to the recorded value.
"""
from __future__ import annotations

import hashlib
import html
import inspect
import json
import re
from datetime import datetime
from pathlib import Path

import httpx

from reverb.env import load_local_env
from reverb.errors import ReverbError
from reverb.qwen import QwenClient, QwenCredentials
from reverb.reconciliation import (
    Citation, ExtractedFactCandidate, FactExtraction, FrozenThesis, MetricFact, ground_extracted_facts, parse_source_number,
    reconcile_claims, source_text_sha256, verify_frozen_thesis,
)

ROOT = Path(__file__).resolve().parents[1]
EVENT = ROOT / "evidence" / "events" / "apld-q1-fy27"
OUT = EVENT / "post_event"
QWEN_RUNS = 5


def normalize(body: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", body))).strip()


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def main() -> None:
    source = json.loads((OUT / "release_source.json").read_text())
    body = (OUT / "release_exhibit_99_1.htm").read_bytes()
    if hashlib.sha256(body).hexdigest() != source["html_sha256"]:
        raise SystemExit("saved exhibit does not match its recorded hash")
    text = normalize(body.decode("utf-8", errors="replace"))
    if text != (OUT / "release.txt").read_text(encoding="utf-8"):
        raise SystemExit("saved release text does not match the exhibit")
    exhibit_url, captured_at = source["url"], parse_time(source["captured_at"])
    digest = source_text_sha256(text)
    release = json.loads((OUT / "issuer_release_timestamp.json").read_text())
    published_at = parse_time(release["issuer_release_timestamp"])

    thesis = FrozenThesis.model_validate_json((EVENT / "frozen_thesis.json").read_text())
    if not verify_frozen_thesis(thesis):
        raise SystemExit("frozen thesis hash does not verify")
    prior_text = (EVENT / "pre_event" / "q4_fy26_release.txt").read_text(encoding="utf-8")

    def cite(excerpt: str) -> Citation:
        offset = text.find(excerpt)
        if offset < 0 or text.find(excerpt, offset + 1) >= 0:
            raise SystemExit(f"excerpt not found exactly once: {excerpt[:60]!r}")
        return Citation(source_url=exhibit_url, published_at=published_at, captured_at=captured_at,
                        source_sha256=digest, location=f"normalized exhibit text offsets {offset}:{offset + len(excerpt)}",
                        excerpt=excerpt)

    revenue = "Revenues: $341.9 million, up 322% from the prior year comparable period"
    ebitda = "Adjusted EBITDA: $64.4 million"
    net_loss = "Net loss attributable to common stockholders: $221.0 million"
    capacity = "As of August 31, 2026, the Company has leases for approximately 1.41 GW of critical IT load across five campuses"
    facts = (
        MetricFact(claim_id="c1", current_value_text="$341.9 million", unit="usd", citation=cite(revenue)),
        MetricFact(claim_id="c2", current_value_text="$64.4 million", unit="usd", citation=cite(ebitda)),
        MetricFact(claim_id="c3", current_value_text="$221.0 million", unit="usd", citation=cite(net_loss)),
        # The release states GW; the frozen claim and reference are MW. The code compares only like
        # units and nothing converts after the fact, so this is recorded as stated.
        MetricFact(claim_id="c4", current_value_text="1.41", unit="GW", citation=cite(capacity)),
    )
    result = reconcile_claims(claims=thesis.claims, knowledge=thesis.knowledge_snapshot, facts=facts,
                              references=thesis.references, frozen_at=thesis.frozen_at,
                              source_documents={digest: text, source_text_sha256(prior_text): prior_text})

    # Live Qwen cross-check: candidate facts only, grounded by code, never scored.
    revision = json.loads((ROOT / "evidence/qwen/release_prompt_revision.json").read_text())
    prompt_sha256 = hashlib.sha256(inspect.getsource(QwenClient.extract_release_facts).encode()).hexdigest()
    if prompt_sha256 != revision["prompt_method_sha256"]:
        raise SystemExit("Qwen release prompt changed since the recorded revision; the out-of-sample test would not hold")
    load_local_env(ROOT)
    claims_payload = [{"claim_id": c.claim_id, "text": c.text, "variable": c.variable,
                       "comparison": c.comparison.value} for c in thesis.claims]
    # Hand-selected values per scored claim; compared numerically so "$341.9 million" and "341.9 million" agree.
    human = {"c1": ("$341.9 million", None), "c2": ("$64.4 million", None), "c3": ("$221.0 million", None)}

    def number(value: str | None):
        if value is None:
            return None
        try:
            stripped = value.strip()
            negative = stripped.startswith("(") and stripped.endswith(")")
            parsed = parse_source_number(stripped.strip("()"))
            return -parsed if negative else parsed
        except ValueError:
            return value

    def matches(facts, cid, pair) -> bool:
        return any(f.claim_id == cid and number(f.current_value_text) == number(pair[0])
                   and (pair[1] is None or number(f.prior_value_text) == number(pair[1])) for f in facts)

    def ground(candidates):
        grounded, rejected = [], []
        for fact in candidates:
            try:
                grounded += ground_extracted_facts(
                    extraction=FactExtraction(facts=(fact,)), claims=thesis.claims, source_url=exhibit_url,
                    source_text=text, published_at=published_at, captured_at=captured_at)
            except ValueError as exc:
                rejected.append({"claim_id": fact.claim_id, "reason": str(exc)})
        return grounded, rejected

    def diagnose(raw: str) -> dict:
        """Disclosed diagnostic, not the strict check: drop value-less candidates, ground the rest."""
        try:
            items = json.loads(raw)["facts"]
        except (ValueError, KeyError, TypeError):
            return {"parsed": False}
        empty = [item.get("claim_id") for item in items
                 if not any(item.get(k) for k in ("current_value_text", "prior_value_text", "attribution_quote"))]
        kept = []
        for item in items:
            if item.get("claim_id") in empty:
                continue
            try:
                kept.append(ExtractedFactCandidate.model_validate(item))
            except ValueError as exc:
                return {"parsed": True, "value_less_candidates": empty, "other_schema_error": str(exc)[:200]}
        grounded, rejected = ground(kept)
        return {"parsed": True, "value_less_candidates": empty,
                "grounded_facts": [{"claim_id": f.claim_id, "current": f.current_value_text,
                                    "prior": f.prior_value_text} for f in grounded],
                "rejected_candidates": rejected,
                "claims_matching_human_selection": sorted(cid for cid, pair in human.items() if matches(grounded, cid, pair))}

    attempts = []
    try:
        credentials = QwenCredentials.from_env()
    except ReverbError as exc:
        credentials = None
        attempts.append({"status": "unavailable", "error_type": type(exc).__name__})
    for _ in range(QWEN_RUNS if credentials else 0):
        raw_replies: list[str] = []

        def keep_reply(response: httpx.Response) -> None:
            response.read()
            try:
                raw_replies.append(response.json()["choices"][0]["message"]["content"])
            except (ValueError, KeyError, IndexError, TypeError):
                pass

        try:
            with QwenClient(credentials) as model:
                model._client.event_hooks["response"].append(keep_reply)
                candidate = model.extract_release_facts(release_text=text, claims=claims_payload)
        except (ReverbError, ValueError) as exc:
            attempt = {"status": "rejected_or_unavailable", "error_type": type(exc).__name__, "reason": str(exc)[:200]}
            if raw_replies:
                attempt["output_sha256"] = hashlib.sha256(raw_replies[-1].encode()).hexdigest()
                attempt["diagnostic"] = diagnose(raw_replies[-1])
            attempts.append(attempt)
            continue
        grounded, rejected = ground(candidate.extraction.facts)
        attempts.append({
            "status": "returned", "output_sha256": candidate.output_sha256,
            "unaddressed_claim_ids": list(candidate.unaddressed_claim_ids),
            "parser_rejected_facts": [{"claim_id": cid, "reason": why} for cid, why in candidate.rejected_facts],
            "grounded_facts": [{"claim_id": f.claim_id, "current": f.current_value_text, "prior": f.prior_value_text,
                                "current_period": f.current_period_text, "prior_period": f.prior_period_text,
                                "attribution_quote": f.attribution_quote} for f in grounded],
            "rejected_candidates": rejected,
            "claims_matching_human_selection": sorted(cid for cid, pair in human.items() if matches(grounded, cid, pair)),
            "matches_human_selection": all(matches(grounded, cid, pair) for cid, pair in human.items()),
        })
    qwen = {
        "provider": "bitget-qwen", "model": credentials.model if credentials else None, "runs": len(attempts),
        "schema_valid_runs": sum(a["status"] == "returned" for a in attempts),
        "runs_matching_human_selection": sum(bool(a.get("matches_human_selection")) for a in attempts),
        "human_selection": {cid: {"current": pair[0], "prior": pair[1]} for cid, pair in human.items()},
        "attempts": attempts,
        "role": "candidate cross-check only; scores come from the hand-selected verbatim facts",
        "prompt_method_sha256": prompt_sha256,
        "out_of_sample": ("First event released after the 2026-10-07 prompt revision "
                          "(evidence/qwen/release_prompt_revision.json); the prompt hash above matches it."),
        "diagnostic_rule": ("For replies rejected by the strict schema, value-less candidates are dropped and the rest "
                            "grounded by the same code. Reported per attempt; never counted as schema-valid."),
    }

    context = {
        "contracted_capacity_unit": ("Applied Digital states leases for approximately 1.41 GW of critical IT load as of "
                                     "August 31, 2026. The frozen claim and reference are in MW, and nothing converts units "
                                     "after the release, so c4 is not addressed. 1.41 GW equals the frozen 1,410 MW; it is "
                                     "not above it."),
        "new_lease": ("The only lease in Recent Highlights is the 210 MW Delta Forge 2 lease, announced 8 June 2026, "
                      "before the freeze. Subsequent to the quarter the release lists a capacity delivery, a Finland power "
                      "agreement and a power purchase agreement, not a new lease."),
        "net_loss_basis": ("Both releases report continuing operations only. Q1 FY27 continuing net loss attributable to "
                           "common stockholders is $221.0 million; including discontinued operations it is $237.1 million. "
                           "Either way it is above the frozen $110.6 million."),
        "conference_call": "Not captured; anything said on the call is not evidence here.",
    }

    report = {
        "frozen_thesis_sha256": thesis.sha256,
        "source": {"url": exhibit_url, "filing_index": source["filing_index"], "text_path": source["text_path"],
                   "text_sha256": digest, "html_sha256": source["html_sha256"], "captured_at": source["captured_at"]},
        "issuer_release_timestamp": {
            "value": release["issuer_release_timestamp"],
            "kind": "ISSUER_PRESS_RELEASE_FEED",
            "note": f"Applied Digital's own RSS pubDate with explicit offset; 8-K acceptance {release['upper_bound_8k_acceptance']} is the upper bound.",
        },
        "reconciliation": json.loads(result.model_dump_json()),
        "qwen_release_check": qwen,
        "unscored_context": context,
    }
    (OUT / "reconciliation.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"scored": f"{result.scored_confirmed}/{result.scored_total}",
                      "qwen": {k: qwen[k] for k in ("runs", "schema_valid_runs", "runs_matching_human_selection")},
                      "claims": {row.claim_id: [row.status.value, row.reason] for row in result.claims}}, indent=2))


if __name__ == "__main__":
    main()
