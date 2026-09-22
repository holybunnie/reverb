"""Evaluate one reaction window and, only when explicitly enabled, submit it.

This command is intentionally fail-closed.  The repository feasibility gate,
account liveness, a pre-registration, a complete order intent, and runtime
instrument constraints must all be present before Agent Hub is called.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from reverb.agent_hub import AgentHubExecutor  # noqa: E402
from reverb.bitget import BitgetClient, Credentials  # noqa: E402
from reverb.config import EngineConfig, load_config  # noqa: E402
from reverb.errors import ConfigurationError, ReverbError  # noqa: E402
from reverb.execution import RealityOrderConstraints, place_reaction_limit  # noqa: E402
from reverb.env import load_local_env  # noqa: E402
from reverb.ledger import Ledger  # noqa: E402
from reverb.liveness import check_account_liveness  # noqa: E402
from reverb.m0 import gate_passed  # noqa: E402
from reverb.service import DecisionService  # noqa: E402


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ConfigurationError("event timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def run_once(*, symbol: str, event_at: datetime, enable_live: bool = False) -> int:
    load_local_env(ROOT)
    loaded = load_config(ROOT / "config" / "engine.json", EngineConfig)
    ledger = Ledger(Path(os.getenv("REVERB_LEDGER_PATH", str(ROOT / "data" / "private" / "ledger.jsonl"))))
    try:
        credentials = Credentials.from_env()
    except ConfigurationError:
        if enable_live:
            raise ConfigurationError("live reaction execution requires local Bitget credentials")
        credentials = None
    with BitgetClient(credentials=credentials) as client:
        with DecisionService(client, loaded.value, ledger, engine_config_sha256=loaded.sha256) as service:
            result = service.react(symbol=symbol, event_at=event_at)
            print(result.model_dump_json(indent=2))
            if result.status.value != "act":
                return 0
            if not enable_live:
                ledger.append("execution_blocked", {"decision_id": result.decision_id,
                                                     "reason": "paper/public-data mode; --enable-live was not supplied"})
                return 0
            if not gate_passed(ROOT):
                ledger.append("execution_blocked", {"decision_id": result.decision_id,
                                                     "reason": "docs/m0_gate.json is not a verified PASSED artifact"})
                raise ConfigurationError("live execution is blocked until docs/m0_gate.json is hash-verified and PASSED")
            liveness = check_account_liveness(client)
            decision = result.decision
            if not isinstance(decision, dict):
                raise ConfigurationError("ACT result has no structured reaction decision")
            from reverb.models import ReactionDecision
            parsed_decision = ReactionDecision.model_validate(decision)
            instrument = client.instrument(parsed_decision.symbol)
            constraints = RealityOrderConstraints.from_instrument(instrument)
            if parsed_decision.intended_side is None or parsed_decision.order_quantity is None or parsed_decision.order_price is None:
                raise ConfigurationError("ACT result has no complete order intent")
            available_quantity = None
            if parsed_decision.intended_side == "sell":
                coin = parsed_decision.symbol.removesuffix("USDT")
                assets = client.account_assets()
                matches = [row for row in assets if isinstance(row, dict) and row.get("coin") == coin]
                if len(matches) != 1:
                    raise ConfigurationError("verified sell balance is unavailable for the Reality token")
                raw_available = matches[0].get("available", matches[0].get("availableBalance"))
                if raw_available in (None, ""):
                    raise ConfigurationError("account asset has no validated available balance")
                available_quantity = Decimal(str(raw_available))
            executor = AgentHubExecutor()
            available_quote = None
            if parsed_decision.intended_side == "buy":
                available_quote = executor.available_quote_for_limit(
                    symbol=parsed_decision.symbol, side="buy", price=parsed_decision.order_price)
            response = place_reaction_limit(
                executor=executor, ledger=ledger, decision=parsed_decision,
                symbol=parsed_decision.symbol, side=parsed_decision.intended_side,
                quantity=parsed_decision.order_quantity, price=parsed_decision.order_price,
                client_oid="reverb-" + parsed_decision.decision_id,
                liveness=liveness, constraints=constraints,
                reference_price=parsed_decision.observed_price,
                available_quantity=available_quantity,
                available_quote=available_quote,
            )
            print({"order_submitted": response["orderId"]})
            return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("symbol")
    parser.add_argument("event_at", help="ISO timestamp with timezone")
    parser.add_argument("--enable-live", action="store_true", help="allow Agent Hub after all gates pass")
    args = parser.parse_args()
    try:
        return run_once(symbol=args.symbol, event_at=_timestamp(args.event_at), enable_live=args.enable_live)
    except (ConfigurationError, ReverbError, ValueError) as exc:
        print(f"REVERB HALTED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
