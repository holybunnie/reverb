"""Fifteen-minute heartbeat for registered event recordings; read-only, no order path.

Outside an event's window (with a 30-minute margin) it does nothing. Inside, it
appends one line per event to data/private/run-journal/<UTC date>/heartbeat.log:
recorder state, slots captured versus expected so far, gaps, last candle close,
public-book levels, ticker bid/ask and non-success responses. From the window
start it also polls SEC EDGAR for the issuer's results 8-K and stores the raw
filing index once, so the release time is evidenced without waiting for a human.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CIK = {"stz-q2-fy27": "0000016918", "apld-q1-fy27": "0001144879"}
USER_AGENT = "Reverb evidence capture admin@example.invalid"
MARGIN = timedelta(minutes=30)


def now() -> datetime:
    return datetime.now(timezone.utc)


def parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def latest_run(event_id: str) -> Path | None:
    runs = sorted(p for p in (ROOT / "data/private/event-recordings" / event_id).glob("2026*") if p.is_dir())
    return runs[-1] if runs else None


def recorder_state(event_id: str) -> str:
    unit = f"reverb-{event_id}-recorder.service"
    result = subprocess.run(["systemctl", "--user", "is-active", unit], capture_output=True, text=True)
    return result.stdout.strip() or "unknown"


def summarize_run(run: Path, start: datetime, end: datetime) -> dict:
    rows = [json.loads(line) for line in (run / "ledger.jsonl").read_text(encoding="utf-8").splitlines()]
    slots = [r["payload"] for r in rows if r["kind"] == "capture_slot"]
    gaps = sum(r["kind"] == "capture_gap" for r in rows)
    attempts = [r["payload"] for r in rows if r["kind"] == "capture_attempt"]
    failures = [f"{a['endpoint']}:{a.get('http_status')}/{a.get('bitget_code')}" for a in attempts[-60:]
                if not a.get("success") and not a["endpoint"].startswith("reality_")]
    out = {"run": run.name, "slots": len(slots), "complete": sum(bool(s.get("complete")) for s in slots), "gaps": gaps,
           "expected_so_far": max(0, min(int((now() - start).total_seconds() // 60) + 1, int((end - start).total_seconds() // 60))),
           "failures_recent": sorted(set(failures))}
    latest = {}
    for attempt in reversed(attempts):
        if attempt.get("success") and attempt.get("body") and attempt["endpoint"] not in latest:
            latest[attempt["endpoint"]] = json.loads((run / Path(attempt["body"]).name).read_text())["data"]
    if latest.get("candles"):
        last = max(latest["candles"], key=lambda c: int(c[0]))
        out["last_close"] = [datetime.fromtimestamp(int(last[0]) / 1000, timezone.utc).strftime("%H:%M"), last[4]]
    if isinstance(latest.get("public_orderbook"), dict):
        out["book_levels"] = len(latest["public_orderbook"].get("a", [])) + len(latest["public_orderbook"].get("b", []))
    if latest.get("ticker"):
        out["bid_ask"] = [latest["ticker"][0].get("bid1Price"), latest["ticker"][0].get("ask1Price")]
    return out


def watch_edgar(event_id: str, frozen_at: datetime) -> dict:
    target = ROOT / "data/private/event-recordings" / event_id / "release"
    found = target / "edgar_8k.json"
    if found.exists():
        return {"edgar_8k": json.loads(found.read_text())["acceptanceDateTime"]}
    request = urllib.request.Request(f"https://data.sec.gov/submissions/CIK{CIK[event_id]}.json",
                                     headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=20) as response:
        body = response.read()
    recent = json.loads(body)["filings"]["recent"]
    for i, form in enumerate(recent["form"]):
        accepted = parse(recent["acceptanceDateTime"][i])
        if form == "8-K" and "2.02" in recent["items"][i] and accepted > frozen_at:
            target.mkdir(parents=True, exist_ok=True)
            record = {key: recent[key][i] for key in ("accessionNumber", "acceptanceDateTime", "filingDate",
                                                       "items", "primaryDocument")}
            record.update({"observed_at": now().isoformat().replace("+00:00", "Z"),
                           "submissions_sha256": hashlib.sha256(body).hexdigest()})
            (target / "edgar_submissions.json").write_bytes(body)
            found.write_text(json.dumps(record, indent=2) + "\n")
            return {"edgar_8k": record["acceptanceDateTime"], "edgar_first_seen": record["observed_at"]}
    return {"edgar_8k": None}


def preflight(event_id: str) -> dict:
    out = {}
    try:
        sent = now().timestamp()
        with urllib.request.urlopen("https://api.bitget.com/api/v2/public/time", timeout=10) as response:
            server = int(json.loads(response.read())["data"]["serverTime"])
        out["clock_offset_ms"] = round(server - (sent + now().timestamp()) / 2 * 1000)
    except Exception as exc:
        out["clock_error"] = type(exc).__name__
    meminfo = dict(line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines())
    out["mem_available_mb"] = int(meminfo["MemAvailable"].split()[0]) // 1024
    stat = __import__("shutil").disk_usage(ROOT)
    out["disk_free_gb"] = stat.free // 2**30
    timer = subprocess.run(["systemctl", "--user", "show", f"reverb-{event_id}-recorder.timer",
                            "-p", "NextElapseUSecRealtime", "-p", "ActiveState"], capture_output=True, text=True).stdout
    out["timer"] = " ".join(timer.split())
    out["env_present"] = (ROOT / ".env").exists()
    if abs(out.get("clock_offset_ms", 0)) > 2000 or out["mem_available_mb"] < 120 or not out["env_present"]:
        out["ALERT"] = "preflight outside limits"
    return out


def main() -> int:
    lines = []
    for config_path in sorted((ROOT / "config/events").glob("*.json")):
        config = json.loads(config_path.read_text(encoding="utf-8"))
        event_id = config["event_id"]
        start, end = parse(config["window_start"]), parse(config["window_end"])
        if not (start - MARGIN <= now() <= end + MARGIN):
            continue
        entry = {"at": now().strftime("%Y-%m-%dT%H:%M:%SZ"), "event": event_id, "recorder": recorder_state(event_id)}
        if now() < start:
            entry.update(preflight(event_id))
        run = latest_run(event_id)
        try:
            entry.update(summarize_run(run, start, end) if run else {"run": None})
        except (OSError, ValueError, KeyError) as exc:
            entry["run_error"] = f"{type(exc).__name__}: {exc}"
        if now() >= start:
            frozen = json.loads((ROOT / "evidence/events" / event_id / "registration_manifest.json").read_text())
            try:
                entry.update(watch_edgar(event_id, parse(frozen["frozen_at"])))
            except Exception as exc:  # the heartbeat must never stop on an EDGAR hiccup
                entry["edgar_error"] = type(exc).__name__
        if now() >= start + timedelta(minutes=2) and entry["recorder"] != "active" and now() < end:
            entry["ALERT"] = "recorder is not active inside its window"
        lines.append(json.dumps(entry, sort_keys=True))
    if lines:
        log = ROOT / "data/private/run-journal" / now().strftime("%Y-%m-%d") / "heartbeat.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
        print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
