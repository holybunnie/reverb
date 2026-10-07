"""Record an event's issuer release time from the issuer's own press-release RSS feed.

Finds the results release in the feed by its headline, takes its pubDate (which must carry an
explicit UTC offset), and bounds it by the EDGAR 8-K acceptance on the same day. Writes the
feed body and issuer_release_timestamp.json under the event's post_event directory. Without
an explicit offset, or if the feed time is after the 8-K, it refuses rather than guesses.

    python scripts/issuer_release_record.py apld-q1-fy27
    python scripts/issuer_release_record.py stz-q2-fy27 --check   # compare with the committed record
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ElementTree
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
USER_AGENT = "Reverb evidence capture admin@example.invalid"
EVENTS = {
    "stz-q2-fy27": {"issuer": "Constellation Brands", "short": "Constellation", "cik": "0000016918", "date": "2026-10-06",
                    "feed": "https://ir.cbrands.com/news-events/press-releases/rss",
                    "headline": r"Reports Second Quarter Fiscal 2027 Financial Results"},
    "apld-q1-fy27": {"issuer": "Applied Digital", "short": "Applied Digital", "cik": "0001144879", "date": "2026-10-07",
                     "feed": "https://ir.applieddigital.com/news-events/press-releases/rss",
                     "headline": r"Reports (Fiscal )?First Quarter (Fiscal )?(Year )?2027\b.*Results"},
}


def fetch(url: str, agent: str) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": agent}), timeout=30) as response:
        return response.read()


def utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build(event_id: str, captured_at: str) -> tuple[bytes, dict]:
    event = EVENTS[event_id]
    body = fetch(event["feed"], "Mozilla/5.0")
    items = [(item.findtext("title") or "", item.findtext("pubDate") or "")
             for item in ElementTree.fromstring(body).iter("item")]
    results = [(title, stamp) for title, stamp in items if re.search(event["headline"], title)]
    if len(results) != 1:
        raise SystemExit(f"expected one results release in the feed, found {len(results)}: {results}")
    title, stamp = results[0]
    if not re.search(r"[+-]\d{4}$", stamp.strip()):
        raise SystemExit(f"feed pubDate has no explicit UTC offset: {stamp!r}")
    released = parsedate_to_datetime(stamp)
    if released.date().isoformat() != event["date"]:
        raise SystemExit(f"release dated {released.date()}, expected {event['date']}")
    filings = json.loads(fetch(f"https://data.sec.gov/submissions/CIK{event['cik']}.json", USER_AGENT))["filings"]["recent"]
    acceptances = [filings["acceptanceDateTime"][i] for i, form in enumerate(filings["form"])
                   if form == "8-K" and filings["filingDate"][i] == event["date"]]
    if not acceptances:
        raise SystemExit("no same-day 8-K on EDGAR yet; the release time cannot be bounded")
    upper = datetime.fromisoformat(min(acceptances).replace("Z", "+00:00"))
    if released > upper:
        raise SystemExit(f"feed time {utc(released)} is after the 8-K acceptance {utc(upper)}")
    others = [f"{t}, pubDate {s} ({utc(parsedate_to_datetime(s))})" for t, s in items
              if t != title and re.search(r"[+-]\d{4}$", s.strip())
              and parsedate_to_datetime(s).date().isoformat() == event["date"]
              and parsedate_to_datetime(s) > released]
    post = f"evidence/events/{event_id}/post_event"
    record = {
        "source": f"{event['issuer']} investor relations press-release RSS feed ({event['feed'].split('//', 1)[1]})",
        "captured_at": captured_at,
        "body_path": f"{post}/issuer_press_release_feed.xml",
        "body_sha256": hashlib.sha256(body).hexdigest(),
        "headline": title.strip(),
        "feed_press_release_date": released.strftime("%m/%d/%Y %H:%M:%S"),
        "timezone": "America/New_York",
        "timezone_basis": (f"The feed's pubDate carries an explicit {stamp.strip()[-5:]} offset ({stamp.strip()}). "
                           f"It precedes the EDGAR 8-K acceptance at {upper.astimezone(released.tzinfo).strftime('%H:%M:%S')} ET."),
        "issuer_release_timestamp": utc(released),
        "upper_bound_8k_acceptance": utc(upper),
    }
    if others:
        record["same_window_issuer_release"] = "; ".join(others)
    return body, record


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("event", choices=sorted(EVENTS))
    parser.add_argument("--check", action="store_true", help="compare with the committed record; write nothing")
    args = parser.parse_args()
    post = ROOT / f"evidence/events/{args.event}/post_event"
    if args.check:
        committed = json.loads((post / "issuer_release_timestamp.json").read_text())
        _, record = build(args.event, committed["captured_at"])
        keys = ("headline", "feed_press_release_date", "issuer_release_timestamp", "upper_bound_8k_acceptance")
        diff = {k: (committed.get(k), record.get(k)) for k in keys if committed.get(k) != record.get(k)}
        print("matches committed record" if not diff else f"differs: {diff}")
        return
    body, record = build(args.event, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    post.mkdir(parents=True, exist_ok=True)
    (post / "issuer_press_release_feed.xml").write_bytes(body)
    (post / "issuer_release_timestamp.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
