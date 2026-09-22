"""Read-only local Bitget liveness check. Never prints credentials."""
from __future__ import annotations

import sys
from pathlib import Path

from reverb.bitget import BitgetClient, Credentials
from reverb.env import load_local_env
from reverb.errors import BitgetAPIError, ConfigurationError, DataUnavailable
from reverb.liveness import check_account_liveness


def main() -> int:
    try:
        load_local_env(Path(__file__).resolve().parents[1])
        credentials = Credentials.from_env()
        with BitgetClient(credentials=credentials) as client:
            liveness = check_account_liveness(client)
            print({"status": "verified", "read_only": liveness.read_verified,
                   "trade_permission": liveness.trade_permission,
                   "withdrawal_permission": liveness.withdrawal_permission,
                   "ip_binding_present": liveness.ip_binding_present,
                   "settings_verified": liveness.account_settings_verified})
        return 0
    except ConfigurationError as exc:
        print(f"REVERB HALTED: {exc}. Load local environment variables; no credentials are accepted as command arguments.", file=sys.stderr)
    except BitgetAPIError as exc:
        if exc.code in {"40006", "40009", "40010"}:
            print("REVERB HALTED: Bitget rejected the API authentication. Check the key, secret, passphrase, API permission, IP binding, and local clock.", file=sys.stderr)
        elif exc.code == "40012":
            print("REVERB HALTED: Bitget rejected the protected UTA v3 route with 40012. If the v2 diagnostic recognizes this key and reports that the account is already UTA, the immediate blocker is v3 key activation—not funding or a separate Stock+ checkbox. Stock+ eligibility cannot be inferred until v3 authentication succeeds. No order was sent.", file=sys.stderr)
        else:
            print(f"REVERB HALTED: Bitget returned code {exc.code}. Check the Stock+ and UTA permissions.", file=sys.stderr)
    except DataUnavailable as exc:
        print(f"REVERB HALTED: read-only liveness check failed: {exc}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
