from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass
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
        if response.status_code >= 400 or document.get("code") != "00000":
            raise BitgetAPIError(response.status_code, document.get("code"), str(document.get("msg", "unknown error")))
        if not isinstance(document.get("data"), (dict, list)):
            raise DataUnavailable(f"Bitget response has no structured data for {path}")
        return document

    def instruments(self) -> list[dict[str, Any]]:
        return self._request("GET", "/api/v3/market/instruments", {"category": "SPOT"})["data"]

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
        return self._request("GET", "/api/v3/market/candles", {"category": "SPOT", "symbol": symbol, "interval": interval,
                                                                    "type": candle_type, "limit": limit})["data"]

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
        return rows

    def account_settings(self) -> dict[str, Any]:
        return self._request("GET", "/api/v3/account/settings", private=True)["data"]

    def account_assets(self) -> list[dict[str, Any]]:
        data = self._request("GET", "/api/v3/account/assets", private=True)["data"]
        if not isinstance(data, list):
            raise DataUnavailable("Bitget account assets response is not a list")
        return data

    def place_reality_limit(self, *, symbol: str, side: str, quantity: Decimal, price: Decimal, client_oid: str) -> dict[str, Any]:
        if side not in {"buy", "sell"} or quantity <= 0 or price <= 0 or not client_oid:
            raise ConfigurationError("invalid Reality limit order intent")
        return self._request("POST", "/api/v3/trade/place-reality-order", body={"category": "SPOT", "symbol": symbol,
            "side": side, "orderType": "limit", "qty": str(quantity), "price": str(price), "clientOid": client_oid}, private=True)["data"]
