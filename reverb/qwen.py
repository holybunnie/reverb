from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from typing import Any

import httpx

from .errors import ConfigurationError, DataUnavailable


@dataclass(frozen=True)
class QwenCredentials:
    api_key: str
    base_url: str
    model: str

    @classmethod
    def from_env(cls) -> "QwenCredentials":
        api_key = os.getenv("BITGET_QWEN_API_KEY")
        if not api_key:
            raise ConfigurationError("BITGET_QWEN_API_KEY is not set; deterministic narration remains available")
        base_url = os.getenv("BITGET_QWEN_BASE_URL", "https://hackathon.bitgetops.com/v1").rstrip("/")
        model = os.getenv("BITGET_QWEN_MODEL", "qwen3.6-plus")
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


class QwenClient:
    def __init__(self, credentials: QwenCredentials, timeout: float = 30.0,
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
