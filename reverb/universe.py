from __future__ import annotations

from typing import Any

from .errors import DataUnavailable


def reality_instruments(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    if not isinstance(rows, list) or not rows:
        raise DataUnavailable("Bitget returned no spot instruments")
    result = {}
    for row in rows:
        if row.get("isReality") != "yes":
            continue
        if row.get("symbolType") != "stock" or not str(row.get("baseCoin", "")).startswith("r"):
            raise DataUnavailable("Bitget Reality metadata disagrees with stock identity")
        if row.get("status") == "online":
            base = str(row["baseCoin"]).upper()
            if base in result:
                raise DataUnavailable(f"duplicate live Reality base coin: {base}")
            result[base] = row
    if not result:
        raise DataUnavailable("no online Reality stock instruments")
    return result


def rtoken_for_underlying(underlying_symbol: str) -> str:
    value = underlying_symbol.upper()
    if not value.endswith(".US") or len(value) <= 3:
        raise DataUnavailable(f"unsupported Stock+ underlying symbol: {underlying_symbol}")
    return "R" + value[:-3]


def option_reality_intersection(option_underlyings: set[str], rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    if not option_underlyings:
        raise DataUnavailable("option universe is empty or unavailable")
    reality = reality_instruments(rows)
    result = {}
    for underlying in option_underlyings:
        token = rtoken_for_underlying(underlying)
        if token in reality:
            result[underlying.upper()] = reality[token]
    return result
