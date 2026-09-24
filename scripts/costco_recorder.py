"""Read-only one-minute Costco Reality evidence recorder; no trading methods are called."""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from reverb.bitget import BitgetClient, Credentials  # noqa: E402
from reverb.env import load_local_env  # noqa: E402
from reverb.errors import DataUnavailable, ReverbError  # noqa: E402
from reverb.recording import CaptureTrace, EventRecorder, iso_utc, utc_now  # noqa: E402


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("recording schedule timestamps must include a timezone")
    return parsed.astimezone(timezone.utc)


def schedule(args: argparse.Namespace) -> tuple[datetime, datetime, int]:
    if args.start_at or args.end_at:
        if not args.start_at or not args.end_at or args.duration_minutes is not None:
            raise ValueError("provide both --start-at and --end-at, or only --duration-minutes")
        start, end = parse_utc(args.start_at), parse_utc(args.end_at)
        duration = (end - start).total_seconds()
        if duration <= 0 or duration % 60:
            raise ValueError("recording window must be a positive whole number of minutes")
        if start.second or start.microsecond or end.second or end.microsecond:
            raise ValueError("recording bounds must align exactly to a UTC minute")
        count = int(duration // 60)
    else:
        minutes = args.duration_minutes if args.duration_minutes is not None else 60
        if minutes < 1 or minutes > 1440:
            raise ValueError("duration must be between 1 and 1440 minutes")
        now = utc_now()
        start = datetime.fromtimestamp((int(now.timestamp()) // 60 + 1) * 60, timezone.utc)
        end = start + timedelta(minutes=minutes)
        count = minutes
    return start, end, count


def create_run_directory() -> Path:
    root = ROOT / "data" / "private" / "costco-recordings"
    root.mkdir(parents=True, exist_ok=True)
    name = utc_now().strftime("%Y%m%dT%H%M%SZ-") + uuid4().hex[:8]
    return root / name


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-at", help="UTC ISO-8601 start, e.g. 2026-09-24T19:30:00Z")
    parser.add_argument("--end-at", help="UTC ISO-8601 end, exclusive")
    parser.add_argument("--duration-minutes", type=int,
                        help="one-minute diagnostic duration (defaults to 60 when no window is supplied)")
    parser.add_argument("--max-lateness-seconds", type=int, default=10,
                        help="late slots are marked as gaps, never backfilled")
    args = parser.parse_args()

    try:
        start_at, end_at, expected_slots = schedule(args)
        if args.max_lateness_seconds < 0 or args.max_lateness_seconds >= 60:
            raise ValueError("max lateness must be between 0 and 59 seconds")
        load_local_env(ROOT)
        # The recorder never trades, so prefer dedicated read-only credentials
        # without replacing the existing order-capable key.
        credentials = Credentials.from_env_priority("BITGET_READ", "BITGET_DATA", "BITGET")
        config_bytes = (ROOT / "config" / "costco_run.json").read_bytes()
        config = json.loads(config_bytes)
        symbol = config["token_symbol"]
        if symbol != "RCOSTUSDT":
            raise ValueError("Costco recorder requires the live-probed RCOSTUSDT pair")
    except (ValueError, KeyError, ReverbError, OSError, json.JSONDecodeError) as exc:
        print(f"RECORDER HALTED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    trace = CaptureTrace()
    http = httpx.Client(timeout=20.0, event_hooks={
        "request": [trace.on_request], "response": [trace.on_response],
    })
    client = BitgetClient(credentials=credentials, client=http)
    directory = create_run_directory()
    recorder = EventRecorder(directory=directory, config=config, config_bytes=config_bytes,
                             client=client, trace=trace, symbol=symbol)
    interrupted = False
    try:
        instrument = client.instrument(symbol)
        stock_info = client.reality_stock_info(symbol)
        if len(stock_info) != 1 or stock_info[0].get("symbol") != symbol:
            raise DataUnavailable("live stock-info did not return exactly one Costco Reality token")
        metadata = stock_info[0]
        if instrument.get("isReality") != "yes" or instrument.get("status") != "online":
            raise DataUnavailable("Costco pair no longer matches live online Reality instrument metadata")
        if "after_hours" not in metadata.get("tradingPeriod", []):
            raise DataUnavailable("Costco is not currently listed for after-hours trading")

        recorder.ledger.append("eligibility_preflight", {
            "checked_at": iso_utc(utc_now()),
            "symbol": symbol,
            "is_reality": instrument.get("isReality"),
            "instrument_status": instrument.get("status"),
            "trading_period": metadata.get("tradingPeriod"),
            "weekend_tradable": metadata.get("weekendTradable"),
            "source": "live Bitget instruments + Reality stock-info",
        })
        print(f"Read-only Costco recorder started: {symbol}; raw captures stay under data/private.", flush=True)
        print(f"Window: {iso_utc(start_at)} → {iso_utc(end_at)} ({expected_slots} minute slots).", flush=True)
        print("Candles and the raw account-scoped Reality order book are required. Public book/fills are diagnostics; Reality platform fills are optional provenance. No order path is called.", flush=True)

        slot = start_at
        while slot < end_at:
            while True:
                seconds = (slot - utc_now()).total_seconds()
                if seconds <= 0:
                    break
                time.sleep(min(seconds, 1.0))
            lateness = (utc_now() - slot).total_seconds()
            if lateness > args.max_lateness_seconds:
                recorder.ledger.append("capture_gap", {
                    "slot_at": iso_utc(slot),
                    "noticed_at": iso_utc(utc_now()),
                    "lateness_seconds": round(lateness, 3),
                    "reason": "recorder did not begin the required minute slot in time; no backfill attempted",
                })
                print(f"GAP: {iso_utc(slot)} missed by {lateness:.1f}s", flush=True)
            else:
                result = recorder.capture_slot(slot)
                states = ", ".join(f"{row['endpoint']}={'ok' if row['success'] else 'blocked'}"
                                    for row in result["endpoint_results"])
                print(f"{iso_utc(slot)} complete={result['complete']} {states}", flush=True)
            slot += timedelta(minutes=1)
    except KeyboardInterrupt:
        interrupted = True
        print("Recorder interrupted; finalizing an INCOMPLETE marker.", file=sys.stderr, flush=True)
    except Exception as exc:
        interrupted = True
        print(f"Recorder stopped after {type(exc).__name__}; evidence remains INCOMPLETE.", file=sys.stderr, flush=True)
    finally:
        try:
            summary = recorder.finish(expected_slots=expected_slots, end_at=end_at, interrupted=interrupted)
            print(json.dumps({"directory": str(directory.relative_to(ROOT)), **summary}, sort_keys=True), flush=True)
        finally:
            client.close()

    return 0 if summary["status"] == "COMPLETE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
