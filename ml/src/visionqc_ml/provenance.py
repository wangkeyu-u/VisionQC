"""Runtime, source-control, and hardware provenance helpers."""

from __future__ import annotations

import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any


def git_commit(repository_root: Path) -> str:
    """Return the current commit plus a dirty marker without mutating Git state."""
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repository_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain", "--", "ml"],
            cwd=repository_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        return f"{commit}-dirty" if dirty else commit
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def runtime_environment() -> dict[str, Any]:
    """Collect reproducibility-relevant host metadata without secrets."""
    result: dict[str, Any] = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor() or "unknown",
        "cpu_count": os.cpu_count(),
    }
    try:
        import torch

        result["torch"] = torch.__version__
        result["cuda_available"] = torch.cuda.is_available()
        result["mps_available"] = bool(hasattr(torch.backends, "mps") and torch.backends.mps.is_available())
        if torch.cuda.is_available():
            result["cuda_device"] = torch.cuda.get_device_name(0)
    except ImportError:
        result["torch"] = "not-installed"
    try:
        import anomalib

        result["anomalib"] = anomalib.__version__
    except ImportError:
        result["anomalib"] = "not-installed"
    return result

