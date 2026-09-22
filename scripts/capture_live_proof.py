"""Capture a read-only Agent Hub order receipt as non-pre-registered execution evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from reverb.env import load_local_env  # noqa: E402
from reverb.ledger import Ledger  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("order_id")
    args = parser.parse_args()
    if not args.order_id.isdigit():
        print("REVERB HALTED: order id must contain digits only", file=sys.stderr)
        return 2
    load_local_env(ROOT)
    completed = subprocess.run(
        ["bgc", "--read-only", "order", "--action", "detail", "--orderId", args.order_id, "--view", "full"],
        capture_output=True, text=True, timeout=40, check=False, shell=False,
    )
    if completed.returncode != 0:
        print("REVERB HALTED: Agent Hub could not read the order receipt", file=sys.stderr)
        return 2
    try:
        document = json.loads(completed.stdout)
        data = document["data"]
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        print("REVERB HALTED: Agent Hub returned an invalid order receipt", file=sys.stderr)
        return 2
    required = {"orderId", "category", "symbol", "side", "price", "qty", "cumExecQty", "cumExecValue", "avgPrice", "orderStatus", "feeDetail"}
    if not isinstance(data, dict) or not required.issubset(data) or data["orderId"] != args.order_id:
        print("REVERB HALTED: order receipt is incomplete", file=sys.stderr)
        return 2
    captured = datetime.now(timezone.utc)
    directory = ROOT / "evidence" / "live" / captured.strftime("%Y%m%dT%H%M%SZ")
    directory.mkdir(parents=True, exist_ok=False)
    body = json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    receipt = directory / "order-receipt.json"
    receipt.write_bytes(body)
    digest = hashlib.sha256(body).hexdigest()
    ledger = Ledger(directory / "ledger.jsonl")
    ledger.append("manual_agent_hub_execution_proof", {
        "order_id": args.order_id,
        "receipt": receipt.name,
        "receipt_sha256": digest,
        "classification": "live_execution_transport_proof",
        "pre_registered_by_reverb": False,
        "profitability_claim": False,
        "captured_at": captured.isoformat(),
    })
    print(json.dumps({"status": "captured", "directory": str(directory.relative_to(ROOT)),
                      "order_id": args.order_id, "pre_registered_by_reverb": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
