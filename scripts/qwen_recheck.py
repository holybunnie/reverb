"""Re-run the Qwen release-fact cross-check for a scored event with the current prompt and parser.

Writes post_event/qwen_recheck_<label>.json beside the event's reconciliation and never
touches scores: those come only from the human-selected facts already committed. The
human selection is read from the committed reconciliation, not typed here. A recheck of
an event whose failures informed the prompt is in-sample and is labelled as such.

    python scripts/qwen_recheck.py costco --label 2026-10-07 --sample in-sample
"""
from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from reverb.env import load_local_env  # noqa: E402
from reverb.errors import ReverbError  # noqa: E402
from reverb.qwen import QwenClient, QwenCredentials  # noqa: E402
from reverb.reconciliation import (  # noqa: E402
    Comparison, FactExtraction, FrozenThesis, ground_extracted_facts, parse_fact_value,
)

EVENTS = {
    "costco": {"dir": ROOT / "evidence/costco", "thesis": "frozen_thesis_v2.json"},
    "stz-q2-fy27": {"dir": ROOT / "evidence/events/stz-q2-fy27", "thesis": "frozen_thesis.json"},
    "apld-q1-fy27": {"dir": ROOT / "evidence/events/apld-q1-fy27", "thesis": "frozen_thesis.json"},
}
RUNS = 5
# Claims whose comparison value is a frozen reference rather than a figure from the release.
REFERENCE_RULES = {Comparison.ABOVE_REFERENCE, Comparison.BELOW_REFERENCE, Comparison.STATED_INCREASE}


def prompt_sha256() -> str:
    """Identify the prompt and parser revision by hashing the extraction method's source."""
    return hashlib.sha256(inspect.getsource(QwenClient.extract_release_facts).encode()).hexdigest()


def number(value: str | None):
    if value is None:
        return None
    try:
        return parse_fact_value(value)
    except ValueError:
        return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("event", choices=sorted(EVENTS))
    parser.add_argument("--label", required=True)
    parser.add_argument("--sample", choices=("in-sample", "out-of-sample"), required=True,
                        help="in-sample when this event's failures informed the current prompt")
    args = parser.parse_args()
    event = EVENTS[args.event]
    thesis = FrozenThesis.model_validate_json((event["dir"] / event["thesis"]).read_text())
    recon = json.loads((event["dir"] / "post_event/reconciliation.json").read_text())
    text = (ROOT / recon["source"]["text_path"]).read_text(encoding="utf-8")
    release_at = datetime.fromisoformat(recon["issuer_release_timestamp"]["value"].replace("Z", "+00:00"))
    rules = {c.claim_id: c.comparison for c in thesis.claims}
    human = {}
    for row in recon["reconciliation"]["claims"]:
        if row["scored"] and row["current_value_text"]:
            prior = None if rules[row["claim_id"]] in REFERENCE_RULES else row["comparison_value_text"]
            human[row["claim_id"]] = (row["current_value_text"], prior)

    def matches(facts, cid) -> bool:
        current, prior = human[cid]
        return any(f.claim_id == cid and number(f.current_value_text) == number(current)
                   and (prior is None or number(f.prior_value_text) == number(prior)) for f in facts)

    load_local_env(ROOT)
    claims_payload = [{"claim_id": c.claim_id, "text": c.text, "variable": c.variable,
                       "comparison": c.comparison.value} for c in thesis.claims]
    credentials = QwenCredentials.from_env()
    attempts = []
    for _ in range(RUNS):
        try:
            with QwenClient(credentials) as model:
                candidate = model.extract_release_facts(release_text=text, claims=claims_payload,
                                                        reporting_period=thesis.event)
        except (ReverbError, ValueError) as exc:
            attempts.append({"status": "rejected_or_unavailable", "error_type": type(exc).__name__,
                             "reason": str(exc)[:200]})
            continue
        grounded, rejected = [], []
        for fact in candidate.extraction.facts:
            try:
                grounded += ground_extracted_facts(
                    extraction=FactExtraction(facts=(fact,)), claims=thesis.claims, source_url=recon["source"]["url"],
                    source_text=text, published_at=release_at, captured_at=datetime.now(timezone.utc))
            except ValueError as exc:
                rejected.append({"claim_id": fact.claim_id, "reason": str(exc)})
        attempts.append({
            "status": "returned", "output_sha256": candidate.output_sha256,
            "unaddressed_claim_ids": list(candidate.unaddressed_claim_ids),
            "parser_rejected_facts": [{"claim_id": cid, "reason": why} for cid, why in candidate.rejected_facts],
            "grounded_facts": [{"claim_id": f.claim_id, "current": f.current_value_text, "prior": f.prior_value_text,
                                "current_period": f.current_period_text, "prior_period": f.prior_period_text}
                               for f in grounded],
            "rejected_candidates": rejected,
            "claims_matching_human_selection": sorted(cid for cid in human if matches(grounded, cid)),
        })
    per_claim = {cid: sum(cid in a.get("claims_matching_human_selection", []) for a in attempts) for cid in human}
    report = {
        "event": thesis.event, "label": args.label, "sample": args.sample,
        "note": ("In-sample: this event's earlier failures informed the prompt revision, so this shows "
                 "whether the fix works on the case it was built from, not how it generalises."
                 if args.sample == "in-sample" else
                 "Out-of-sample: the prompt revision was committed before this event's release."),
        "prompt_method_sha256": prompt_sha256(), "model": credentials.model,
        "checked_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "runs": len(attempts), "schema_valid_runs": sum(a["status"] == "returned" for a in attempts),
        "human_selection": {cid: {"current": c, "prior": p} for cid, (c, p) in human.items()},
        "runs_matching_per_claim": per_claim,
        "runs_matching_every_claim": sum(set(human) <= set(a.get("claims_matching_human_selection", []))
                                         for a in attempts),
        "attempts": attempts,
        "role": "candidate cross-check only; scores come from the human-selected verbatim facts",
    }
    out = event["dir"] / f"post_event/qwen_recheck_{args.label}.json"
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("event", "sample", "runs", "schema_valid_runs",
                                             "runs_matching_per_claim", "runs_matching_every_claim")}, indent=1))


if __name__ == "__main__":
    main()
