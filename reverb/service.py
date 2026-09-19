from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .adapters import parse_option_quote, parse_rtoken_ticker, parse_stock_quote
from .bitget import BitgetClient
from .calendar import EarningsCalendar
from .chooser import paired_symbols, parse_chain, select_at_the_money, select_contract, select_expiry
from .config import EngineConfig
from .errors import BitgetAPIError, ConfigurationError, DataUnavailable
from .gate import evaluate_option
from .ledger import Ledger
from .models import DecisionStatus, ReasonCode, Thesis, ToolDecision, View
from .reaction import baseline_price, evaluate_reaction
from .sessions import Session, session_at
from .universe import reality_instruments, rtoken_for_underlying


def _underlying(symbol: str) -> str:
    value = symbol.strip().upper()
    if not value:
        raise ConfigurationError("symbol is required")
    return value if value.endswith(".US") else f"{value}.US"


def _aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None:
        raise ConfigurationError(f"{name} must include a timezone")
    return value.astimezone(timezone.utc)


def _failure_reason(error: Exception) -> ReasonCode:
    if isinstance(error, BitgetAPIError) and error.code in {"40006", "40009", "40010"}:
        return ReasonCode.API_NOT_ENTITLED
    if isinstance(error, ConfigurationError):
        return ReasonCode.DATA_UNAVAILABLE
    return ReasonCode.DATA_UNAVAILABLE


@dataclass
class DecisionService:
    client: BitgetClient
    engine: EngineConfig
    ledger: Ledger
    per_contract_fees: Decimal | None = None
    calendar: EarningsCalendar | None = None

    def __enter__(self) -> "DecisionService":
        return self

    def __exit__(self, *_: object) -> None:
        self.client.close()
        if self.calendar is not None:
            self.calendar.close()

    def _record(self, result: ToolDecision, kind: str = "tool_observation") -> ToolDecision:
        self.ledger.append(kind, result.model_dump(mode="json"))
        return result

    def _refusal(self, tool: str, symbol: str | None, reason: ReasonCode,
                 arithmetic: dict[str, str], explanation: str) -> ToolDecision:
        return self._record(ToolDecision(
            decision_id=str(uuid4()), tool=tool, status=DecisionStatus.REFUSE, symbol=symbol,
            reason_codes=(reason,), decision=None, arithmetic=arithmetic,
            explanation=explanation, created_at=datetime.now(timezone.utc),
        ), kind="pre_registration")

    def _error(self, tool: str, symbol: str | None, error: Exception) -> ToolDecision:
        code = _failure_reason(error)
        explanation = (
            "Reverb refused because the required live input is unavailable."
            if code is ReasonCode.DATA_UNAVAILABLE else
            "Reverb refused because this account is not entitled to the required Bitget API path."
        )
        return self._refusal(tool, symbol, code,
                             {"error_type": type(error).__name__}, explanation)

    def _r_token(self, underlying: str) -> str:
        instruments = reality_instruments(self.client.instruments())
        token = rtoken_for_underlying(underlying)
        if token not in instruments:
            raise DataUnavailable(f"no online Reality instrument for {underlying}")
        return f"{token}USDT"

    def position_for(self, *, symbol: str, view: View, expected_move_pct: Decimal,
                     max_loss: Decimal, event_at: datetime, user_timezone: str) -> ToolDecision:
        tool = "position_for"
        try:
            if self.per_contract_fees is None or self.per_contract_fees < 0:
                raise ConfigurationError("verified per-contract fees are required; no fee default is permitted")
            event_at = _aware(event_at, "event_at")
            underlying_symbol = _underlying(symbol)
            thesis = Thesis(symbol=underlying_symbol.removesuffix(".US"), view=view,
                            expected_move_pct=expected_move_pct, max_loss=max_loss,
                            event_at=event_at, user_timezone=user_timezone)
            now = datetime.now(timezone.utc)
            session = session_at(now).session
            if session is not Session.REGULAR:
                return self._refusal(tool, thesis.symbol, ReasonCode.SESSION_UNAVAILABLE,
                                     {"session": session.value, "required_session": Session.REGULAR.value},
                                     "Reverb refused because options can only be positioned during the verified regular session.")
            underlying = parse_stock_quote(self.client.stock_quote(underlying_symbol), observed_at=now)
            expiry_value, expiry = select_expiry(self.client.option_expiry_dates(underlying_symbol), event_at.date())
            chain = parse_chain(self.client.option_chain(underlying_symbol, expiry_value), expiry)
            selected_contract = select_contract(chain, view.direction, underlying.price, expected_move_pct)
            selected_symbol, paired_symbol = paired_symbols(selected_contract, view.direction)
            rows = self.client.option_quotes([selected_symbol, paired_symbol])
            observed_quotes = {str(row.get("symbol")): parse_option_quote(row, observed_at=now) for row in rows}
            option = observed_quotes.get(selected_symbol)
            paired = observed_quotes.get(paired_symbol)
            if option is None or paired is None:
                raise DataUnavailable("selected or paired option quote is missing")
            for label, quote in (("selected", option), ("paired", paired)):
                age_ms = int((now - quote.source_timestamp).total_seconds() * 1000)
                if age_ms < 0 or age_ms > self.engine.max_quote_age_ms:
                    return self._refusal(tool, thesis.symbol, ReasonCode.STALE_OPTION,
                                         {"quote": label, "quote_age_ms": str(age_ms),
                                          "max_quote_age_ms": str(self.engine.max_quote_age_ms)},
                                         "Reverb refused because an option quote was outside the freshness gate.")
            if option.strike != paired.strike or option.expiry != paired.expiry:
                raise DataUnavailable("selected and paired option quotes do not describe the same contract")
            if not option.executable or not paired.executable or option.ask is None or paired.ask is None:
                return self._refusal(tool, thesis.symbol, ReasonCode.PAIR_BID_ASK_UNAVAILABLE,
                                     {"selected_symbol": selected_symbol, "paired_symbol": paired_symbol,
                                      "selected_bid": str(option.bid), "selected_ask": str(option.ask),
                                      "paired_bid": str(paired.bid), "paired_ask": str(paired.ask)},
                                     "Reverb refused because both sides of the same-strike volatility check need executable quotes.")
            implied_move = (option.ask + paired.ask) / underlying.price
            decision = evaluate_option(
                thesis=thesis, underlying=underlying, option=option,
                paired_straddle_move_pct=implied_move,
                risk_free_rate=self.engine.risk_free_rate,
                dividend_yield=self.engine.dividend_yield,
                post_event_volatility=self.engine.post_event_volatility,
                per_contract_fees=self.per_contract_fees,
                max_quote_age_ms=self.engine.max_quote_age_ms,
                now=now,
            )
            self.ledger.register(decision.model_dump(mode="json"))
            return ToolDecision(
                decision_id=decision.decision_id, tool=tool, status=decision.status, symbol=decision.symbol,
                reason_codes=decision.reason_codes, decision=decision.model_dump(mode="json"),
                arithmetic={**decision.arithmetic, "market_implied_move_pct": str(implied_move),
                            "selected_expiry": expiry.isoformat()},
                explanation=self._decision_explanation(decision.status, decision.reason_codes),
                created_at=decision.created_at,
            )
        except (BitgetAPIError, ConfigurationError, DataUnavailable, ValueError) as exc:
            return self._error(tool, symbol, exc)

    def whats_priced_in(self, *, symbol: str, event_at: datetime,
                        historical_move_pct: Decimal | None = None) -> ToolDecision:
        tool = "whats_priced_in"
        try:
            event_at = _aware(event_at, "event_at")
            underlying_symbol = _underlying(symbol)
            now = datetime.now(timezone.utc)
            underlying = parse_stock_quote(self.client.stock_quote(underlying_symbol), observed_at=now)
            expiry_value, expiry = select_expiry(self.client.option_expiry_dates(underlying_symbol), event_at.date())
            chain = parse_chain(self.client.option_chain(underlying_symbol, expiry_value), expiry)
            contract = select_at_the_money(chain, underlying.price)
            rows = self.client.option_quotes([contract.call_symbol, contract.put_symbol])
            quotes = {str(row.get("symbol")): parse_option_quote(row, observed_at=now) for row in rows}
            call = quotes.get(contract.call_symbol)
            put = quotes.get(contract.put_symbol)
            for label, quote in (("call", call), ("put", put)):
                if quote is not None:
                    age_ms = int((now - quote.source_timestamp).total_seconds() * 1000)
                    if age_ms < 0 or age_ms > self.engine.max_quote_age_ms:
                        return self._refusal(tool, symbol, ReasonCode.STALE_OPTION,
                                             {"quote": label, "quote_age_ms": str(age_ms),
                                              "max_quote_age_ms": str(self.engine.max_quote_age_ms)},
                                             "Reverb refused because a paired option quote was outside the freshness gate.")
            if call is None or put is None or not call.executable or not put.executable or call.ask is None or put.ask is None:
                return self._refusal(tool, symbol, ReasonCode.PAIR_BID_ASK_UNAVAILABLE,
                                     {"call_symbol": contract.call_symbol, "put_symbol": contract.put_symbol},
                                     "Reverb refused to state what is priced in because the paired executable quotes are incomplete.")
            implied_move = (call.ask + put.ask) / underlying.price
            arithmetic = {"market_implied_move_pct": str(implied_move), "expiry": expiry.isoformat(),
                          "historical_move_pct": str(historical_move_pct) if historical_move_pct is not None else "unavailable"}
            if historical_move_pct is None:
                return self._refusal(tool, symbol, ReasonCode.DATA_UNAVAILABLE, arithmetic,
                                     "Reverb measured the market-implied move but refused a comparison because no validated historical earnings sample was supplied.")
            status = DecisionStatus.HOLD if implied_move >= historical_move_pct else DecisionStatus.ACT
            reason_codes = ((ReasonCode.MARKET_EXPECTS_LARGER_MOVE,) if status is DecisionStatus.HOLD else ())
            result = ToolDecision(decision_id=str(uuid4()), tool=tool, status=status, symbol=symbol,
                                  reason_codes=reason_codes, decision=None, arithmetic=arithmetic,
                                  explanation=("The market already prices at least the supplied historical move; Reverb would not force an entry."
                                               if status is DecisionStatus.HOLD else
                                               "The market-implied move is below the supplied historical move; this is a comparison, not a trade approval."),
                                  created_at=datetime.now(timezone.utc))
            return self._record(result)
        except (BitgetAPIError, ConfigurationError, DataUnavailable, ValueError) as exc:
            return self._error(tool, symbol, exc)

    def react(self, *, symbol: str, event_at: datetime, user_timezone: str = "America/New_York",
              order_type: str = "limit") -> ToolDecision:
        tool = "react"
        try:
            event_at = _aware(event_at, "event_at")
            underlying_symbol = _underlying(symbol)
            token = self._r_token(underlying_symbol)
            now = datetime.now(timezone.utc)
            rows = self.client.candles(token, interval="1m", candle_type="market", limit=100)
            baseline, baseline_arithmetic = baseline_price(rows, event_at, self.engine.baseline_window_minutes,
                                                            self.engine.baseline_min_points)
            quote = parse_rtoken_ticker(self.client.ticker(token), observed_at=now)
            # Order sessions are Bitget's New York session; the user's zone is
            # only for narration and display.
            session = session_at(quote.source_timestamp, "America/New_York").session
            decision = evaluate_reaction(
                symbol=token, baseline=baseline, observed_price=quote.price,
                observed_at=quote.source_timestamp, baseline_observed_at=event_at,
                trigger_pct=self.engine.reaction_trigger_pct, session=session,
                order_type=order_type, max_quote_age_ms=self.engine.max_quote_age_ms, now=now,
            )
            self.ledger.register(decision.model_dump(mode="json"))
            return ToolDecision(
                decision_id=decision.decision_id, tool=tool, status=decision.status, symbol=decision.symbol,
                reason_codes=decision.reason_codes, decision=decision.model_dump(mode="json"),
                arithmetic={**baseline_arithmetic, **decision.arithmetic},
                explanation=("The token move crossed the configured trigger; execution still requires the guarded order path."
                             if decision.status is DecisionStatus.ACT else
                             "The reaction did not produce an executable ACT decision."),
                created_at=decision.observed_at,
            )
        except (BitgetAPIError, ConfigurationError, DataUnavailable, ValueError) as exc:
            return self._error(tool, symbol, exc)

    def earnings_this_week(self, *, user_timezone: str) -> ToolDecision:
        tool = "earnings_this_week"
        calendar = self.calendar
        owned_calendar = calendar is None
        try:
            calendar = calendar or EarningsCalendar()
            events = calendar.this_week()
            instruments = reality_instruments(self.client.instruments())
            try:
                ZoneInfo(user_timezone)
            except (ZoneInfoNotFoundError, ValueError) as exc:
                raise ConfigurationError(f"unknown user timezone: {user_timezone}") from exc
            items: list[dict[str, str]] = []
            for event in events:
                underlying_symbol = _underlying(event.symbol)
                token = rtoken_for_underlying(underlying_symbol)
                token_status = "available" if token in instruments else "missing"
                option_status = "unverified"
                if self.client.credentials is not None:
                    try:
                        self.client.option_expiry_dates(underlying_symbol)
                        option_status = "available"
                    except (BitgetAPIError, DataUnavailable):
                        option_status = "unverified_or_not_entitled"
                items.append({
                    "symbol": event.symbol,
                    "event_at_utc": event.event_at.isoformat(),
                    "event_at_local": event.event_at.astimezone(ZoneInfo(user_timezone)).isoformat(),
                    "token_status": token_status,
                    "options_status": option_status,
                    "calendar_source": event.source,
                    "calendar_event_id": event.source_id,
                })
            result = ToolDecision(decision_id=str(uuid4()), tool=tool, status=DecisionStatus.HOLD,
                                  symbol=None, reason_codes=(), decision={"events": items},
                                  arithmetic={"event_count": str(len(items))},
                                  explanation="Reverb found calendar events and reports each leg's verified or unverified availability.",
                                  created_at=datetime.now(timezone.utc))
            return self._record(result)
        except (BitgetAPIError, ConfigurationError, DataUnavailable, ValueError) as exc:
            return self._error(tool, None, exc)
        finally:
            if owned_calendar and calendar is not None:
                calendar.close()

    def my_positions(self) -> ToolDecision:
        """Return positions known to Reverb's ledger with outcome attribution."""
        tool = "my_positions"
        records = self.ledger.verify()
        registrations = {
            str(row["payload"].get("decision_id")): row["payload"]
            for row in records
            if row.get("kind") == "pre_registration" and row.get("payload", {}).get("decision_id")
        }
        outcomes = {
            str(row["payload"].get("decision_id")): row["payload"]
            for row in records
            if row.get("kind") == "outcome" and row.get("payload", {}).get("decision_id")
        }
        positions: list[dict[str, Any]] = []
        for decision_id, registration in registrations.items():
            if registration.get("status") != DecisionStatus.ACT.value:
                continue
            positions.append({
                "decision_id": decision_id,
                "status": "closed" if decision_id in outcomes else "registered_not_attributed",
                "decision": registration.get("decision", registration),
                "outcome": outcomes.get(decision_id),
            })
        result = ToolDecision(
            decision_id=str(uuid4()), tool=tool, status=DecisionStatus.HOLD, symbol=None,
            reason_codes=(), decision={"positions": positions},
            arithmetic={"position_count": str(len(positions))},
            explanation="Reverb reports only positions and outcomes recorded in its hash-chained ledger.",
            created_at=datetime.now(timezone.utc),
        )
        return self._record(result)

    @staticmethod
    def _decision_explanation(status: DecisionStatus, reasons: tuple[ReasonCode, ...]) -> str:
        if status is DecisionStatus.ACT:
            return "The deterministic gate found an executable long option within the stated premium budget."
        if ReasonCode.MARKET_EXPECTS_LARGER_MOVE in reasons:
            return "Reverb refused because the paired option prices already imply at least the user's expected move."
        if ReasonCode.NEGATIVE_EXPECTED_VALUE in reasons:
            return "Reverb refused because the post-event volatility scenario did not cover the premium and fees."
        return "Reverb refused or held because a deterministic risk or freshness condition was not satisfied."
