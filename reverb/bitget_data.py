"""Read-only adapter for Bitget's keyless US-equity data service (bitget-mcp-server).

Bitget publishes earnings calendars, quotes and analyst consensus for US stocks
through an MCP server that needs no account or key. Reverb uses it as a second,
independent source next to the issuer's own release feed and Bitget's Reality
token market data. Everything here is context for the trader: no value from this
service is a scoring input, a sizing input or an order input.

Rules kept from the rest of Reverb:
- only allow-listed catalog entries can be queried, and nothing is written;
- a missing, malformed or empty answer is reported as unavailable, never filled in;
- analyst consensus must be recent and must have been scraped before the release,
  otherwise it is reported as stale or post-release rather than shown as current.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import httpx

from .config import BitgetDataConfig, load_config
from .errors import ConfigurationError, DataUnavailable

NEW_YORK = ZoneInfo("America/New_York")
SOURCE_NAME = "bitget-mcp-server"
PROTOCOL_VERSION = "2025-03-26"

ENTRY_CALENDAR = "equity_calendar"
ENTRY_QUOTE = "equity_price_quote"
ENTRY_CONSENSUS = "equity_estimates_consensus"
ALLOWED_ENTRIES = frozenset({ENTRY_CALENDAR, ENTRY_QUOTE, ENTRY_CONSENSUS})

# Bitget labels the reporting session in Chinese; Reverb compares English codes.
_SESSION_LABELS = {"盘后": "after_close", "盘前": "before_open", "盘中": "during_market"}
_SYMBOL = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
_QUARTER_LABEL = re.compile(r"^(CurrentQtr|NextQtr)\.\(([A-Z][a-z]{2})(\d{4})\)$")
_MONTHS = {name: number for number, name in enumerate(
    ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), start=1)}
_INDICATORS = ("EPS", "Revenue")


def normalize_symbol(symbol: str) -> str:
    """Accept COST, cost or COST.US and return the bare US ticker."""
    value = (symbol or "").strip().upper().removesuffix(".US")
    if not _SYMBOL.match(value):
        raise ConfigurationError("symbol must be a US ticker such as COST")
    return value


@dataclass(frozen=True)
class ReportedRelease:
    period_ending: date
    fiscal_year: str
    release_date: date | None
    filing_date: date | None
    session: str


@dataclass(frozen=True)
class Quote:
    symbol: str
    last_price: Decimal
    previous_close: Decimal
    change_pct: Decimal
    market_cap: Decimal | None


@dataclass(frozen=True)
class ConsensusEstimate:
    indicator: str
    quarter_label: str
    quarter_end_month: str
    mean: Decimal
    low: Decimal | None
    high: Decimal | None
    analysts: int | None
    scraped_on: date
    upstream_source: str | None


def _date(value: Any) -> date | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError as exc:
        raise DataUnavailable(f"Bitget data returned an invalid date: {value!r}") from exc


def _decimal(value: Any, name: str, *, required: bool = True) -> Decimal | None:
    if value is None and not required:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise DataUnavailable(f"Bitget data field {name} is missing or not numeric")
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise DataUnavailable(f"Bitget data field {name} is not numeric") from exc
    if not result.is_finite():
        raise DataUnavailable(f"Bitget data field {name} is not finite")
    return result


def parse_calendar(rows: Iterable[dict], symbol: str) -> tuple[ReportedRelease, ...]:
    """Distinct reported periods, newest release first."""
    releases: dict[tuple, ReportedRelease] = {}
    for row in rows:
        if not isinstance(row, dict) or str(row.get("symbol", "")).upper() != symbol:
            continue
        period = _date(row.get("period_ending"))
        if period is None:
            continue
        release = ReportedRelease(
            period_ending=period,
            fiscal_year=str(row.get("fiscal_year") or ""),
            release_date=_date(row.get("perf_brief_dsclsr_date")) or _date(row.get("perf_briefing_fore_dsclsr_date")),
            filing_date=_date(row.get("perf_report_dsclsr_date")),
            session=_SESSION_LABELS.get(str(row.get("is_trading_time") or ""), "unspecified"),
        )
        # Bitget lists a quarter and its annual report as separate rows, sometimes
        # with a period end a day apart. One release per (month, release date).
        key = (period.year, period.month, release.release_date)
        kept = releases.get(key)
        if kept is None or (kept.filing_date is None and release.filing_date is not None):
            releases[key] = release
    return tuple(sorted(releases.values(), key=lambda item: (item.release_date or date.min, item.period_ending),
                        reverse=True))


def parse_quote(rows: Iterable[dict], symbol: str) -> Quote:
    for row in rows:
        if isinstance(row, dict) and str(row.get("symbol", "")).upper() == symbol:
            return Quote(
                symbol=symbol,
                last_price=_decimal(row.get("last_price"), "last_price"),
                previous_close=_decimal(row.get("prev_close"), "prev_close"),
                # Bitget returns the change as a fraction (-0.0052 is -0.52%).
                change_pct=_decimal(row.get("change_percent"), "change_percent") * 100,
                market_cap=_decimal(row.get("total_market_cap"), "total_market_cap", required=False),
            )
    raise DataUnavailable(f"Bitget data returned no quote for {symbol}")


def _quarter_end_month(label: str) -> str | None:
    match = _QUARTER_LABEL.match(label or "")
    if not match or match.group(2) not in _MONTHS:
        return None
    return f"{match.group(3)}-{_MONTHS[match.group(2)]:02d}"


def parse_consensus(rows: Iterable[dict], symbol: str) -> tuple[ConsensusEstimate, ...]:
    """Quarterly EPS and revenue consensus rows; annual rows are not used."""
    estimates = []
    for row in rows:
        if not isinstance(row, dict) or str(row.get("symbol", "")).upper() != symbol:
            continue
        indicator = row.get("fore_indicator_name")
        label = str(row.get("report_period_scraped") or "")
        month = _quarter_end_month(label)
        scraped = _date(row.get("scraped_date"))
        if indicator not in _INDICATORS or month is None or scraped is None or row.get("fore_mean") is None:
            continue
        if row.get("currency_unit") not in (None, "USD"):
            continue
        analysts = row.get("fore_org_num")
        estimates.append(ConsensusEstimate(
            indicator=indicator,
            quarter_label=label,
            quarter_end_month=month,
            mean=_decimal(row.get("fore_mean"), "fore_mean"),
            low=_decimal(row.get("min_fore_value"), "min_fore_value", required=False),
            high=_decimal(row.get("high_fore_value"), "high_fore_value", required=False),
            analysts=analysts if isinstance(analysts, int) and not isinstance(analysts, bool) else None,
            scraped_on=scraped,
            upstream_source=_upstream_name(row.get("data_source")),
        ))
    return tuple(estimates)


def _upstream_name(value: Any) -> str | None:
    if value == "雅虎财经":
        return "Yahoo Finance"
    return str(value) if value else None


def session_of(moment: datetime) -> str:
    """Name the US cash session a timestamp falls in (weekday hours, New York)."""
    if moment.tzinfo is None:
        raise ConfigurationError("release time must include a timezone")
    local = moment.astimezone(NEW_YORK).time()
    if local < time(9, 30):
        return "before_open"
    if local >= time(16, 0):
        return "after_close"
    return "during_market"


def compare_release(releases: tuple[ReportedRelease, ...], *, expected_date: date,
                    window_days: int, issuer_release_at: datetime | None = None) -> dict[str, Any]:
    """Compare another source's release date (and session, when known) with Bitget's calendar."""
    nearby = [item for item in releases if item.release_date is not None
              and abs((item.release_date - expected_date).days) <= window_days]
    if not nearby:
        return {"status": "not_listed", "expected_date": expected_date.isoformat(),
                "detail": f"Bitget lists no release within {window_days} days of this date."}
    match = min(nearby, key=lambda item: (abs((item.release_date - expected_date).days), -item.period_ending.toordinal()))
    difference = (match.release_date - expected_date).days
    result: dict[str, Any] = {
        "status": "agrees" if difference == 0 else "differs",
        "expected_date": expected_date.isoformat(),
        "bitget_release_date": match.release_date.isoformat(),
        "difference_days": difference,
        "period_ending": match.period_ending.isoformat(),
        "fiscal_year": match.fiscal_year,
        "bitget_session": match.session,
        "filing_date": match.filing_date.isoformat() if match.filing_date else None,
    }
    if issuer_release_at is not None:
        issuer_session = session_of(issuer_release_at)
        result["issuer_session"] = issuer_session
        result["session_status"] = ("unspecified" if match.session == "unspecified"
                                    else "agrees" if match.session == issuer_session else "differs")
    return result


def select_consensus(estimates: tuple[ConsensusEstimate, ...], *, period_ending: date, today: date,
                     max_age_days: int, release_date: date | None = None) -> dict[str, Any]:
    """Pick the consensus for the quarter being reported, or say why there is none.

    A row qualifies only if its quarter label ends in the reported period's month,
    it was scraped before the release when the release date is known (a later
    scrape is not a pre-release expectation), and it is at most ``max_age_days``
    old at the release or today, whichever comes first.
    """
    month = f"{period_ending.year}-{period_ending.month:02d}"
    for_quarter = [item for item in estimates if item.quarter_end_month == month]
    if not for_quarter:
        return {"status": "not_listed", "quarter_end_month": month, "estimates": []}
    pre_release = [item for item in for_quarter if release_date is None or item.scraped_on < release_date]
    if not pre_release:
        return {"status": "post_release_only", "quarter_end_month": month, "estimates": [],
                "detail": "Every consensus row for this quarter was scraped on or after the release."}
    chosen: dict[str, ConsensusEstimate] = {}
    for item in pre_release:
        kept = chosen.get(item.indicator)
        if kept is None or item.scraped_on > kept.scraped_on:
            chosen[item.indicator] = item
    # Age is measured at the release when it has already happened, otherwise today.
    reference = min(today, release_date) if release_date else today
    fresh = [item for item in chosen.values() if (reference - item.scraped_on).days <= max_age_days]
    if not fresh:
        newest = max(item.scraped_on for item in chosen.values())
        return {"status": "stale", "quarter_end_month": month, "estimates": [],
                "newest_scrape": newest.isoformat(),
                "detail": f"The newest consensus for this quarter is older than {max_age_days} days."}
    ordered = sorted(fresh, key=lambda item: _INDICATORS.index(item.indicator))
    return {"status": "current", "quarter_end_month": month,
            "estimates": [_jsonable(asdict(item)) for item in ordered]}


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _event_stream_messages(response: httpx.Response) -> list[dict]:
    """Decode a JSON or text/event-stream JSON-RPC response into its messages."""
    text = response.text
    if response.headers.get("content-type", "").startswith("text/event-stream"):
        chunks = [line[5:].strip() for line in text.splitlines() if line.startswith("data:")]
    else:
        chunks = [text]
    messages = []
    for chunk in chunks:
        if not chunk:
            continue
        try:
            value = json.loads(chunk)
        except ValueError as exc:
            raise DataUnavailable("Bitget data returned a malformed MCP message") from exc
        messages.extend(value if isinstance(value, list) else [value])
    return [item for item in messages if isinstance(item, dict)]


class BitgetDataClient:
    """Minimal MCP (streamable HTTP) client for Bitget's read-only data catalog."""

    def __init__(self, url: str | None = None, timeout: float | None = None, client: httpx.Client | None = None,
                 config_path: str | None = None):
        path = Path(config_path) if config_path else Path(__file__).resolve().parents[1] / "config" / "bitget_data.json"
        loaded = load_config(path, BitgetDataConfig)
        self.config = loaded.value
        self.config_sha256 = loaded.sha256
        self.url = url or loaded.value.url
        self._client = client or httpx.Client(timeout=timeout if timeout is not None else loaded.value.timeout_seconds)
        self._session_id: str | None = None
        self._next_id = 0

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "BitgetDataClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _post(self, message: dict) -> httpx.Response:
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        try:
            return self._client.post(self.url, json=message, headers=headers)
        except httpx.HTTPError as exc:
            raise DataUnavailable(f"Bitget data request failed: {type(exc).__name__}") from exc

    def _rpc(self, method: str, params: dict) -> dict:
        self._next_id += 1
        request_id = self._next_id
        response = self._post({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        if response.status_code != 200:
            raise DataUnavailable(f"Bitget data returned HTTP {response.status_code} for {method}")
        for message in _event_stream_messages(response):
            if message.get("id") != request_id:
                continue
            if "error" in message:
                raise DataUnavailable(f"Bitget data rejected {method}: {message['error'].get('message', 'error')}")
            result = message.get("result")
            if isinstance(result, dict):
                if method == "initialize":
                    self._session_id = response.headers.get("mcp-session-id")
                return result
        raise DataUnavailable(f"Bitget data returned no result for {method}")

    def _ensure_session(self) -> None:
        if self._session_id is not None:
            return
        self._rpc("initialize", {"protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                                 "clientInfo": {"name": "reverb", "version": "1"}})
        response = self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        if response.status_code not in (200, 202, 204):
            raise DataUnavailable(f"Bitget data refused the MCP session (HTTP {response.status_code})")

    def query(self, entry_id: str, params: dict[str, Any]) -> list[dict]:
        """Run one allow-listed catalog entry and return its result rows."""
        if entry_id not in ALLOWED_ENTRIES:
            raise ConfigurationError(f"Bitget data entry {entry_id!r} is not allow-listed")
        self._ensure_session()
        result = self._rpc("tools/call", {"name": "do_query", "arguments": {"entry_id": entry_id, "params": params}})
        if result.get("isError"):
            raise DataUnavailable(f"Bitget data could not run {entry_id}")
        texts = [item.get("text") for item in result.get("content", []) if isinstance(item, dict)]
        if not texts or not isinstance(texts[0], str):
            raise DataUnavailable(f"Bitget data returned no content for {entry_id}")
        try:
            body = json.loads(texts[0])
        except ValueError as exc:
            raise DataUnavailable(f"Bitget data returned non-JSON content for {entry_id}") from exc
        if not isinstance(body, dict) or body.get("success") is not True:
            raise DataUnavailable(f"Bitget data reported a failed query for {entry_id}")
        if body.get("status_code") == 204:
            return []
        if body.get("status_code") != 200:
            raise DataUnavailable(f"Bitget data returned status {body.get('status_code')} for {entry_id}")
        data = body.get("data")
        rows = data.get("results") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            raise DataUnavailable(f"Bitget data returned no result rows for {entry_id}")
        return rows

    def releases(self, symbol: str) -> tuple[ReportedRelease, ...]:
        ticker = normalize_symbol(symbol)
        return parse_calendar(self.query(ENTRY_CALENDAR, {"symbol": ticker}), ticker)

    def quote(self, symbol: str) -> Quote:
        ticker = normalize_symbol(symbol)
        return parse_quote(self.query(ENTRY_QUOTE, {"symbol": ticker}), ticker)

    def consensus(self, symbol: str) -> tuple[ConsensusEstimate, ...]:
        ticker = normalize_symbol(symbol)
        return parse_consensus(self.query(ENTRY_CONSENSUS, {"symbol": ticker}), ticker)


def _unavailable(error: Exception) -> dict[str, Any]:
    return {"status": "unavailable", "detail": str(error)}


def event_context(client: BitgetDataClient, symbol: str, *, event_date: date,
                  now: datetime | None = None) -> dict[str, Any]:
    """Bitget's view of an upcoming earnings event, each part labelled with its own status.

    One failing part never hides the others, and none of them is invented.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ConfigurationError("reference time must include a timezone")
    ticker = normalize_symbol(symbol)
    config = client.config
    context: dict[str, Any] = {
        "symbol": ticker,
        "source": SOURCE_NAME,
        "source_url": client.url,
        "fetched_at": now.astimezone(timezone.utc).isoformat(),
        "use": "Context for the trader only; not a scoring, sizing or order input.",
    }
    period_ending: date | None = None
    release_date: date | None = None
    try:
        calendar = compare_release(client.releases(ticker), expected_date=event_date,
                                   window_days=config.calendar_match_window_days)
        context["calendar"] = calendar
        if calendar.get("period_ending"):
            period_ending = date.fromisoformat(calendar["period_ending"])
            release_date = date.fromisoformat(calendar["bitget_release_date"])
    except (DataUnavailable, ConfigurationError) as exc:
        context["calendar"] = _unavailable(exc)
    try:
        context["quote"] = {"status": "ok", **_jsonable(asdict(client.quote(ticker))),
                            "note": "Bitget's response carries no exchange timestamp; read it as of fetched_at."}
    except (DataUnavailable, ConfigurationError) as exc:
        context["quote"] = _unavailable(exc)
    if period_ending is None:
        context["consensus"] = {"status": "unavailable",
                                "detail": "No reported period to match: Bitget's calendar did not list this release."}
    else:
        try:
            context["consensus"] = select_consensus(
                client.consensus(ticker), period_ending=period_ending, today=now.date(),
                max_age_days=config.consensus_max_age_days,
                release_date=min(release_date, event_date) if release_date else event_date)
        except (DataUnavailable, ConfigurationError) as exc:
            context["consensus"] = _unavailable(exc)
    return context
