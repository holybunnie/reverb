import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import issuer_release_record as record  # noqa: E402

FEED = """<rss><channel>
<item><title>Applied Digital Reports Fiscal First Quarter 2027 Results</title><pubDate>{stamp}</pubDate></item>
<item><title>Applied Digital Announces New Lease</title><pubDate>Wed, 07 Oct 26 16:15:00 -0400</pubDate></item>
<item><title>Applied Digital Sets Fiscal First Quarter 2027 Conference Call</title><pubDate>Mon, 28 Sep 26 16:05:00 -0400</pubDate></item>
</channel></rss>"""
EDGAR = {"filings": {"recent": {"form": ["8-K"], "filingDate": ["2026-10-07"],
                                "acceptanceDateTime": ["2026-10-07T20:10:00.000Z"]}}}


class IssuerReleaseRecordTests(unittest.TestCase):
    def run_with(self, stamp: str):
        def fake_fetch(url, agent):
            return json.dumps(EDGAR).encode() if "sec.gov" in url else FEED.format(stamp=stamp).encode()
        original, record.fetch = record.fetch, fake_fetch
        try:
            return record.build("apld-q1-fy27", "2026-10-08T00:00:00Z")[1]
        finally:
            record.fetch = original

    def test_release_time_comes_from_the_zoned_feed_and_is_bounded_by_the_8k(self):
        result = self.run_with("Wed, 07 Oct 26 16:05:00 -0400")
        self.assertEqual(result["issuer_release_timestamp"], "2026-10-07T20:05:00Z")
        self.assertEqual(result["upper_bound_8k_acceptance"], "2026-10-07T20:10:00Z")
        self.assertIn("New Lease", result["same_window_issuer_release"])

    def test_refuses_a_time_without_an_offset_or_after_the_filing(self):
        with self.assertRaises(SystemExit):
            self.run_with("Wed, 07 Oct 26 16:05:00")
        with self.assertRaises(SystemExit):
            self.run_with("Wed, 07 Oct 26 16:30:00 -0400")


if __name__ == "__main__":
    unittest.main()
