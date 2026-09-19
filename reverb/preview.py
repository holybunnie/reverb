from __future__ import annotations

import html
import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from .errors import DataUnavailable, LedgerError


GENESIS = "0" * 64


@dataclass(frozen=True)
class PreviewSnapshot:
    run_id: str
    captured_at: str
    ledger_head: str
    gate_status: str
    spot_instruments: int
    online_reality: int
    samples: tuple[dict[str, str], ...]
    failures: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": "evidence_replay",
            "run_id": self.run_id,
            "captured_at": self.captured_at,
            "ledger_head": self.ledger_head,
            "gate_status": self.gate_status,
            "spot_instruments": self.spot_instruments,
            "online_reality": self.online_reality,
            "samples": list(self.samples),
            "failures": list(self.failures),
            "orders_submitted": False,
            "credentials_required": False,
            "earnings_event": False,
        }


def _canonical(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _sha256(value: bytes) -> str:
    import hashlib

    return hashlib.sha256(value).hexdigest()


def _verified_records(directory: Path) -> list[dict[str, Any]]:
    ledger = directory / "ledger.jsonl"
    if not ledger.exists():
        raise LedgerError(f"evidence ledger is missing: {ledger}")
    records: list[dict[str, Any]] = []
    previous = GENESIS
    for expected, line in enumerate(ledger.read_bytes().splitlines(), 1):
        try:
            record = json.loads(line)
            claimed = record.pop("hash")
            if (record["sequence"] != expected or record["previous"] != previous
                    or _sha256(_canonical(record)) != claimed):
                raise LedgerError(f"evidence hash mismatch at sequence {expected}")
            if record.get("body"):
                body_name = record["body"]
                if Path(body_name).name != body_name:
                    raise LedgerError("evidence body path escapes the run directory")
                body = directory / body_name
                if not body.exists() or _sha256(body.read_bytes()) != record.get("body_sha256"):
                    raise LedgerError(f"evidence body integrity failed for {record.get('name')}")
            record["hash"] = claimed
            records.append(record)
            previous = claimed
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise LedgerError(f"malformed evidence ledger at sequence {expected}: {exc}") from exc
    if not records or records[-1].get("kind") != "complete":
        raise DataUnavailable("latest evidence capture is incomplete; the preview will not replay a partial run")
    return records


def _body(directory: Path, record: dict[str, Any]) -> dict[str, Any] | list[Any]:
    if record.get("error") or record.get("status") != 200:
        raise DataUnavailable(f"{record.get('name')}: {record.get('error') or record.get('status')}")
    value = json.loads((directory / record["body"]).read_bytes())
    if value.get("code") != "00000":
        raise DataUnavailable(f"{record.get('name')}: Bitget {value.get('code')} {value.get('msg', '')}")
    return value["data"]


def _book_summary(data: dict[str, Any], record: dict[str, Any], symbol: str) -> dict[str, str]:
    bids = [(Decimal(str(price)), Decimal(str(quantity))) for price, quantity in data.get("b", [])]
    asks = [(Decimal(str(price)), Decimal(str(quantity))) for price, quantity in data.get("a", [])]
    if not bids or not asks:
        raise DataUnavailable(f"{symbol}: empty order-book side")
    bid = max(price for price, _ in bids)
    ask = min(price for price, _ in asks)
    if bid <= 0 or ask <= bid:
        raise DataUnavailable(f"{symbol}: invalid or crossed order book")
    received_at = datetime.fromisoformat(record["received_at"])
    age_ms = int(received_at.timestamp() * 1000) - int(data["ts"])
    return {
        "symbol": symbol,
        "spread_bps": str((ask - bid) / ((ask + bid) / 2) * 10000),
        "displayed_bid_notional": str(sum(price * quantity for price, quantity in bids)),
        "displayed_ask_notional": str(sum(price * quantity for price, quantity in asks)),
        "book_age_ms": str(age_ms),
        "freshness": "FRESH" if 0 <= age_ms <= 5000 else "STALE",
    }


def load_preview_snapshot(root: Path) -> PreviewSnapshot:
    runs_root = root / "evidence" / "runs"
    if not runs_root.exists():
        raise DataUnavailable("no evidence capture exists; run scripts/probe.py capture first")
    runs = sorted(path for path in runs_root.iterdir() if path.is_dir())
    if not runs:
        raise DataUnavailable("no evidence capture exists; run scripts/probe.py capture first")
    directory = runs[-1]
    records = _verified_records(directory)
    requests = {record["name"]: record for record in records if record.get("kind") == "http"}
    try:
        instruments = _body(directory, requests["instruments"])
        online = [row for row in instruments if row.get("isReality") == "yes" and row.get("status") == "online"]
        if not online:
            raise DataUnavailable("evidence contains no online Reality instruments")
        selection = next(record for record in records if record.get("kind") == "selection")
        samples = tuple(_book_summary(_body(directory, requests[f"book-{symbol}"]),
                                      requests[f"book-{symbol}"], symbol)
                        for symbol in selection["symbols"])
    except (KeyError, StopIteration, TypeError, ValueError) as exc:
        raise DataUnavailable(f"evidence replay is incomplete: {exc}") from exc
    complete = records[-1]
    captured_at = complete.get("at")
    if not isinstance(captured_at, str):
        raise DataUnavailable("evidence completion timestamp is missing")
    return PreviewSnapshot(
        run_id=directory.name,
        captured_at=captured_at,
        ledger_head=complete["hash"],
        gate_status=str(complete.get("m0_gate", "BLOCKED")),
        spot_instruments=len(instruments),
        online_reality=len(online),
        samples=samples,
        failures=tuple(f"{row.get('request')}: {row.get('reason')}" for row in complete.get("failures", [])),
    )


def _number(value: str, places: int = 4) -> str:
    return f"{Decimal(value):.{places}f}"


def render_preview_html(snapshot: PreviewSnapshot) -> str:
    rows = "".join(
        "<tr>"
        f"<td>{html.escape(row['symbol'])}</td>"
        f"<td>{_number(row['spread_bps'])} bps</td>"
        f"<td>{html.escape(row['displayed_bid_notional'])} / {html.escape(row['displayed_ask_notional'])}</td>"
        f"<td>{html.escape(row['book_age_ms'])} ms</td>"
        f"<td><span class=\"pill {row['freshness'].lower()}\">{html.escape(row['freshness'])}</span></td>"
        "</tr>"
        for row in snapshot.samples
    )
    failures = "".join(f"<li>{html.escape(value)}</li>" for value in snapshot.failures)
    if not failures:
        failures = "<li>No collection failures in this capture.</li>"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Reverb — live evidence preview</title>
<style>
:root {{ color-scheme: dark; --bg:#0c1117; --panel:#141c25; --line:#293646; --text:#edf4f7; --muted:#9aabb7; --cyan:#72e4d2; --amber:#f4c46d; --red:#ff8d85; }}
* {{ box-sizing:border-box; }} body {{ margin:0; background:radial-gradient(circle at 15% 0%,#173442 0,#0c1117 40%); color:var(--text); font:16px/1.55 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
main {{ max-width:1060px; margin:auto; padding:42px 20px 72px; }} .eyebrow {{ color:var(--cyan); letter-spacing:.12em; text-transform:uppercase; font-size:12px; font-weight:700; }}
h1 {{ max-width:760px; font-size:clamp(38px,7vw,76px); line-height:.98; letter-spacing:-.05em; margin:18px 0; }} h2 {{ margin:0 0 12px; font-size:22px; }} p {{ color:var(--muted); max-width:760px; }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:12px; margin:28px 0; }} .card {{ background:rgba(20,28,37,.88); border:1px solid var(--line); border-radius:16px; padding:18px; }} .label {{ color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.08em; }} .value {{ font-size:25px; margin-top:7px; }}
.blocked {{ color:var(--amber); }} .section {{ margin-top:36px; }} table {{ width:100%; border-collapse:collapse; overflow:hidden; border:1px solid var(--line); border-radius:14px; background:rgba(20,28,37,.78); }} th,td {{ text-align:left; padding:13px 14px; border-bottom:1px solid var(--line); }} th {{ color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.06em; }} tr:last-child td {{ border:0; }}
.pill {{ display:inline-block; border-radius:999px; padding:2px 9px; font-size:12px; font-weight:700; }} .fresh {{ background:#173c39; color:var(--cyan); }} .stale {{ background:#4a2629; color:var(--red); }} .notice {{ border-left:3px solid var(--amber); padding:12px 16px; background:#211c13; color:#e9d9af; }} code {{ color:var(--cyan); }} a {{ color:var(--cyan); }} ul {{ color:var(--muted); }} footer {{ color:var(--muted); font-size:13px; margin-top:42px; }}
@media(max-width:650px) {{ main {{ padding-top:28px; }} table {{ display:block; overflow-x:auto; white-space:nowrap; }} th,td {{ padding:11px; }} }}
</style></head><body><main>
<div class="eyebrow">Reverb · live evidence preview</div>
<h1>The clock matters. The evidence matters more.</h1>
<p>This credential-free preview replays a real, timestamped public-data capture from Bitget. It proves the data path and shows where Reverb refuses to overclaim. It is not an earnings event, a trade, or a profitability claim.</p>
<div class="grid">
<div class="card"><div class="label">Feasibility gate</div><div class="value blocked">{html.escape(snapshot.gate_status)}</div></div>
<div class="card"><div class="label">Spot instruments seen</div><div class="value">{snapshot.spot_instruments}</div></div>
<div class="card"><div class="label">Online Reality instruments</div><div class="value">{snapshot.online_reality}</div></div>
<div class="card"><div class="label">Account required</div><div class="value">No</div></div>
</div>
<div class="notice"><strong>Honest status:</strong> option eligibility, the options/Reality intersection, earnings-window measurements, and fills are not verified yet. Reverb will not turn this capture into a fake trade.</div>
<section class="section"><h2>What the capture observed</h2><p>Live order-book diagnostics selected from the runtime Reality universe. Displayed depth is not a guaranteed fill.</p>
<table><thead><tr><th>Symbol</th><th>Spread</th><th>Displayed bid / ask value</th><th>Book age</th><th>Freshness</th></tr></thead><tbody>{rows}</tbody></table></section>
<section class="section"><h2>What was refused</h2><ul>{failures}</ul><p>The refusal is part of the product: missing eligibility or incomplete event evidence is a halt, not an invitation to guess.</p></section>
<section class="section"><h2>Reproduce it</h2><p>From the repository, run <code>python3 scripts/probe.py report --check</code> to verify the published table against the hash-chained capture, or start this page with <code>./.venv/bin/python scripts/preview_server.py</code>.</p></section>
<footer>Capture <code>{html.escape(snapshot.run_id)}</code> · ledger head <code>{html.escape(snapshot.ledger_head[:16])}…</code> · completed {html.escape(snapshot.captured_at)}</footer>
</main></body></html>"""
