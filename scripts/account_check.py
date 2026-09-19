"""Read-only local Bitget liveness check. Never prints credentials."""
from __future__ import annotations

import sys

from reverb.bitget import BitgetClient, Credentials
from reverb.errors import BitgetAPIError, ConfigurationError, DataUnavailable


def main() -> int:
    try:
        credentials = Credentials.from_env()
        with BitgetClient(credentials=credentials) as client:
            settings = client.account_settings()
            print({"status": "verified", "read_only": True, "settings_fields": sorted(settings.keys())})
        return 0
    except ConfigurationError as exc:
        print(f"REVERB HALTED: {exc}. Load local environment variables; no credentials are accepted as command arguments.", file=sys.stderr)
    except BitgetAPIError as exc:
        if exc.code in {"40006", "40009", "40010"}:
            print("REVERB HALTED: Bitget rejected the API authentication. Check the key, secret, passphrase, API permission, IP binding, and local clock.", file=sys.stderr)
        else:
            print(f"REVERB HALTED: Bitget returned code {exc.code}. Check the Stock+ and UTA permissions.", file=sys.stderr)
    except DataUnavailable as exc:
        print(f"REVERB HALTED: read-only liveness check failed: {exc}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
