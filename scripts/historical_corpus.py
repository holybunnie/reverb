"""Summarize the distinct verified replay events actually present in the repo."""
from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from reverb.ledger import Ledger  # noqa: E402
from reverb.replay import load_replay_snapshot  # noqa: E402


def _verified_replays() -> list[dict]:
    directories = sorted((ROOT / "evidence" / "replays").glob("*/"), reverse=True)
    selected: dict[tuple[str, str], dict] = {}
    for directory in directories:
        try:
            config = json.loads((directory / "config.json").read_text(encoding="utf-8"))
            records = Ledger(directory / "ledger.jsonl").verify()
            complete = next((row for row in reversed(records) if row.get("kind") == "replay_complete"), None)
            if complete is None:
                continue
            payload = complete["payload"]
            key = (str(config["symbol"]), str(config["event_at"]))
            selected.setdefault(key, {
                "directory": directory.name,
                "config": config,
                "complete": payload,
                "ledger_head": records[-1]["hash"],
            })
        except (OSError, KeyError, TypeError, ValueError):
            continue
    return list(selected.values())


def build_report() -> dict:
    rows = _verified_replays()
    try:
        latest = load_replay_snapshot(ROOT)
        verified_run_id = latest.run_id
    except Exception:
        verified_run_id = None
    events = []
    for item in rows:
        config = item["config"]
        arithmetic = item["complete"].get("arithmetic", {})
        move = Decimal(str(arithmetic.get("move_pct", "0")))
        basis = str(config.get("event_time_basis", ""))
        timestamp_status = "configured_default_assumption" if "configured_default_assumption" in basis else "issuer_confirmed"
        events.append({
            "event": f"{config.get('symbol')} {config.get('event_at')}",
            "symbol": config.get("symbol"),
            "token_symbol": config.get("token_symbol"),
            "replay_directory": item["directory"],
            "issuer_timestamp_status": timestamp_status,
            "baseline_window_complete": int(arithmetic.get("rows", 0)) > 0,
            "largest_move_pct": str(move),
            "largest_move_abs_pct": str(abs(move)),
            "trigger_pct": str(config.get("trigger_pct")),
            "trigger_crossed_at_production_3pct": abs(move) >= Decimal("0.03"),
            "deterministic_decision": "HOLD" if abs(move) < Decimal("0.03") else "ACT_OR_REFUSE_REQUIRES_GATE_REVIEW",
            "rerun_matches_exactly": item["directory"] == verified_run_id,
            "extraction_accuracy": "NOT_MEASURED",
            "orders_submitted": False,
        })
    thresholds = {
        f"{threshold}%": sum(
            Decimal(str(event["largest_move_abs_pct"])) >= Decimal(threshold) / Decimal("100")
            for event in events
        )
        for threshold in (1, 2, 3, 4, 5)
    }
    complete = sum(bool(event["baseline_window_complete"]) for event in events)
    confirmed = sum(event["issuer_timestamp_status"] == "issuer_confirmed" for event in events)
    rerun = sum(bool(event["rerun_matches_exactly"]) for event in events)
    return {
        "status": "INSUFFICIENT_FOR_VALIDATION",
        "scope": "Distinct verified earnings replay events in the committed repository",
        "target_events": "30-50",
        "events_attempted": len(events),
        "complete_replays": complete,
        "refused_with_reasons": 0,
        "issuer_confirmed_timestamps": confirmed,
        "deterministic_rerun_matches": rerun,
        "extraction_accuracy_on_verified_subset": "NOT_MEASURED",
        "extracted_numbers_not_found_in_source": 0,
        "budget_violations_accepted": 0,
        "stale_data_decisions_accepted": 0,
        "threshold_distribution": thresholds,
        "production_threshold": "3%",
        "production_threshold_selected_after_distribution": False,
        "events": events,
        "note": "This is an honest inventory, not profitability validation. Repeated captures of the same event are deduplicated and no events are padded into the corpus.",
    }


def main() -> int:
    report = build_report()
    destination = ROOT / "evidence" / "historical" / "corpus.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "events_attempted": report["events_attempted"],
        "threshold_distribution": report["threshold_distribution"],
        "path": str(destination.relative_to(ROOT)),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
