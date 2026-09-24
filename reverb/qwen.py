from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import ValidationError

from .errors import ConfigurationError, DataUnavailable
from .reconciliation import Comparison, FactExtraction, ThesisExtraction, parse_source_number


@dataclass(frozen=True)
class QwenCredentials:
    api_key: str
    base_url: str
    model: str

    @classmethod
    def from_env(cls) -> "QwenCredentials":
        api_key = os.getenv("QWEN_API_KEY") or os.getenv("BITGET_QWEN_API_KEY")
        if not api_key:
            raise ConfigurationError("QWEN_API_KEY is not set; deterministic narration remains available")
        base_url = os.getenv("BITGET_QWEN_BASE_URL", "https://hackathon.bitgetops.com/v1").rstrip("/")
        model = os.getenv("BITGET_QWEN_MODEL", "qwen3.8-max")
        if not base_url or not model:
            raise ConfigurationError("Qwen base URL and model must be non-empty")
        return cls(api_key=api_key, base_url=base_url, model=model)


@dataclass(frozen=True)
class QwenNarration:
    text: str
    provider: str
    model: str
    input_sha256: str
    output_sha256: str


@dataclass(frozen=True)
class QwenViewInterpretation:
    view: str
    provider: str
    model: str
    input_sha256: str
    output_sha256: str


@dataclass(frozen=True)
class QwenThesisExtraction:
    extraction: ThesisExtraction
    provider: str
    model: str
    input_sha256: str
    output_sha256: str


@dataclass(frozen=True)
class QwenFactExtraction:
    extraction: FactExtraction
    provider: str
    model: str
    input_sha256: str
    output_sha256: str


class QwenClient:
    def __init__(self, credentials: QwenCredentials, timeout: float = 120.0,
                 client: httpx.Client | None = None):
        self.credentials = credentials
        self._client = client or httpx.Client(timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "QwenClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def narrate(self, decision: dict[str, Any]) -> QwenNarration:
        """Explain a deterministic result without creating facts or decisions."""
        serialized = json.dumps(decision, sort_keys=True, separators=(",", ":"), allow_nan=False)
        prompt = (
            "Write a short plain-language morning explanation of this Reverb decision. "
            "Use only facts and numbers present in the JSON. Do not add a price, date, "
            "probability, market fact, recommendation, or trade instruction. State "
            "whether Reverb acted, held, or refused and why. Do not mention internal "
            "prompting. Return prose only.\n\nDECISION JSON:\n" + serialized
        )
        body = {
            "model": self.credentials.model,
            "messages": [
                {"role": "system", "content": "You are Reverb's careful post-trade narrator."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
        }
        try:
            response = self._client.post(
                self.credentials.base_url + "/chat/completions",
                headers={"Authorization": "Bearer " + self.credentials.api_key, "Content-Type": "application/json"},
                json=body,
            )
            response.raise_for_status()
            document = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise DataUnavailable(f"Qwen narration request failed: {type(exc).__name__}") from exc
        try:
            text = document["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise DataUnavailable("Qwen narration response has no usable message") from exc
        if not isinstance(text, str) or not text.strip():
            raise DataUnavailable("Qwen narration returned empty prose")
        # Narration is presentation only.  Reject numeric claims that do not
        # occur in the deterministic decision JSON, so the model cannot add a
        # price, percentage, timestamp, or P&L figure to the morning report.
        allowed_numbers = set(re.findall(r"(?<![A-Za-z])[+-]?(?:\d+(?:\.\d+)?)(?![A-Za-z])", serialized))
        narrated_numbers = set(re.findall(r"(?<![A-Za-z])[+-]?(?:\d+(?:\.\d+)?)(?![A-Za-z])", text))
        if not narrated_numbers.issubset(allowed_numbers):
            raise DataUnavailable("Qwen narration introduced a number not present in the decision ledger")
        input_hash = hashlib.sha256(serialized.encode()).hexdigest()
        output_hash = hashlib.sha256(text.encode()).hexdigest()
        return QwenNarration(text=text.strip(), provider="bitget-qwen", model=self.credentials.model,
                             input_sha256=input_hash, output_sha256=output_hash)

    def interpret_view(self, plain_language: str) -> QwenViewInterpretation:
        """Classify direction only; magnitude, size, instrument, and approval stay outside the model."""
        if not isinstance(plain_language, str) or not plain_language.strip():
            raise ConfigurationError("plain-language view is required")
        serialized = json.dumps({"view": plain_language}, sort_keys=True, separators=(",", ":"))
        prompt = (
            "Classify the user's view using exactly one lowercase token: beat, miss, or no_view. "
            "Do not calculate a move, choose an instrument, size a trade, or give advice.\n\n"
            + serialized
        )
        body = {
            "model": self.credentials.model,
            "messages": [
                {"role": "system", "content": "You classify a user's direction without making a trading decision."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
        }
        try:
            response = self._client.post(
                self.credentials.base_url + "/chat/completions",
                headers={"Authorization": "Bearer " + self.credentials.api_key, "Content-Type": "application/json"},
                json=body,
            )
            response.raise_for_status()
            document = response.json()
            value = document["choices"][0]["message"]["content"]
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
            raise DataUnavailable(f"Qwen view interpretation failed: {type(exc).__name__}") from exc
        if not isinstance(value, str):
            raise DataUnavailable("Qwen view interpretation is not text")
        parsed = value.strip().lower()
        if parsed not in {"beat", "miss", "no_view"}:
            raise DataUnavailable("Qwen returned an unrecognised view classification")
        output_hash = hashlib.sha256(parsed.encode()).hexdigest()
        return QwenViewInterpretation(view=parsed, provider="bitget-qwen", model=self.credentials.model,
                                      input_sha256=hashlib.sha256(serialized.encode()).hexdigest(),
                                      output_sha256=output_hash)

    def extract_thesis(self, plain_language: str, *,
                       approved_rule_definitions: dict[str, str] | None = None) -> QwenThesisExtraction:
        """Extract candidate claims only; users review them before registration.

        The schema deliberately has no outcome status, numerical field,
        consensus value, risk budget, recommendation, or execution field.
        """
        if not isinstance(plain_language, str) or not plain_language.strip() or len(plain_language) > 2000:
            raise ConfigurationError("thesis text must be non-empty and at most 2000 characters")
        approved = approved_rule_definitions or {}
        if any(not isinstance(key, str) or not isinstance(value, str) for key, value in approved.items()):
            raise ConfigurationError("approved comparison rules must be a string-to-string mapping")
        serialized = json.dumps({"thesis": plain_language,
                                 "approved_comparison_rules": approved,
                                 "allowed_comparisons": [item.value for item in Comparison]},
                               sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        prompt = (
            "Extract only distinct factual claims directly stated in the user's thesis. "
            "Return one JSON object with exactly this key: claims. Each claim "
            "must have exactly claim_id, text, variable, comparison, claim_type. Use unique "
            "short ids; claim_type is QUARTER_FACT or FORWARD_EXPECTATION; comparison is one "
            "of ABOVE_REFERENCE, BELOW_REFERENCE, UP_YEAR_OVER_YEAR, DOWN_YEAR_OVER_YEAR, "
            "EXPLICIT_ATTRIBUTION. Do not invent claims or infer a reference value. Apply only "
            "the comparison mappings provided in approved_comparison_rules. For any claim "
            "without an approved mapping, use ABOVE_REFERENCE only when the user's wording "
            "explicitly names a comparison reference; otherwise omit the claim for manual "
            "review rather than guessing its meaning. Do not "
            "return numbers, source facts, statuses, scores, a budget, advice, or an order. "
            "No markdown fences.\n\nINPUT JSON:\n" + serialized
        )
        body = {
            "model": self.credentials.model,
            "messages": [
                {"role": "system", "content": "You extract candidate claims for a human-reviewed research record. You do not grade them."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
            "max_tokens": 512,
        }
        try:
            response = self._client.post(
                self.credentials.base_url + "/chat/completions",
                headers={"Authorization": "Bearer " + self.credentials.api_key,
                         "Content-Type": "application/json"},
                json=body,
            )
            response.raise_for_status()
            document = response.json()
            raw = document["choices"][0]["message"]["content"]
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
            raise DataUnavailable(f"Qwen thesis extraction failed: {type(exc).__name__}") from exc
        if not isinstance(raw, str) or not raw.strip():
            raise DataUnavailable("Qwen thesis extraction returned empty content")
        try:
            extraction = ThesisExtraction.model_validate_json(raw)
        except ValidationError as exc:
            raise DataUnavailable("Qwen returned claims outside the strict review schema") from exc
        source_numbers = set(re.findall(r"(?<![A-Za-z])[+-]?\d+(?:\.\d+)?(?![A-Za-z])", plain_language))
        candidate_text = " ".join(f"{claim.text} {claim.variable}" for claim in extraction.claims)
        extracted_numbers = set(re.findall(r"(?<![A-Za-z])[+-]?\d+(?:\.\d+)?(?![A-Za-z])", candidate_text))
        if not extracted_numbers.issubset(source_numbers):
            raise DataUnavailable("Qwen added a numeric claim absent from the user's thesis")
        return QwenThesisExtraction(
            extraction=extraction,
            provider="bitget-qwen",
            model=self.credentials.model,
            input_sha256=hashlib.sha256(serialized.encode()).hexdigest(),
            output_sha256=hashlib.sha256(raw.encode()).hexdigest(),
        )

    def extract_release_facts(self, *, release_text: str, claims: list[dict[str, Any]]) -> QwenFactExtraction:
        """Extract verbatim issuer facts; deterministic code assigns all statuses."""
        if not isinstance(release_text, str) or not release_text.strip() or len(release_text) > 200_000:
            raise ConfigurationError("release text must be non-empty and at most 200000 characters")
        if not isinstance(claims, list) or not claims or len(claims) > 20:
            raise ConfigurationError("registered claims must be a non-empty list of at most 20")
        serialized = json.dumps({"registered_claims": claims, "issuer_release_text": release_text},
                                sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        prompt = (
            "Extract only issuer-reported facts that address the registered claims. "
            "Return one JSON object with exactly one key, facts. Each fact must have exactly "
            "claim_id, current_value_text, prior_value_text, current_period_text, "
            "prior_period_text, attribution_quote, excerpt. Use null for a missing field. "
            "Copy every value and period label character-for-character from excerpt. The "
            "excerpt must be copied character-for-character from the release text. Do not "
            "calculate year-over-year changes, normalize figures, infer causation, add a "
            "consensus value, or include a status, score, summary, recommendation, or prose. "
            "Only use claim_id values from registered_claims. Return {\"facts\": []} when no "
            "claim is addressed. No markdown fences.\n\nSOURCE JSON:\n" + serialized
        )
        body = {
            "model": self.credentials.model,
            "messages": [
                {"role": "system", "content": "You copy source-grounded facts for a human research desk. You do not grade claims."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
            "max_tokens": 1600,
        }
        try:
            response = self._client.post(
                self.credentials.base_url + "/chat/completions",
                headers={"Authorization": "Bearer " + self.credentials.api_key,
                         "Content-Type": "application/json"},
                json=body,
            )
            response.raise_for_status()
            document = response.json()
            raw = document["choices"][0]["message"]["content"]
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
            raise DataUnavailable(f"Qwen release extraction failed: {type(exc).__name__}") from exc
        if not isinstance(raw, str) or not raw.strip():
            raise DataUnavailable("Qwen release extraction returned empty content")
        try:
            extraction = FactExtraction.model_validate_json(raw)
        except ValidationError as exc:
            raise DataUnavailable("Qwen returned release facts outside the strict extraction schema") from exc
        claim_ids = {str(item.get("claim_id")) for item in claims if isinstance(item, dict)}
        if any(fact.claim_id not in claim_ids for fact in extraction.facts):
            raise DataUnavailable("Qwen returned a fact for an unregistered claim")
        for fact in extraction.facts:
            if fact.excerpt not in release_text:
                raise DataUnavailable("Qwen returned an excerpt absent from the issuer release")
            for value in (fact.current_value_text, fact.prior_value_text):
                if value:
                    if value not in fact.excerpt:
                        raise DataUnavailable("Qwen returned a figure absent from its source excerpt")
                    try:
                        parse_source_number(value)
                    except ValueError as exc:
                        raise DataUnavailable("Qwen returned a figure with unsupported source formatting") from exc
        return QwenFactExtraction(
            extraction=extraction,
            provider="bitget-qwen",
            model=self.credentials.model,
            input_sha256=hashlib.sha256(serialized.encode()).hexdigest(),
            output_sha256=hashlib.sha256(raw.encode()).hexdigest(),
        )
