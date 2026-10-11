"""Cross-check each forward run's issuer release against Bitget's earnings calendar.

Reverb times every run from the issuer's own press-release feed. This script asks a second,
independent source, Bitget's keyless US-equity data service (bitget-mcp-server, the
`equity_calendar` entry), for the same release and records whether the date and the
trading session agree. The raw Bitget rows are written next to the result so the
comparison can be re-run offline. Nothing here changes a frozen thesis or a score.

    python scripts/bitget_data_crosscheck.py           # fetch from Bitget and write the evidence
    python scripts/bitget_data_crosscheck.py --check   # recompute from the committed raw rows
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from reverb.bitget_data import (  # noqa: E402
    ENTRY_CALENDAR, NEW_YORK, SOURCE_NAME, BitgetDataClient, compare_release, parse_calendar,
)

OUTPUT = ROOT / "evidence" / "bitget-data" / "release_crosscheck.json"
RAW = ROOT / "evidence" / "bitget-data" / "raw"
RUNS = {
    "costco-q4-fy26": {"symbol": "COST", "event_date": "2026-09-24",
                       "issuer_record": "evidence/costco/post_event/issuer_release_timestamp.json"},
    "stz-q2-fy27": {"symbol": "STZ", "event_date": "2026-10-06",
                    "issuer_record": "evidence/events/stz-q2-fy27/post_event/issuer_release_timestamp.json"},
    "apld-q1-fy27": {"symbol": "APLD", "event_date": "2026-10-07",
                     "issuer_record": "evidence/events/apld-q1-fy27/post_event/issuer_release_timestamp.json"},
}


def _canonical(value) -> bytes:
    return (json.dumps(value, indent=1, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def compare_run(run_id: str, rows: list[dict], window_days: int) -> dict:
    run = RUNS[run_id]
    issuer = json.loads((ROOT / run["issuer_record"]).read_text(encoding="utf-8"))
    released_at = datetime.fromisoformat(issuer["issuer_release_timestamp"].replace("Z", "+00:00"))
    # The issuer's own timestamp, read in New York, is the date under test.
    issuer_date = released_at.astimezone(NEW_YORK).date()
    if issuer_date != date.fromisoformat(run["event_date"]):
        raise ValueError(f"{run_id}: issuer release date {issuer_date} is not the registered event date")
    comparison = compare_release(parse_calendar(rows, run["symbol"]), expected_date=issuer_date,
                                 window_days=window_days, issuer_release_at=released_at)
    return {"run": run_id, "symbol": run["symbol"], "issuer_record": run["issuer_record"],
            "issuer_release_at": issuer["issuer_release_timestamp"], **comparison}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="recompute from committed raw rows; no network")
    args = parser.parse_args()

    if args.check:
        committed = json.loads(OUTPUT.read_text(encoding="utf-8"))
        failures = []
        for item in committed["runs"]:
            raw_path = ROOT / item["raw_path"]
            if hashlib.sha256(raw_path.read_bytes()).hexdigest() != item["raw_sha256"]:
                failures.append(f"{item['run']}: raw rows do not match their recorded sha256")
                continue
            recomputed = compare_run(item["run"], json.loads(raw_path.read_text(encoding="utf-8")),
                                     committed["calendar_match_window_days"])
            expected = {key: value for key, value in item.items() if key not in {"raw_path", "raw_sha256"}}
            if recomputed != expected:
                failures.append(f"{item['run']}: recomputed comparison differs from the committed one")
        for failure in failures:
            print(failure, file=sys.stderr)
        print("ok" if not failures else f"{len(failures)} mismatch(es)")
        return 1 if failures else 0

    fetched_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    RAW.mkdir(parents=True, exist_ok=True)
    results = []
    with BitgetDataClient() as client:
        window_days = client.config.calendar_match_window_days
        for run_id, run in RUNS.items():
            rows = client.query(ENTRY_CALENDAR, {"symbol": run["symbol"]})
            raw_path = RAW / f"{run['symbol']}_{ENTRY_CALENDAR}.json"
            body = _canonical(rows)
            raw_path.write_bytes(body)
            results.append({**compare_run(run_id, rows, window_days),
                            "raw_path": str(raw_path.relative_to(ROOT)),
                            "raw_sha256": hashlib.sha256(body).hexdigest()})
        source_url, config_sha256 = client.url, client.config_sha256
    document = {
        "source": SOURCE_NAME, "source_url": source_url, "entry": ENTRY_CALENDAR,
        "fetched_at": fetched_at, "config_sha256": config_sha256,
        "calendar_match_window_days": window_days,
        "method": ("For each run, the issuer's own feed time is compared with the release Bitget lists "
                   "closest to the run's date: same date, and same US session (before open, during market, "
                   "after close). A second source agreeing is corroboration, not proof; a disagreement "
                   "would be reported, never resolved in Bitget's favour."),
        "runs": results,
    }
    OUTPUT.write_bytes(_canonical(document))
    for item in results:
        print(f"{item['run']}: date {item['status']}, session {item.get('session_status')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
