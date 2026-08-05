#!/usr/bin/env python3
"""CI guard: datasets, weights, feature banks, and generated artifacts stay local."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

MAX_TRACKED_BYTES = 10 * 1024 * 1024
FORBIDDEN_PARTS = {".data", ".cache", ".artifacts", "models"}
FORBIDDEN_SUFFIXES = {".pt", ".pth", ".ckpt", ".onnx", ".bin", ".safetensors"}


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    tracked = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"], check=True, capture_output=True
    ).stdout.decode().split("\0")
    violations: list[str] = []
    for raw in tracked:
        if not raw:
            continue
        path = root / raw
        parts = set(path.parts)
        if parts & FORBIDDEN_PARTS or path.suffix.lower() in FORBIDDEN_SUFFIXES:
            violations.append(f"forbidden tracked artifact: {raw}")
        if path.is_file() and path.stat().st_size > MAX_TRACKED_BYTES:
            violations.append(f"tracked file exceeds {MAX_TRACKED_BYTES} bytes: {raw}")
    if violations:
        print("\n".join(violations), file=sys.stderr)
        return 1
    print("tracked artifact guard passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
