import unittest
from datetime import datetime, timezone
from decimal import Decimal

from reverb.reconciliation import (
    _ALUMINUM_TARIFF_CAUSAL, _FREIGHT_CAUSAL, Citation, ClaimStatus, ClaimType, Comparison, KnowledgeItem,
    KnowledgeSnapshot, KnowledgeStatus, MetricFact, ThesisClaim, parse_signed_percent, reconcile_claims,
    source_text_sha256,
)

STZ_2025 = ("Operating margin decreased 200 basis points to 40.6% primarily due to unfavorable impacts from "
            "increased COGS (inclusive of fixed cost absorption from lower volumes and aluminum tariffs) and "
            "increased marketing as a percentage of net sales, partly offset by favorable pricing.")
FROZEN = datetime(2026, 10, 4, 18, 0, tzinfo=timezone.utc)
RELEASE = datetime(2026, 10, 6, 20, 10, tzinfo=timezone.utc)


def run(claim: ThesisClaim, fact_kwargs: dict, document: str):
    digest = source_text_sha256(document)
    citation = Citation(source_url="https://www.sec.gov/x.htm", published_at=RELEASE, captured_at=RELEASE,
                        source_sha256=digest, location="test", excerpt=document)
    fact = MetricFact(claim_id=claim.claim_id, citation=citation, **fact_kwargs)
    knowledge = KnowledgeSnapshot(frozen_at=FROZEN, items=(KnowledgeItem(
        claim_id=claim.claim_id, status=KnowledgeStatus.UNKNOWN, reason="test"),))
    return reconcile_claims(claims=(claim,), knowledge=knowledge, facts=(fact,), references=(),
                            frozen_at=FROZEN, source_documents={digest: document}).claims[0]


class EventRuleTests(unittest.TestCase):
    def test_signed_percent_reads_issuer_table_cells(self):
        self.assertEqual(parse_signed_percent("(0.3%)"), Decimal("-0.3"))
        self.assertEqual(parse_signed_percent("1.8%"), Decimal("1.8"))
        self.assertEqual(parse_signed_percent("-2.7%"), Decimal("-2.7"))
        for bad in ("(0.3%", "0.3", "1.8 bps", "up 2%"):
            with self.assertRaises(ValueError):
                parse_signed_percent(bad)

    def test_stated_increase_claim(self):
        claim = ThesisClaim(claim_id="c2", text="Beer depletions turn positive", variable="beer depletions",
                            comparison=Comparison.STATED_INCREASE, claim_type=ClaimType.QUARTER_FACT, unit="percent")
        doc = "Shipments Depletions Net Sales August 31, 2026 % Change 1.2% 0.4% 3%"
        up = run(claim, {"current_value_text": "0.4%", "current_period_text": "August 31, 2026", "unit": "percent"}, doc)
        self.assertIs(up.status, ClaimStatus.CONFIRMED)
        doc = "Shipments Depletions Net Sales August 31, 2026 % Change 1.2% (0.4%) 3%"
        down = run(claim, {"current_value_text": "(0.4%)", "current_period_text": "August 31, 2026", "unit": "percent"}, doc)
        self.assertIs(down.status, ClaimStatus.CONTRADICTED)

    def test_aluminum_tariff_attribution_matches_last_years_sentence_only(self):
        self.assertTrue(_ALUMINUM_TARIFF_CAUSAL.search(STZ_2025))
        self.assertFalse(_ALUMINUM_TARIFF_CAUSAL.search("Operating margin decreased 50 basis points due to higher marketing."))
        self.assertFalse(_FREIGHT_CAUSAL.search(STZ_2025))
        claim = ThesisClaim(claim_id="c4", text="Constellation blames aluminum or tariffs for beer margin",
                            variable="aluminum or tariff attribution", comparison=Comparison.EXPLICIT_ATTRIBUTION,
                            claim_type=ClaimType.QUARTER_FACT)
        result = run(claim, {"attribution_quote": STZ_2025}, STZ_2025)
        self.assertIs(result.status, ClaimStatus.CONFIRMED)

    def test_unknown_attribution_variable_is_never_scored(self):
        claim = ThesisClaim(claim_id="c9", text="x", variable="weather attribution",
                            comparison=Comparison.EXPLICIT_ATTRIBUTION, claim_type=ClaimType.QUARTER_FACT)
        self.assertIs(run(claim, {"attribution_quote": STZ_2025}, STZ_2025).status, ClaimStatus.NOT_ADDRESSED)


if __name__ == "__main__":
    unittest.main()
