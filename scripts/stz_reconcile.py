"""Reconcile the frozen STZ Q2 FY2027 thesis against Constellation's own release.

Source: Exhibit 99.1 of Constellation's 6 October 2026 Form 8-K on SEC EDGAR, a
first-party issuer filing. Facts are human-selected verbatim excerpts; no model
supplies values. The release time comes from Constellation's own press-release
feed (explicit -0400 offset), recorded in issuer_release_timestamp.json.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
from datetime import datetime, timezone
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
EVENT = ROOT / "evidence" / "events" / "stz-q2-fy27"
FILING = "https://www.sec.gov/Archives/edgar/data/16918/000001691826000039"
EXHIBIT_URL = f"{FILING}/stzex991_83120268kearnings.htm"
USER_AGENT = "Reverb evidence capture admin@example.invalid"
OUT = EVENT / "post_event"
QWEN_RUNS = 5


def normalize(body: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", body))).strip()


def main() -> None:
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=30) as client:
        exhibit = client.get(EXHIBIT_URL)
        exhibit.raise_for_status()
    captured_at = datetime.now(timezone.utc)
    text = normalize(exhibit.text)
    digest = source_text_sha256(text)
    release = json.loads((OUT / "issuer_release_timestamp.json").read_text())
    published_at = datetime.fromisoformat(release["issuer_release_timestamp"].replace("Z", "+00:00"))

    thesis = FrozenThesis.model_validate_json((EVENT / "frozen_thesis.json").read_text())
    if not verify_frozen_thesis(thesis):
        raise SystemExit("frozen thesis hash does not verify")
    prior_text = (EVENT / "pre_event" / "q2_fy26_release.txt").read_text(encoding="utf-8")

    def cite(excerpt: str) -> Citation:
        offset = text.find(excerpt)
        if offset < 0:
            raise SystemExit(f"excerpt not found verbatim: {excerpt[:60]!r}")
        return Citation(source_url=EXHIBIT_URL, published_at=published_at, captured_at=captured_at,
                        source_sha256=digest, location=f"normalized exhibit text offsets {offset}:{offset + len(excerpt)}",
                        excerpt=excerpt)

    table = re.search(r"BEER Shipments Depletions Net Sales Operating Income \(Loss\) Three Months Ended .*?"
                      r"August 31, 2026 [\d.]+ \$2,473\.6 .*?August 31, 2025 [\d.]+ \$2,345\.0 .*?% Change [\d.]+% \(0\.6%\)", text)
    margin = re.search(r"Operating margin decreased 160 bps to 39\.0% as lower tariff expenses .*?SG&A spend\.", text)
    if not table or not margin:
        raise SystemExit("beer table or beer margin sentence not found in the expected shape")
    facts = (
        MetricFact(claim_id="c1", current_value_text="$2,473.6", prior_value_text="$2,345.0",
                   current_period_text="August 31, 2026", prior_period_text="August 31, 2025",
                   unit="usd", citation=cite(table.group(0))),
        MetricFact(claim_id="c2", current_value_text="(0.6%)", current_period_text="August 31, 2026",
                   unit="percent", citation=cite(table.group(0))),
        MetricFact(claim_id="c3", current_value_text="39.0%", unit="percent", citation=cite(margin.group(0))),
        MetricFact(claim_id="c4", attribution_quote=margin.group(0), citation=cite(margin.group(0))),
    )
    result = reconcile_claims(claims=thesis.claims, knowledge=thesis.knowledge_snapshot, facts=facts,
                              references=thesis.references, frozen_at=thesis.frozen_at,
                              source_documents={digest: text, source_text_sha256(prior_text): prior_text})

    # Live Qwen cross-check: candidate facts only, grounded by code, never scored.
    # Repeated so reliability is measured rather than a single run cherry-picked.
    load_local_env(ROOT)
    claims_payload = [{"claim_id": c.claim_id, "text": c.text, "variable": c.variable,
                       "comparison": c.comparison.value} for c in thesis.claims]
    # Human-selected values per claim; compared numerically so "$2,473.6" and "2,473.6" agree.
    human = {"c1": ("$2,473.6", "$2,345.0"), "c2": ("(0.6%)", None), "c3": ("39.0%", None)}

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

    attempts = []
    try:
        credentials = QwenCredentials.from_env()
    except ReverbError as exc:
        credentials = None
        attempts.append({"status": "unavailable", "error_type": type(exc).__name__})
    def ground(candidates):
        grounded, rejected = [], []
        for fact in candidates:
            try:
                grounded += ground_extracted_facts(
                    extraction=FactExtraction(facts=(fact,)), claims=thesis.claims, source_url=EXHIBIT_URL,
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
        grounded, rejected = [], []
        for fact in candidate.extraction.facts:
            try:
                grounded += ground_extracted_facts(
                    extraction=FactExtraction(facts=(fact,)), claims=thesis.claims, source_url=EXHIBIT_URL,
                    source_text=text, published_at=published_at, captured_at=captured_at)
            except ValueError as exc:
                rejected.append({"claim_id": fact.claim_id, "reason": str(exc)})
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
        "role": "candidate cross-check only; scores come from the human-selected verbatim facts",
        "earlier_run": ("evidence/events/stz-q2-fy27/post_event/qwen_check_before_fix.json: 0 of 5 schema-valid "
                        "before the 2026-10-07 parser fix; kept as recorded."),
        "diagnostic_rule": ("For replies rejected by the strict schema, value-less candidates are dropped and the rest "
                            "grounded by the same code. Reported per attempt; never counted as schema-valid."),
    }

    context = {
        "beer_margin_drivers": ("Constellation states lower tariff expenses helped beer margin and that increased "
                                "marketing and other SG&A spend more than offset it. Tariffs are named as a tailwind, "
                                "not a cause of the decline; c4 stays NOT_ADDRESSED under the frozen pattern."),
        "same_window_release": release.get("same_window_issuer_release"),
        "conference_call": "Not captured; any attribution on the 7 Oct call is not evidence here.",
    }

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "q2_release.txt").write_text(text, encoding="utf-8")
    report = {
        "frozen_thesis_sha256": thesis.sha256,
        "source": {"url": EXHIBIT_URL, "filing_index": f"{FILING}/", "text_path": "evidence/events/stz-q2-fy27/post_event/q2_release.txt",
                   "text_sha256": digest, "captured_at": captured_at.isoformat().replace("+00:00", "Z")},
        "issuer_release_timestamp": {
            "value": release["issuer_release_timestamp"],
            "kind": "ISSUER_PRESS_RELEASE_FEED",
            "note": f"Constellation's own RSS pubDate with explicit offset; 8-K acceptance {release['upper_bound_8k_acceptance']} is the upper bound.",
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
