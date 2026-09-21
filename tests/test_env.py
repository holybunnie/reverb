import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from reverb.env import load_local_env


class EnvTests(unittest.TestCase):
    def test_loader_reads_simple_local_values_without_overriding_process(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            (root / ".env").write_text("# comment\nTEST_REVERB_VALUE='local'\nexport TEST_REVERB_OTHER=two\n")
            os.environ.pop("TEST_REVERB_VALUE", None)
            os.environ["TEST_REVERB_OTHER"] = "explicit"
            load_local_env(root)
            self.assertEqual(os.environ.get("TEST_REVERB_VALUE"), "local")
            self.assertEqual(os.environ.get("TEST_REVERB_OTHER"), "explicit")
            os.environ.pop("TEST_REVERB_VALUE", None)


if __name__ == "__main__":
    unittest.main()
