"""Reconcile the frozen Costco v2 thesis against Costco's own Q4 FY2026 release.

Source: Exhibit 99.1 of Costco's 24 September 2026 Form 8-K on SEC EDGAR, a
first-party issuer filing (investor.costco.com is behind a bot challenge from
this host). Facts are human-selected verbatim excerpts; no model supplies values.
The 8-K acceptance time is an upper bound on release time, not the wire time.
"""
from __future__ import annotations

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
    ADDENDUM_RULE_ADDED, ADDENDUM_RULE_ID, Citation, FactExtraction, FrozenThesis, MetricFact, StatedChangeFact,
    ground_extracted_facts, reconcile_claims, reconcile_stated_changes, source_text_sha256,
    verify_frozen_thesis,
)

ROOT = Path(__file__).resolve().parents[1]
FILING = "https://www.sec.gov/Archives/edgar/data/909832/000090983226000084"
EXHIBIT_URL = f"{FILING}/costex9918-k92426.htm"
SUPPLEMENT_URL = f"{FILING}/costex9928-k92426.htm"
HEADER_URL = f"{FILING}/0000909832-26-000084-index-headers.html"
USER_AGENT = "Reverb evidence capture admin@example.invalid"
OUT = ROOT / "evidence" / "costco" / "post_event"
QWEN_RUNS = 5


def normalize(body: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", body))).strip()


def acceptance_utc(header: str) -> datetime:
    # EDGAR ACCEPTANCE-DATETIME is US Eastern; 24 Sep 2026 is EDT (UTC-4).
    stamp = re.search(r"ACCEPTANCE-DATETIME>\s*(\d{14})", header)
    if not stamp:
        raise SystemExit("EDGAR header has no ACCEPTANCE-DATETIME")
    local = datetime.strptime(stamp.group(1), "%Y%m%d%H%M%S")
    if local.date().isoformat() != "2026-09-24":
        raise SystemExit("unexpected filing date; revisit the EDT offset")
    return local.replace(tzinfo=timezone.utc) + (datetime(2000, 1, 1, 4) - datetime(2000, 1, 1))


def main() -> None:
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=30) as client:
        exhibit = client.get(EXHIBIT_URL)
        exhibit.raise_for_status()
        header = client.get(HEADER_URL)
        header.raise_for_status()
        supplement = client.get(SUPPLEMENT_URL)
        supplement.raise_for_status()
    captured_at = datetime.now(timezone.utc)
    text = normalize(exhibit.text)
    published_at = acceptance_utc(header.text)
    digest = source_text_sha256(text)

    thesis = FrozenThesis.model_validate_json((ROOT / "evidence/costco/frozen_thesis_v2.json").read_text())
    if not verify_frozen_thesis(thesis):
        raise SystemExit("frozen thesis hash does not verify")

    supplement_text = normalize(supplement.text)
    supplement_digest = source_text_sha256(supplement_text)

    def cite(excerpt: str, *, source: str = text, url: str = EXHIBIT_URL) -> Citation:
        offset = source.find(excerpt)
        if offset < 0:
            raise SystemExit(f"excerpt not found verbatim: {excerpt[:60]!r}")
        return Citation(source_url=url, published_at=published_at, captured_at=captured_at,
                        source_sha256=source_text_sha256(source),
                        location=f"normalized exhibit text offsets {offset}:{offset + len(excerpt)}",
                        excerpt=excerpt)

    table = re.search(r"16 Weeks Ended 52 Weeks Ended August 30, 2026 August 31, 2025 .*?Membership fees 1,850 1,724", text)
    if not table:
        raise SystemExit("membership-fee row not found in the expected table shape")
    facts = (
        MetricFact(claim_id="c2", current_value_text="1,850", prior_value_text="1,724",
                   current_period_text="August 30, 2026", prior_period_text="August 31, 2025",
                   unit="usd", citation=cite(table.group(0))),
    )
    result = reconcile_claims(claims=thesis.claims, knowledge=thesis.knowledge_snapshot, facts=facts,
                              references=thesis.references, frozen_at=thesis.frozen_at,
                              source_documents={digest: text})

    # Disclosed post-release addendum: Exhibit 99.2 states the margin change directly.
    margin = re.search(r"Fourth Quarter FY 2026 .*?Gross Margin 11\.02% -11 bps vs Q4 FY.25", supplement_text)
    if not margin:
        raise SystemExit("gross-margin statement not found in Exhibit 99.2")
    prior_label = re.search(r"Q4 FY.25", margin.group(0)).group(0)
    addendum = reconcile_stated_changes(
        claims=thesis.claims, frozen=result, frozen_at=thesis.frozen_at,
        facts=(StatedChangeFact(claim_id="c3", change_text="-11 bps", current_period_text="Fourth Quarter FY 2026",
                                prior_period_text=prior_label,
                                citation=cite(margin.group(0), source=supplement_text, url=SUPPLEMENT_URL)),),
        source_documents={digest: text, supplement_digest: supplement_text})
    addendum_by_id = {row.claim_id: row for row in addendum}
    combined = [addendum_by_id.get(row.claim_id, row) for row in result.claims]
    scored = [row for row in combined if row.scored]

    # Live Qwen cross-check: candidate facts only, grounded by code, never scored.
    # Repeated so reliability is measured rather than a single run cherry-picked.
    load_local_env(ROOT)
    claims_payload = [{"claim_id": c.claim_id, "text": c.text, "variable": c.variable,
                       "comparison": c.comparison.value} for c in thesis.claims]
    human = {"c2": ("1,850", "1,724")}
    attempts = []
    try:
        credentials = QwenCredentials.from_env()
    except ReverbError as exc:
        credentials = None
        attempts.append({"status": "unavailable", "error_type": type(exc).__name__})
    for _ in range(QWEN_RUNS if credentials else 0):
        try:
            with QwenClient(credentials) as model:
                candidate = model.extract_release_facts(release_text=text, claims=claims_payload)
        except (ReverbError, ValueError) as exc:
            attempts.append({"status": "rejected_or_unavailable", "error_type": type(exc).__name__,
                             "reason": str(exc)[:200]})
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
            "grounded_facts": [{"claim_id": f.claim_id, "current": f.current_value_text, "prior": f.prior_value_text,
                                "current_period": f.current_period_text, "prior_period": f.prior_period_text,
                                "attribution_quote": f.attribution_quote} for f in grounded],
            "rejected_candidates": rejected,
            "matches_human_selection": all(
                any(f.claim_id == cid and (f.current_value_text, f.prior_value_text) == pair for f in grounded)
                for cid, pair in human.items()),
        })
    qwen = {
        "provider": "bitget-qwen", "model": credentials.model if credentials else None, "runs": len(attempts),
        "schema_valid_runs": sum(a["status"] == "returned" for a in attempts),
        "runs_matching_human_selection": sum(bool(a.get("matches_human_selection")) for a in attempts),
        "attempts": attempts,
        "role": "candidate cross-check only; scores come from the human-selected verbatim facts",
    }

    # Unscored context: derived, not verbatim, so the frozen rules cannot score it.
    sales = re.search(r"Net sales \$ ([\d,]+) \$ ([\d,]+)", text)
    costs = re.search(r"Merchandise costs ([\d,]+) ([\d,]+)", text)
    n = lambda value: int(value.replace(",", ""))
    margin = lambda s, c: round((n(s) - n(c)) / n(s) * 100, 3)
    context = {
        "derived_gross_margin_pct_of_net_sales": {
            "q4_fy2026": margin(sales.group(1), costs.group(1)),
            "q4_fy2025": margin(sales.group(2), costs.group(2)),
            "note": "Derived as (net sales - merchandise costs) / net sales; not stated verbatim, so c3 is not scored.",
        },
        "diluted_eps": "$6.75 reported, including a stated non-recurring $0.15 IEEPA tariff-refund benefit; c1 stays unscored (no matching-basis consensus frozen).",
        "freight_mentioned_in_release": "freight" in text.casefold(),
        "conference_call": "Not captured; any freight attribution on the call is not evidence here.",
    }

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "q4_release.txt").write_text(text, encoding="utf-8")
    (OUT / "q4_supplement.txt").write_text(supplement_text, encoding="utf-8")
    report = {
        "frozen_thesis_sha256": thesis.sha256,
        "source": {"url": EXHIBIT_URL, "filing_index": f"{FILING}/", "text_path": "evidence/costco/post_event/q4_release.txt",
                   "text_sha256": digest, "captured_at": captured_at.isoformat().replace("+00:00", "Z")},
        "issuer_release_timestamp": {
            "value": published_at.isoformat().replace("+00:00", "Z"),
            "kind": "UPPER_BOUND_8K_ACCEPTANCE",
            "note": "SEC acceptance of the 8-K carrying the release; the wire release may be earlier.",
        },
        "reconciliation": json.loads(result.model_dump_json()),
        "addendum": {
            "rule": ADDENDUM_RULE_ID, "added": ADDENDUM_RULE_ADDED,
            "disclosure": ("Added after the release. Scores a YoY claim the frozen rules left NOT_ADDRESSED "
                           "when the issuer states the signed change verbatim. Frozen results are unchanged."),
            "source": {"url": SUPPLEMENT_URL, "text_path": "evidence/costco/post_event/q4_supplement.txt",
                       "text_sha256": supplement_digest},
            "claims": [json.loads(row.model_dump_json()) for row in addendum],
            "scored_confirmed": sum(row.status.value == "CONFIRMED" for row in scored),
            "scored_total": len(scored),
        },
        "qwen_release_check": qwen,
        "unscored_context": context,
    }
    (OUT / "reconciliation.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"scored": f"{result.scored_confirmed}/{result.scored_total}",
                      "with_addendum": f"{report['addendum']['scored_confirmed']}/{report['addendum']['scored_total']}",
                      "qwen": {k: qwen[k] for k in ("runs", "schema_valid_runs", "runs_matching_human_selection")},
                      "claims": {row.claim_id: row.status.value for row in result.claims},
                      "context": context, "release_upper_bound": report["issuer_release_timestamp"]["value"]}, indent=2))


if __name__ == "__main__":
    main()
