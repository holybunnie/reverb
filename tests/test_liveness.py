from datetime import datetime, timezone
import unittest

from reverb.errors import ConfigurationError
from reverb.liveness import check_account_liveness


class FakeClient:
    def __init__(self, permissions=None, perm_type="read-and-write", ips="1.2.3.4"):
        self.permissions = permissions if permissions is not None else ["uta_trade", "uta_mgt"]
        self.perm_type = perm_type
        self.ips = ips

    def account_info(self):
        return {"permissions": self.permissions, "permType": self.perm_type, "ips": self.ips}

    def account_settings(self):
        return {"accountMode": "unified", "holdMode": "one_way_mode"}


class LivenessTests(unittest.TestCase):
    def test_live_shape_accepts_underscore_permission_and_null_ips(self):
        client = FakeClient(permissions=["uta_trade", "uta_mgt"], perm_type="read_and_write", ips=None)
        result = check_account_liveness(client)
        self.assertTrue(result.trade_permission)
        self.assertFalse(result.ip_binding_present)

    def test_trade_and_read_permissions_are_verified_without_withdrawal(self):
        result = check_account_liveness(FakeClient(), datetime(2026, 9, 19, tzinfo=timezone.utc))
        self.assertTrue(result.read_verified)
        self.assertTrue(result.trade_permission)
        self.assertFalse(result.withdrawal_permission)

    def test_withdrawal_scope_halts_the_path(self):
        with self.assertRaises(ConfigurationError):
            check_account_liveness(FakeClient(["uta_trade", "uta_mgt", "withdraw"]))

    def test_missing_management_scope_verifies_trade_but_not_execution_settings(self):
        result = check_account_liveness(FakeClient(["uta_trade"]))
        self.assertTrue(result.trade_permission)
        self.assertFalse(result.account_settings_verified)

    def test_naive_check_timestamp_halts_the_path(self):
        with self.assertRaises(ConfigurationError):
            check_account_liveness(FakeClient(), datetime(2026, 9, 19, 10, 0))
