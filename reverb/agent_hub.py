from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Callable, Sequence

from .errors import AgentHubError, ConfigurationError, DataUnavailable


Runner = Callable[..., subprocess.CompletedProcess[str]]


def _positive_finite(value: Decimal, label: str) -> None:
    if not value.is_finite() or value <= 0:
        raise ConfigurationError(f"{label} must be a positive finite decimal")


@dataclass(frozen=True)
class AgentHubExecutor:
    """Local Agent Hub order adapter.

    Reverb deliberately keeps credentials out of this process's arguments. The
    local ``bgc`` process reads its own credential environment and performs the
    signed write. There is no raw Bitget order fallback in this adapter.
    """

    executable: str = field(default_factory=lambda: os.getenv("REVERB_AGENT_HUB_BIN", "bgc"))
    timeout_seconds: float = 20.0
    runner: Runner | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not self.executable or not self.executable.strip():
            raise ConfigurationError("REVERB_AGENT_HUB_BIN must name the local Agent Hub executable")
        if self.timeout_seconds <= 0:
            raise ConfigurationError("Agent Hub timeout must be positive")

    def _run(self, args: Sequence[str]) -> dict[str, Any]:
        command = [self.executable, *args]
        run = self.runner or subprocess.run
        try:
            completed = run(command, capture_output=True, text=True,
                            timeout=self.timeout_seconds, check=False, shell=False)
        except FileNotFoundError as exc:
            raise AgentHubError(
                "Agent Hub executable was not found; install or configure the local bgc command"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise AgentHubError("Agent Hub command timed out before returning an order result") from exc
        except OSError as exc:
            raise AgentHubError(f"Agent Hub command could not start: {type(exc).__name__}") from exc

        if completed.returncode != 0:
            raise AgentHubError(
                f"Agent Hub command failed with exit code {completed.returncode}; "
                f"error_type={self._error_type(completed.stderr)}"
            )
        try:
            document = json.loads(completed.stdout)
        except (TypeError, ValueError) as exc:
            raise DataUnavailable("Agent Hub returned non-JSON output") from exc
        if not isinstance(document, dict):
            raise DataUnavailable("Agent Hub returned a non-object result")
        return document

    @staticmethod
    def _error_type(stderr: str | None) -> str:
        if not stderr:
            return "UNKNOWN_AGENT_HUB_ERROR"
        try:
            document = json.loads(stderr)
        except (TypeError, ValueError):
            return "CLI_ERROR"
        if not isinstance(document, dict):
            return "CLI_ERROR"
        error = document.get("error")
        if isinstance(error, dict) and isinstance(error.get("type"), str) and error["type"]:
            return error["type"]
        if isinstance(document.get("type"), str) and document["type"]:
            return document["type"]
        return "CLI_ERROR"

    def place_reality_limit(self, *, symbol: str, side: str, quantity: Decimal,
                            price: Decimal, client_oid: str, dry_run: bool = False) -> dict[str, Any]:
        """Place a Reality spot limit order through Agent Hub's documented order tool."""
        if not symbol or any(character.isspace() for character in symbol):
            raise ConfigurationError("invalid Reality symbol")
        if side not in {"buy", "sell"}:
            raise ConfigurationError("Reality order side must be buy or sell")
        _positive_finite(quantity, "Reality order quantity")
        _positive_finite(price, "Reality order price")
        if not client_oid or any(character.isspace() for character in client_oid):
            raise ConfigurationError("invalid Reality client order id")

        args = [
            "order", "--action", "place", "--category", "SPOT",
            "--symbol", symbol, "--side", side, "--orderType", "limit",
            "--price", str(price), "--qty", str(quantity),
            "--clientOid", client_oid,
        ]
        if dry_run:
            args.append("--dry-run")
        document = self._run(args)
        data = document.get("data")
        if not isinstance(data, dict):
            raise DataUnavailable("Agent Hub order result has no structured data")
        order_id = data.get("orderId")
        if not isinstance(order_id, str) or not order_id:
            raise DataUnavailable("Agent Hub order result has no order id")
        return data
