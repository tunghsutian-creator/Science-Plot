from __future__ import annotations

import sys
from pathlib import Path


def legacy_root() -> Path:
    return Path(__file__).resolve().parent / "_vendor"


def ensure_legacy_core() -> Path:
    root = legacy_root()
    root_text = str(root)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)
    return root


__all__ = ["ensure_legacy_core", "legacy_root"]
