import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import event_post_capture as post  # noqa: E402


class EventPostCaptureTests(unittest.TestCase):
    def test_exhibit_99_1_is_picked_and_99_2_or_99_10_are_not(self):
        picked = [name for name in ("stzex991_83120268kearnings.htm", "apld-ex99_1.htm", "ex99-1.htm", "ex9901.htm",
                                    "ex99-2.htm", "ex9910.htm", "stz-20261006.htm") if post.EXHIBIT.search(name)]
        self.assertEqual(picked, ["stzex991_83120268kearnings.htm", "apld-ex99_1.htm", "ex99-1.htm", "ex9901.htm"])

    def test_release_text_normalisation_matches_the_stz_reconciliation(self):
        import stz_reconcile
        sample = "<p>Net&nbsp;sales</p>\n<td>$2,473.6</td>  <b>(0.6%)</b>"
        self.assertEqual(post.normalize(sample), stz_reconcile.normalize(sample))
        self.assertEqual(post.normalize(sample), "Net sales $2,473.6 (0.6%)")


if __name__ == "__main__":
    unittest.main()
