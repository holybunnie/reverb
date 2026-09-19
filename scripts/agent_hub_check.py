"""Read-only local Agent Hub preflight. Never prints credentials or submits an order."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys


def main() -> int:
    executable = os.getenv("REVERB_AGENT_HUB_BIN", "bgc")
    resolved = executable if "/" in executable else shutil.which(executable)
    if not resolved:
        print("REVERB HALTED: local Agent Hub executable was not found; configure bgc or REVERB_AGENT_HUB_BIN.", file=sys.stderr)
        return 2
    try:
        result = subprocess.run([resolved, "discover"], capture_output=True, text=True,
                                timeout=20, check=False, shell=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"REVERB HALTED: Agent Hub discovery could not complete: {type(exc).__name__}.", file=sys.stderr)
        return 2
    if result.returncode != 0:
        print(f"REVERB HALTED: Agent Hub discovery exited with code {result.returncode}.", file=sys.stderr)
        return 2
    print("Agent Hub catalog is reachable locally. No order was submitted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
