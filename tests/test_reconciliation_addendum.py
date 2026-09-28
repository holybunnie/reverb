from datetime import datetime, timedelta, timezone
import unittest

from reverb.reconciliation import (
    Citation, ClaimResult, ClaimStatus, ClaimType, Comparison, ReconciliationResult, StatedChangeFact,
    ThesisClaim, reconcile_stated_changes, source_text_sha256,
)


FREEZE = datetime(2026, 9, 24, 6, 30, tzinfo=timezone.utc)
RELEASED = FREEZE + timedelta(hours=14)
DECK = "Supplemental Information Fourth Quarter FY 2026 Gross Margin 11.02% -11 bps vs Q4 FY’25"


def margin_claim(comparison: Comparison = Comparison.DOWN_YEAR_OVER_YEAR) -> ThesisClaim:
    return ThesisClaim(claim_id="c3", text="Margins disappoint", variable="gross margin",
                       comparison=comparison, claim_type=ClaimType.QUARTER_FACT, unit="percent")


def frozen_result(status: ClaimStatus = ClaimStatus.NOT_ADDRESSED) -> ReconciliationResult:
    scored = status in {ClaimStatus.CONFIRMED, ClaimStatus.CONTRADICTED}
    return ReconciliationResult(claims=(ClaimResult(claim_id="c3", text="Margins disappoint", status=status,
                                                    scored=scored, reason="frozen"),),
                                scored_confirmed=int(status is ClaimStatus.CONFIRMED), scored_total=int(scored))


def fact(change: str = "-11 bps", published: datetime = RELEASED, body: str = DECK) -> StatedChangeFact:
    return StatedChangeFact(
        claim_id="c3", change_text=change, current_period_text="Fourth Quarter FY 2026",
        prior_period_text="Q4 FY’25",
        citation=Citation(source_url="https://www.sec.gov/ex99-2.htm", published_at=published,
                          captured_at=RELEASED, source_sha256=source_text_sha256(body),
                          location="deck", excerpt=body))


class AddendumTests(unittest.TestCase):
    def run_rule(self, **kwargs):
        body = kwargs.pop("body", DECK)
        return reconcile_stated_changes(
            claims=(kwargs.pop("claim", margin_claim()),), frozen=kwargs.pop("frozen", frozen_result()),
            facts=(kwargs.pop("fact", fact(body=body)),), frozen_at=FREEZE,
            source_documents={source_text_sha256(body): body})

    def test_issuer_stated_decline_confirms_down_claim_and_is_labelled(self):
        (row,) = self.run_rule()
        self.assertEqual(row.status, ClaimStatus.CONFIRMED)
        self.assertIn("added 2026-09-28 after the release", row.reason)

    def test_stated_decline_contradicts_up_claim(self):
        (row,) = self.run_rule(claim=margin_claim(Comparison.UP_YEAR_OVER_YEAR))
        self.assertEqual(row.status, ClaimStatus.CONTRADICTED)

    def test_frozen_scored_result_is_never_overridden(self):
        self.assertEqual(self.run_rule(frozen=frozen_result(ClaimStatus.CONTRADICTED)), ())

    def test_change_published_before_freeze_is_excluded(self):
        (row,) = self.run_rule(fact=fact(published=FREEZE - timedelta(days=1)))
        self.assertEqual(row.status, ClaimStatus.ALREADY_KNOWN)

    def test_change_text_must_be_verbatim(self):
        with self.assertRaises(ValueError):
            self.run_rule(fact=fact(change="-12 bps"))

    def test_non_adjacent_fiscal_years_do_not_score(self):
        body = DECK.replace("FY’25", "FY’24")
        stale = fact(body=body).model_copy(update={"prior_period_text": "Q4 FY’24"})
        (row,) = self.run_rule(fact=stale, body=body)
        self.assertEqual(row.status, ClaimStatus.NOT_ADDRESSED)


if __name__ == "__main__":
    unittest.main()
