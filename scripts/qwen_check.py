"""Verify Reverb's optional Qwen language layer without touching Bitget trading APIs."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from reverb.env import load_local_env  # noqa: E402
from reverb.errors import ReverbError  # noqa: E402
from reverb.qwen import QwenClient, QwenCredentials  # noqa: E402


def main() -> int:
    load_local_env(ROOT)
    try:
        credentials = QwenCredentials.from_env()
        with QwenClient(credentials) as qwen:
            result = qwen.interpret_view("I expect the company to report stronger results.")
    except ReverbError as exc:
        print(f"REVERB QWEN HALTED: {exc}", file=sys.stderr)
        return 2
    print(f"Qwen ready: provider={result.provider} model={result.model} classification={result.view}")
    print("No Bitget account endpoint or order path was called.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
