"""Source-grounded earnings-thesis reconciliation.

The language model may propose claims and source facts, but this module owns
the status assignment. Numbers are accepted only when their exact text is in
the captured source excerpt and that excerpt is in the hash-identified source
document.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator

from .models import StrictModel


class ClaimType(str, Enum):
    QUARTER_FACT = "QUARTER_FACT"
    FORWARD_EXPECTATION = "FORWARD_EXPECTATION"


class Comparison(str, Enum):
    ABOVE_REFERENCE = "ABOVE_REFERENCE"
    BELOW_REFERENCE = "BELOW_REFERENCE"
    UP_YEAR_OVER_YEAR = "UP_YEAR_OVER_YEAR"
    DOWN_YEAR_OVER_YEAR = "DOWN_YEAR_OVER_YEAR"
    EXPLICIT_ATTRIBUTION = "EXPLICIT_ATTRIBUTION"


class ClaimStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    CONTRADICTED = "CONTRADICTED"
    NOT_ADDRESSED = "NOT_ADDRESSED"
    ALREADY_KNOWN = "ALREADY_KNOWN"


class KnowledgeStatus(str, Enum):
    KNOWN = "KNOWN"
    UNKNOWN = "UNKNOWN"


class ThesisCandidate(StrictModel):
    """Untrusted model output before human confirmation; deliberately has no unit field."""

    claim_id: str = Field(min_length=1, max_length=32)
    text: str = Field(min_length=1, max_length=240)
    variable: str = Field(min_length=1, max_length=80)
    comparison: Comparison
    claim_type: ClaimType

    @field_validator("claim_id", "variable")
    @classmethod
    def normalized_key(cls, value: str) -> str:
        return value.strip()


class ThesisClaim(StrictModel):
    """Human-reviewed, frozen claim with an explicit unit for numeric comparisons."""

    claim_id: str = Field(min_length=1, max_length=32)
    text: str = Field(min_length=1, max_length=240)
    variable: str = Field(min_length=1, max_length=80)
    comparison: Comparison
    claim_type: ClaimType
    unit: str | None = Field(default=None, max_length=40)
    scoreable: bool = True
    unscored_reason: str | None = Field(default=None, max_length=400)

    @model_validator(mode="after")
    def scoreability_is_explicit(self) -> "ThesisClaim":
        if not self.scoreable and not (self.unscored_reason and self.unscored_reason.strip()):
            raise ValueError("a human-marked unscored claim needs an explicit reason")
        if self.scoreable and self.unscored_reason is not None:
            raise ValueError("a scoreable claim cannot carry an unscored reason")
        return self

    @field_validator("claim_id", "variable")
    @classmethod
    def normalized_key(cls, value: str) -> str:
        return value.strip()


class ThesisExtraction(StrictModel):
    """Candidate extraction only. Statuses, numbers, and budgets are forbidden."""

    claims: tuple[ThesisCandidate, ...] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def ids_are_unique(self) -> "ThesisExtraction":
        ids = [claim.claim_id for claim in self.claims]
        if len(ids) != len(set(ids)):
            raise ValueError("thesis claim ids must be unique")
        return self


class ExtractedFactCandidate(StrictModel):
    """Model-proposed source facts; no grading/status field is accepted."""

    claim_id: str = Field(min_length=1, max_length=32)
    current_value_text: str | None = Field(default=None, max_length=80)
    prior_value_text: str | None = Field(default=None, max_length=80)
    current_period_text: str | None = Field(default=None, max_length=120)
    prior_period_text: str | None = Field(default=None, max_length=120)
    attribution_quote: str | None = Field(default=None, max_length=1000)
    excerpt: str = Field(min_length=1, max_length=4000)

    @model_validator(mode="after")
    def has_groundable_fact(self) -> "ExtractedFactCandidate":
        if not any((self.current_value_text, self.prior_value_text, self.attribution_quote)):
            raise ValueError("candidate must include a source value or attribution quote")
        return self


class FactExtraction(StrictModel):
    facts: tuple[ExtractedFactCandidate, ...] = Field(max_length=20)

    @model_validator(mode="after")
    def claims_are_unique(self) -> "FactExtraction":
        ids = [fact.claim_id for fact in self.facts]
        if len(ids) != len(set(ids)):
            raise ValueError("release fact candidates must be unique per claim")
        return self


class Citation(StrictModel):
    source_url: str = Field(min_length=8, max_length=2048)
    published_at: datetime
    captured_at: datetime
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    location: str = Field(min_length=1, max_length=240)
    excerpt: str = Field(min_length=1, max_length=4000)

    @field_validator("published_at", "captured_at")
    @classmethod
    def timestamps_are_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("citation timestamps must include a timezone")
        return value

    @field_validator("source_url")
    @classmethod
    def citation_is_https(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("citations must use an https source URL")
        return value


class KnowledgeEvidence(StrictModel):
    claim_id: str = Field(min_length=1, max_length=32)
    fact_text: str = Field(min_length=1, max_length=1000)
    citation: Citation


class KnowledgeItem(StrictModel):
    claim_id: str
    status: KnowledgeStatus
    evidence: tuple[KnowledgeEvidence, ...] = ()
    reason: str


class KnowledgeSnapshot(StrictModel):
    frozen_at: datetime
    items: tuple[KnowledgeItem, ...]

    @field_validator("frozen_at")
    @classmethod
    def timestamp_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("knowledge snapshot time must include a timezone")
        return value


class MetricFact(StrictModel):
    claim_id: str = Field(min_length=1, max_length=32)
    current_value_text: str | None = Field(default=None, max_length=80)
    prior_value_text: str | None = Field(default=None, max_length=80)
    current_period_text: str | None = Field(default=None, max_length=120)
    prior_period_text: str | None = Field(default=None, max_length=120)
    unit: str | None = Field(default=None, max_length=40)
    attribution_quote: str | None = Field(default=None, max_length=1000)
    citation: Citation

    @model_validator(mode="after")
    def fact_has_evidence(self) -> "MetricFact":
        if not any((self.current_value_text, self.prior_value_text, self.attribution_quote)):
            raise ValueError("a metric fact must contain a source-grounded value or attribution quote")
        return self


class FrozenReference(StrictModel):
    claim_id: str = Field(min_length=1, max_length=32)
    value_text: str = Field(min_length=1, max_length=80)
    unit: str = Field(min_length=1, max_length=40)
    citation: Citation


class ClaimResult(StrictModel):
    claim_id: str
    text: str
    status: ClaimStatus
    scored: bool
    reason: str
    current_value_text: str | None = None
    comparison_value_text: str | None = None
    citation: Citation | None = None


class ReconciliationResult(StrictModel):
    claims: tuple[ClaimResult, ...]
    scored_confirmed: int
    scored_total: int


class FrozenThesis(StrictModel):
    event: str = Field(min_length=1, max_length=160)
    thesis_text: str = Field(min_length=1, max_length=2000)
    claims: tuple[ThesisClaim, ...]
    knowledge_snapshot: KnowledgeSnapshot
    references: tuple[FrozenReference, ...]
    risk_budget_usdt: Decimal = Field(gt=Decimal("0"))
    reaction_trigger_pct: Decimal = Field(gt=Decimal("0"), lt=Decimal("1"))
    baseline_method: str = Field(min_length=1, max_length=1000)
    capture_plan: str = Field(min_length=1, max_length=2000)
    code_commit: str = Field(pattern=r"^[0-9a-f]{7,40}$")
    frozen_at: datetime
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def _aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None:
        raise ValueError(f"{name} must include a timezone")
    return value.astimezone(timezone.utc)


def _canonical(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False,
                      default=lambda item: item.isoformat() if isinstance(item, datetime) else str(item)).encode()


def source_text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def verify_citation(citation: Citation, source_documents: dict[str, str]) -> None:
    """Require an exact excerpt match in the captured, hash-identified text."""
    document = source_documents.get(citation.source_sha256)
    if document is None:
        raise ValueError("cited source text is not present in the capture set")
    if source_text_sha256(document) != citation.source_sha256:
        raise ValueError("cited source text does not match its SHA-256")
    if citation.excerpt not in document:
        raise ValueError("citation excerpt does not appear verbatim in the source")


_NUMBER = re.compile(
    r"^\s*[+$€£]?\s*([-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\s*(%|percent)?\s*(thousand|million|billion|trillion)?\s*$",
    re.IGNORECASE,
)
_SCALE = {"thousand": Decimal("1000"), "million": Decimal("1000000"),
          "billion": Decimal("1000000000"), "trillion": Decimal("1000000000000")}
_FISCAL_YEAR = re.compile(r"\bFY\s*(\d{2,4})\b", re.IGNORECASE)
_CALENDAR_YEAR = re.compile(r"\b(20\d{2})\b")


def parse_source_number(value_text: str) -> Decimal:
    """Parse a number only after callers have checked its verbatim source text."""
    match = _NUMBER.fullmatch(value_text)
    if not match:
        raise ValueError(f"source number has an unsupported format: {value_text!r}")
    try:
        value = Decimal(match.group(1).replace(",", ""))
    except InvalidOperation as exc:
        raise ValueError("source number is not decimal") from exc
    scale = match.group(3)
    return value * _SCALE[scale.casefold()] if scale else value


def _period_year(value: str) -> int | None:
    fiscal = _FISCAL_YEAR.search(value)
    if fiscal:
        year = int(fiscal.group(1))
        return year + 2000 if year < 100 else year
    calendar = _CALENDAR_YEAR.findall(value)
    return int(calendar[0]) if len(set(calendar)) == 1 else None


def _validate_value(citation: Citation, value_text: str | None,
                    source_documents: dict[str, str]) -> None:
    if value_text is None:
        return
    verify_citation(citation, source_documents)
    if value_text not in citation.excerpt:
        raise ValueError("extracted numeric value is not verbatim in its citation excerpt")
    parse_source_number(value_text)


def build_knowledge_snapshot(*, claims: tuple[ThesisClaim, ...],
                             evidence: tuple[KnowledgeEvidence, ...], frozen_at: datetime,
                             source_documents: dict[str, str]) -> KnowledgeSnapshot:
    """Classify claim-resolving public evidence as of the proposed freeze time.

    Evidence is attached to claim IDs after source review; merely knowing a
    comparison benchmark (for example consensus EPS) does not make the future
    outcome itself already known.
    """
    frozen = _aware(frozen_at, "frozen_at")
    claim_ids = {claim.claim_id for claim in claims}
    by_claim: dict[str, list[KnowledgeEvidence]] = {claim_id: [] for claim_id in claim_ids}
    for item in evidence:
        if item.claim_id not in claim_ids:
            raise ValueError(f"knowledge evidence refers to unknown claim {item.claim_id}")
        verify_citation(item.citation, source_documents)
        if item.fact_text not in item.citation.excerpt:
            raise ValueError("known fact is not verbatim in its citation excerpt")
        by_claim[item.claim_id].append(item)

    items: list[KnowledgeItem] = []
    for claim in claims:
        public = tuple(row for row in by_claim[claim.claim_id]
                       if _aware(row.citation.published_at, "published_at") <= frozen
                       and _aware(row.citation.captured_at, "captured_at") <= frozen)
        future = tuple(row for row in by_claim[claim.claim_id] if row not in public)
        if public:
            items.append(KnowledgeItem(claim_id=claim.claim_id, status=KnowledgeStatus.KNOWN,
                                       evidence=public, reason="claim-resolving source was public by freeze"))
        else:
            reason = "no claim-resolving source was public by freeze"
            if future:
                reason = "candidate evidence was published after freeze and cannot mark the claim known"
            items.append(KnowledgeItem(claim_id=claim.claim_id, status=KnowledgeStatus.UNKNOWN,
                                       evidence=(), reason=reason))
    return KnowledgeSnapshot(frozen_at=frozen, items=tuple(items))


def ground_extracted_facts(*, extraction: FactExtraction, claims: tuple[ThesisClaim, ...],
                           source_url: str, source_text: str, published_at: datetime,
                           captured_at: datetime) -> tuple[MetricFact, ...]:
    """Attach deterministic locations and source hashes to model candidates."""
    claim_by_id = {claim.claim_id: claim for claim in claims}
    digest = source_text_sha256(source_text)
    result: list[MetricFact] = []
    for candidate in extraction.facts:
        if candidate.claim_id not in claim_by_id:
            raise ValueError("model returned a fact for a claim that was not registered")
        if candidate.excerpt not in source_text:
            raise ValueError("model fact excerpt does not appear verbatim in the captured release")
        for value in (candidate.current_value_text, candidate.prior_value_text):
            if value:
                if value not in candidate.excerpt:
                    raise ValueError("model fact number does not appear verbatim in its excerpt")
                parse_source_number(value)
        for period in (candidate.current_period_text, candidate.prior_period_text):
            if period and period not in candidate.excerpt:
                raise ValueError("model comparison period does not appear verbatim in its excerpt")
        if candidate.attribution_quote and candidate.attribution_quote not in candidate.excerpt:
            raise ValueError("model attribution quote does not appear verbatim in its excerpt")
        offset = source_text.find(candidate.excerpt)
        citation = Citation(
            source_url=source_url,
            published_at=published_at,
            captured_at=captured_at,
            source_sha256=digest,
            location=f"normalized release text offsets {offset}:{offset + len(candidate.excerpt)}",
            excerpt=candidate.excerpt,
        )
        result.append(MetricFact(
            claim_id=candidate.claim_id,
            current_value_text=candidate.current_value_text,
            prior_value_text=candidate.prior_value_text,
            current_period_text=candidate.current_period_text,
            prior_period_text=candidate.prior_period_text,
            unit=claim_by_id[candidate.claim_id].unit,
            attribution_quote=candidate.attribution_quote,
            citation=citation,
        ))
    return tuple(result)


def _result(claim: ThesisClaim, status: ClaimStatus, reason: str,
            fact: MetricFact | None = None, current: str | None = None,
            comparison_value: str | None = None) -> ClaimResult:
    scored = status in {ClaimStatus.CONFIRMED, ClaimStatus.CONTRADICTED}
    return ClaimResult(claim_id=claim.claim_id, text=claim.text, status=status, scored=scored,
                       reason=reason, current_value_text=current,
                       comparison_value_text=comparison_value,
                       citation=fact.citation if fact else None)


_FREIGHT_CAUSAL = re.compile(
    r"\b(?:freight|shipping|transportation)\b.{0,120}\b(?:drove|caused|pressured|reduced|lowered|weighed on|contributed to|due to|because of|attributable to|reflected in)\b.{0,120}\b(?:margin|gross profit|cost of sales)\b"
    r"|\b(?:margin|gross profit|cost of sales)\b.{0,120}\b(?:due to|because of|from|driven by|pressured by|attributable to|reflecting)\b.{0,120}\b(?:freight|shipping|transportation)\b",
    re.IGNORECASE | re.DOTALL,
)


def reconcile_claims(*, claims: tuple[ThesisClaim, ...], knowledge: KnowledgeSnapshot,
                     facts: tuple[MetricFact, ...], references: tuple[FrozenReference, ...],
                     frozen_at: datetime, source_documents: dict[str, str]) -> ReconciliationResult:
    """Assign all reconciliation statuses with deterministic arithmetic."""
    frozen = _aware(frozen_at, "frozen_at")
    if _aware(knowledge.frozen_at, "knowledge.frozen_at") != frozen:
        raise ValueError("reconciliation freeze time differs from the knowledge snapshot")
    ids = [claim.claim_id for claim in claims]
    if len(ids) != len(set(ids)) or {item.claim_id for item in knowledge.items} != set(ids):
        raise ValueError("knowledge snapshot must cover each unique claim exactly once")
    fact_by_id: dict[str, MetricFact] = {}
    for fact in facts:
        if fact.claim_id not in set(ids) or fact.claim_id in fact_by_id:
            raise ValueError("release facts must refer once to a registered claim")
        verify_citation(fact.citation, source_documents)
        _validate_value(fact.citation, fact.current_value_text, source_documents)
        _validate_value(fact.citation, fact.prior_value_text, source_documents)
        for period in (fact.current_period_text, fact.prior_period_text):
            if period and period not in fact.citation.excerpt:
                raise ValueError("comparison period is not verbatim in its citation excerpt")
        if fact.attribution_quote and fact.attribution_quote not in fact.citation.excerpt:
            raise ValueError("attribution quote is not verbatim in its citation excerpt")
        fact_by_id[fact.claim_id] = fact
    reference_by_id: dict[str, FrozenReference] = {}
    for reference in references:
        if reference.claim_id not in set(ids) or reference.claim_id in reference_by_id:
            raise ValueError("frozen references must refer once to a registered claim")
        verify_citation(reference.citation, source_documents)
        _validate_value(reference.citation, reference.value_text, source_documents)
        if _aware(reference.citation.published_at, "reference published_at") > frozen or \
                _aware(reference.citation.captured_at, "reference captured_at") > frozen:
            raise ValueError("a comparison reference must be published and captured before freeze")
        reference_by_id[reference.claim_id] = reference

    results: list[ClaimResult] = []
    knowledge_by_id = {item.claim_id: item for item in knowledge.items}
    for claim in claims:
        known = knowledge_by_id[claim.claim_id]
        if known.status is KnowledgeStatus.KNOWN:
            results.append(_result(claim, ClaimStatus.ALREADY_KNOWN,
                                   "excluded because source-backed claim evidence was public at freeze"))
            continue
        if not claim.scoreable:
            results.append(_result(claim, ClaimStatus.NOT_ADDRESSED,
                                   claim.unscored_reason or "the user left this claim unscored"))
            continue
        fact = fact_by_id.get(claim.claim_id)
        if fact is None:
            results.append(_result(claim, ClaimStatus.NOT_ADDRESSED,
                                   "the issuer release supplied no grounded fact for this claim"))
            continue
        # A source predating the freeze cannot silently be scored as a new result.
        if _aware(fact.citation.published_at, "fact published_at") <= frozen:
            results.append(_result(claim, ClaimStatus.ALREADY_KNOWN,
                                   "the cited fact predates the freeze and is excluded", fact))
            continue

        if claim.comparison in {Comparison.ABOVE_REFERENCE, Comparison.BELOW_REFERENCE}:
            reference = reference_by_id.get(claim.claim_id)
            if not fact.current_value_text or not reference:
                results.append(_result(claim, ClaimStatus.NOT_ADDRESSED,
                                       "actual value or pre-frozen comparison reference is unavailable", fact))
                continue
            if not claim.unit or fact.unit != claim.unit or reference.unit != claim.unit:
                results.append(_result(claim, ClaimStatus.NOT_ADDRESSED,
                                       "actual value and frozen reference do not match the frozen claim unit", fact))
                continue
            actual = parse_source_number(fact.current_value_text)
            benchmark = parse_source_number(reference.value_text)
            satisfied = actual > benchmark if claim.comparison is Comparison.ABOVE_REFERENCE else actual < benchmark
            relation = "above" if claim.comparison is Comparison.ABOVE_REFERENCE else "below"
            results.append(_result(claim, ClaimStatus.CONFIRMED if satisfied else ClaimStatus.CONTRADICTED,
                                   f"issuer value is {relation} the frozen reference", fact,
                                   fact.current_value_text, reference.value_text))
            continue

        if claim.comparison in {Comparison.UP_YEAR_OVER_YEAR, Comparison.DOWN_YEAR_OVER_YEAR}:
            if (not fact.current_value_text or not fact.prior_value_text or not claim.unit
                    or fact.unit != claim.unit or not fact.current_period_text or not fact.prior_period_text):
                results.append(_result(claim, ClaimStatus.NOT_ADDRESSED,
                                       "comparable values, the frozen unit, or period labels are missing", fact))
                continue
            current_year = _period_year(fact.current_period_text)
            prior_year = _period_year(fact.prior_period_text)
            if current_year is None or prior_year is None or current_year - prior_year != 1:
                results.append(_result(claim, ClaimStatus.NOT_ADDRESSED,
                                       "source period labels do not prove an exact one-year comparison", fact))
                continue
            current = parse_source_number(fact.current_value_text)
            prior = parse_source_number(fact.prior_value_text)
            satisfied = current > prior if claim.comparison is Comparison.UP_YEAR_OVER_YEAR else current < prior
            relation = "higher" if claim.comparison is Comparison.UP_YEAR_OVER_YEAR else "lower"
            results.append(_result(claim, ClaimStatus.CONFIRMED if satisfied else ClaimStatus.CONTRADICTED,
                                   f"current value is {relation} than the cited prior-year value", fact,
                                   fact.current_value_text, fact.prior_value_text))
            continue

        quote = fact.attribution_quote
        if quote and _FREIGHT_CAUSAL.search(quote):
            results.append(_result(claim, ClaimStatus.CONFIRMED,
                                   "the cited issuer text explicitly links freight to margin/cost", fact))
        else:
            results.append(_result(claim, ClaimStatus.NOT_ADDRESSED,
                                   "no explicit freight-to-margin attribution appears in the cited text", fact))

    scored = [result for result in results if result.scored]
    return ReconciliationResult(claims=tuple(results), scored_confirmed=sum(
        result.status is ClaimStatus.CONFIRMED for result in scored), scored_total=len(scored))


def freeze_thesis(*, event: str, thesis_text: str, claims: tuple[ThesisClaim, ...],
                  confirmed_claim_ids: set[str], knowledge_snapshot: KnowledgeSnapshot,
                  references: tuple[FrozenReference, ...], risk_budget_usdt: Decimal,
                  reaction_trigger_pct: Decimal, baseline_method: str, capture_plan: str,
                  code_commit: str, frozen_at: datetime,
                  source_documents: dict[str, str]) -> FrozenThesis:
    """Create the immutable pre-registration only after explicit user review."""
    claim_ids = {claim.claim_id for claim in claims}
    if not claim_ids or confirmed_claim_ids != claim_ids:
        raise ValueError("the user must explicitly confirm every extracted claim before freeze")
    frozen = _aware(frozen_at, "frozen_at")
    if _aware(knowledge_snapshot.frozen_at, "knowledge_snapshot.frozen_at") != frozen:
        raise ValueError("knowledge snapshot must use the same freeze timestamp")
    if {item.claim_id for item in knowledge_snapshot.items} != claim_ids or \
            len(knowledge_snapshot.items) != len(claim_ids):
        raise ValueError("knowledge snapshot must cover each claim exactly once")
    for item in knowledge_snapshot.items:
        for evidence in item.evidence:
            verify_citation(evidence.citation, source_documents)
            if evidence.fact_text not in evidence.citation.excerpt:
                raise ValueError("knowledge evidence must be verbatim in its citation")
    for reference in references:
        if reference.claim_id not in claim_ids:
            raise ValueError("a frozen reference must refer to a registered claim")
        verify_citation(reference.citation, source_documents)
        _validate_value(reference.citation, reference.value_text, source_documents)
        if _aware(reference.citation.published_at, "reference published_at") > frozen or \
                _aware(reference.citation.captured_at, "reference captured_at") > frozen:
            raise ValueError("a reference must be captured and public before the thesis freeze")
    reference_ids = {reference.claim_id for reference in references}
    if any(claim.scoreable and claim.comparison in {
            Comparison.ABOVE_REFERENCE, Comparison.BELOW_REFERENCE,
    } and claim.claim_id not in reference_ids for claim in claims):
        raise ValueError("a scoreable reference claim needs its source-backed benchmark frozen first")
    if any(claim.scoreable and claim.comparison in {
            Comparison.ABOVE_REFERENCE, Comparison.BELOW_REFERENCE,
            Comparison.UP_YEAR_OVER_YEAR, Comparison.DOWN_YEAR_OVER_YEAR,
    } and not claim.unit for claim in claims):
        raise ValueError("each numeric comparison needs an explicitly reviewed unit before freeze")
    body = {
        "event": event, "thesis_text": thesis_text,
        "claims": [claim.model_dump(mode="json") for claim in claims],
        "knowledge_snapshot": knowledge_snapshot.model_dump(mode="json"),
        "references": [reference.model_dump(mode="json") for reference in references],
        "risk_budget_usdt": str(risk_budget_usdt),
        "reaction_trigger_pct": str(reaction_trigger_pct),
        "baseline_method": baseline_method, "capture_plan": capture_plan,
        "code_commit": code_commit, "frozen_at": frozen.isoformat(),
    }
    candidate = FrozenThesis(**body, sha256="0" * 64)
    canonical_payload = candidate.model_dump(mode="json", exclude={"sha256"})
    digest = hashlib.sha256(_canonical(canonical_payload)).hexdigest()
    return candidate.model_copy(update={"sha256": digest})


def verify_frozen_thesis(thesis: FrozenThesis) -> bool:
    """Check the immutable pre-registration hash before use or publication."""
    body = thesis.model_dump(mode="json", exclude={"sha256"})
    return hashlib.sha256(_canonical(body)).hexdigest() == thesis.sha256
