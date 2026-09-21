"""Evaluate and preregister one pre-close option decision.

The decision path is live-data only.  Order submission is deliberately
separate: the Stock+ order endpoint and this account's entitlement must be
verified before a pre-close write can be enabled.
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

from reverb.bitget import BitgetClient, Credentials  # noqa: E402
from reverb.config import EngineConfig, load_config  # noqa: E402
from reverb.errors import ConfigurationError, ReverbError  # noqa: E402
from reverb.env import load_local_env  # noqa: E402
from reverb.ledger import Ledger  # noqa: E402
from reverb.m0 import gate_passed  # noqa: E402
from reverb.models import View  # noqa: E402
from reverb.service import DecisionService  # noqa: E402


def _timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ConfigurationError(f"invalid event timestamp: {value}") from exc
    if parsed.tzinfo is None:
        raise ConfigurationError("event timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def _decimal(value: str, field: str) -> Decimal:
    try:
        parsed = Decimal(value)
    except ArithmeticError as exc:
        raise ConfigurationError(f"{field} must be a decimal") from exc
    if not parsed.is_finite():
        raise ConfigurationError(f"{field} must be finite")
    return parsed


def evaluate(*, symbol: str, view: View, expected_move_pct: Decimal, max_loss: Decimal,
             event_at: datetime, user_timezone: str) -> dict:
    load_local_env(ROOT)
    loaded = load_config(ROOT / "config" / "engine.json", EngineConfig)
    ledger = Ledger(Path(os.getenv("REVERB_LEDGER_PATH", str(ROOT / "data" / "private" / "ledger.jsonl"))))
    credentials = Credentials.from_env()
    fee_text = os.getenv("REVERB_OPTION_FEES_PER_CONTRACT")
    if not fee_text:
        raise ConfigurationError("REVERB_OPTION_FEES_PER_CONTRACT must be verified before option sizing")
    fees = _decimal(fee_text, "REVERB_OPTION_FEES_PER_CONTRACT")
    with BitgetClient(credentials=credentials) as client:
        with DecisionService(client, loaded.value, ledger, fees,
                             engine_config_sha256=loaded.sha256) as service:
            return service.position_for(
                symbol=symbol, view=view, expected_move_pct=expected_move_pct,
                max_loss=max_loss, event_at=event_at, user_timezone=user_timezone,
            ).model_dump(mode="json")


def run_once(*, symbol: str, view: View, expected_move_pct: Decimal, max_loss: Decimal,
             event_at: datetime, user_timezone: str, enable_live: bool = False) -> int:
    result = evaluate(symbol=symbol, view=view, expected_move_pct=expected_move_pct,
                      max_loss=max_loss, event_at=event_at, user_timezone=user_timezone)
    print(result)
    if result.get("status") != "act":
        return 0
    ledger = Ledger(Path(os.getenv("REVERB_LEDGER_PATH", str(ROOT / "data" / "private" / "ledger.jsonl"))))
    decision_id = result.get("decision_id")
    if not enable_live:
        ledger.append("execution_blocked", {"decision_id": decision_id,
                                             "reason": "--enable-live was not supplied"})
        return 0
    if not gate_passed(ROOT):
        ledger.append("execution_blocked", {"decision_id": decision_id,
                                             "reason": "docs/m0_gate.json is not a verified PASSED artifact"})
        raise ConfigurationError("live option execution is blocked until docs/m0_gate.json is hash-verified and PASSED")
    # The official Stock+ place-order endpoint exists, but its request schema,
    # account entitlement, and safe order constraints are not yet verified in
    # this workspace.  Do not guess a payload or fall back to a raw order call.
    ledger.append("execution_blocked", {"decision_id": decision_id,
                                         "reason": "Stock+ option order schema and entitlement are not verified"})
    raise ConfigurationError("Stock+ option execution is blocked until the endpoint schema and account entitlement are verified")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("symbol")
    parser.add_argument("view", choices=[value.value for value in View])
    parser.add_argument("expected_move_pct")
    parser.add_argument("max_loss")
    parser.add_argument("event_at", help="ISO timestamp with timezone")
    parser.add_argument("--timezone", default="America/New_York")
    parser.add_argument("--enable-live", action="store_true", help="allow option writes after every gate passes")
    args = parser.parse_args()
    try:
        return run_once(
            symbol=args.symbol, view=View(args.view),
            expected_move_pct=_decimal(args.expected_move_pct, "expected_move_pct"),
            max_loss=_decimal(args.max_loss, "max_loss"), event_at=_timestamp(args.event_at),
            user_timezone=args.timezone, enable_live=args.enable_live,
        )
    except (ConfigurationError, ReverbError, ValueError) as exc:
        print(f"REVERB HALTED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
