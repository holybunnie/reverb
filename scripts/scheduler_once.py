"""Run one UTC scheduler wake with liveness and gap markers; never places an order."""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from reverb.bitget import BitgetClient, Credentials  # noqa: E402
from reverb.errors import BitgetAPIError, ConfigurationError, DataUnavailable  # noqa: E402
from reverb.ledger import Ledger  # noqa: E402
from reverb.liveness import check_account_liveness  # noqa: E402
from reverb.scheduler import WakeAction, build_schedule, due_action, heartbeat_from_ledger  # noqa: E402


def _parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ConfigurationError(f"invalid event timestamp: {value}") from exc
    if parsed.tzinfo is None:
        raise ConfigurationError("event timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def run_once(*, event_id: str, event_at: datetime, now: datetime | None = None) -> int:
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
    print({"status": "wake", "event_id": event_id, "action": action.value, "at": current.isoformat()})
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("event_id")
    parser.add_argument("event_at", help="ISO timestamp with timezone, e.g. 2026-09-24T16:05:00-04:00")
    args = parser.parse_args()
    return run_once(event_id=args.event_id, event_at=_parse_timestamp(args.event_at))


if __name__ == "__main__":
    raise SystemExit(main())
