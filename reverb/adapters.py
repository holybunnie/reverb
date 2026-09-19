from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from .errors import DataUnavailable
from .models import Direction, OptionQuote, UnderlyingQuote


def _required(row: dict[str, Any], key: str) -> Any:
    if key not in row or row[key] in (None, ""):
        raise DataUnavailable(f"required Bitget field missing: {key}")
    return row[key]


def _decimal(row: dict[str, Any], key: str, positive: bool = True) -> Decimal:
    try:
        value = Decimal(str(_required(row, key)))
    except (ArithmeticError, ValueError, TypeError) as exc:
        raise DataUnavailable(f"Bitget field is not numeric: {key}") from exc
    if not value.is_finite() or (positive and value <= 0):
        raise DataUnavailable(f"Bitget field is outside its valid range: {key}")
    return value


def source_timestamp(value: Any) -> datetime:
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit()):
        return datetime.fromtimestamp(int(value) / 1000, timezone.utc)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
        except ValueError as exc:
            raise DataUnavailable("invalid Bitget timestamp") from exc
    raise DataUnavailable("missing Bitget timestamp")


def option_expiry(value: str) -> date:
    if not isinstance(value, str):
        raise DataUnavailable("option expiry is not a string")
    formats = ("%Y%m%d",) if len(value) == 8 else ("%y%m%d",) if len(value) == 6 else ()
    for fmt in formats:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise DataUnavailable(f"unsupported option expiry format: {value}")


def parse_option_quote(row: dict[str, Any], observed_at: datetime | None = None) -> OptionQuote:
    direction = _required(row, "direction")
    if direction not in {"C", "P"}:
        raise DataUnavailable(f"unsupported option direction: {direction}")
    source_time = source_timestamp(_required(row, "timestamp"))
    return OptionQuote(
        symbol=str(_required(row, "symbol")), underlying_symbol=str(_required(row, "underlyingSymbol")),
        direction=Direction.CALL if direction == "C" else Direction.PUT,
        strike=_decimal(row, "strikePrice"), expiry=option_expiry(str(_required(row, "expiryDate"))),
        contract_multiplier=_decimal(row, "contractMultipier"),
        last_done=_decimal(row, "lastDone") if row.get("lastDone") not in (None, "") else None,
        bid=_decimal(row, "bid") if row.get("bid") not in (None, "") else None,
        ask=_decimal(row, "ask") if row.get("ask") not in (None, "") else None,
        published_iv=_decimal(row, "impliedVolatility") if row.get("impliedVolatility") not in (None, "") else None,
        observed_at=observed_at or datetime.now(timezone.utc), source_timestamp=source_time,
        trade_status=str(row["tradeStatus"]) if row.get("tradeStatus") not in (None, "") else None,
    )


def parse_stock_quote(row: dict[str, Any], observed_at: datetime | None = None) -> UnderlyingQuote:
    source_time = source_timestamp(_required(row, "timestamp"))
    return UnderlyingQuote(
        symbol=str(_required(row, "symbol")), price=_decimal(row, "lastDone"),
        bid=_decimal(row, "bid") if row.get("bid") not in (None, "") else None,
        ask=_decimal(row, "ask") if row.get("ask") not in (None, "") else None,
        observed_at=observed_at or datetime.now(timezone.utc), source_timestamp=source_time,
    )


def parse_rtoken_ticker(row: dict[str, Any], observed_at: datetime | None = None) -> UnderlyingQuote:
    source_time = source_timestamp(_required(row, "ts"))
    return UnderlyingQuote(
        symbol=str(_required(row, "symbol")), price=_decimal(row, "lastPrice"),
        bid=_decimal(row, "bid1Price") if row.get("bid1Price") not in (None, "") else None,
        ask=_decimal(row, "ask1Price") if row.get("ask1Price") not in (None, "") else None,
        observed_at=observed_at or datetime.now(timezone.utc), source_timestamp=source_time,
    )
