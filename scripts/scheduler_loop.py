"""Keep the UTC scheduler awake for configured event timestamps.

The loop records every heartbeat and delegates each wake to ``scheduler_once``.
It does not invent a thesis or submit an order; a position/reaction intent must
already exist in the ledger and the guarded execution command remains separate.
"""
from __future__ import annotations

import argparse
import signal
import sys
import time
from datetime import datetime, timezone

from scheduler_once import run_once, _parse_timestamp


STOP = False


def _stop(_signum: int, _frame: object) -> None:
    global STOP
    STOP = True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("event_id")
    parser.add_argument("event_at", help="ISO timestamp with timezone")
    parser.add_argument("--interval", type=float, default=60.0)
    args = parser.parse_args()
    if args.interval <= 0:
        parser.error("--interval must be positive")
    event_at = _parse_timestamp(args.event_at)
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    exit_code = 0
    while not STOP:
        code = run_once(event_id=args.event_id, event_at=event_at, now=datetime.now(timezone.utc))
        exit_code = max(exit_code, code)
        if not STOP:
            time.sleep(args.interval)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
