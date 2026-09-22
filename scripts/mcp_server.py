"""Expose Reverb decisions through MCP; raw Bitget data is never a tool result."""
from __future__ import annotations

import os
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from reverb.bitget import BitgetClient, Credentials  # noqa: E402
from reverb.config import EngineConfig, load_config  # noqa: E402
from reverb.errors import ConfigurationError, ReverbError  # noqa: E402
from reverb.env import load_local_env  # noqa: E402
from reverb.ledger import Ledger  # noqa: E402
from reverb.language import decision_with_narration, interpret_view_and_record, optional_qwen_client  # noqa: E402
from reverb.models import View  # noqa: E402
from reverb.service import DecisionService  # noqa: E402


def _service(*, require_credentials: bool = True) -> DecisionService:
    load_local_env(ROOT)
    credentials = None
    try:
        credentials = Credentials.from_env()
    except ConfigurationError:
        # The service converts missing credentials into a structured refusal;
        # an MCP caller should receive a decision object, not a raw exception.
        if require_credentials:
            credentials = None
    loaded = load_config(ROOT / "config" / "engine.json", EngineConfig)
    ledger_path = Path(os.getenv("REVERB_LEDGER_PATH", str(ROOT / "data" / "private" / "ledger.jsonl")))
    fee_text = os.getenv("REVERB_OPTION_FEES_PER_CONTRACT")
    try:
        fees = Decimal(fee_text) if fee_text else None
    except ArithmeticError:
        fees = None
    return DecisionService(BitgetClient(credentials=credentials), loaded.value, Ledger(ledger_path), fees,
                           engine_config_sha256=loaded.sha256)


def _parse_datetime(value: str, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be an ISO timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed


def _parse_decimal(value: str, field: str) -> Decimal:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a decimal string")
    parsed = Decimal(value)
    if not parsed.is_finite():
        raise ValueError(f"{field} must be finite")
    return parsed


def _input_refusal(tool: str, symbol: str | None, field: str, error: Exception) -> dict:
    with _service(require_credentials=False) as service:
        return service.input_refusal(tool=tool, symbol=symbol, field=field, error=error).model_dump(mode="json")


def _ledger() -> Ledger:
    return Ledger(Path(os.getenv("REVERB_LEDGER_PATH", str(ROOT / "data" / "private" / "ledger.jsonl"))))


def _render(decision: dict) -> dict:
    qwen = optional_qwen_client()
    try:
        return decision_with_narration(decision=decision, ledger=_ledger(), qwen=qwen)
    finally:
        if qwen is not None:
            qwen.close()


def _view(value: str) -> View:
    try:
        return View(value.strip().lower())
    except (AttributeError, TypeError, ValueError):
        qwen = optional_qwen_client()
        if qwen is None:
            raise ValueError("view must be beat, miss, or no_view unless local Qwen is configured")
        try:
            return interpret_view_and_record(text=value, ledger=_ledger(), qwen=qwen)
        finally:
            qwen.close()


try:
    from mcp.server.mcpserver import MCPServer
except ImportError as exc:  # pragma: no cover - exercised by installation, not the deterministic unit suite
    raise SystemExit("Install the project first: uv pip install --python .venv/bin/python -e .") from exc


mcp = MCPServer("Reverb", description="Decision-only earnings tools for Bitget; raw market data is not exposed.")


@mcp.tool()
def earnings_this_week(user_timezone: str) -> dict:
    """Return reporting names, local times, and explicitly qualified leg availability."""
    with _service(require_credentials=False) as service:
        decision = service.earnings_this_week(user_timezone=user_timezone).model_dump(mode="json")
    return _render(decision)


@mcp.tool()
def position_for(symbol: str, view: str, expected_move_pct: str, max_loss: str,
                event_at: str, user_timezone: str) -> dict:
    """Return a guarded option decision or a refusal with its arithmetic."""
    try:
        parsed_view = _view(view)
    except (TypeError, ValueError) as exc:
        return _input_refusal("position_for", symbol, "view", exc)
    try:
        parsed_expected_move = _parse_decimal(expected_move_pct, "expected_move_pct")
    except (ArithmeticError, TypeError, ValueError) as exc:
        return _input_refusal("position_for", symbol, "expected_move_pct", exc)
    if parsed_expected_move <= 0 or parsed_expected_move >= 1:
        return _input_refusal("position_for", symbol, "expected_move_pct",
                              ValueError("expected_move_pct must be between zero and one"))
    try:
        parsed_max_loss = _parse_decimal(max_loss, "max_loss")
    except (ArithmeticError, TypeError, ValueError) as exc:
        return _input_refusal("position_for", symbol, "max_loss", exc)
    if parsed_max_loss <= 0:
        return _input_refusal("position_for", symbol, "max_loss", ValueError("max_loss must be positive"))
    try:
        parsed_event_at = _parse_datetime(event_at, "event_at")
    except (TypeError, ValueError) as exc:
        return _input_refusal("position_for", symbol, "event_at", exc)
    with _service() as service:
        decision = service.position_for(symbol=symbol, view=parsed_view, expected_move_pct=parsed_expected_move,
                                        max_loss=parsed_max_loss, event_at=parsed_event_at,
                                        user_timezone=user_timezone).model_dump(mode="json")
    return _render(decision)


@mcp.tool()
def whats_priced_in(symbol: str, event_at: str, historical_move_pct: str | None = None) -> dict:
    """Compare an executable paired-option move with a supplied historical sample."""
    try:
        parsed_event_at = _parse_datetime(event_at, "event_at")
    except (TypeError, ValueError) as exc:
        return _input_refusal("whats_priced_in", symbol, "event_at", exc)
    if historical_move_pct is not None:
        try:
            historical = _parse_decimal(historical_move_pct, "historical_move_pct")
        except (ArithmeticError, TypeError, ValueError) as exc:
            return _input_refusal("whats_priced_in", symbol, "historical_move_pct", exc)
        if historical <= 0 or historical >= 1:
            return _input_refusal("whats_priced_in", symbol, "historical_move_pct",
                                  ValueError("historical_move_pct must be between zero and one"))
    else:
        historical = None
    with _service() as service:
        decision = service.whats_priced_in(symbol=symbol, event_at=parsed_event_at,
                                           historical_move_pct=historical).model_dump(mode="json")
    return _render(decision)


@mcp.tool()
def react(symbol: str, event_at: str, user_timezone: str = "America/New_York",
          order_type: str = "limit") -> dict:
    """Return the session-aware reaction decision, never a raw candle stream."""
    try:
        parsed_event_at = _parse_datetime(event_at, "event_at")
    except (TypeError, ValueError) as exc:
        return _input_refusal("react", symbol, "event_at", exc)
    with _service(require_credentials=False) as service:
        decision = service.react(symbol=symbol, event_at=parsed_event_at,
                                 user_timezone=user_timezone, order_type=order_type).model_dump(mode="json")
    return _render(decision)


@mcp.tool()
def my_positions() -> dict:
    """Return ledger-known positions with outcome attribution, never raw account data."""
    with _service(require_credentials=False) as service:
        decision = service.my_positions().model_dump(mode="json")
    return _render(decision)


def main() -> int:
    try:
        mcp.run()
    except (ConfigurationError, ReverbError) as exc:
        print(f"REVERB HALTED: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
