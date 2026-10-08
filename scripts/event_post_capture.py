"""After an event's recording window: the mechanical post-capture steps, safe to re-run.

1. Wait until the recorder has finished and its ledger says recording_complete.
2. Record the issuer release time from the issuer's own feed, bounded by the same-day 8-K.
3. Save Exhibit 99.1 of that 8-K (the release) as fetched HTML and whitespace-normalised text.
4. Publish the public part of the raw capture (account-scoped bodies withheld by hash).
5. Build capture_summary.json from the published raw capture.

Steps already done are skipped; a step that cannot run yet (recorder active, 8-K not filed)
is reported as pending and the script exits 75 so a later timer firing retries. It never
scores claims, never calls a model, and never commits or pushes.

    python scripts/event_post_capture.py apld-q1-fy27
    python scripts/event_post_capture.py stz-q2-fy27 --out-root /tmp/check   # rebuild check
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import subprocess
from decimal import Decimal
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import costco_capture_summary as capture_summary  # noqa: E402
import costco_publish_raw as publish_raw  # noqa: E402
import issuer_release_record as release_record  # noqa: E402
from reverb.ledger import Ledger  # noqa: E402

PENDING = 75
EXHIBIT = re.compile(r"ex[-_]?99[-_.]?0?1(?!\d)", re.IGNORECASE)
DECLARED = re.compile(r"<TYPE>EX-99\.0?1\s*<SEQUENCE>\d+\s*<FILENAME>(\S+)", re.IGNORECASE)


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize(body: str) -> str:
    """The same normalisation the STZ reconciliation used for its release text."""
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", body))).strip()


def recorder_active(event_id: str) -> bool:
    state = subprocess.run(["systemctl", "--user", "is-active", f"reverb-{event_id}-recorder.service"],
                           capture_output=True, text=True).stdout.strip()
    return state in {"active", "activating", "reloading"}


def finished_capture(event_id: str) -> Path | None:
    runs = sorted(p for p in (ROOT / "data/private/event-recordings" / event_id).glob("2026*") if p.is_dir())
    if not runs:
        return None
    rows = Ledger(runs[-1] / "ledger.jsonl").verify()
    return runs[-1] if any(row["kind"] == "recording_complete" for row in rows) else None


def declared_exhibits(headers_html: str) -> list[str]:
    """Filenames the filing's own SGML header types as EX-99.1 (issuers name the file freely)."""
    return [name for name in DECLARED.findall(html.unescape(headers_html)) if name.lower().endswith((".htm", ".html"))]


def save_release_text(event_id: str, post: Path) -> dict:
    event = release_record.EVENTS[event_id]
    filings = json.loads(release_record.fetch(f"https://data.sec.gov/submissions/CIK{event['cik']}.json",
                                              release_record.USER_AGENT))["filings"]["recent"]
    same_day = [i for i, form in enumerate(filings["form"]) if form == "8-K" and filings["filingDate"][i] == event["date"]]
    if not same_day:
        raise LookupError("no same-day 8-K on EDGAR yet")
    i = min(same_day, key=lambda k: filings["acceptanceDateTime"][k])
    folder = f"https://www.sec.gov/Archives/edgar/data/{int(event['cik'])}/{filings['accessionNumber'][i].replace('-', '')}"
    accession = filings["accessionNumber"][i]
    headers = release_record.fetch(f"{folder}/{accession}-index-headers.html", release_record.USER_AGENT)
    exhibits = declared_exhibits(headers.decode("utf-8", errors="replace"))
    if not exhibits:
        index = json.loads(release_record.fetch(f"{folder}/index.json", release_record.USER_AGENT))
        exhibits = [item["name"] for item in index["directory"]["item"]
                    if item["name"].lower().endswith((".htm", ".html")) and EXHIBIT.search(item["name"])]
    if len(exhibits) != 1:
        raise LookupError(f"expected one Exhibit 99.1 in {folder}, found {exhibits}")
    url = f"{folder}/{exhibits[0]}"
    body = release_record.fetch(url, release_record.USER_AGENT)
    text = normalize(body.decode("utf-8", errors="replace"))
    post.mkdir(parents=True, exist_ok=True)
    (post / "release_exhibit_99_1.htm").write_bytes(body)
    (post / "release.txt").write_text(text, encoding="utf-8")
    source = {"url": url, "filing_index": f"{folder}/", "acceptance": filings["acceptanceDateTime"][i],
              "captured_at": now(), "html_sha256": hashlib.sha256(body).hexdigest(),
              "text_path": str((post / "release.txt").relative_to(ROOT)) if post.is_relative_to(ROOT) else str(post / "release.txt"),
              "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
              "normalisation": "tags replaced by spaces, HTML entities unescaped, whitespace runs collapsed"}
    (post / "release_source.json").write_text(json.dumps(source, indent=2) + "\n", encoding="utf-8")
    return source


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("event", choices=sorted(release_record.EVENTS))
    parser.add_argument("--out-root", type=Path, help="write here instead of evidence/events/<event> (rebuild checks)")
    args = parser.parse_args()
    config = json.loads((ROOT / "config/events" / f"{args.event}.json").read_text())
    out = (args.out_root or ROOT / "evidence/events" / args.event).resolve()
    post = out / "post_event"
    log: list[dict] = []
    pending = False

    def step(name: str, status: str, **detail) -> None:
        log.append({"at": now(), "event": args.event, "step": name, "status": status, **detail})

    if recorder_active(args.event):
        step("recording", "pending", reason="recorder still active")
        pending = True
        capture = None
    else:
        capture = finished_capture(args.event)
        if capture is None:
            step("recording", "pending", reason="no finished capture with recording_complete")
            pending = True
        else:
            step("recording", "done", capture=capture.name)

    record_path = post / "issuer_release_timestamp.json"
    if record_path.exists():
        step("release_time", "skipped", reason="already recorded")
    else:
        try:
            body, record = release_record.build(args.event, now())
            post.mkdir(parents=True, exist_ok=True)
            (post / "issuer_press_release_feed.xml").write_bytes(body)
            record["body_path"] = str((post / "issuer_press_release_feed.xml").relative_to(ROOT)) \
                if post.is_relative_to(ROOT) else str(post / "issuer_press_release_feed.xml")
            record_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
            step("release_time", "done", issuer_release_timestamp=record["issuer_release_timestamp"])
        except SystemExit as exc:
            step("release_time", "pending", reason=str(exc))
            pending = True

    if (post / "release.txt").exists():
        step("release_text", "skipped", reason="already saved")
    else:
        try:
            source = save_release_text(args.event, post)
            step("release_text", "done", url=source["url"])
        except (LookupError, OSError, ValueError, KeyError) as exc:
            step("release_text", "pending", reason=str(exc)[:200])
            pending = True

    if capture is not None:
        raw = out / "raw" / capture.name
        if raw.exists():
            step("raw_publish", "skipped", reason="already published")
        else:
            publish_raw.publish(capture, out / "raw")
            step("raw_publish", "done", files=sum(1 for _ in raw.iterdir()))
        baseline_ms = int(datetime.fromisoformat(config["baseline_at"].replace("Z", "+00:00")).timestamp() * 1000)
        text = capture_summary.render(raw, symbol=config["token_symbol"], baseline_ms=baseline_ms,
                                      trigger_pct=float(Decimal(config["reaction_trigger_pct"]) * 100),
                                      release_record=record_path, issuer=release_record.EVENTS[args.event]["short"])
        (out / "capture_summary.json").write_text(text, encoding="utf-8")
        status = json.loads(text)["run_status"]
        step("capture_summary", "done", run_status=status)

    journal = ROOT / "data/private/run-journal" / datetime.now(timezone.utc).strftime("%Y-%m-%d") / "post_capture.log"
    journal.parent.mkdir(parents=True, exist_ok=True)
    with journal.open("a", encoding="utf-8") as handle:
        handle.write("".join(json.dumps(row) + "\n" for row in log))
    for row in log:
        print(json.dumps(row))
    return PENDING if pending else 0


if __name__ == "__main__":
    sys.exit(main())
