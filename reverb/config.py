from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ConfigDict, Field

from .errors import ConfigurationError


class EngineConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_quote_age_ms: int = Field(gt=0)
    risk_free_rate: Decimal = Field(ge=Decimal("-1"), lt=Decimal("1"))
    post_event_volatility: Decimal = Field(gt=Decimal("0"), lt=Decimal("10"))
    dividend_yield: Decimal = Field(ge=Decimal("-1"), lt=Decimal("1"))
    reaction_trigger_pct: Decimal = Field(gt=Decimal("0"), lt=Decimal("1"))
    baseline_window_minutes: int = Field(gt=0)
    baseline_min_points: int = Field(gt=0)


T = TypeVar("T", bound=BaseModel)


class LoadedConfig:
    def __init__(self, value: T, sha256: str, path: Path):
        self.value = value
        self.sha256 = sha256
        self.path = path


def load_config(path: Path, model: type[T]) -> LoadedConfig:
    try:
        body = path.read_bytes()
        value = model.model_validate_json(body)
    except (OSError, ValueError) as exc:
        raise ConfigurationError(f"cannot load configuration {path}: {exc}") from exc
    return LoadedConfig(value, hashlib.sha256(body).hexdigest(), path)
