from __future__ import annotations

import os
import sys
import tempfile
import threading
from pathlib import Path

from sciplot_core._paths import REPO_ROOT, RUNTIME_REPO_ROOT


def bundled_qt_library() -> Path | None:
    """Prefer an explicit Qt library, then the ignored local Mac runtime."""

    configured = os.environ.get("SCIPLOT_BUNDLED_QT_LIB")
    if configured:
        directory = Path(configured)
        if not directory.is_dir():
            raise ValueError("The bundled Qt library directory is missing; repair this installation.")
        return directory
    runtime_repo = Path(os.environ.get("SCIPLOT_RUNTIME_REPO") or RUNTIME_REPO_ROOT)
    local = runtime_repo / ".local/runtime/qt/lib"
    return local if sys.platform == "darwin" and local.is_dir() else None


def configure_qt_loader_environment(
    env: dict[str, str], framework_paths: list[Path], *, bundled: bool,
) -> None:
    """Select Qt before launch without losing a relocated framework Python."""

    if not framework_paths:
        return
    joined = os.pathsep.join(str(path) for path in framework_paths)
    if bundled:
        frameworks = [joined]
        executable = str(Path(sys.executable).resolve())
        marker = "/Python.framework/Versions/"
        if sys.platform == "darwin" and marker in executable:
            root, relative = executable.split(marker, 1)
            version = relative.split("/", 1)[0]
            if (Path(root) / "Python.framework/Versions" / version / "Python").is_file():
                frameworks.insert(0, root)
        env["SCIPLOT_BUNDLED_QT_LIB"] = str(framework_paths[0])
        env["DYLD_FRAMEWORK_PATH"] = os.pathsep.join(frameworks)
    else:
        current = env.get("DYLD_FRAMEWORK_PATH")
        env["DYLD_FRAMEWORK_PATH"] = f"{joined}{os.pathsep}{current}" if current else joined
    env["SCIPLOT_STUDIO_QT_RUNTIME"] = "1"


def veusz_worker_environment() -> dict[str, str]:
    """Return the minimal environment for an offscreen vendored Veusz export."""

    env = os.environ.copy()
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    env.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "sciplot-mpl"))
    framework_paths = [
        Path("/opt/homebrew/opt/qtbase/lib"),
        Path("/opt/homebrew/opt/qt/lib"),
    ]
    bundled = bundled_qt_library()
    existing = [bundled] if bundled else [path for path in framework_paths if path.exists()]
    configure_qt_loader_environment(env, existing, bundled=bundled is not None)
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
