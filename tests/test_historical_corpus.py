import json
from pathlib import Path
import unittest

from scripts.historical_corpus import build_report


ROOT = Path(__file__).resolve().parents[1]


class HistoricalCorpusTests(unittest.TestCase):
    def test_corpus_reports_actual_distinct_count_without_padding(self):
        report = build_report()
        self.assertEqual(report["status"], "INSUFFICIENT_FOR_VALIDATION")
        self.assertEqual(report["events_attempted"], 1)
        self.assertEqual(report["complete_replays"], 1)
        self.assertEqual(report["threshold_distribution"], {
            "1%": 1, "2%": 1, "3%": 0, "4%": 0, "5%": 0,
        })
        self.assertFalse(report["production_threshold_selected_after_distribution"])
        self.assertEqual(report["events"][0]["deterministic_decision"], "HOLD")


if __name__ == "__main__":
    unittest.main()
