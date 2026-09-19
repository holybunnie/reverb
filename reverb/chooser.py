from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from .adapters import option_expiry
from .errors import DataUnavailable
from .models import Direction


@dataclass(frozen=True)
class ChainContract:
    strike: Decimal
    call_symbol: str
    put_symbol: str
    expiry: date


def _decimal(value: Any, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (ArithmeticError, TypeError, ValueError) as exc:
        raise DataUnavailable(f"option chain field is not numeric: {field}") from exc
    if not result.is_finite() or result <= 0:
        raise DataUnavailable(f"option chain field is invalid: {field}")
    return result


def parse_chain(rows: list[dict[str, Any]], expiry: date) -> tuple[ChainContract, ...]:
    if not isinstance(rows, list) or not rows:
        raise DataUnavailable("option chain is empty")
    contracts: list[ChainContract] = []
    for row in rows:
        if not isinstance(row, dict):
            raise DataUnavailable("option chain row is not an object")
        if row.get("standard") is not True:
            continue
        strike = _decimal(row.get("price"), "price")
        call_symbol = row.get("callSymbol")
        put_symbol = row.get("putSymbol")
        if not isinstance(call_symbol, str) or not call_symbol or not isinstance(put_symbol, str) or not put_symbol:
            raise DataUnavailable("option chain row is missing a call or put symbol")
        contracts.append(ChainContract(strike, call_symbol, put_symbol, expiry))
    if not contracts:
        raise DataUnavailable("option chain has no standard contracts")
    return tuple(sorted(contracts, key=lambda item: item.strike))


def select_expiry(expiry_values: list[str], event_date: date) -> tuple[str, date]:
    if not isinstance(expiry_values, list) or not expiry_values:
        raise DataUnavailable("option expiry list is empty")
    parsed: list[tuple[str, date]] = []
    for value in expiry_values:
        if not isinstance(value, str):
            raise DataUnavailable("option expiry list contains a non-string value")
        parsed.append((value, option_expiry(value)))
    eligible = sorted((pair for pair in parsed if pair[1] > event_date), key=lambda pair: pair[1])
    if not eligible:
        raise DataUnavailable("no option expiry occurs after the earnings event")
    return eligible[0]


def select_contract(contracts: tuple[ChainContract, ...], direction: Direction,
                    spot: Decimal, expected_move_pct: Decimal) -> ChainContract:
    if spot <= 0 or expected_move_pct <= 0 or expected_move_pct >= 1:
        raise DataUnavailable("contract selection inputs are outside their valid ranges")
    target = spot * (Decimal("1") + expected_move_pct if direction is Direction.CALL
                     else Decimal("1") - expected_move_pct)
    return min(contracts, key=lambda item: (abs(item.strike - target), item.strike))


def select_at_the_money(contracts: tuple[ChainContract, ...], spot: Decimal) -> ChainContract:
    if spot <= 0:
        raise DataUnavailable("spot must be positive for an at-the-money selection")
    return min(contracts, key=lambda item: (abs(item.strike - spot), item.strike))


def paired_symbols(contract: ChainContract, direction: Direction) -> tuple[str, str]:
    selected = contract.call_symbol if direction is Direction.CALL else contract.put_symbol
    paired = contract.put_symbol if direction is Direction.CALL else contract.call_symbol
    return selected, paired
