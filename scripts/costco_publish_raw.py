"""Publish the public part of the private Costco capture as committable raw evidence.

Copies the whole ledger (so its hash chain still verifies), the run config, and
the public market-data bodies. Account-scoped Reality bodies are withheld and
listed by hash in WITHHELD.md. Every published file must pass the secret scan.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from reverb.ledger import Ledger  # noqa: E402

PUBLISHED_ENDPOINTS = {"candles", "public_orderbook", "ticker", "public_fills"}
WITHHELD_ENDPOINTS = {"reality_orderbook", "reality_fills"}
SECRET_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"ACCESS-(KEY|SIGN|PASSPHRASE|TIMESTAMP)",
        r'"(apiKey|api_key|secret|secretKey|passphrase|signature|sign)"\s*:',
        r'"(uid|userId|user_id|accountId|account_id|email)"\s*:',
        r'"(balance|available|equity|frozen|locked)"\s*:',
        r"bg_[0-9a-f]{20,}",
        r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
    )
]


def scan_text(text: str) -> list[str]:
    return [pattern.pattern for pattern in SECRET_PATTERNS if pattern.search(text)]


def scan_tree(directory: Path) -> dict[str, list[str]]:
    hits = {}
    for path in sorted(directory.rglob("*")):
        if path.is_file() and path.suffix != ".md":
            found = scan_text(path.read_text(encoding="utf-8", errors="replace"))
            if found:
                hits[str(path.relative_to(directory))] = found
    return hits


def publish(source: Path, out_root: Path) -> Path:
    rows = Ledger(source / "ledger.jsonl").verify()
    target = out_root / source.name
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    shutil.copy2(source / "ledger.jsonl", target / "ledger.jsonl")
    shutil.copy2(source / "config.json", target / "config.json")
    withheld = []
    for row in rows:
        payload = row["payload"]
        if row["kind"] != "capture_attempt" or not payload.get("body"):
            continue
        name = Path(payload["body"]).name
        body = (source / name).read_bytes()
        if hashlib.sha256(body).hexdigest() != payload["body_sha256"]:
            raise SystemExit(f"body hash mismatch: {name}")
        if payload["endpoint"] in PUBLISHED_ENDPOINTS and not scan_text(body.decode("utf-8", errors="replace")):
            (target / name).write_bytes(body)
        else:
            reason = ("authenticated, account-scoped route" if payload["endpoint"] in WITHHELD_ENDPOINTS
                      else "failed secret scan")
            withheld.append((name, payload["body_sha256"], reason))
    lines = [
        "# Withheld bodies",
        "",
        "These capture bodies are not published. Their SHA-256 values are also in `ledger.jsonl`,",
        "so the hash chain still verifies. None of them feeds `capture_summary.json`.",
        "",
        "| Body | SHA-256 | Reason |",
        "|---|---|---|",
        *[f"| `{name}` | `{digest}` | {reason} |" for name, digest, reason in withheld],
        "",
    ]
    (target / "WITHHELD.md").write_text("\n".join(lines), encoding="utf-8")
    hits = scan_tree(target)
    if hits:
        shutil.rmtree(target)
        raise SystemExit(f"secret scan failed: {hits}")
    return target


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("capture_dir", type=Path)
    parser.add_argument("--out-root", type=Path, default=ROOT / "evidence/costco/raw")
    args = parser.parse_args()
    target = publish(args.capture_dir, args.out_root.resolve())
    print(f"published {sum(1 for _ in target.iterdir())} files to {target.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
