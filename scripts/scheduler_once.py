"""Run one UTC scheduler wake, then dispatch the due engine action.

Without ``--dispatch`` a due wake is recorded as blocked instead of being
reported as a successful no-op. With it, the scheduler invokes the same
structured decision paths exposed by the command-line tools. Live writes
remain guarded by their own feasibility, liveness, and registration checks.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from reverb.bitget import BitgetClient, Credentials  # noqa: E402
from reverb.errors import BitgetAPIError, ConfigurationError, DataUnavailable  # noqa: E402
from reverb.env import load_local_env  # noqa: E402
from reverb.ledger import Ledger  # noqa: E402
from reverb.liveness import check_account_liveness  # noqa: E402
from reverb.models import View  # noqa: E402
from reverb.scheduler import (WakeAction, build_schedule, dispatch_action, due_action,
                              heartbeat_from_ledger)  # noqa: E402


def _parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ConfigurationError(f"invalid event timestamp: {value}") from exc
    if parsed.tzinfo is None:
        raise ConfigurationError("event timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def _decimal(value: str | None, field: str) -> Decimal | None:
    if value is None:
        return None
    try:
        parsed = Decimal(value)
    except ArithmeticError as exc:
        raise ConfigurationError(f"{field} must be a decimal") from exc
    if not parsed.is_finite():
        raise ConfigurationError(f"{field} must be finite")
    return parsed


def _dispatcher(*, symbol: str | None, view: View | None, expected_move_pct: Decimal | None,
                max_loss: Decimal | None, user_timezone: str, enable_live: bool,
                ledger: Ledger):
    def dispatch(action: WakeAction, schedule, current: datetime) -> dict:
        if not symbol:
            raise ConfigurationError("a scheduler dispatch requires --symbol")
        if action is WakeAction.POSITION:
            if view is None or expected_move_pct is None or max_loss is None:
                raise ConfigurationError("position dispatch requires --view, --expected-move-pct, and --max-loss")
            from position_once import evaluate
            result = evaluate(symbol=symbol, view=view, expected_move_pct=expected_move_pct,
                              max_loss=max_loss, event_at=schedule.event_at_utc,
                              user_timezone=user_timezone)
            if result.get("status") == "act":
                reason = ("--enable-live was not supplied" if not enable_live else
                          "Stock+ option order schema and entitlement are not verified")
                ledger.append("execution_blocked", {"decision_id": result.get("decision_id"),
                                                     "reason": reason, "action": action.value})
                result = {**result, "execution": "blocked", "execution_block_reason": reason}
            return result
        if action is WakeAction.REACT:
            from react_once import run_once as react_run_once
            exit_code = react_run_once(symbol=symbol, event_at=schedule.event_at_utc,
                                       enable_live=enable_live)
            return {"delegated_to": "react_once", "exit_code": str(exit_code)}
        raise ConfigurationError("option-leg management dispatch is not implemented until next-open hours are verified")
    return dispatch


def run_once(*, event_id: str, event_at: datetime, now: datetime | None = None,
             dispatch: bool = False, symbol: str | None = None, view: View | None = None,
             expected_move_pct: Decimal | None = None, max_loss: Decimal | None = None,
             user_timezone: str = "America/New_York", enable_live: bool = False) -> int:
    load_local_env(ROOT)
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    schedule = build_schedule(event_id, event_at)
    ledger = Ledger(Path(os.getenv("REVERB_LEDGER_PATH", str(ROOT / "data" / "private" / "ledger.jsonl"))))
    heartbeat_from_ledger(ledger).tick(current)
    time_to_event = schedule.event_at_utc - current
    if timedelta(0) <= time_to_event <= timedelta(hours=24):
        existing = [row for row in ledger.verify() if row.get("kind") == "key_liveness_t_minus_24h" and row["payload"].get("event_id") == event_id]
        if not existing:
            ledger.append("key_liveness_t_minus_24h", {"event_id": event_id, "at": current.isoformat()})
    try:
        credentials = Credentials.from_env()
        with BitgetClient(credentials=credentials) as client:
            liveness = check_account_liveness(client, now=current)
            ledger.append("key_liveness", {"event_id": event_id, **liveness.model_dump(mode="json")})
    except (BitgetAPIError, ConfigurationError, DataUnavailable) as exc:
        ledger.append("key_liveness_failure", {"event_id": event_id, "error_type": type(exc).__name__})
        print(f"REVERB HALTED: key liveness failed ({type(exc).__name__})", file=sys.stderr)
        return 2
    action = due_action(schedule, current)
    if action is None:
        if current >= schedule.next_open_at_utc and schedule.next_open_status != "verified":
            ledger.append("management_blocked", {
                "event_id": event_id,
                "reason": "next options-open timestamp is not verified against an exchange holiday/early-close calendar",
                "tentative_next_open_at_utc": schedule.next_open_at_utc.isoformat(),
            })
            print("REVERB HALTED: next-open management is not verified", file=sys.stderr)
            return 2
        if current > schedule.react_until_utc:
            existing = [row for row in ledger.verify() if row.get("kind") == "missed_window" and row["payload"].get("event_id") == event_id]
            if not existing:
                ledger.append("missed_window", {"event_id": event_id, "event_at_utc": schedule.event_at_utc.isoformat(), "observed_at": current.isoformat()})
                print("REVERB ALERT: reaction window was missed", file=sys.stderr)
                return 2
        print({"status": "sleeping", "event_id": event_id, "at": current.isoformat()})
        return 0
    try:
        result = dispatch_action(
            ledger=ledger, event_id=event_id, action=action, schedule=schedule, now=current,
            dispatcher=(_dispatcher(symbol=symbol, view=view, expected_move_pct=expected_move_pct,
                                    max_loss=max_loss, user_timezone=user_timezone,
                                    enable_live=enable_live, ledger=ledger) if dispatch else None),
        )
    except (BitgetAPIError, ConfigurationError, DataUnavailable) as exc:
        print(f"REVERB HALTED: action dispatch failed ({type(exc).__name__})", file=sys.stderr)
        return 2
    print(result)
    return 0 if result.get("status") == "dispatched" else 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("event_id")
    parser.add_argument("event_at", help="ISO timestamp with timezone, e.g. 2026-09-24T16:05:00-04:00")
    parser.add_argument("--dispatch", action="store_true", help="invoke the due decision path instead of only recording a blocked wake")
    parser.add_argument("--symbol", help="underlying symbol for a position or reaction dispatch")
    parser.add_argument("--view", choices=[value.value for value in View])
    parser.add_argument("--expected-move-pct")
    parser.add_argument("--max-loss")
    parser.add_argument("--timezone", default="America/New_York")
    parser.add_argument("--enable-live", action="store_true", help="allow a downstream live write only if every path permits it")
    args = parser.parse_args()
    try:
        return run_once(
            event_id=args.event_id, event_at=_parse_timestamp(args.event_at), dispatch=args.dispatch,
            symbol=args.symbol, view=View(args.view) if args.view else None,
            expected_move_pct=_decimal(args.expected_move_pct, "expected_move_pct"),
            max_loss=_decimal(args.max_loss, "max_loss"), user_timezone=args.timezone,
            enable_live=args.enable_live,
        )
    except (ConfigurationError, ValueError) as exc:
        print(f"REVERB HALTED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
