"""Verified, credential-free historical earnings replay support.

The replay is deliberately a small evidence product, not a backtest.  It
captures the issuer's first-party event page and the corresponding public
Bitget Reality candles, then regenerates two structured decisions from those
raw responses every time the demo is loaded.  No order is submitted.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from .errors import DataUnavailable, LedgerError
from .ledger import Ledger
from .models import ReactionDecision
from .reaction import baseline_price, evaluate_reaction, parse_candle
from .sessions import session_at


REPLAY_CONFIG = "config/replay.json"
GENESIS = "0" * 64
_ALLOWED_EVENT_HOSTS = {"investor.nvidia.com"}
_ALLOWED_MARKET_HOSTS = {"api.bitget.com"}


def _canonical(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _write_new(path: Path, body: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())


def _parse_timestamp(value: str) -> datetime:
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DataUnavailable("replay event timestamp is invalid") from exc
    if timestamp.tzinfo is None:
        raise DataUnavailable("replay event timestamp must include a timezone")
    return timestamp.astimezone(timezone.utc)


def _decimal(config: dict[str, Any], name: str, *, positive: bool = True) -> Decimal:
    try:
        value = Decimal(str(config[name]))
    except (KeyError, ArithmeticError, TypeError, ValueError) as exc:
        raise DataUnavailable(f"replay configuration is missing a numeric {name}") from exc
    if not value.is_finite() or (positive and value <= 0):
        raise DataUnavailable(f"replay configuration {name} is outside its valid range")
    return value


def _config(path: Path) -> tuple[dict[str, Any], bytes, str]:
    try:
        body = path.read_bytes()
        value = json.loads(body)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise DataUnavailable(f"replay configuration cannot be loaded: {path}") from exc
    if not isinstance(value, dict):
        raise DataUnavailable("replay configuration must be an object")
    return value, body, _sha256(body)


def _validate_config(config: dict[str, Any]) -> tuple[datetime, datetime, datetime]:
    event_at = _parse_timestamp(str(config.get("event_at", "")))
    try:
        history_minutes = int(config["history_start_minutes"])
        reaction_minutes = int(config["reaction_window_minutes"])
        max_age = int(config["max_quote_age_ms"])
    except (KeyError, TypeError, ValueError) as exc:
        raise DataUnavailable("replay window configuration is invalid") from exc
    if history_minutes <= 0 or reaction_minutes <= 0 or max_age <= 0:
        raise DataUnavailable("replay window configuration must be positive")
    start_at = event_at - timedelta(minutes=history_minutes)
    end_at = event_at + timedelta(minutes=reaction_minutes)
    return event_at, start_at, end_at


def _url_for(config: dict[str, Any], start_at: datetime, end_at: datetime) -> str:
    query = urllib.parse.urlencode({
        "category": "SPOT", "symbol": str(config["token_symbol"]), "interval": "1m",
        "type": "market", "startTime": str(int(start_at.timestamp() * 1000)),
        "endTime": str(int(end_at.timestamp() * 1000)), "limit": "100",
    })
    return "https://api.bitget.com/api/v3/market/history-candles?" + query


def _fetch(url: str, timeout: float) -> tuple[int, bytes]:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname not in (_ALLOWED_EVENT_HOSTS | _ALLOWED_MARKET_HOSTS):
        raise DataUnavailable("replay URL is outside the first-party allowlist")
    request = urllib.request.Request(url, headers={"User-Agent": "Reverb-replay/0.1"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return int(response.status), response.read()
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise DataUnavailable(f"replay network request failed: {type(exc).__name__}") from exc


def _json_payload(body: bytes, label: str) -> list[list[Any]]:
    try:
        value = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DataUnavailable(f"{label} response is not JSON") from exc
    if not isinstance(value, dict) or value.get("code") != "00000":
        raise DataUnavailable(f"{label} response is not a successful Bitget response")
    rows = value.get("data")
    if not isinstance(rows, list) or not rows:
        raise DataUnavailable(f"{label} response contains no candle rows")
    if any(not isinstance(row, list) for row in rows):
        raise DataUnavailable(f"{label} response contains a non-list candle row")
    return rows


def _validate_event_source(body: bytes, config: dict[str, Any]) -> None:
    text = " ".join(body.decode("utf-8", "replace").casefold().split())
    required = (
        "nvidia announces financial results for second quarter fiscal 2027",
        "august 26, 2026",
    )
    if any(marker not in text for marker in required):
        raise DataUnavailable("issuer event page does not contain the configured release evidence")
    if str(config.get("symbol", "")).upper() != "NVDA":
        raise DataUnavailable("the checked issuer page is only approved for the configured NVDA replay")


def _validate_timing_source(body: bytes) -> None:
    text = " ".join(body.decode("utf-8", "replace").casefold().split())
    required = ("nvidia sets conference call for second-quarter financial results",
                "august 26", "approximately 1:20 p.m. pt")
    if any(marker not in text for marker in required):
        raise DataUnavailable("issuer timing page does not contain the configured release-time evidence")


def _validated_rows(rows: list[list[Any]], event_at: datetime, start_at: datetime,
                    end_at: datetime) -> list[list[Any]]:
    selected: list[tuple[datetime, list[Any]]] = []
    seen: set[datetime] = set()
    for row in rows:
        timestamp, _ = parse_candle(row)
        if start_at <= timestamp < end_at:
            if timestamp in seen:
                raise DataUnavailable("replay candles contain duplicate timestamps")
            seen.add(timestamp)
            selected.append((timestamp, row))
    selected.sort(key=lambda item: item[0])
    expected = int((end_at - start_at).total_seconds() / 60)
    if len(selected) != expected:
        raise DataUnavailable(f"replay has {len(selected)} one-minute rows; {expected} required")
    for left, right in zip(selected, selected[1:]):
        if right[0] - left[0] != timedelta(minutes=1):
            raise DataUnavailable("replay candle window has a one-minute timestamp gap")
    if selected[0][0] != start_at or selected[-1][0] != end_at - timedelta(minutes=1):
        raise DataUnavailable("replay candle window does not cover the configured bounds")
    return [row for _, row in selected]


def _build_decisions(config: dict[str, Any], rows: list[list[Any]], *, event_at: datetime,
                     start_at: datetime, end_at: datetime) -> tuple[ReactionDecision, ReactionDecision, dict[str, str]]:
    validated = _validated_rows(rows, event_at, start_at, end_at)
    try:
        trigger = _decimal(config, "trigger_pct")
        if trigger >= 1:
            raise DataUnavailable("replay trigger_pct must be below one")
    except KeyError as exc:
        raise DataUnavailable("replay trigger_pct is missing") from exc
    baseline, baseline_arithmetic = baseline_price(
        validated, event_at, int(config["history_start_minutes"]),
        max(1, int(config["history_start_minutes"])),
    )
    reaction: list[tuple[datetime, Decimal]] = []
    for row in validated:
        timestamp, close = parse_candle(row)
        if event_at <= timestamp < end_at:
            reaction.append((timestamp, close))
    if not reaction:
        raise DataUnavailable("replay reaction window has no candles")
    observed_at, observed_price = reaction[-1]
    move = (observed_price - baseline) / baseline
    for candidate_at, candidate_price in reaction:
        candidate_move = (candidate_price - baseline) / baseline
        if abs(candidate_move) >= trigger:
            observed_at, observed_price, move = candidate_at, candidate_price, candidate_move
            break
    baseline_observed_at = datetime.fromisoformat(baseline_arithmetic["baseline_last_at"])
    session = session_at(observed_at, "America/New_York").session
    side = "sell" if move < 0 else "buy"
    budget = _decimal(config, "risk_budget")
    action_quantity = _decimal(config, "action_quantity")
    refusal_quantity = _decimal(config, "refusal_quantity")
    common = {
        "symbol": str(config["token_symbol"]), "baseline": baseline,
        "observed_price": observed_price, "observed_at": observed_at,
        "baseline_observed_at": baseline_observed_at, "trigger_pct": trigger,
        "session": session, "order_type": str(config["order_type"]),
        "max_quote_age_ms": int(config["max_quote_age_ms"]), "intended_side": side,
        "order_price": observed_price, "risk_budget": budget, "now": observed_at,
    }
    action = evaluate_reaction(**common, order_quantity=action_quantity)
    refusal = evaluate_reaction(**common, order_quantity=refusal_quantity)
    arithmetic = {
        "event_at": event_at.isoformat(), "baseline_window_start": start_at.isoformat(),
        "reaction_window_end": end_at.isoformat(), "rows": str(len(validated)),
        "baseline": str(baseline), "observed_at": observed_at.isoformat(),
        "observed_price": str(observed_price), "move_pct": str(move),
        "trigger_pct": str(trigger), "risk_budget": str(budget),
        "action_order_notional": str(action_quantity * observed_price),
        "refusal_order_notional": str(refusal_quantity * observed_price),
        "action_quantity": str(action_quantity), "refusal_quantity": str(refusal_quantity),
    }
    return action, refusal, arithmetic


def _record_body(directory: Path, ledger: Ledger, name: str, body: bytes, status: int, url: str) -> dict[str, Any]:
    filename = f"{len(ledger.verify()) + 1:03d}-{name}.body"
    _write_new(directory / filename, body)
    return ledger.append("replay_http", {
        "name": name, "url": url, "status": status, "body": filename,
        "body_sha256": _sha256(body),
    })


def capture_replay(root: Path, config_path: Path | None = None) -> Path:
    config_path = config_path or root / REPLAY_CONFIG
    config, config_bytes, config_hash = _config(config_path)
    event_at, start_at, end_at = _validate_config(config)
    event_url = str(config.get("event_source_url", ""))
    timing_url = str(config.get("timing_source_url", ""))
    if any(urllib.parse.urlsplit(url).hostname not in _ALLOWED_EVENT_HOSTS for url in (event_url, timing_url)):
        raise DataUnavailable("event source is not an approved first-party issuer URL")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ-") + uuid4().hex[:8]
    directory = root / "evidence" / "replays" / run_id
    directory.mkdir(parents=True, exist_ok=False)
    _write_new(directory / "config.json", config_bytes)
    ledger = Ledger(directory / "ledger.jsonl")
    ledger.append("replay_start", {
        "config_sha256": config_hash, "symbol": config.get("symbol"),
        "token_symbol": config.get("token_symbol"), "event_at": event_at.isoformat(),
    })
    timeout = float(config.get("timeout_seconds", 20))
    event_status, event_body = _fetch(event_url, timeout)
    _record_body(directory, ledger, "event-source", event_body, event_status, event_url)
    if event_status != 200:
        raise DataUnavailable(f"event source returned HTTP_{event_status}")
    _validate_event_source(event_body, config)
    timing_status, timing_body = _fetch(timing_url, timeout)
    _record_body(directory, ledger, "timing-source", timing_body, timing_status, timing_url)
    if timing_status != 200:
        raise DataUnavailable(f"event timing source returned HTTP_{timing_status}")
    _validate_timing_source(timing_body)
    market_url = _url_for(config, start_at, end_at)
    market_status, market_body = _fetch(market_url, timeout)
    _record_body(directory, ledger, "candles", market_body, market_status, market_url)
    if market_status != 200:
        raise DataUnavailable(f"Bitget history candles returned HTTP_{market_status}")
    rows = _json_payload(market_body, "Bitget history candles")
    action, refusal, arithmetic = _build_decisions(config, rows, event_at=event_at,
                                                   start_at=start_at, end_at=end_at)
    action_payload = {**action.model_dump(mode="json"), "replay_role": "action_signal"}
    refusal_payload = {**refusal.model_dump(mode="json"), "replay_role": "refusal"}
    ledger.register(action_payload)
    ledger.register(refusal_payload)
    ledger.append("replay_complete", {
        "symbol": config.get("symbol"), "token_symbol": config.get("token_symbol"),
        "event_at": event_at.isoformat(), "arithmetic": arithmetic,
        "orders_submitted": False, "event_source_sha256": _sha256(event_body),
        "candles_sha256": _sha256(market_body),
    })
    return directory


def _verify_body(directory: Path, payload: dict[str, Any]) -> bytes:
    body_name = payload.get("body")
    if not isinstance(body_name, str) or Path(body_name).name != body_name:
        raise LedgerError("replay body path escapes its evidence directory")
    body_path = directory / body_name
    if not body_path.exists() or _sha256(body_path.read_bytes()) != payload.get("body_sha256"):
        raise LedgerError(f"replay body integrity failed for {payload.get('name')}")
    return body_path.read_bytes()


def _same_decision(stored: dict[str, Any], fresh: ReactionDecision) -> bool:
    generated = fresh.model_dump(mode="json")
    fields = (
        "status", "symbol", "session", "baseline_price", "observed_price", "move_pct",
        "trigger_pct", "reason_codes", "observed_at", "arithmetic", "intended_side",
        "order_quantity", "order_price", "maximum_loss", "risk_budget",
    )
    return all(stored.get(field) == generated.get(field) for field in fields)


@dataclass(frozen=True)
class ReplaySnapshot:
    run_id: str
    symbol: str
    token_symbol: str
    event_at: str
    event_time_basis: str
    event_source_url: str
    ledger_head: str
    action: dict[str, Any]
    refusal: dict[str, Any]
    arithmetic: dict[str, str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": "historical_earnings_replay", "run_id": self.run_id,
            "symbol": self.symbol, "token_symbol": self.token_symbol,
            "event_at": self.event_at, "event_time_basis": self.event_time_basis,
            "event_source_url": self.event_source_url, "ledger_head": self.ledger_head,
            "action": self.action, "refusal": self.refusal, "arithmetic": self.arithmetic,
            "orders_submitted": False, "credentials_required": False,
        }


def _candidate_directories(root: Path) -> list[Path]:
    path = root / "evidence" / "replays"
    if not path.exists():
        return []
    return sorted((item for item in path.iterdir() if item.is_dir()), reverse=True)


def load_replay_snapshot(root: Path) -> ReplaySnapshot:
    failures: list[str] = []
    for directory in _candidate_directories(root):
        try:
            ledger = Ledger(directory / "ledger.jsonl")
            records = ledger.verify()
            complete = next((row for row in reversed(records) if row.get("kind") == "replay_complete"), None)
            if complete is None:
                raise DataUnavailable("replay capture is incomplete")
            config, config_bytes, config_hash = _config(directory / "config.json")
            starts = [row for row in records if row.get("kind") == "replay_start"]
            if len(starts) != 1 or starts[0]["payload"].get("config_sha256") != config_hash:
                raise LedgerError("replay configuration checksum is not verified")
            http_records = {row["payload"].get("name"): row for row in records if row.get("kind") == "replay_http"}
            event_record = http_records.get("event-source")
            timing_record = http_records.get("timing-source")
            candle_record = http_records.get("candles")
            if event_record is None or timing_record is None or candle_record is None:
                raise DataUnavailable("replay capture is missing a required source")
            event_payload = event_record["payload"]
            candle_payload = candle_record["payload"]
            event_body = _verify_body(directory, event_payload)
            timing_body = _verify_body(directory, timing_record["payload"])
            candles_body = _verify_body(directory, candle_payload)
            if (event_payload.get("status") != 200 or timing_record["payload"].get("status") != 200
                    or candle_payload.get("status") != 200):
                raise DataUnavailable("replay source returned a non-200 response")
            _validate_event_source(event_body, config)
            _validate_timing_source(timing_body)
            event_at, start_at, end_at = _validate_config(config)
            rows = _json_payload(candles_body, "Bitget history candles")
            action, refusal, arithmetic = _build_decisions(config, rows, event_at=event_at,
                                                            start_at=start_at, end_at=end_at)
            registrations = [row["payload"] for row in records if row.get("kind") == "pre_registration"]
            stored_action = next((row for row in registrations if row.get("replay_role") == "action_signal"), None)
            stored_refusal = next((row for row in registrations if row.get("replay_role") == "refusal"), None)
            if stored_action is None or stored_refusal is None or not _same_decision(stored_action, action) or not _same_decision(stored_refusal, refusal):
                raise LedgerError("replay decisions do not regenerate from the captured candles")
            if complete["payload"].get("arithmetic") != arithmetic:
                raise LedgerError("replay completion arithmetic does not regenerate")
            return ReplaySnapshot(
                run_id=directory.name, symbol=str(config["symbol"]),
                token_symbol=str(config["token_symbol"]), event_at=event_at.isoformat(),
                event_time_basis=str(config["event_time_basis"]),
                event_source_url=str(config["event_source_url"]), ledger_head=records[-1]["hash"],
                action=stored_action, refusal=stored_refusal, arithmetic=arithmetic,
            )
        except (DataUnavailable, LedgerError, KeyError, TypeError, ValueError, OSError) as exc:
            failures.append(f"{directory.name}: {exc}")
    raise DataUnavailable("no complete verified earnings replay exists: " + "; ".join(failures))


def _pct(value: Any) -> str:
    try:
        return f"{Decimal(str(value)) * 100:.2f}%"
    except (ArithmeticError, TypeError, ValueError):
        return html.escape(str(value))


def _money(value: Any) -> str:
    try:
        return f"${Decimal(str(value)):,.4f}"
    except (ArithmeticError, TypeError, ValueError):
        return html.escape(str(value))


def _decision_card(title: str, decision: dict[str, Any], *, refusal: bool = False) -> str:
    reasons = ", ".join(str(item).replace("_", " ") for item in decision.get("reason_codes", []))
    arithmetic = decision.get("arithmetic", {})
    items = "".join(
        f"<li><span>{html.escape(str(key).replace('_', ' ').capitalize())}</span>: {html.escape(str(value))}</li>"
        for key, value in arithmetic.items()
    )
    status = html.escape(str(decision.get("status", "unknown")).upper())
    color = "refusal" if refusal else "action"
    return (
        f"<article class=\"decision {color}\"><div class=\"decision-head\"><strong>{status}</strong>"
        f"<span>{html.escape(title)}</span></div><p>{html.escape(reasons or ('Signal crossed the configured trigger.' if not refusal else 'No trade.'))}</p>"
        f"<p class=\"small\"><strong>Arithmetic recorded before the decision</strong></p><ul class=\"small\">{items}</ul></article>"
    )


def render_replay_html(snapshot: ReplaySnapshot) -> str:
    event = _parse_timestamp(snapshot.event_at)
    new_york = event.astimezone(ZoneInfo("America/New_York"))
    lagos = event.astimezone(ZoneInfo("Africa/Lagos"))
    action = snapshot.action
    refusal = snapshot.refusal
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Reverb — historical earnings replay</title>
<style>
:root {{ color-scheme:dark; --bg:#0b1016; --panel:#151d26; --line:#2a3947; --text:#f3f7f8; --muted:#9cadb9; --mint:#75e6d4; --gold:#f2c66f; --red:#ff928d; }}
* {{ box-sizing:border-box; }} body {{ margin:0; background:radial-gradient(circle at 15% 0%,#173442 0,#0b1016 42%); color:var(--text); font:16px/1.5 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }} main {{ max-width:980px; margin:auto; padding:34px 18px 64px; }}
.eyebrow {{ color:var(--mint); letter-spacing:.12em; text-transform:uppercase; font-size:12px; font-weight:700; }} h1 {{ max-width:780px; font-size:clamp(40px,7vw,76px); line-height:.98; letter-spacing:-.055em; margin:16px 0; }} h2 {{ margin:0 0 10px; }} p {{ color:var(--muted); max-width:780px; }} .notice {{ border-left:3px solid var(--gold); padding:13px 16px; background:#211c13; color:#ead9af; margin:24px 0; }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:12px; margin:26px 0; }} .card, .decision {{ background:rgba(21,29,38,.9); border:1px solid var(--line); border-radius:16px; padding:17px; }} .label {{ color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.08em; }} .value {{ font-size:24px; margin-top:5px; }} .section {{ margin-top:34px; }} .decisions {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(280px,1fr)); gap:14px; }} .decision-head {{ display:flex; justify-content:space-between; gap:12px; align-items:center; margin-bottom:10px; }} .decision-head strong {{ border-radius:999px; padding:3px 10px; font-size:12px; }} .action .decision-head strong {{ background:#173c39; color:var(--mint); }} .refusal .decision-head strong {{ background:#4a2629; color:var(--red); }} .decision-head span {{ color:var(--muted); font-size:13px; }} ul {{ color:var(--muted); padding-left:20px; }} li {{ margin:4px 0; }} li span {{ color:var(--text); }} .small {{ font-size:13px; }} a {{ color:var(--mint); }} code {{ color:var(--mint); }} footer {{ color:var(--muted); font-size:13px; margin-top:40px; }}
</style></head><body><main>
<div class="eyebrow">BELLRING · historical earnings replay</div>
<h1>The moment happened while the normal market was closed.</h1>
<p>This is a replay of NVIDIA's 26 August 2026 results using the issuer's release page and public Bitget <code>{html.escape(snapshot.token_symbol)}</code> one-minute candles. Every number below regenerates from the hash-chained capture. It is evidence, not a profitable-strategy claim.</p>
<div class="notice"><strong>No order was submitted.</strong> The action is a paper replay of the deterministic reaction signal. Credentials are not required, and the live order path remains gated.</div>
<div class="grid"><div class="card"><div class="label">Issuer event</div><div class="value">{html.escape(snapshot.symbol)}</div><div class="small">{html.escape(new_york.isoformat())} New York time<br>{html.escape(event.isoformat())} UTC · {html.escape(lagos.isoformat())} Lagos time</div></div>
<div class="card"><div class="label">Baseline</div><div class="value">{_money(snapshot.arithmetic.get('baseline'))}</div><div class="small">60 contiguous one-minute candles</div></div>
<div class="card"><div class="label">Observed reaction</div><div class="value">{_pct(snapshot.arithmetic.get('move_pct'))}</div><div class="small">{html.escape(snapshot.arithmetic.get('observed_at', ''))}</div></div>
<div class="card"><div class="label">Risk budget</div><div class="value">{_money(snapshot.arithmetic.get('risk_budget'))}</div><div class="small">Declared replay budget, not a recommendation</div></div></div>
<section class="section"><h2>Before the close / after the release</h2><p>The release notice says results were announced at approximately 1:20 p.m. Pacific. The replay maps that to 20:20 UTC and watches the Reality token after the regular US session. The observed move crossed the configured {html.escape(snapshot.arithmetic.get('trigger_pct', ''))} trigger at {html.escape(snapshot.arithmetic.get('observed_at', ''))}.</p></section>
<section class="section"><h2>One action and one refusal</h2><div class="decisions">{_decision_card('paper reaction signal', action)}{_decision_card('same signal, oversized intent', refusal, refusal=True)}</div></section>
<section class="section"><h2>Morning report</h2><p>The report carries both outcomes. The small intent fits the declared budget; the one-unit intent is refused because its notional exceeds that same budget. Neither is a fill.</p><div class="card"><ul class="small"><li><span>Action notional</span>: {_money(snapshot.arithmetic.get('action_order_notional'))}</li><li><span>Refusal notional</span>: {_money(snapshot.arithmetic.get('refusal_order_notional'))}</li><li><span>Risk budget</span>: {_money(snapshot.arithmetic.get('risk_budget'))}</li><li><span>Orders submitted</span>: no</li></ul></div></section>
<section class="section"><h2>Evidence and limits</h2><p><a href="{html.escape(snapshot.event_source_url)}">Issuer release</a> · <a href="https://www.bitget.com/docs/uta/agent-hub">Bitget Agent Hub documentation</a>. This replay does not prove account eligibility, options access, fills, slippage, or profitability. The current options order schema and account entitlement remain unresolved, so the live path still refuses.</p></section>
<footer>Replay <code>{html.escape(snapshot.run_id)}</code> · ledger head <code>{html.escape(snapshot.ledger_head[:16])}…</code> · <a href="preview">view live feasibility evidence</a></footer>
</main></body></html>"""


def render_replay_report(snapshot: ReplaySnapshot) -> str:
    """Small ledger-backed report fragment used by the consumer app."""
    return (
        _decision_card("paper reaction signal", snapshot.action)
        + _decision_card("same signal, oversized intent", snapshot.refusal, refusal=True)
        + '<p class="small">No order was submitted; this report is a verified historical replay.</p>'
    )
