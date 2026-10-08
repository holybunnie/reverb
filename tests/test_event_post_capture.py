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

    def test_exhibit_99_1_is_read_from_the_filing_header_type_not_the_filename(self):
        headers = ("&lt;DOCUMENT&gt;\n&lt;TYPE&gt;8-K\n&lt;SEQUENCE&gt;1\n&lt;FILENAME&gt;apld-20261007.htm\n"
                   "&lt;DOCUMENT&gt;\n&lt;TYPE&gt;EX-99.1\n&lt;SEQUENCE&gt;2\n&lt;FILENAME&gt;apldq127earningsrelease.htm\n"
                   "&lt;DOCUMENT&gt;\n&lt;TYPE&gt;EX-99.10\n&lt;SEQUENCE&gt;3\n&lt;FILENAME&gt;other.htm\n"
                   "&lt;DOCUMENT&gt;\n&lt;TYPE&gt;EX-101.SCH\n&lt;SEQUENCE&gt;4\n&lt;FILENAME&gt;apld-20261007.xsd\n")
        self.assertEqual(post.declared_exhibits(headers), ["apldq127earningsrelease.htm"])

    def test_release_text_normalisation_matches_the_stz_reconciliation(self):
        import stz_reconcile
        sample = "<p>Net&nbsp;sales</p>\n<td>$2,473.6</td>  <b>(0.6%)</b>"
        self.assertEqual(post.normalize(sample), stz_reconcile.normalize(sample))
        self.assertEqual(post.normalize(sample), "Net sales $2,473.6 (0.6%)")


if __name__ == "__main__":
    unittest.main()
