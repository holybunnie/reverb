"""Keep the UTC scheduler awake and dispatch due decision actions.

The loop requires ``--dispatch`` to invoke a position/reaction path. Without
it, every due wake is recorded as a blocked dispatch rather than disappearing.
"""
from __future__ import annotations

import argparse
import signal
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal

from scheduler_once import run_once, _parse_timestamp
from reverb.models import View


STOP = False


def _stop(_signum: int, _frame: object) -> None:
    global STOP
    STOP = True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("event_id")
    parser.add_argument("event_at", help="ISO timestamp with timezone")
    parser.add_argument("--interval", type=float, default=60.0)
    parser.add_argument("--dispatch", action="store_true")
    parser.add_argument("--symbol")
    parser.add_argument("--view", choices=[value.value for value in View])
    parser.add_argument("--expected-move-pct")
    parser.add_argument("--max-loss")
    parser.add_argument("--timezone", default="America/New_York")
    parser.add_argument("--enable-live", action="store_true")
    args = parser.parse_args()
    if args.interval <= 0:
        parser.error("--interval must be positive")
    event_at = _parse_timestamp(args.event_at)
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    exit_code = 0
    while not STOP:
        code = run_once(
            event_id=args.event_id, event_at=event_at, now=datetime.now(timezone.utc),
            dispatch=args.dispatch, symbol=args.symbol,
            view=View(args.view) if args.view else None,
            expected_move_pct=Decimal(args.expected_move_pct) if args.expected_move_pct else None,
            max_loss=Decimal(args.max_loss) if args.max_loss else None,
            user_timezone=args.timezone, enable_live=args.enable_live,
        )
        exit_code = max(exit_code, code)
        if not STOP:
            time.sleep(args.interval)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
