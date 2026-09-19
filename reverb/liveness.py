from __future__ import annotations

from datetime import datetime, timezone

from .bitget import BitgetClient
from .errors import ConfigurationError, DataUnavailable
from .models import LivenessDecision


def check_account_liveness(client: BitgetClient, now: datetime | None = None) -> LivenessDecision:
    """Verify read access, UTA trade scope, and account settings without placing an order."""
    checked_at = now or datetime.now(timezone.utc)
    info = client.account_info()
    permissions = info.get("permissions")
    perm_type = info.get("permType")
    ips = info.get("ips")
    if not isinstance(permissions, list) or any(not isinstance(value, str) for value in permissions):
        raise DataUnavailable("Bitget account info has no validated permission list")
    if not isinstance(perm_type, str) or not isinstance(ips, str):
        raise DataUnavailable("Bitget account info has no validated permission type or IP list")
    settings = client.account_settings()
    if not isinstance(settings, dict) or not settings:
        raise DataUnavailable("Bitget account settings are empty")
    trade = "uta_trade" in permissions and perm_type == "read-and-write"
    withdrawal = "withdraw" in permissions
    if withdrawal:
        raise ConfigurationError("API key includes withdrawal permission; create a read-and-trade-only key")
    if not trade:
        raise ConfigurationError("API key does not have UTA read-and-write trade permission")
    return LivenessDecision(
        checked_at=checked_at, read_verified=True, trade_permission=True,
        withdrawal_permission=False, ip_binding_present=bool(ips.strip()),
        account_permission_type=perm_type, account_settings_verified=True,
        arithmetic={"permission_count": str(len(permissions)), "settings_field_count": str(len(settings))},
    )

