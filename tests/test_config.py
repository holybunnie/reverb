from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from reverb.config import EngineConfig, load_config


class ConfigTests(unittest.TestCase):
    def test_config_checksum_is_content_addressed(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "engine.json"
            path.write_text(Path("config/engine.json").read_text())
            loaded = load_config(path, EngineConfig)
            self.assertEqual(len(loaded.sha256), 64)
            self.assertEqual(loaded.value.baseline_min_points, 30)


if __name__ == "__main__":
    unittest.main()
