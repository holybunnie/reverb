from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from reverb.errors import ConfigurationError, LedgerError
from reverb.execution import RealityOrderConstraints, place_reaction_limit
from reverb.ledger import Ledger
from reverb.models import DecisionStatus, LivenessDecision, ReactionDecision


class FakeExecutor:
    def __init__(self):
        self.calls = []

    def place_reality_limit(self, **kwargs):
        self.calls.append(kwargs)
        return {"orderId": "order-1"}


def _decision(status=DecisionStatus.ACT):
    return ReactionDecision(
        decision_id="reaction-1", status=status, symbol="RNVDAUSDT", session="after_hours",
        baseline_price=Decimal("100"), observed_price=Decimal("105"), move_pct=Decimal("0.05"),
        trigger_pct=Decimal("0.03"), reason_codes=(),
        observed_at=datetime(2026, 9, 19, 20, 5, tzinfo=timezone.utc),
        arithmetic={"order_type": "limit"}, intended_side="buy",
        order_quantity=Decimal("1"), order_price=Decimal("105"),
        maximum_loss=Decimal("105"), risk_budget=Decimal("105"),
    )


def _liveness():
    return LivenessDecision(
        checked_at=datetime(2026, 9, 19, 20, 0, tzinfo=timezone.utc), read_verified=True,
        trade_permission=True, withdrawal_permission=False, ip_binding_present=True,
        account_permission_type="read-and-write", account_settings_verified=True,
        arithmetic={},
    )


class ExecutionTests(unittest.TestCase):
    def test_order_requires_liveness_even_with_act_decision(self):
        with TemporaryDirectory() as temp:
            ledger = Ledger(Path(temp) / "ledger.jsonl")
            ledger.register({"decision_id": "reaction-1", "status": "act"})
            with self.assertRaises(ConfigurationError):
                place_reaction_limit(
                    executor=FakeExecutor(), ledger=ledger, decision=_decision(), symbol="RNVDAUSDT",
                    side="buy", quantity=Decimal("1"), price=Decimal("105"), client_oid="oid-1",
                )

    def test_order_records_submission_after_liveness_and_registration(self):
        with TemporaryDirectory() as temp:
            ledger = Ledger(Path(temp) / "ledger.jsonl")
            ledger.register({"decision_id": "reaction-1", "status": "act"})
            executor = FakeExecutor()
            response = place_reaction_limit(
                executor=executor, ledger=ledger, decision=_decision(), symbol="RNVDAUSDT",
                side="buy", quantity=Decimal("1"), price=Decimal("105"), client_oid="oid-1",
                liveness=_liveness(), constraints=RealityOrderConstraints(
                    price_precision=2, quantity_precision=4,
                    min_order_qty=Decimal("0.0001"), min_order_amount=Decimal("10"),
                ), available_quote=Decimal("105"),
            )
            self.assertEqual(response["orderId"], "order-1")
            self.assertEqual(ledger.verify()[-1]["kind"], "order_submitted")
            self.assertEqual(executor.calls[0]["client_oid"], "oid-1")

    def test_refused_registration_cannot_be_used_for_an_order(self):
        with TemporaryDirectory() as temp:
            ledger = Ledger(Path(temp) / "ledger.jsonl")
            ledger.register({"decision_id": "reaction-1", "status": "refuse"})
            with self.assertRaises(LedgerError):
                place_reaction_limit(
                    executor=FakeExecutor(), ledger=ledger, decision=_decision(), symbol="RNVDAUSDT",
                    side="buy", quantity=Decimal("1"), price=Decimal("105"), client_oid="oid-1",
                    liveness=_liveness(),
                )

    def test_order_intent_cannot_be_changed_at_execution(self):
        with TemporaryDirectory() as temp:
            ledger = Ledger(Path(temp) / "ledger.jsonl")
            ledger.register({"decision_id": "reaction-1", "status": "act"})
            with self.assertRaises(ConfigurationError):
                place_reaction_limit(
                    executor=FakeExecutor(), ledger=ledger, decision=_decision(), symbol="RNVDAUSDT",
                    side="sell", quantity=Decimal("1"), price=Decimal("105"), client_oid="oid-1",
                    liveness=_liveness(), constraints=RealityOrderConstraints(
                        price_precision=2, quantity_precision=4,
                        min_order_qty=Decimal("0.0001"), min_order_amount=Decimal("10"),
                    ),
                )

    def test_runtime_instrument_constraints_are_required(self):
        with TemporaryDirectory() as temp:
            ledger = Ledger(Path(temp) / "ledger.jsonl")
            ledger.register({"decision_id": "reaction-1", "status": "act"})
            with self.assertRaises(ConfigurationError):
                place_reaction_limit(
                    executor=FakeExecutor(), ledger=ledger, decision=_decision(), symbol="RNVDAUSDT",
                    side="buy", quantity=Decimal("1"), price=Decimal("105"), client_oid="oid-1",
                    liveness=_liveness(),
                )

    def test_sell_requires_verified_available_balance(self):
        sell_decision = _decision().model_copy(update={"intended_side": "sell"})
        with TemporaryDirectory() as temp:
            ledger = Ledger(Path(temp) / "ledger.jsonl")
            ledger.register({"decision_id": "reaction-1", "status": "act"})
            with self.assertRaises(ConfigurationError):
                place_reaction_limit(
                    executor=FakeExecutor(), ledger=ledger, decision=sell_decision,
                    symbol="RNVDAUSDT", side="sell", quantity=Decimal("1"), price=Decimal("105"), client_oid="oid-1",
                    liveness=_liveness(), constraints=RealityOrderConstraints(
                        price_precision=2, quantity_precision=4,
                        min_order_qty=Decimal("0.0001"), min_order_amount=Decimal("10"),
                    ), available_quantity=Decimal("0.5"),
                )


if __name__ == "__main__":
    unittest.main()
