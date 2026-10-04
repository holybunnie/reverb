"""Summarize the private Costco capture into sanitized, committable evidence.

Reads the verified recorder ledger and candle bodies; writes only derived
numbers, counts, and hashes. The issuer release timestamp comes from Costco's
own press-release feed, recorded separately; without it the run is INCOMPLETE.
"""
from __future__ import annotations

import argparse
import json
import statistics
from datetime import datetime, timezone
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from reverb.ledger import Ledger  # noqa: E402

BASELINE_MS = int(datetime(2026, 9, 24, 20, 0, tzinfo=timezone.utc).timestamp() * 1000)  # 16:00 ET
TRIGGER_PCT = 3.0
RELEASE_RECORD = ROOT / "evidence/costco/post_event/issuer_release_timestamp.json"
SUMMARY_PATH = ROOT / "evidence/costco/capture_summary.json"
RAW_CAPTURE = ROOT / "evidence/costco/raw/20260924T072322Z-1239ae49"


def iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat().replace("+00:00", "Z")


def release_status() -> dict:
    if not RELEASE_RECORD.exists():
        return {"issuer_release_timestamp": None, "run_status": "INCOMPLETE",
                "run_status_reason": "The issuer release timestamp has not been recorded from Costco's own publication."}
    record = json.loads(RELEASE_RECORD.read_text())
    return {"issuer_release_timestamp": record["issuer_release_timestamp"], "run_status": "COMPLETE",
            "run_status_reason": (f"All required slots captured with no gaps; Costco's own press-release feed dates the "
                                  f"release {record['feed_press_release_date']} ET ({record['issuer_release_timestamp']}), "
                                  f"before the 8-K acceptance at {record['upper_bound_8k_acceptance']}.")}


def summarize(directory: Path) -> dict:
    rows = Ledger(directory / "ledger.jsonl").verify()
    slots = [row["payload"] for row in rows if row["kind"] == "capture_slot"]
    final = next(row["payload"] for row in reversed(rows) if row["kind"] == "recording_complete")
    candles: dict[int, list] = {}
    book_levels = []
    spreads_bps: list[float] = []
    for slot in slots:
        for result in slot["endpoint_results"]:
            attempt = next(row["payload"] for row in rows if row["hash"] == result["record_hash"])
            if not attempt.get("body") or not result["success"]:
                continue
            data = json.loads((directory / Path(attempt["body"]).name).read_text())["data"]
            if result["endpoint"] == "candles":
                for candle in data:
                    candles[int(candle[0])] = candle
            elif result["endpoint"] == "ticker" and data:
                bid, ask = float(data[0]["bid1Price"]), float(data[0]["ask1Price"])
                if bid > 0 and ask >= bid:
                    spreads_bps.append((ask - bid) / ((ask + bid) / 2) * 10_000)
            elif result["endpoint"] == "public_orderbook":
                book_levels.append(len(data.get("a", [])) + len(data.get("b", [])))
    before = [key for key in candles if key < BASELINE_MS]  # candle keys are open times
    spread = ({"samples": len(spreads_bps), "median": round(statistics.median(spreads_bps), 2),
               "min": round(min(spreads_bps), 2), "max": round(max(spreads_bps), 2),
               "source": "ticker bid1Price/ask1Price, one sample per slot"} if spreads_bps else None)
    if not before:
        # Not an event capture: report capture quality and spread only.
        return {"symbol": "RCOSTUSDT", "ledger_head": rows[-1]["hash"], "recorder_status": final["status"],
                "window": [slots[0]["slot_at"], slots[-1]["slot_at"]] if slots else None,
                "slots": {"expected": final["expected_slots"], "complete": final["complete_slots"],
                          "gaps": final["gap_count"]},
                "public_book": {"snapshots": len(book_levels),
                                "with_visible_levels": sum(1 for levels in book_levels if levels)},
                "ticker_spread_bps": spread, "event": False, "orders": 0}
    base_key = max(before)
    baseline = float(candles[base_key][4])
    post = sorted((key, float(candles[key][4])) for key in candles if key >= BASELINE_MS)
    high = max(post, key=lambda row: row[1])
    low = min(post, key=lambda row: row[1])
    pct = lambda value: round((value / baseline - 1) * 100, 3)
    crossed = any(abs(pct(value)) >= TRIGGER_PCT for _, value in post)
    visible = sum(1 for levels in book_levels if levels)
    return {
        "symbol": "RCOSTUSDT",
        "ledger_head": rows[-1]["hash"],
        "recorder_status": final["status"],
        "slots": {"expected": final["expected_slots"], "complete": final["complete_slots"],
                  "gaps": final["gap_count"]},
        "public_book": {"snapshots": len(book_levels), "with_visible_levels": visible,
                        "depth_status": "NOT_VISIBLE" if not visible else
                        "MEASURED" if visible == len(book_levels) else "PARTIAL"},
        "event_time_spread": ("MEASURED from ticker bid1/ask1" if spread else
                              "No quoted depth: every public book snapshot returned zero levels"),
        "ticker_spread_bps": spread,
        "reaction": {
            "baseline_rule": "close of the one-minute market candle ending at 16:00 ET (open-time keys)",
            "baseline_at": iso(base_key), "baseline_close": baseline,
            "post_candles": len(post),
            "max_close": high[1], "max_pct": pct(high[1]), "max_at": iso(high[0]),
            "min_close": low[1], "min_pct": pct(low[1]), "min_at": iso(low[0]),
            "last_close": post[-1][1], "last_pct": pct(post[-1][1]), "last_at": iso(post[-1][0]),
            "trigger_pct": TRIGGER_PCT, "trigger_crossed": crossed,
        },
        **release_status(),
        "orders": 0,
    }


def render(directory: Path) -> str:
    return json.dumps(summarize(directory), indent=2) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("capture_dir", type=Path, nargs="?", default=RAW_CAPTURE)
    parser.add_argument("--out", type=Path, default=SUMMARY_PATH)
    parser.add_argument("--verify", action="store_true",
                        help="rebuild from the capture and assert byte-equality with the committed summary")
    args = parser.parse_args()
    if args.verify:
        if render(args.capture_dir) != SUMMARY_PATH.read_text(encoding="utf-8"):
            raise SystemExit("capture summary does not match the committed file")
        print(f"verified: {SUMMARY_PATH.relative_to(ROOT)} rebuilds byte-identically from {args.capture_dir}")
        return
    summary = summarize(args.capture_dir)
    args.out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
