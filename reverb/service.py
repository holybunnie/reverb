from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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
from .math import straddle_implied_move
from .models import DecisionStatus, ReasonCode, Thesis, ToolDecision, View
from .reaction import baseline_price, evaluate_reaction, parse_candle
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
    # 40012 is the response Bitget currently returns when the authenticated
    # key can reach Stock+/UTA routes but lacks the product entitlement.  Keep
    # it distinct from an unavailable market feed so the user gets an
    # actionable permission refusal rather than a generic data error.
    if isinstance(error, BitgetAPIError) and error.code in {"40006", "40009", "40010", "40012"}:
        return ReasonCode.API_NOT_ENTITLED
    if isinstance(error, ConfigurationError):
        return ReasonCode.DATA_UNAVAILABLE
    return ReasonCode.DATA_UNAVAILABLE


def _public_option_decision(decision: Any) -> dict[str, Any]:
    """Keep the MCP/app surface conclusion-only; raw quote fields stay local."""
    value = decision.model_dump(mode="json")
    instrument = value.get("instrument")
    if isinstance(instrument, dict):
        value["instrument"] = {
            key: instrument[key]
            for key in ("symbol", "underlying_symbol", "direction", "strike", "expiry", "contract_multiplier")
            if key in instrument
        }
    value["inputs"] = {
        key: item for key, item in value.get("inputs", {}).items()
        if key not in {"underlying_observed_at", "option_observed_at"}
    }
    return value


@dataclass
class DecisionService:
    client: BitgetClient
    engine: EngineConfig
    ledger: Ledger
    per_contract_fees: Decimal | None = None
    calendar: EarningsCalendar | None = None
    engine_config_sha256: str | None = None

    def __enter__(self) -> "DecisionService":
        return self

    def __exit__(self, *_: object) -> None:
        self.client.close()
        if self.calendar is not None:
            self.calendar.close()

    def _record(self, result: ToolDecision, kind: str = "tool_observation") -> ToolDecision:
        if self.engine_config_sha256 and result.arithmetic.get("engine_config_sha256") != self.engine_config_sha256:
            result = result.model_copy(update={"arithmetic": {**result.arithmetic,
                                                               "engine_config_sha256": self.engine_config_sha256}})
        self.ledger.append(kind, result.model_dump(mode="json"))
        return result

    def _refusal(self, tool: str, symbol: str | None, reason: ReasonCode,
                 arithmetic: dict[str, str], explanation: str) -> ToolDecision:
        if self.engine_config_sha256:
            arithmetic = {**arithmetic, "engine_config_sha256": self.engine_config_sha256}
        return self._record(ToolDecision(
            decision_id=str(uuid4()), tool=tool, status=DecisionStatus.REFUSE, symbol=symbol,
            reason_codes=(reason,), decision=None, arithmetic=arithmetic,
            explanation=explanation, created_at=datetime.now(timezone.utc),
        ), kind="pre_registration")

    def _error(self, tool: str, symbol: str | None, error: Exception) -> ToolDecision:
        code = ReasonCode.CALENDAR_UNAVAILABLE if tool == "earnings_this_week" else _failure_reason(error)
        explanation = (
            "Reverb refused because the earnings calendar is unavailable or unresolved."
            if code is ReasonCode.CALENDAR_UNAVAILABLE else
            "Reverb refused because the required live input is unavailable."
            if code is ReasonCode.DATA_UNAVAILABLE else
            "Reverb refused because this account is not entitled to the required Bitget API path."
        )
        return self._refusal(tool, symbol, code,
                             {"error_type": type(error).__name__}, explanation)

    def input_refusal(self, *, tool: str, symbol: str | None, field: str,
                      error: Exception) -> ToolDecision:
        """Record malformed tool input as a normal, structured refusal."""
        return self._refusal(
            tool, symbol, ReasonCode.INVALID_INPUT,
            {"field": field, "error_type": type(error).__name__},
            f"Reverb refused because the {field} input is invalid; no market request was made.",
        )

    def _r_token(self, underlying: str) -> str:
        instruments = reality_instruments(self.client.instruments())
        token = rtoken_for_underlying(underlying)
        if token not in instruments:
            raise DataUnavailable(f"no online Reality instrument for {underlying}")
        if not self.engine.weekend_source_url:
            raise ConfigurationError("24/7 source URL is required; online Reality status alone is insufficient")
        try:
            verified_tokens = self.client.weekend_tokens(self.engine.weekend_source_url)
        except AttributeError as exc:
            raise DataUnavailable("Bitget client has no 24/7 source verifier") from exc
        if token not in verified_tokens:
            raise DataUnavailable(f"{token} is not verified in the configured 24/7 source")
        return f"{token}USDT"

    def position_for(self, *, symbol: str, view: View, expected_move_pct: Decimal,
                     max_loss: Decimal, event_at: datetime, user_timezone: str) -> ToolDecision:
        tool = "position_for"
        try:
            if self.per_contract_fees is None or self.per_contract_fees < 0:
                raise ConfigurationError("verified per-contract fees are required; no fee default is permitted")
            event_at = _aware(event_at, "event_at")
            underlying_symbol = _underlying(symbol)
            try:
                ZoneInfo(user_timezone)
            except (ZoneInfoNotFoundError, ValueError) as exc:
                raise ConfigurationError(f"unknown user timezone: {user_timezone}") from exc
            reaction_budget = self.engine.reaction_budget
            option_budget = max_loss
            if reaction_budget is not None:
                if max_loss <= reaction_budget:
                    return self._refusal(tool, symbol, ReasonCode.RISK_BUDGET_EXCEEDED,
                                         {"combined_budget": str(max_loss), "reaction_budget": str(reaction_budget),
                                          "decision": "the option leg must leave room for the reaction leg"},
                                         "Reverb refused because the combined earnings budget cannot fund both legs.")
                option_budget = max_loss - reaction_budget
            thesis = Thesis(symbol=underlying_symbol.removesuffix(".US"), view=view,
                            expected_move_pct=expected_move_pct, max_loss=option_budget,
                            event_at=event_at, user_timezone=user_timezone)
            if not self.engine.post_event_volatility_verified or self.engine.post_event_volatility is None:
                return self._refusal(
                    tool, thesis.symbol, ReasonCode.UNVERIFIED_ASSUMPTION,
                    {"post_event_volatility": str(self.engine.post_event_volatility),
                     "post_event_volatility_verified": str(self.engine.post_event_volatility_verified).lower()},
                    "Reverb refused because post-event volatility calibration is not verified for this universe.",
                )
            now = datetime.now(timezone.utc)
            session = session_at(now).session
            if session is not Session.REGULAR:
                return self._refusal(tool, thesis.symbol, ReasonCode.SESSION_UNAVAILABLE,
                                     {"session": session.value, "required_session": Session.REGULAR.value},
                                     "Reverb refused because options can only be positioned during the verified regular session.")
            # The binary-event design requires both legs on the same name.
            # Online Reality metadata alone does not prove 24/7 eligibility;
            # _r_token verifies the configured first-party announcement too.
            self._r_token(underlying_symbol)
            underlying = parse_stock_quote(self.client.stock_quote(underlying_symbol), observed_at=now)
            expiry_value, expiry = select_expiry(self.client.option_expiry_dates(underlying_symbol), event_at.date())
            chain = parse_chain(self.client.option_chain(underlying_symbol, expiry_value), expiry)
            selected_contract = select_contract(chain, view.direction, underlying.price, expected_move_pct)
            # The directional contract is chosen from the thesis, but the
            # market's event move must be measured from the same-expiry ATM
            # straddle.  Using the thesis strike would make the refusal gate
            # depend on the user's strike selection rather than the market's
            # priced move.
            atm_contract = select_at_the_money(chain, underlying.price)
            selected_symbol, paired_symbol = paired_symbols(selected_contract, view.direction)
            quote_symbols = list(dict.fromkeys([
                selected_symbol, paired_symbol, atm_contract.call_symbol, atm_contract.put_symbol,
            ]))
            rows = self.client.option_quotes(quote_symbols)
            observed_quotes = {str(row.get("symbol")): parse_option_quote(row, observed_at=now) for row in rows}
            option = observed_quotes.get(selected_symbol)
            paired = observed_quotes.get(paired_symbol)
            atm_call = observed_quotes.get(atm_contract.call_symbol)
            atm_put = observed_quotes.get(atm_contract.put_symbol)
            required_quotes = (("selected", option), ("selected_pair", paired),
                               ("atm_call", atm_call), ("atm_put", atm_put))
            if any(quote is None for _, quote in required_quotes):
                return self._refusal(tool, thesis.symbol, ReasonCode.PAIR_BID_ASK_UNAVAILABLE,
                                     {label + "_symbol": symbol for label, symbol in (
                                         ("selected", selected_symbol), ("selected_pair", paired_symbol),
                                         ("atm_call", atm_contract.call_symbol), ("atm_put", atm_contract.put_symbol),
                                     )},
                                     "Reverb refused because the selected contract and ATM straddle quotes were incomplete.")
            assert option is not None and paired is not None and atm_call is not None and atm_put is not None
            if any(quote.underlying_symbol != underlying_symbol for _, quote in required_quotes):
                raise DataUnavailable("option quote underlying identity does not match the requested stock")
            if any(quote.trade_status not in {"1", "online", "ONLINE", "active", "ACTIVE"}
                   for _, quote in required_quotes):
                return self._refusal(tool, thesis.symbol, ReasonCode.INSTRUMENT_UNAVAILABLE,
                                     {label + "_trade_status": str(quote.trade_status)
                                      for label, quote in required_quotes},
                                     "Reverb refused because a selected or ATM option contract is not verified as tradeable.")
            for label, quote in required_quotes:
                age_ms = int((now - quote.source_timestamp).total_seconds() * 1000)
                if age_ms < 0 or age_ms > self.engine.max_quote_age_ms:
                    return self._refusal(tool, thesis.symbol, ReasonCode.STALE_OPTION,
                                         {"quote": label, "quote_age_ms": str(age_ms),
                                          "max_quote_age_ms": str(self.engine.max_quote_age_ms)},
                                         "Reverb refused because an option quote was outside the freshness gate.")
            if option.strike != paired.strike or option.expiry != paired.expiry:
                raise DataUnavailable("selected and paired option quotes do not describe the same contract")
            if atm_call.strike != atm_put.strike or atm_call.expiry != atm_put.expiry:
                raise DataUnavailable("ATM call and put quotes do not describe the same contract")
            if (not option.executable or not paired.executable or not atm_call.executable or not atm_put.executable
                    or option.ask is None or paired.ask is None or atm_call.ask is None or atm_put.ask is None):
                return self._refusal(tool, thesis.symbol, ReasonCode.PAIR_BID_ASK_UNAVAILABLE,
                                     {"selected_symbol": selected_symbol, "paired_symbol": paired_symbol,
                                      "selected_bid": str(option.bid), "selected_ask": str(option.ask),
                                      "paired_bid": str(paired.bid), "paired_ask": str(paired.ask),
                                      "atm_call_symbol": atm_contract.call_symbol, "atm_put_symbol": atm_contract.put_symbol,
                                      "atm_call_ask": str(atm_call.ask), "atm_put_ask": str(atm_put.ask)},
                                     "Reverb refused because the selected option and ATM straddle need executable quotes.")
            implied_move = straddle_implied_move(atm_call.ask, atm_put.ask, underlying.price)
            decision = evaluate_option(
                thesis=thesis, underlying=underlying, option=option,
                paired_straddle_move_pct=implied_move,
                risk_free_rate=self.engine.risk_free_rate,
                dividend_yield=self.engine.dividend_yield,
                post_event_volatility=self.engine.post_event_volatility,
                post_event_volatility_verified=self.engine.post_event_volatility_verified,
                per_contract_fees=self.per_contract_fees,
                max_quote_age_ms=self.engine.max_quote_age_ms,
                now=now,
            )
            if self.engine_config_sha256:
                decision = decision.model_copy(update={
                    "inputs": {**decision.inputs, "engine_config_sha256": self.engine_config_sha256}
                })
            self.ledger.register(decision.model_dump(mode="json"))
            return self._record(ToolDecision(
                decision_id=decision.decision_id, tool=tool, status=decision.status, symbol=decision.symbol,
                reason_codes=decision.reason_codes, decision=_public_option_decision(decision),
                arithmetic={**decision.arithmetic, "market_implied_move_pct": str(implied_move),
                            "combined_budget": str(max_loss), "reaction_budget": str(reaction_budget),
                            "selected_expiry": expiry.isoformat(),
                            "implied_move_strike": str(atm_contract.strike)},
                explanation=self._decision_explanation(decision.status, decision.reason_codes),
                created_at=decision.created_at,
            ))
        except (BitgetAPIError, ConfigurationError, DataUnavailable, ValueError) as exc:
            return self._error(tool, symbol, exc)

    def whats_priced_in(self, *, symbol: str, event_at: datetime,
                        historical_move_pct: Decimal | None = None) -> ToolDecision:
        tool = "whats_priced_in"
        try:
            event_at = _aware(event_at, "event_at")
            underlying_symbol = _underlying(symbol)
            if historical_move_pct is not None and (not historical_move_pct.is_finite()
                                                     or historical_move_pct <= 0 or historical_move_pct >= 1):
                raise ConfigurationError("historical_move_pct must be between 0 and 1")
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
            if call.trade_status not in {"1", "online", "ONLINE", "active", "ACTIVE"} or put.trade_status not in {"1", "online", "ONLINE", "active", "ACTIVE"}:
                return self._refusal(tool, symbol, ReasonCode.INSTRUMENT_UNAVAILABLE,
                                     {"call_trade_status": str(call.trade_status), "put_trade_status": str(put.trade_status)},
                                     "Reverb refused to state what is priced in because the option status is not verified as tradeable.")
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
            if now < event_at:
                return self._refusal(tool, symbol, ReasonCode.REPLAY_UNAVAILABLE,
                                     {"event_at": event_at.isoformat(), "now": now.isoformat()},
                                     "Reverb refused because the reaction window has not started.")
            if now > event_at + timedelta(minutes=30):
                rows = self.client.history_candles(
                    token, start_time=event_at - timedelta(minutes=self.engine.baseline_window_minutes),
                    end_time=event_at + timedelta(minutes=30), interval="1m", candle_type="market", limit=100,
                )
                reaction_rows = []
                for row in rows:
                    parsed = parse_candle(row)
                    if event_at <= parsed[0] <= event_at + timedelta(minutes=30):
                        reaction_rows.append(parsed)
                if not reaction_rows:
                    raise DataUnavailable("historical reaction window has no candles")
                observed_at, observed_price = sorted(reaction_rows, key=lambda item: item[0])[-1]
                quote = None
                decision_now = observed_at
            else:
                rows = self.client.candles(token, interval="1m", candle_type="market", limit=100)
                quote = parse_rtoken_ticker(self.client.ticker(token), observed_at=now)
                if quote.source_timestamp < event_at:
                    return self._refusal(tool, symbol, ReasonCode.STALE_REACTION,
                                         {"quote_source_timestamp": quote.source_timestamp.isoformat(),
                                          "event_at": event_at.isoformat()},
                                         "Reverb refused because the current token quote predates the event.")
                observed_at, observed_price = quote.source_timestamp, quote.price
                decision_now = now
            baseline, baseline_arithmetic = baseline_price(rows, event_at, self.engine.baseline_window_minutes,
                                                            self.engine.baseline_min_points)
            baseline_observed_at = datetime.fromisoformat(baseline_arithmetic["baseline_last_at"])
            intended_side = None
            order_quantity = self.engine.reaction_quantity
            order_price = None
            if quote is not None and self.engine.reaction_policy in {"momentum", "momentum_long_only"}:
                if quote.bid is None or quote.ask is None:
                    return self._refusal(tool, symbol, ReasonCode.PAIR_BID_ASK_UNAVAILABLE,
                                         {"bid": str(quote.bid), "ask": str(quote.ask)},
                                         "Reverb refused because the reaction limit price needs a live bid and ask.")
                intended_side = "buy" if quote.price >= baseline else "sell"
                order_price = quote.ask if intended_side == "buy" else quote.bid
            # Order sessions are Bitget's New York session; the user's zone is
            # only for narration and display.
            session = session_at(observed_at, "America/New_York").session
            decision = evaluate_reaction(
                symbol=token, baseline=baseline, observed_price=observed_price,
                observed_at=observed_at, baseline_observed_at=baseline_observed_at,
                trigger_pct=self.engine.reaction_trigger_pct, session=session,
                order_type=order_type, max_quote_age_ms=self.engine.max_quote_age_ms,
                intended_side=intended_side, order_quantity=order_quantity,
                order_price=order_price, risk_budget=self.engine.reaction_budget,
                now=decision_now,
            )
            if self.engine_config_sha256:
                decision = decision.model_copy(update={
                    "arithmetic": {**decision.arithmetic, "engine_config_sha256": self.engine_config_sha256}
                })
            self.ledger.register(decision.model_dump(mode="json"))
            return self._record(ToolDecision(
                decision_id=decision.decision_id, tool=tool, status=decision.status, symbol=decision.symbol,
                reason_codes=decision.reason_codes, decision=decision.model_dump(mode="json"),
                arithmetic={**baseline_arithmetic, **decision.arithmetic},
                explanation=("The token move crossed the configured trigger; execution still requires the guarded order path."
                             if decision.status is DecisionStatus.ACT else
                             "The reaction did not produce an executable ACT decision."),
                created_at=decision.observed_at,
            ))
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
            weekend_tokens: set[str] | None = None
            if self.engine.weekend_source_url and hasattr(self.client, "weekend_tokens"):
                try:
                    weekend_tokens = self.client.weekend_tokens(self.engine.weekend_source_url)
                except DataUnavailable:
                    weekend_tokens = None
            try:
                ZoneInfo(user_timezone)
            except (ZoneInfoNotFoundError, ValueError) as exc:
                raise ConfigurationError(f"unknown user timezone: {user_timezone}") from exc
            items: list[dict[str, str]] = []
            for event in events:
                underlying_symbol = _underlying(event.symbol)
                token = rtoken_for_underlying(underlying_symbol)
                token_status = ("verified_24_7" if token in instruments and weekend_tokens and token in weekend_tokens
                                else "online_reality_unverified_24_7" if token in instruments else "missing")
                option_status = "unverified"
                if self.client.credentials is not None:
                    try:
                        expiry_values = self.client.option_expiry_dates(underlying_symbol)
                        valid_expiries = [value for value in expiry_values if value]
                        if valid_expiries:
                            expiry_value, expiry = select_expiry(valid_expiries, event.event_at.date())
                            chain = parse_chain(self.client.option_chain(underlying_symbol, expiry_value), expiry)
                            option_status = "available" if chain else "unverified_or_not_entitled"
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
                                  arithmetic={"event_count": str(len(items)),
                                              "calendar_config_sha256": calendar.config_sha256 if calendar is not None else "unavailable"},
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
