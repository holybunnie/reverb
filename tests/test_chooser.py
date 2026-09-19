from datetime import date
from decimal import Decimal
import unittest

from reverb.chooser import parse_chain, select_at_the_money, select_contract, select_expiry
from reverb.errors import DataUnavailable
from reverb.models import Direction


class ChooserTests(unittest.TestCase):
    def setUp(self):
        self.rows = [
            {"price": "95", "callSymbol": "NVDA261016C095000.US", "putSymbol": "NVDA261016P095000.US", "standard": True},
            {"price": "100", "callSymbol": "NVDA261016C100000.US", "putSymbol": "NVDA261016P100000.US", "standard": True},
            {"price": "110", "callSymbol": "NVDA261016C110000.US", "putSymbol": "NVDA261016P110000.US", "standard": True},
        ]

    def test_expiry_is_first_one_after_event(self):
        value, parsed = select_expiry(["20261002", "20261016", "20260925"], date(2026, 10, 5))
        self.assertEqual(value, "20261016")
        self.assertEqual(parsed, date(2026, 10, 16))

    def test_strike_selection_is_deterministic_from_view_and_move(self):
        contracts = parse_chain(self.rows, date(2026, 10, 16))
        call = select_contract(contracts, Direction.CALL, Decimal("100"), Decimal("0.08"))
        put = select_contract(contracts, Direction.PUT, Decimal("100"), Decimal("0.08"))
        self.assertEqual(call.strike, Decimal("110"))
        self.assertEqual(put.strike, Decimal("95"))
        self.assertEqual(select_at_the_money(contracts, Decimal("103")).strike, Decimal("100"))

    def test_nonstandard_only_chain_fails_loudly(self):
        rows = [{**self.rows[0], "standard": False}]
        with self.assertRaises(DataUnavailable):
            parse_chain(rows, date(2026, 10, 16))

