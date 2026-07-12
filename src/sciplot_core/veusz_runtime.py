from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def veusz_worker_environment() -> dict[str, str]:
    """Return the minimal environment for an offscreen vendored Veusz export."""

    env = os.environ.copy()
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    framework_paths = [Path("/opt/homebrew/opt/qtbase/lib"), Path("/opt/homebrew/opt/qt/lib")]
    existing = [str(path) for path in framework_paths if path.exists()]
    if existing:
        joined = ":".join(existing)
        for key in ("DYLD_FRAMEWORK_PATH", "DYLD_LIBRARY_PATH"):
            current = env.get(key)
            env[key] = f"{joined}:{current}" if current else joined
        env.setdefault("SCIPLOT_STUDIO_QT_RUNTIME", "1")
    source_root = str(REPO_ROOT / "src")
    python_path = env.get("PYTHONPATH")
    env["PYTHONPATH"] = f"{source_root}:{python_path}" if python_path else source_root
    return env


__all__ = ["veusz_worker_environment"]
