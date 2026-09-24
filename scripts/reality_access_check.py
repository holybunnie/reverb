"""Check optional authenticated Reality book/fills access; never places orders."""
from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from reverb.bitget import BitgetClient, Credentials  # noqa: E402
from reverb.env import load_local_env  # noqa: E402
from reverb.errors import BitgetAPIError, ConfigurationError, DataUnavailable  # noqa: E402
from reverb.ledger import Ledger  # noqa: E402


def digest(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def permission_requirement(exc: BitgetAPIError) -> str | None:
    """Persist only the API's named scope requirement, never arbitrary text."""
    message = str(exc)
    if "need UTA manage read or UTA manage write permissions" in message:
        return "UTA manage read or UTA manage write"
    return None


def check() -> dict[str, object]:
    load_local_env(ROOT)
    # Prefer the user's separate read-only UTA key. Keep the established
    # trading key untouched as a fallback for older installs.
    prefixes = ("BITGET_READ", "BITGET_DATA", "BITGET")
    credentials = Credentials.from_env_priority(*prefixes)
    credential_set = next(prefix for prefix in prefixes if os.getenv(f"{prefix}_API_KEY"))
    client = BitgetClient(credentials=credentials, timeout=15)
    results: dict[str, object] = {"symbol": "RCOSTUSDT", "checked_at": datetime.now(timezone.utc).isoformat(),
                                  "orders_submitted": False,
                                  "credential_set": credential_set,
                                  "public_market_data_is_not_a_reality_feed_substitute": True}
    try:
        # Bitget's account-info route returns the calling key's permission
        # scopes. Record only the two relevant booleans; never persist identity
        # fields or the raw response.
        try:
            account_info = client.account_info()
            permissions = account_info.get("permissions") if isinstance(account_info, dict) else None
            if not isinstance(permissions, list) or not all(isinstance(item, str) for item in permissions):
                results["api_key_scope_diagnostic"] = {"status": "unexpected_response_shape"}
            else:
                results["api_key_scope_diagnostic"] = {
                    "status": "available",
                    "permission_type": account_info.get("permType"),
                    "uta_trade": "uta_trade" in permissions,
                    "uta_management": "uta_mgt" in permissions,
                }
        except BitgetAPIError as exc:
            results["api_key_scope_diagnostic"] = {
                "status": "unavailable", "http_status": exc.status, "bitget_code": exc.code,
            }
        except DataUnavailable as exc:
            results["api_key_scope_diagnostic"] = {
                "status": "unavailable", "error_type": type(exc).__name__,
            }

        diagnostics = []
        for symbol in ("RCOSTUSDT", "RNVDAUSDT"):
            snapshot: dict[str, object] = {"symbol": symbol}
            try:
                book = client.orderbook(symbol, limit=50)
                snapshot["public_market_orderbook"] = {
                    "status": "available",
                    "exchange_timestamp": book.get("ts"),
                    "bid_levels": len(book.get("b", [])) if isinstance(book.get("b"), list) else None,
                    "ask_levels": len(book.get("a", [])) if isinstance(book.get("a"), list) else None,
                    "sha256": digest(book),
                    "proven_reality_depth_route": True,
                }
            except BitgetAPIError as exc:
                snapshot["public_market_orderbook"] = {
                    "status": "unavailable", "http_status": exc.status, "bitget_code": exc.code,
                }
            except DataUnavailable as exc:
                snapshot["public_market_orderbook"] = {
                    "status": "unavailable", "error_type": type(exc).__name__,
                }
            try:
                public_fills = client.public_fills(symbol, limit=100)
                snapshot["generic_public_fills"] = {
                    "status": "available", "rows": len(public_fills), "sha256": digest(public_fills),
                    "distinct_from_reality_platform_fills": True,
                }
            except BitgetAPIError as exc:
                snapshot["generic_public_fills"] = {
                    "status": "unavailable", "http_status": exc.status, "bitget_code": exc.code,
                }
            except DataUnavailable as exc:
                snapshot["generic_public_fills"] = {
                    "status": "unavailable", "error_type": type(exc).__name__,
                }
            diagnostics.append(snapshot)
        results["public_fallback_diagnostics"] = diagnostics
        try:
            book = client.reality_orderbook("RCOSTUSDT")
            results["reality_orderbook"] = {"status": "available", "exchange_timestamp": book["ts"],
                                               "sha256": digest(book)}
        except BitgetAPIError as exc:
            results["reality_orderbook"] = {"status": "blocked", "http_status": exc.status,
                                               "bitget_code": exc.code,
                                               "required_permission": permission_requirement(exc)}
        except DataUnavailable as exc:
            results["reality_orderbook"] = {"status": "unavailable", "error_type": type(exc).__name__}
        try:
            fills = client.reality_fills("RCOSTUSDT")
            results["reality_fills"] = {"status": "available", "rows": len(fills), "sha256": digest(fills)}
        except BitgetAPIError as exc:
            results["reality_fills"] = {"status": "blocked", "http_status": exc.status,
                                          "bitget_code": exc.code,
                                          "required_permission": permission_requirement(exc)}
        except DataUnavailable as exc:
            results["reality_fills"] = {"status": "unavailable", "error_type": type(exc).__name__}
    finally:
        client.close()
    entry = Ledger(ROOT / "evidence" / "reality-access" / "ledger.jsonl").append(
        "reality_access_check", results)
    return {"results": results, "ledger_head": entry["hash"]}


def main() -> int:
    try:
        result = check()
    except ConfigurationError as exc:
        print(f"REVERB HALTED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
