from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from sciplot_core._paths import VENDORED_CORE_ROOT


def legacy_root() -> Path:
    return VENDORED_CORE_ROOT


def ensure_legacy_core() -> Path:
    fallback_config = Path(tempfile.gettempdir()) / "sciplot-mpl"
    matplotlib_config = Path(os.environ.get("MPLCONFIGDIR") or fallback_config)
    try:
        matplotlib_config.mkdir(parents=True, exist_ok=True)
    except OSError:
        matplotlib_config = fallback_config
        matplotlib_config.mkdir(parents=True, exist_ok=True)
    os.environ["MPLCONFIGDIR"] = str(matplotlib_config)
    root = legacy_root()
    root_text = str(root)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)
    return root


__all__ = ["ensure_legacy_core", "legacy_root"]
