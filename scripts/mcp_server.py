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
from reverb.ledger import Ledger  # noqa: E402
from reverb.models import View  # noqa: E402
from reverb.service import DecisionService  # noqa: E402


def _service(*, require_credentials: bool = True) -> DecisionService:
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
    fees = Decimal(fee_text) if fee_text else None
    return DecisionService(BitgetClient(credentials=credentials), loaded.value, Ledger(ledger_path), fees)


try:
    from mcp.server.mcpserver import MCPServer
except ImportError as exc:  # pragma: no cover - exercised by installation, not the deterministic unit suite
    raise SystemExit("Install the project first: uv pip install --python .venv/bin/python -e .") from exc


mcp = MCPServer("Reverb", description="Decision-only earnings tools for Bitget; raw market data is not exposed.")


@mcp.tool()
def earnings_this_week(user_timezone: str) -> dict:
    """Return reporting names, local times, and verified leg availability."""
    with _service(require_credentials=False) as service:
        return service.earnings_this_week(user_timezone=user_timezone).model_dump(mode="json")


@mcp.tool()
def position_for(symbol: str, view: str, expected_move_pct: str, max_loss: str,
                event_at: str, user_timezone: str) -> dict:
    """Return a guarded option decision or a refusal with its arithmetic."""
    with _service() as service:
        return service.position_for(symbol=symbol, view=View(view), expected_move_pct=Decimal(expected_move_pct),
                                    max_loss=Decimal(max_loss), event_at=datetime.fromisoformat(event_at),
                                    user_timezone=user_timezone).model_dump(mode="json")


@mcp.tool()
def whats_priced_in(symbol: str, event_at: str, historical_move_pct: str | None = None) -> dict:
    """Compare an executable paired-option move with a supplied historical sample."""
    with _service() as service:
        historical = Decimal(historical_move_pct) if historical_move_pct is not None else None
        return service.whats_priced_in(symbol=symbol, event_at=datetime.fromisoformat(event_at),
                                       historical_move_pct=historical).model_dump(mode="json")


@mcp.tool()
def react(symbol: str, event_at: str, user_timezone: str = "America/New_York",
          order_type: str = "limit") -> dict:
    """Return the session-aware reaction decision, never a raw candle stream."""
    with _service(require_credentials=False) as service:
        return service.react(symbol=symbol, event_at=datetime.fromisoformat(event_at),
                             user_timezone=user_timezone, order_type=order_type).model_dump(mode="json")


@mcp.tool()
def my_positions() -> dict:
    """Return ledger-known positions with outcome attribution, never raw account data."""
    with _service(require_credentials=False) as service:
        return service.my_positions().model_dump(mode="json")


def main() -> int:
    try:
        mcp.run()
    except (ConfigurationError, ReverbError) as exc:
        print(f"REVERB HALTED: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
