"""Read-only feasibility evidence. No credentials, orders, or strategy decisions."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
GENESIS = "0" * 64


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(value).hexdigest()


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def write_new(path, body):
    with path.open("xb") as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())


class Evidence:
    def __init__(self, directory):
        self.directory = directory
        self.ledger = directory / "ledger.jsonl"
        self.previous = GENESIS
        self.sequence = 0

    def append(self, event):
        self.sequence += 1
        record = {"sequence": self.sequence, "previous": self.previous, **event}
        record["hash"] = digest(canonical(record))
        with self.ledger.open("ab") as stream:
            stream.write(canonical(record) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        self.previous = record["hash"]
        return record

    def get(self, name, url, timeout):
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "https" or parsed.hostname not in {"api.bitget.com", "www.bitget.com"}:
            raise ValueError("Evidence collector only accepts official Bitget HTTPS URLs")
        sent_at = utc_now()
        started = time.monotonic()
        error = None
        status = None
        body = None
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "Reverb-feasibility/0.1"})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                status = response.status
                body = response.read()
        except urllib.error.HTTPError as exc:
            status = exc.code
            body = exc.read()
            error = f"HTTP_{status}"
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            error = f"{type(exc).__name__}: {exc}"
        received_at = utc_now()
        filename = None
        if body is not None:
            filename = f"{self.sequence + 1:03d}-{name}.body"
            write_new(self.directory / filename, body)
        event = self.append({
            "kind": "http", "name": name, "url": url, "sent_at": sent_at,
            "received_at": received_at, "elapsed_ms": round((time.monotonic() - started) * 1000),
            "status": status, "error": error, "body": filename,
            "body_sha256": digest(body) if body is not None else None,
        })
        print(f"{name}: {status if status is not None else 'NETWORK_ERROR'}", flush=True)
        return event


def verify(directory):
    records = []
    previous = GENESIS
    for sequence, line in enumerate((directory / "ledger.jsonl").read_bytes().splitlines(), 1):
        row = json.loads(line)
        claimed = row.pop("hash")
        if row["sequence"] != sequence or row["previous"] != previous or digest(canonical(row)) != claimed:
            raise ValueError(f"Ledger integrity failed at record {sequence}")
        if row.get("body"):
            if Path(row["body"]).name != row["body"]:
                raise ValueError("Invalid evidence file path")
            if digest((directory / row["body"]).read_bytes()) != row["body_sha256"]:
                raise ValueError(f"Response integrity failed: {row['name']}")
        row["hash"] = claimed
        records.append(row)
        previous = claimed
    if not records or records[-1]["kind"] != "complete":
        raise ValueError("Interrupted capture: no completion record; retain as gap evidence")
    if digest((directory / "config.json").read_bytes()) != records[0]["config_sha256"]:
        raise ValueError("Configuration integrity failed")
    return records


def payload(directory, record):
    if record["error"] or record["status"] != 200:
        raise ValueError(f"{record['name']}: {record['error'] or record['status']}")
    response = json.loads((directory / record["body"]).read_bytes())
    if response["code"] != "00000":
        raise ValueError(f"{record['name']}: Bitget {response['code']} {response.get('msg', '')}")
    return response["data"]


class TokenTable(HTMLParser):
    """Extract table cells only; never mistake navigation prose for token membership."""
    def __init__(self):
        super().__init__()
        self.in_cell = False
        self.parts = []
        self.tokens = set()

    def handle_starttag(self, tag, attrs):
        if tag in {"td", "th"}:
            self.in_cell = True
            self.parts = []

    def handle_data(self, data):
        if self.in_cell:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag in {"td", "th"} and self.in_cell:
            value = "".join(self.parts).strip()
            if re.fullmatch(r"r[A-Z][A-Z0-9.]*", value):
                self.tokens.add(value)
            self.in_cell = False


def reality(rows):
    if not isinstance(rows, list) or not rows:
        raise ValueError("Instrument universe missing")
    selected = []
    for row in rows:
        if row.get("isReality") == "yes":
            if row["symbolType"] != "stock" or not row["baseCoin"].startswith("r"):
                raise ValueError("Reality metadata disagreement")
            if row["status"] == "online":
                selected.append(row)
    if not selected:
        raise ValueError("No online Reality instruments identified")
    return selected


def continuously_traded_symbols(rows):
    if not isinstance(rows, list) or not rows:
        raise ValueError("Reality stock session metadata missing")
    selected = set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("symbol"), str):
            raise ValueError("Malformed Reality stock session metadata")
        periods = row.get("tradingPeriod")
        if row.get("weekendTradable") == "yes" and isinstance(periods, list) and "after_hours" in periods:
            selected.add(row["symbol"])
    if not selected:
        raise ValueError("No continuously traded Reality symbols identified")
    return selected


def book_metrics(data, record, config):
    bids = [(Decimal(str(p)), Decimal(str(q))) for p, q in data["b"]]
    asks = [(Decimal(str(p)), Decimal(str(q))) for p, q in data["a"]]
    if not bids or not asks:
        raise ValueError("Book has an empty side")
    if any(not p.is_finite() or not q.is_finite() or p <= 0 or q <= 0 for p, q in bids + asks):
        raise ValueError("Invalid price or size in book")
    bid = max(p for p, _ in bids)
    ask = min(p for p, _ in asks)
    if ask <= bid:
        raise ValueError("Locked or crossed book")
    received_ms = int(datetime.fromisoformat(record["received_at"]).timestamp() * 1000)
    age = received_ms - int(data["ts"])
    status = "FRESH"
    if age > config["max_book_age_ms"]:
        status = "STALE"
    elif age < -config["max_future_skew_ms"]:
        status = "FUTURE_TIMESTAMP"
    return {
        # Small negative values are ordinary cross-host clock skew and pass the
        # configured tolerance. Publish zero rather than a nonsensical age.
        "status": status, "age_ms": max(age, 0),
        "spread_bps": str((ask - bid) / ((ask + bid) / 2) * 10000),
        "displayed_bid_notional": str(sum(p * q for p, q in bids)),
        "displayed_ask_notional": str(sum(p * q for p, q in asks)),
    }


def capture(config_path):
    config_bytes = config_path.read_bytes()
    config = json.loads(config_bytes)
    if config["candle_type"] != "market" or config["candle_interval"] != "1m":
        raise ValueError("Feasibility capture requires one-minute market candles")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ-") + uuid4().hex[:8]
    directory = ROOT / "evidence" / "runs" / run_id
    directory.mkdir(parents=True, exist_ok=False)
    write_new(directory / "config.json", config_bytes)
    evidence = Evidence(directory)
    evidence.append({"kind": "start", "at": utc_now(), "config_sha256": digest(config_bytes)})
    failures = []

    def fetch(name, endpoint, params):
        url = config["api_base"] + config["paths"][endpoint] + "?" + urllib.parse.urlencode(params)
        row = evidence.get(name, url, config["timeout_seconds"])
        try:
            return payload(directory, row)
        except (ValueError, KeyError, TypeError) as exc:
            reason = str(exc)
            failures.append({"request": name, "reason": reason})
            evidence.append({"kind": "failure", "request": name, "reason": reason, "at": utc_now()})
            print(reason, file=sys.stderr, flush=True)
            return None

    rows = fetch("instruments", "instruments", {"category": "SPOT"})
    tickers = fetch("tickers", "tickers", {"category": "SPOT"})
    stock_info = fetch("stock-info", "stock_info", {})
    fetch("fee-group", "fee_group", {"category": "SPOT"})
    try:
        continuous_symbols = continuously_traded_symbols(stock_info)
        evidence.append({"kind": "session_metadata", "source": config["paths"]["stock_info"],
                         "continuous_symbol_count": len(continuous_symbols), "at": utc_now()})
    except (ValueError, KeyError, TypeError) as exc:
        continuous_symbols = set()
        failures.append({"request": "stock-info-parse", "reason": str(exc)})
        evidence.append({"kind": "failure", "request": "stock-info-parse", "reason": str(exc), "at": utc_now()})
        print(str(exc), file=sys.stderr, flush=True)

    try:
        # The book sample is a live execution diagnostic. It is selected from
        # the runtime Reality universe; the dated weekend list is tracked
        # separately and must never be silently treated as the same universe.
        if not isinstance(tickers, list) or not tickers:
            raise ValueError("Ticker universe unavailable")
        candidates = reality(rows)
        turnover = {r["symbol"]: Decimal(r["turnover24h"]) for r in tickers}
        candidates = [r for r in candidates if r["symbol"] in turnover]
        if any(not turnover[r["symbol"]].is_finite() or turnover[r["symbol"]] < 0 for r in candidates):
            raise ValueError("Invalid ticker turnover")
        selected = sorted(candidates, key=lambda r: (-turnover[r["symbol"]], r["symbol"]))[:config["sample_size"]]
        if len(selected) != config["sample_size"]:
            raise ValueError("Insufficient online Reality candidates for configured sample")
        selected_weekend = [r["symbol"] for r in candidates if r["symbol"] in continuous_symbols]
        evidence.append({"kind": "selection", "method": "online Reality instruments ranked by live ticker turnover24h",
                         "symbols": [r["symbol"] for r in selected], "candidate_count": len(candidates),
                         "weekend_source_status": "AVAILABLE" if continuous_symbols else "UNAVAILABLE",
                         "weekend_candidate_count": len(selected_weekend) if continuous_symbols else None})
        for instrument in selected:
            symbol = instrument["symbol"]
            fetch(f"book-{symbol}", "orderbook", {"category": "SPOT", "symbol": symbol, "limit": config["book_levels"]})
            fetch(f"candles-{symbol}", "candles", {"category": "SPOT", "symbol": symbol,
                  "interval": config["candle_interval"], "type": config["candle_type"], "limit": config["candle_limit"]})
        # Candidate mapping only; entitlement failure is not evidence of no options.
        candidate_underlying = selected[0]["baseCoin"][1:] + ".US"
        fetch("option-expiry-access", "option_expiry", {"symbol": candidate_underlying})
    except (ValueError, KeyError, TypeError) as exc:
        failures.append({"request": "selection", "reason": str(exc)})
        evidence.append({"kind": "failure", "request": "selection", "reason": str(exc), "at": utc_now()})
        print(str(exc), file=sys.stderr, flush=True)
    evidence.append({"kind": "complete", "at": utc_now(), "failures": failures,
                     "m0_gate": "BLOCKED", "orders_submitted": False})
    print(f"Evidence: {directory}", flush=True)
    return 2 if failures else 0


def measurements(directory):
    records = verify(directory)
    config = json.loads((directory / "config.json").read_bytes())
    requests = {r["name"]: r for r in records if r["kind"] == "http"}
    lines = ["# Public-data feasibility measurements", "", f"Run: `{directory.name}`.", "",
             f"Ledger head: `{records[-1]['hash']}`.", "",
             "OBSERVED: these are capture-time diagnostic snapshots, not earnings-window measurements.",
             "The options intersection, event sample, fills and strategy performance remain unmeasured.", ""]
    try:
        rows = payload(directory, requests["instruments"])
        tokens = reality(rows)
        lines.append(f"OBSERVED: {len(rows)} spot instruments returned; {len(tokens)} online Reality instruments.")
    except (ValueError, KeyError, TypeError) as exc:
        lines.append(f"UNAVAILABLE: {exc}")
    selections = [r for r in records if r["kind"] == "selection"]
    if selections:
        selection = selections[0]
        candidate_note = f"OBSERVED: {selection['candidate_count']} online Reality candidates came from the live instruments and ticker feeds."
        if selection.get("weekend_source_status") == "AVAILABLE":
            candidate_note += f" Bitget's live stock-info metadata verified {selection.get('weekend_candidate_count')} of them for weekend plus after-hours trading; this still is not the options intersection."
        else:
            candidate_note += " Live Reality session metadata was unavailable, so 24/7 membership remains unverified; this is not the options intersection."
        lines += ["", candidate_note, "",
                  "| Symbol | Spread (basis points) | Displayed bid / ask value (quote units) | Book age (ms) | Freshness |",
                  "| --- | ---: | ---: | ---: | --- |"]
        for symbol in selection["symbols"]:
            try:
                record = requests[f"book-{symbol}"]
                metric = book_metrics(payload(directory, record), record, config)
                lines.append(f"| {symbol} | {Decimal(metric['spread_bps']):.4f} | {metric['displayed_bid_notional']} / {metric['displayed_ask_notional']} | {metric['age_ms']} | {metric['status']} |")
            except (ValueError, KeyError, TypeError) as exc:
                lines.append(f"| {symbol} | — | — | — | UNAVAILABLE: {exc} |")
        lines += ["", "Displayed depth covers only the requested levels and is not a guaranteed fill.",
                  "A stale timestamp is retained as a failed freshness gate, never promoted to a live quote.", ""]
        for symbol in selection["symbols"]:
            try:
                data = payload(directory, requests[f"candles-{symbol}"])
                if not isinstance(data, list) or not data:
                    raise ValueError("Empty or malformed candle history")
                timestamps = sorted(int(r[0]) for r in data)
                gaps = sum(b - a != 60000 for a, b in zip(timestamps, timestamps[1:]))
                lines.append(f"OBSERVED `{symbol}`: {len(data)} candles returned; {gaps} nonconsecutive timestamp pairs. This is not a validated earnings baseline.")
            except (ValueError, KeyError, TypeError) as exc:
                lines.append(f"UNAVAILABLE `{symbol}` candles: {exc}")
    lines += ["", "## Access and collection failures", ""]
    for failure in records[-1]["failures"]:
        lines.append(f"- OBSERVED `{failure['request']}`: {failure['reason']}")
    if not records[-1]["failures"]:
        lines.append("No HTTP/API collection failures; this does not establish account eligibility or gate completion.")
    lines += ["", "The public option expiry request carries no credentials. Its response cannot establish account eligibility.",
              "`fee-group` records fee-group data only; it is not the user's applicable fee rate.", "",
              "Rebuild: `python3 scripts/probe.py report`. Verify the published table: `python3 scripts/probe.py report --check`.", ""]
    return "\n".join(lines)


def latest_complete_run(root: Path) -> Path:
    """Ignore interrupted captures; retain them as gap evidence without
    making report/preview unusable after a transient network outage."""
    failures = []
    for directory in sorted((path for path in (root / "evidence" / "runs").iterdir() if path.is_dir()), reverse=True):
        try:
            records = verify(directory)
            instruments = next((row for row in records if row.get("kind") == "http" and row.get("name") == "instruments"), None)
            if "selection" not in {row.get("kind") for row in records} or instruments is None or instruments.get("status") != 200:
                raise ValueError("capture has no usable instrument/selection evidence")
            return directory
        except (ValueError, KeyError, OSError) as exc:
            failures.append(f"{directory.name}: {exc}")
    raise ValueError("No complete evidence capture exists: " + "; ".join(failures))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["capture", "report"])
    parser.add_argument("--run", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.action == "capture":
        return capture(ROOT / "config" / "probe.json")
    directory = args.run if args.run is not None else latest_complete_run(ROOT)
    output = measurements(directory)
    target = ROOT / "docs" / "measurements.md"
    if args.check:
        if target.read_text() != output:
            raise ValueError("Published measurements do not regenerate from the evidence ledger")
        print("Published measurements verified")
    else:
        target.write_text(output)
        print(output)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, KeyError, OSError) as exc:
        print(f"REVERB HALTED: {exc}", file=sys.stderr)
        sys.exit(2)
