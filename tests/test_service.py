import unittest

from reverb.errors import BitgetAPIError, DataUnavailable
from reverb.models import ReasonCode
from reverb.service import _failure_reason


class ServiceErrorTests(unittest.TestCase):
    def test_stock_plus_entitlement_response_is_not_reported_as_generic_data(self):
        self.assertEqual(_failure_reason(BitgetAPIError(400, "40012", "not entitled")),
                         ReasonCode.API_NOT_ENTITLED)
        self.assertEqual(_failure_reason(DataUnavailable("network")), ReasonCode.DATA_UNAVAILABLE)


if __name__ == "__main__":
    unittest.main()
