from __future__ import annotations

import os
import sys
import tempfile
import threading
from pathlib import Path

from sciplot_core._paths import REPO_ROOT


def veusz_worker_environment() -> dict[str, str]:
    """Return the minimal environment for an offscreen vendored Veusz export."""

    env = os.environ.copy()
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    env.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "sciplot-mpl"))
    framework_paths = [
        Path("/opt/homebrew/opt/qtbase/lib"),
        Path("/opt/homebrew/opt/qt/lib"),
    ]
    bundled = env.get("SCIPLOT_BUNDLED_QT_LIB")
    if bundled and not Path(bundled).is_dir():
        raise ValueError("The bundled Qt library directory is missing; repair this installation.")
    existing = [bundled] if bundled else [str(path) for path in framework_paths if path.exists()]
    if existing:
        joined = ":".join(existing)
        for key in ("DYLD_FRAMEWORK_PATH", "DYLD_LIBRARY_PATH"):
            current = env.get(key)
            env[key] = joined if bundled else (f"{joined}:{current}" if current else joined)
        env["SCIPLOT_STUDIO_QT_RUNTIME"] = "1"
    source_root = os.environ.get("SCIPLOT_SOURCE_ROOT") or str(REPO_ROOT / "src")
    python_path = env.get("PYTHONPATH")
    env["PYTHONPATH"] = f"{source_root}:{python_path}" if python_path else source_root
    return env


def needs_veusz_worker_process() -> bool:
    """Keep Qt work on a process main thread and load macOS Qt at startup."""

    return threading.current_thread() is not threading.main_thread() or (
        sys.platform == "darwin" and os.environ.get("SCIPLOT_STUDIO_QT_RUNTIME") != "1"
    )


__all__ = ["needs_veusz_worker_process", "veusz_worker_environment"]
