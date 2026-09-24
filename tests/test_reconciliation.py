from datetime import datetime, timedelta, timezone
from decimal import Decimal
import unittest

from pydantic import ValidationError

from reverb.reconciliation import (
    ClaimStatus,
    ClaimType,
    Citation,
    Comparison,
    ExtractedFactCandidate,
    FactExtraction,
    FrozenReference,
    KnowledgeEvidence,
    KnowledgeStatus,
    MetricFact,
    ThesisClaim,
    ThesisExtraction,
    build_knowledge_snapshot,
    freeze_thesis,
    ground_extracted_facts,
    parse_source_number,
    reconcile_claims,
    source_text_sha256,
    verify_frozen_thesis,
)


FREEZE = datetime(2026, 9, 24, 19, 45, tzinfo=timezone.utc)
RELEASED = FREEZE + timedelta(minutes=20)
CAPTURED = FREEZE - timedelta(days=1)


def claim(claim_id: str, variable: str, comparison: Comparison, text: str,
          unit: str | None = None) -> ThesisClaim:
    return ThesisClaim(claim_id=claim_id, text=text, variable=variable, comparison=comparison,
                       claim_type=ClaimType.QUARTER_FACT, unit=unit)


def citation(body: str, excerpt: str, *, published: datetime, captured: datetime = CAPTURED,
             host: str = "investor.costco.com") -> Citation:
    return Citation(source_url=f"https://{host}/release", published_at=published,
                    captured_at=captured, source_sha256=source_text_sha256(body),
                    location="release, paragraph 1", excerpt=excerpt)


class ReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.eps = claim("c1", "adjusted diluted EPS", Comparison.ABOVE_REFERENCE,
                         "Adjusted EPS beats frozen consensus", "adjusted_eps_usd/share")
        self.fees = claim("c2", "membership fee income", Comparison.UP_YEAR_OVER_YEAR,
                          "Membership-fee income increases year over year", "usd")
        self.margin = claim("c3", "gross margin", Comparison.DOWN_YEAR_OVER_YEAR,
                            "Gross margin declines year over year", "percent")
        self.freight = claim("c4", "freight attribution", Comparison.EXPLICIT_ATTRIBUTION,
                             "Freight costs cause margin pressure")
        self.claims = (self.eps, self.fees, self.margin, self.freight)

        self.eps_doc = "Adjusted diluted EPS was $5.55 per share."
        self.eps_citation = citation(self.eps_doc, self.eps_doc, published=RELEASED)
        self.fee_doc = "Q4 FY2026 membership fee income was $1.30 billion versus $1.25 billion in Q4 FY2025."
        self.fee_citation = citation(self.fee_doc, self.fee_doc, published=RELEASED)
        self.margin_doc = "Q4 FY2026 gross margin was 10.00%, compared with 10.20% in Q4 FY2025."
        self.margin_citation = citation(self.margin_doc, self.margin_doc, published=RELEASED)
        self.freight_doc = "Higher freight costs pressured gross margin during the quarter."
        self.freight_citation = citation(self.freight_doc, self.freight_doc, published=RELEASED)
        self.documents = {
            source_text_sha256(self.eps_doc): self.eps_doc,
            source_text_sha256(self.fee_doc): self.fee_doc,
            source_text_sha256(self.margin_doc): self.margin_doc,
            source_text_sha256(self.freight_doc): self.freight_doc,
        }

        self.facts = (
            MetricFact(claim_id="c1", current_value_text="$5.55", unit="adjusted_eps_usd/share",
                       citation=self.eps_citation),
            MetricFact(claim_id="c2", current_value_text="$1.30 billion", prior_value_text="$1.25 billion",
                       current_period_text="Q4 FY2026", prior_period_text="Q4 FY2025",
                       unit="usd", citation=self.fee_citation),
            MetricFact(claim_id="c3", current_value_text="10.00%", prior_value_text="10.20%",
                       current_period_text="Q4 FY2026", prior_period_text="Q4 FY2025",
                       unit="percent", citation=self.margin_citation),
            MetricFact(claim_id="c4", attribution_quote="Higher freight costs pressured gross margin during the quarter.",
                       citation=self.freight_citation),
        )
        self.references = (FrozenReference(
            claim_id="c1", value_text="$5.50", unit="adjusted_eps_usd/share",
            citation=citation("Captured adjusted EPS consensus was $5.50 per share.",
                              "Captured adjusted EPS consensus was $5.50 per share.",
                              published=FREEZE - timedelta(days=2)),
        ),)
        self.documents[source_text_sha256(self.references[0].citation.excerpt)] = self.references[0].citation.excerpt

    def snapshot(self, known=()):
        return build_knowledge_snapshot(claims=self.claims, evidence=tuple(known), frozen_at=FREEZE,
                                        source_documents=self.documents)

    def test_source_numbers_parse_without_model_math(self):
        self.assertEqual(parse_source_number("$1.30 billion"), Decimal("1300000000.00"))
        self.assertEqual(parse_source_number("10.20%"), Decimal("10.20"))
        with self.assertRaises(ValueError):
            parse_source_number("about five dollars")

    def test_wrong_or_missing_year_comparison_is_not_scored(self):
        body = "Q4 FY2026 membership fee income was $1.30 billion versus $1.25 billion in Q4 FY2024."
        cited = citation(body, body, published=RELEASED)
        self.documents[cited.source_sha256] = body
        bad_period = self.facts[1].model_copy(update={
            "current_period_text": "Q4 FY2026", "prior_period_text": "Q4 FY2024", "citation": cited,
        })
        facts = (self.facts[0], bad_period, *self.facts[2:])
        result = reconcile_claims(claims=self.claims, knowledge=self.snapshot(), facts=facts,
                                  references=self.references, frozen_at=FREEZE,
                                  source_documents=self.documents)
        self.assertEqual(result.claims[1].status, ClaimStatus.NOT_ADDRESSED)

    def test_freeze_requires_units_for_numeric_claims(self):
        untyped = self.claims[1].model_copy(update={"unit": None})
        claims = (self.claims[0], untyped, *self.claims[2:])
        snapshot = build_knowledge_snapshot(claims=claims, evidence=(), frozen_at=FREEZE,
                                            source_documents=self.documents)
        with self.assertRaisesRegex(ValueError, "explicitly reviewed unit"):
            freeze_thesis(
                event="COST Q4 FY2026", thesis_text="approved thesis", claims=claims,
                confirmed_claim_ids={item.claim_id for item in claims}, knowledge_snapshot=snapshot,
                references=self.references, risk_budget_usdt=Decimal("100"),
                reaction_trigger_pct=Decimal("0.03"), baseline_method="pre-close window",
                capture_plan="full-window source capture", code_commit="abcdef1",
                frozen_at=FREEZE, source_documents=self.documents,
            )

    def test_deterministic_reconciliation_and_score_excludes_known_claim(self):
        known_doc = "Before registration, Costco had already reported the claim-resolving membership-fee result."
        known_citation = citation(known_doc, known_doc, published=FREEZE - timedelta(days=1))
        self.documents[known_citation.source_sha256] = known_doc
        known = (KnowledgeEvidence(claim_id="c2", fact_text=known_doc, citation=known_citation),)
        snapshot = self.snapshot(known)
        first = reconcile_claims(claims=self.claims, knowledge=snapshot, facts=self.facts,
                                 references=self.references, frozen_at=FREEZE,
                                 source_documents=self.documents)
        second = reconcile_claims(claims=self.claims, knowledge=snapshot, facts=self.facts,
                                  references=self.references, frozen_at=FREEZE,
                                  source_documents=self.documents)
        self.assertEqual(first, second)
        self.assertEqual([row.status for row in first.claims], [
            ClaimStatus.CONFIRMED, ClaimStatus.ALREADY_KNOWN, ClaimStatus.CONFIRMED,
            ClaimStatus.CONFIRMED,
        ])
        self.assertEqual(first.scored_confirmed, 3)
        self.assertEqual(first.scored_total, 3)

    def test_fee_growth_and_margin_use_comparable_prior_year_values(self):
        snapshot = self.snapshot()
        result = reconcile_claims(claims=self.claims, knowledge=snapshot, facts=self.facts,
                                  references=self.references, frozen_at=FREEZE,
                                  source_documents=self.documents)
        self.assertEqual(result.claims[1].status, ClaimStatus.CONFIRMED)
        self.assertEqual(result.claims[2].status, ClaimStatus.CONFIRMED)
        self.assertEqual(result.claims[1].comparison_value_text, "$1.25 billion")
        self.assertEqual(result.claims[2].comparison_value_text, "10.20%")

    def test_missing_eps_reference_stays_visible_but_unscored(self):
        result = reconcile_claims(claims=self.claims, knowledge=self.snapshot(), facts=self.facts,
                                  references=(), frozen_at=FREEZE, source_documents=self.documents)
        self.assertEqual(result.claims[0].status, ClaimStatus.NOT_ADDRESSED)
        self.assertFalse(result.claims[0].scored)

    def test_explicitly_unscored_claim_can_be_frozen_without_a_unit_or_reference(self):
        unscored_eps = self.eps.model_copy(update={
            "unit": None,
            "scoreable": False,
            "unscored_reason": "No consensus source with a matching EPS basis was frozen.",
        })
        claims = (unscored_eps, *self.claims[1:])
        snapshot = build_knowledge_snapshot(claims=claims, evidence=(), frozen_at=FREEZE,
                                            source_documents=self.documents)
        frozen = freeze_thesis(
            event="COST Q4 FY2026", thesis_text="approved thesis", claims=claims,
            confirmed_claim_ids={item.claim_id for item in claims}, knowledge_snapshot=snapshot,
            references=(), risk_budget_usdt=Decimal("100"),
            reaction_trigger_pct=Decimal("0.03"), baseline_method="pre-close window",
            capture_plan="full-window source capture", code_commit="abcdef1",
            frozen_at=FREEZE, source_documents=self.documents,
        )
        self.assertTrue(verify_frozen_thesis(frozen))
        result = reconcile_claims(claims=claims, knowledge=snapshot, facts=self.facts,
                                  references=(), frozen_at=FREEZE,
                                  source_documents=self.documents)
        self.assertEqual(result.claims[0].status, ClaimStatus.NOT_ADDRESSED)
        self.assertFalse(result.claims[0].scored)
        self.assertIn("No consensus source", result.claims[0].reason)

    def test_scoreable_reference_claim_cannot_be_frozen_without_a_reference(self):
        snapshot = self.snapshot()
        with self.assertRaisesRegex(ValueError, "benchmark frozen first"):
            freeze_thesis(
                event="COST Q4 FY2026", thesis_text="approved thesis", claims=self.claims,
                confirmed_claim_ids={item.claim_id for item in self.claims},
                knowledge_snapshot=snapshot, references=(), risk_budget_usdt=Decimal("100"),
                reaction_trigger_pct=Decimal("0.03"), baseline_method="pre-close window",
                capture_plan="full-window source capture", code_commit="abcdef1",
                frozen_at=FREEZE, source_documents=self.documents,
            )

    def test_number_not_verbatim_in_source_is_rejected(self):
        bad_fact = self.facts[0].model_copy(update={"current_value_text": "$5.56"})
        with self.assertRaisesRegex(ValueError, "not verbatim"):
            reconcile_claims(claims=self.claims, knowledge=self.snapshot(),
                             facts=(bad_fact, *self.facts[1:]), references=self.references,
                             frozen_at=FREEZE, source_documents=self.documents)

    def test_release_fact_extraction_is_grounded_and_gets_code_location(self):
        candidate = ExtractedFactCandidate(
            claim_id="c1", current_value_text="$5.55", excerpt=self.eps_doc,
        )
        grounded = ground_extracted_facts(
            extraction=FactExtraction(facts=(candidate,)), claims=self.claims,
            source_url="https://investor.costco.com/release", source_text=self.eps_doc,
            published_at=RELEASED, captured_at=RELEASED + timedelta(seconds=2),
        )
        self.assertEqual(grounded[0].unit, "adjusted_eps_usd/share")
        self.assertIn("offsets 0:", grounded[0].citation.location)
        self.assertEqual(grounded[0].citation.source_sha256, source_text_sha256(self.eps_doc))

    def test_release_fact_candidate_cannot_invent_value_or_status(self):
        with self.assertRaisesRegex(ValueError, "does not appear verbatim"):
            ground_extracted_facts(
                extraction=FactExtraction(facts=(ExtractedFactCandidate(
                    claim_id="c1", current_value_text="$5.56", excerpt=self.eps_doc,
                ),)), claims=self.claims, source_url="https://investor.costco.com/release",
                source_text=self.eps_doc, published_at=RELEASED, captured_at=RELEASED,
            )
        with self.assertRaises(ValidationError):
            FactExtraction.model_validate({"facts": [{
                "claim_id": "c1", "current_value_text": "$5.55", "excerpt": self.eps_doc,
                "status": "CONFIRMED",
            }]})

    def test_freight_requires_an_explicit_source_link_not_margin_direction(self):
        noncausal = "Freight costs increased. Gross margin was lower year over year."
        c = citation(noncausal, noncausal, published=RELEASED)
        docs = {**self.documents, source_text_sha256(noncausal): noncausal}
        facts = (*self.facts[:3], MetricFact(claim_id="c4", attribution_quote=noncausal, citation=c))
        result = reconcile_claims(claims=self.claims, knowledge=self.snapshot(), facts=facts,
                                  references=self.references, frozen_at=FREEZE, source_documents=docs)
        self.assertEqual(result.claims[3].status, ClaimStatus.NOT_ADDRESSED)

    def test_future_or_uncaptured_public_evidence_does_not_mark_known(self):
        doc = "The future earnings result is disclosed."
        future = citation(doc, doc, published=FREEZE + timedelta(minutes=1),
                          captured=FREEZE - timedelta(hours=1))
        late_capture = citation(doc, doc, published=FREEZE - timedelta(hours=1),
                                captured=FREEZE + timedelta(minutes=1))
        evidence = (KnowledgeEvidence(claim_id="c1", fact_text=doc, citation=future),
                    KnowledgeEvidence(claim_id="c1", fact_text=doc, citation=late_capture))
        self.documents[source_text_sha256(doc)] = doc
        snapshot = self.snapshot(evidence)
        self.assertEqual(snapshot.items[0].status, KnowledgeStatus.UNKNOWN)

    def test_extraction_schema_rejects_model_authored_outcome_status(self):
        with self.assertRaises(ValidationError):
            ThesisExtraction.model_validate({"claims": [{
                "claim_id": "c1", "text": "EPS beats consensus", "variable": "EPS",
                "comparison": "ABOVE_REFERENCE", "claim_type": "QUARTER_FACT",
                "status": "CONFIRMED",
            }]})
        with self.assertRaises(ValidationError):
            ThesisExtraction.model_validate({"claims": [{
                "claim_id": "c1", "text": "EPS beats consensus", "variable": "EPS",
                "comparison": "ABOVE_REFERENCE", "claim_type": "QUARTER_FACT",
                "unit": "adjusted EPS",
            }]})

    def test_freeze_requires_confirmation_of_every_claim_and_hash_verifies(self):
        snapshot = self.snapshot()
        kwargs = dict(event="COST Q4 FY2026", thesis_text="approved thesis", claims=self.claims,
                      knowledge_snapshot=snapshot, references=self.references,
                      risk_budget_usdt=Decimal("100"), reaction_trigger_pct=Decimal("0.03"),
                      baseline_method="pre-close window ending 16:00 ET",
                      capture_plan="continuous capture with exchange and receipt timestamps",
                      code_commit="abcdef1", frozen_at=FREEZE, source_documents=self.documents)
        with self.assertRaisesRegex(ValueError, "explicitly confirm"):
            freeze_thesis(**kwargs, confirmed_claim_ids={"c1"})
        frozen = freeze_thesis(**kwargs, confirmed_claim_ids={claim.claim_id for claim in self.claims})
        self.assertTrue(verify_frozen_thesis(frozen))
        changed = frozen.model_copy(update={"risk_budget_usdt": Decimal("101")})
        self.assertFalse(verify_frozen_thesis(changed))


if __name__ == "__main__":
    unittest.main()
