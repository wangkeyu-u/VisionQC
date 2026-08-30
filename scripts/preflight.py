#!/usr/bin/env python3
"""Compatibility entry point for ``visionqc.py preflight``."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


if __name__ == "__main__":
    raise SystemExit(
        subprocess.run(
            [
                sys.executable,
                str(Path(__file__).with_name("visionqc.py")),
                "preflight",
                *sys.argv[1:],
            ],
            check=False,
        ).returncode
    )
