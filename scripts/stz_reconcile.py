"""Reconcile the frozen STZ Q2 FY2027 thesis against Constellation's own release.

Source: Exhibit 99.1 of Constellation's 6 October 2026 Form 8-K on SEC EDGAR, a
first-party issuer filing. Facts are human-selected verbatim excerpts; no model
supplies values. The release time comes from Constellation's own press-release
feed (explicit -0400 offset), recorded in issuer_release_timestamp.json.
"""
from __future__ import annotations

import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import httpx

from reverb.reconciliation import (
    Citation, FrozenThesis, MetricFact, reconcile_claims, source_text_sha256, verify_frozen_thesis,
)

ROOT = Path(__file__).resolve().parents[1]
EVENT = ROOT / "evidence" / "events" / "stz-q2-fy27"
FILING = "https://www.sec.gov/Archives/edgar/data/16918/000001691826000039"
EXHIBIT_URL = f"{FILING}/stzex991_83120268kearnings.htm"
USER_AGENT = "Reverb evidence capture admin@example.invalid"
OUT = EVENT / "post_event"


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

    context = {
        "beer_margin_drivers": ("Constellation states lower tariff expenses helped beer margin and that increased "
                                "marketing and other SG&A spend more than offset it. Tariffs are named as a tailwind, "
                                "not a cause of the decline; c4 stays NOT_ADDRESSED under the frozen pattern."),
        "same_window_release": release.get("same_window_issuer_release"),
        "conference_call": "Not captured; any attribution on the 7 Oct call is not evidence here.",
        "qwen_release_check": "Not run for this event; scores come from the human-selected verbatim facts.",
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
        "unscored_context": context,
    }
    (OUT / "reconciliation.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"scored": f"{result.scored_confirmed}/{result.scored_total}",
                      "claims": {row.claim_id: [row.status.value, row.reason] for row in result.claims}}, indent=2))


if __name__ == "__main__":
    main()
