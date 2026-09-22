"""Regenerate a complete no-order earnings workflow from checked replay evidence."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from reverb.ledger import Ledger  # noqa: E402
from reverb.replay import load_replay_snapshot  # noqa: E402
from reverb.report import morning_report  # noqa: E402


def main() -> int:
    replay = load_replay_snapshot(ROOT)
    created = datetime.now(timezone.utc)
    directory = ROOT / "evidence" / "workflows" / created.strftime("%Y%m%dT%H%M%SZ")
    directory.mkdir(parents=True, exist_ok=False)
    ledger = Ledger(directory / "ledger.jsonl")
    ledger.append("thesis", {
        "symbol": replay.symbol,
        "event_at": replay.event_at,
        "direction": "watch_price_confirmation",
        "expected_move_pct": replay.arithmetic["trigger_pct"],
        "risk_budget": replay.arithmetic["risk_budget"],
        "source_replay": replay.run_id,
        "paper_only": True,
    })
    action = {**replay.action, "workflow_role": "paper_action"}
    refusal = {**replay.refusal, "workflow_role": "paper_refusal"}
    ledger.register(action)
    ledger.register(refusal)
    ledger.append("paper_reaction", {
        "decision_id": action["decision_id"],
        "observed_at": replay.arithmetic["observed_at"],
        "move_pct": replay.arithmetic["move_pct"],
        "orders_submitted": False,
    })
    ledger.outcome(action["decision_id"], {
        "result": "paper signal observed; no order submitted",
        "orders_submitted": False,
    })
    ledger.outcome(refusal["decision_id"], {
        "result": "refused before order because notional exceeded budget",
        "orders_submitted": False,
    })
    report = morning_report(ledger)
    (directory / "morning-report.html").write_text(report, encoding="utf-8")
    records = ledger.verify()
    (directory / "summary.json").write_text(json.dumps({
        "status": "complete_paper_workflow",
        "source_replay": replay.run_id,
        "ledger_head": records[-1]["hash"],
        "stages": ["thesis", "pre_registration", "reaction", "outcome", "morning_report"],
        "orders_submitted": False,
    }, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "complete", "directory": str(directory.relative_to(ROOT)),
                      "ledger_entries": len(records), "orders_submitted": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
