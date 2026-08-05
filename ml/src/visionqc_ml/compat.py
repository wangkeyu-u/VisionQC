"""Narrow compatibility workarounds for pinned third-party runtimes."""

from __future__ import annotations

import importlib
import importlib.machinery
import sys
from itertools import pairwise
from types import ModuleType


class _OVDict(dict[object, object]):
    """Type-only stand-in needed by Anomalib 2.0.0's Torch import path."""


def ensure_anomalib_torch_importable() -> bool:
    """Install a type-only OVDict shim if the optional OpenVINO runtime is unusable.

    Anomalib 2.0.0 imports ``OVDict`` at module import time even for Torch-only
    inference. No OpenVINO behavior is implemented here. Returns ``True`` when
    the shim was required.
    """
    try:
        importlib.import_module("openvino.runtime.utils.data_helpers.wrappers")
        return False
    except (ImportError, OSError):
        for name in list(sys.modules):
            if name == "openvino" or name.startswith("openvino."):
                del sys.modules[name]

    module_names = [
        "openvino",
        "openvino.runtime",
        "openvino.runtime.utils",
        "openvino.runtime.utils.data_helpers",
        "openvino.runtime.utils.data_helpers.wrappers",
    ]
    modules: dict[str, ModuleType] = {}
    for name in module_names:
        module = ModuleType(name)
        is_package = name != module_names[-1]
        module.__spec__ = importlib.machinery.ModuleSpec(name, loader=None, is_package=is_package)
        if is_package:
            module.__path__ = []
        modules[name] = module
        sys.modules[name] = module
    modules[module_names[-1]].OVDict = _OVDict  # type: ignore[attr-defined]
    for parent_name, child_name in pairwise(module_names):
        setattr(modules[parent_name], child_name.rsplit(".", 1)[-1], modules[child_name])
    return True
