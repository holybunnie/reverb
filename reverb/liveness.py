from __future__ import annotations

from datetime import datetime, timezone

from .bitget import BitgetClient
from .errors import BitgetAPIError, ConfigurationError, DataUnavailable
from .models import LivenessDecision


def check_account_liveness(client: BitgetClient, now: datetime | None = None) -> LivenessDecision:
    """Verify read access, UTA trade scope, and account settings without placing an order."""
    checked_at = now or datetime.now(timezone.utc)
    if checked_at.tzinfo is None:
        raise ConfigurationError("liveness check timestamp must include a timezone")
    checked_at = checked_at.astimezone(timezone.utc)
    info = client.account_info()
    permissions = info.get("permissions")
    perm_type = info.get("permType")
    ips = info.get("ips")
    if not isinstance(permissions, list) or any(not isinstance(value, str) for value in permissions):
        raise DataUnavailable("Bitget account info has no validated permission list")
    if not isinstance(perm_type, str) or (ips is not None and not isinstance(ips, str)):
        raise DataUnavailable("Bitget account info has no validated permission type or IP list")
    management = "uta_mgt" in permissions
    normalized_perm_type = perm_type.replace("_", "-").lower()
    trade = "uta_trade" in permissions and normalized_perm_type == "read-and-write"
    withdrawal = "withdraw" in permissions
    if withdrawal:
        raise ConfigurationError("API key includes withdrawal permission; create a read-and-trade-only key")
    if not trade:
        raise ConfigurationError("API key needs UTA read-and-write trade permission")
    settings: dict = {}
    settings_verified = False
    if management:
        try:
            settings = client.account_settings()
        except BitgetAPIError as exc:
            if exc.code != "40014":
                raise
        if settings:
            settings_verified = True
    return LivenessDecision(
        checked_at=checked_at, read_verified=True, trade_permission=True,
        withdrawal_permission=False, ip_binding_present=bool(ips and ips.strip()),
        account_permission_type=normalized_perm_type, account_settings_verified=settings_verified,
        arithmetic={"permission_count": str(len(permissions)), "settings_field_count": str(len(settings)),
                    "management_permission": str(management).lower()},
    )
