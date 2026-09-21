"""Minimal local ``.env`` loader that never prints or transmits its values."""
from __future__ import annotations

import os
from pathlib import Path


def load_local_env(root: Path) -> None:
    """Load ignored local values without overriding an explicit environment.

    This intentionally supports only the simple ``NAME=value`` form used by
    ``.env.example``.  Secrets remain in the process environment and are never
    returned, logged, or accepted as command-line arguments.
    """
    path = root / ".env"
    if not path.exists():
        return
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[7:].lstrip()
        name, separator, value = stripped.partition("=")
        if not separator or not name.isidentifier():
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(name, value)
