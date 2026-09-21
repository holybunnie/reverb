"""Capture and verify the real credential-free historical earnings replay."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from reverb.errors import DataUnavailable, LedgerError  # noqa: E402
from reverb.replay import REPLAY_CONFIG, capture_replay, load_replay_snapshot  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("capture", "check"))
    args = parser.parse_args()
    try:
        if args.action == "capture":
            directory = capture_replay(ROOT, ROOT / REPLAY_CONFIG)
            print(f"Replay evidence: {directory}")
            return 0
        snapshot = load_replay_snapshot(ROOT)
        print({"status": "verified", "run_id": snapshot.run_id,
               "symbol": snapshot.symbol, "ledger_head": snapshot.ledger_head})
        return 0
    except (DataUnavailable, LedgerError, OSError, ValueError) as exc:
        print(f"REVERB HALTED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
