from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Mapping
from urllib.parse import urlencode

import httpx

from .errors import BitgetAPIError, ConfigurationError, DataUnavailable


@dataclass(frozen=True)
class Credentials:
    api_key: str
    secret_key: str
    passphrase: str

    @classmethod
    def from_env(cls) -> "Credentials":
        values = {name: os.getenv(name) for name in ("BITGET_API_KEY", "BITGET_SECRET_KEY", "BITGET_PASSPHRASE")}
        if any(not value for value in values.values()):
            raise ConfigurationError("BITGET_API_KEY, BITGET_SECRET_KEY, and BITGET_PASSPHRASE are required")
        return cls(values["BITGET_API_KEY"], values["BITGET_SECRET_KEY"], values["BITGET_PASSPHRASE"])


def signature(timestamp: str, method: str, request_path: str, query_string: str, body: str, secret_key: str) -> str:
    prehash = timestamp + method.upper() + request_path + query_string + body
    digest = hmac.new(secret_key.encode(), prehash.encode(), hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


class BitgetClient:
    def __init__(self, base_url: str = "https://api.bitget.com", credentials: Credentials | None = None,
                 timeout: float = 20.0, client: httpx.Client | None = None):
        self.base_url = base_url.rstrip("/")
        self.credentials = credentials
        self.timeout = timeout
        self._client = client or httpx.Client(timeout=timeout)

    def close(self):
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def _request(self, method: str, path: str, params: Mapping[str, Any] | None = None,
                 body: Mapping[str, Any] | None = None, private: bool = False) -> dict[str, Any]:
        if private and self.credentials is None:
            raise ConfigurationError("authenticated Bitget access requested without local credentials")
        query = [(key, str(value)) for key, value in (params or {}).items() if value is not None]
        query_string = ("?" + urlencode(query)) if query else ""
        body_text = json.dumps(body, separators=(",", ":"), ensure_ascii=False) if body is not None else ""
        headers = {"Content-Type": "application/json", "locale": "en-US"}
        if private:
            timestamp = str(int(time.time() * 1000))
            headers.update({"ACCESS-KEY": self.credentials.api_key, "ACCESS-SIGN": signature(timestamp, method, path, query_string, body_text, self.credentials.secret_key),
                            "ACCESS-TIMESTAMP": timestamp, "ACCESS-PASSPHRASE": self.credentials.passphrase})
        try:
            response = self._client.request(method, self.base_url + path + query_string, content=body_text or None, headers=headers)
        except httpx.HTTPError as exc:
            raise DataUnavailable(f"Bitget network error for {path}: {type(exc).__name__}") from exc
        try:
            document = response.json()
        except ValueError as exc:
            raise DataUnavailable(f"Bitget returned non-JSON response for {path}") from exc
        if not isinstance(document, dict):
            raise DataUnavailable(f"Bitget returned a non-object response for {path}")
        if response.status_code >= 400 or document.get("code") != "00000":
            raise BitgetAPIError(response.status_code, document.get("code"), str(document.get("msg", "unknown error")))
        if not isinstance(document.get("data"), (dict, list)):
            raise DataUnavailable(f"Bitget response has no structured data for {path}")
        return document

    def instruments(self) -> list[dict[str, Any]]:
        return self._request("GET", "/api/v3/market/instruments", {"category": "SPOT"})["data"]

    def instrument(self, symbol: str) -> dict[str, Any]:
        rows = [row for row in self.instruments() if isinstance(row, dict) and row.get("symbol") == symbol]
        if len(rows) != 1:
            raise DataUnavailable(f"expected one live instrument record for {symbol}, got {len(rows)}")
        return rows[0]

    def weekend_tokens(self, source_url: str) -> set[str]:
        """Parse the configured first-party 24/7 announcement at runtime."""
        if not source_url.startswith("https://www.bitget.com/"):
            raise ConfigurationError("24/7 source must be a first-party Bitget HTTPS URL")
        try:
            response = self._client.get(source_url)
            response.raise_for_status()
            body = response.text
        except httpx.HTTPError as exc:
            raise DataUnavailable(f"Bitget 24/7 source unavailable: {type(exc).__name__}") from exc
        # The page presents symbols as rTokens; do not ship a copied symbol
        # list because the exchange expands it in batches.
        symbols = {match.upper() for match in re.findall(r"\br[A-Z][A-Z0-9]{1,9}\b", body)}
        if not symbols:
            raise DataUnavailable("Bitget 24/7 source contained no rToken symbols")
        return symbols

    def ticker(self, symbol: str) -> dict[str, Any]:
        rows = self._request("GET", "/api/v3/market/tickers", {"category": "SPOT", "symbol": symbol})["data"]
        if len(rows) != 1:
            raise DataUnavailable(f"expected one ticker for {symbol}, got {len(rows)}")
        return rows[0]

    def orderbook(self, symbol: str, limit: int = 5) -> dict[str, Any]:
        return self._request("GET", "/api/v3/market/orderbook", {"category": "SPOT", "symbol": symbol, "limit": limit})["data"]

    def candles(self, symbol: str, interval: str = "1m", candle_type: str = "market", limit: int = 100) -> list[list[str]]:
        if candle_type != "market":
            raise ConfigurationError("Reality candles must request type=market")
        if interval not in {"1m", "5m", "15m", "1H", "4H", "1D"}:
            raise ConfigurationError(f"unsupported Reality candle interval: {interval}")
        if limit <= 0 or limit > 1000:
            raise ConfigurationError("current candle limit must be between 1 and 1000")
        return self._request("GET", "/api/v3/market/candles", {"category": "SPOT", "symbol": symbol, "interval": interval,
                                                                    "type": candle_type, "limit": limit})["data"]

    def history_candles(self, symbol: str, *, start_time: datetime, end_time: datetime,
                        interval: str = "1m", candle_type: str = "market", limit: int = 100) -> list[list[str]]:
        if candle_type != "market":
            raise ConfigurationError("Reality candles must request type=market")
        if interval not in {"1m", "5m", "15m", "1H", "4H", "1D"}:
            raise ConfigurationError(f"unsupported Reality candle interval: {interval}")
        if limit <= 0 or limit > 100:
            raise ConfigurationError("historical candle limit must be between 1 and 100")
        if start_time.tzinfo is None or end_time.tzinfo is None:
            raise ConfigurationError("historical candle bounds must include a timezone")
        start_utc = start_time.astimezone(timezone.utc)
        end_utc = end_time.astimezone(timezone.utc)
        if end_utc <= start_utc:
            raise ConfigurationError("historical candle end must be after start")
        if end_utc - start_utc > timedelta(days=90):
            raise ConfigurationError("historical candle range cannot exceed 90 days")
        return self._request("GET", "/api/v3/market/history-candles", {
            "category": "SPOT", "symbol": symbol, "interval": interval, "type": candle_type,
            "startTime": str(int(start_utc.timestamp() * 1000)),
            "endTime": str(int(end_utc.timestamp() * 1000)), "limit": limit,
        })["data"]

    def fee_group(self) -> list[dict[str, Any]]:
        return self._request("GET", "/api/v3/market/fee-group", {"category": "SPOT"})["data"]

    def stock_quote(self, symbol: str) -> dict[str, Any]:
        rows = self._request("GET", "/api/v3/stockplus/market/quote", {"symbol": symbol}, private=True)["data"]["list"]
        if len(rows) != 1:
            raise DataUnavailable(f"expected one Stock+ quote for {symbol}, got {len(rows)}")
        return rows[0]

    def option_expiry_dates(self, symbol: str) -> list[str]:
        data = self._request("GET", "/api/v3/stockplus/market/option-expiry-date", {"symbol": symbol}, private=True)["data"]
        values = data.get("expiryDate")
        if not isinstance(values, list) or not values or any(not isinstance(value, str) for value in values):
            raise DataUnavailable(f"Bitget returned no usable expiry dates for {symbol}")
        return values

    def option_chain(self, symbol: str, expiry_date: str) -> list[dict[str, Any]]:
        data = self._request("GET", "/api/v3/stockplus/market/option-chain-info", {"symbol": symbol, "expiryDate": expiry_date}, private=True)["data"]
        rows = data.get("strikePriceInfo")
        if not isinstance(rows, list) or not rows:
            raise DataUnavailable(f"Bitget returned no option chain rows for {symbol} {expiry_date}")
        return rows

    def option_quotes(self, symbols: list[str]) -> list[dict[str, Any]]:
        if not symbols or len(symbols) > 500:
            raise ConfigurationError("option quote requests require 1 to 500 symbols")
        data = self._request("GET", "/api/v3/stockplus/market/option-quote", {"symbol": ",".join(symbols)}, private=True)["data"]
        rows = data.get("secuQuote")
        if not isinstance(rows, list) or len(rows) != len(symbols):
            raise DataUnavailable("option quote response is incomplete")
        enriched: list[dict[str, Any]] = []
        for expected_symbol, row in zip(symbols, rows):
            if not isinstance(row, dict) or row.get("symbol") != expected_symbol:
                raise DataUnavailable("option quote response has an unexpected symbol")
            # The documented option-quote response carries last trade/IV but
            # does not publish executable bid/ask fields.  Fetch the matching
            # Stock+ depth snapshot rather than treating lastDone as a fill.
            if row.get("bid") in (None, "") or row.get("ask") in (None, ""):
                depth = self.stockplus_depth(expected_symbol)
                copy = dict(row)
                copy["bid"] = self._depth_top(depth.get("bids"), side="bid")
                copy["ask"] = self._depth_top(depth.get("asks"), side="ask")
                enriched.append(copy)
            else:
                enriched.append(dict(row))
        return enriched

    def stockplus_depth(self, symbol: str) -> dict[str, Any]:
        if not symbol or any(character.isspace() for character in symbol):
            raise ConfigurationError("Stock+ depth requires a valid symbol")
        data = self._request("GET", "/api/v3/stockplus/market/depth", {"symbol": symbol}, private=True)["data"]
        if not isinstance(data, dict):
            raise DataUnavailable("Stock+ depth response is not an object")
        return data

    @staticmethod
    def _depth_top(levels: Any, *, side: str) -> str | None:
        if not isinstance(levels, list):
            raise DataUnavailable("Stock+ depth side is not a list")
        prices: list[Decimal] = []
        for level in levels:
            if not isinstance(level, dict) or level.get("price") in (None, ""):
                raise DataUnavailable("Stock+ depth level has no price")
            try:
                price = Decimal(str(level["price"]))
            except (ArithmeticError, TypeError, ValueError) as exc:
                raise DataUnavailable("Stock+ depth price is not numeric") from exc
            if not price.is_finite() or price <= 0:
                raise DataUnavailable("Stock+ depth price is invalid")
            prices.append(price)
        if not prices:
            return None
        return str(min(prices) if side == "ask" else max(prices))

    def account_settings(self) -> dict[str, Any]:
        return self._request("GET", "/api/v3/account/settings", private=True)["data"]

    def account_info(self) -> dict[str, Any]:
        return self._request("GET", "/api/v3/account/info", private=True)["data"]

    def account_assets(self) -> list[dict[str, Any]]:
        data = self._request("GET", "/api/v3/account/assets", private=True)["data"]
        if not isinstance(data, list):
            raise DataUnavailable("Bitget account assets response is not a list")
        return data
