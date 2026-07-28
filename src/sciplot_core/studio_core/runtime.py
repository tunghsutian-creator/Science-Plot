"""Resolve Veusz runtime status, environment paths, formats, and subprocess diagnostics."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from sciplot_core._paths import VEUSZ_ROOT, VEUSZ_UPSTREAM_COMMIT
from sciplot_core.policy import (
    canonical_export_format,
    normalize_export_formats,
)


def upstream_status() -> dict[str, Any]:
    return {
        "veusz": {
            "name": "Veusz",
            "path": str(VEUSZ_ROOT),
            "commit": VEUSZ_UPSTREAM_COMMIT,
            "license": "GPL-2.0-or-later",
            "vendored": VEUSZ_ROOT.exists(),
        },
    }


def maybe_reexec_with_qt_runtime(original_argv: list[str]) -> None:
    """Restart on macOS with the Qt framework path set before PyQt imports.

    The vendored Veusz helpers are compiled against Homebrew Qt. macOS must see
    those framework paths when the Python process starts, otherwise PyQt may
    load its bundled QtCore while the helper extensions load Homebrew QtGui.
    """
    if sys.platform != "darwin" or os.environ.get("SCIPLOT_STUDIO_QT_RUNTIME") == "1":
        return
    env = os.environ.copy()
    framework_paths = _qt_framework_paths()
    if not framework_paths:
        return
    joined = ":".join(str(path) for path in framework_paths)
    for key in ("DYLD_FRAMEWORK_PATH", "DYLD_LIBRARY_PATH"):
        current = env.get(key)
        env[key] = f"{joined}:{current}" if current else joined
    env["SCIPLOT_STUDIO_QT_RUNTIME"] = "1"
    os.execvpe(
        sys.executable, [sys.executable, "-m", "sciplot_core.cli", *original_argv], env
    )


def _ensure_veusz_on_path() -> None:
    if VEUSZ_ROOT.exists():
        sys.path.insert(0, str(VEUSZ_ROOT))


@contextmanager
def _capture_process_stderr(log_path: Path):
    if os.environ.get("SCIPLOT_STUDIO_SHOW_QT_WARNINGS") == "1":
        yield None
        return
    log_path.parent.mkdir(parents=True, exist_ok=True)
    original_fd: int | None = None
    try:
        sys.stderr.flush()
        original_fd = os.dup(2)
        with tempfile.TemporaryFile(mode="w+b") as buffer:
            os.dup2(buffer.fileno(), 2)
            try:
                yield log_path
            finally:
                sys.stderr.flush()
                if original_fd is not None:
                    os.dup2(original_fd, 2)
                buffer.seek(0)
                captured = buffer.read()
        if captured.strip():
            log_path.write_bytes(captured)
        elif log_path.exists():
            log_path.unlink()
    finally:
        if original_fd is not None:
            os.close(original_fd)


def _qt_framework_paths() -> list[Path]:
    candidates = [
        Path("/opt/homebrew/opt/qtbase/lib"),
        Path("/opt/homebrew/opt/qt/lib"),
    ]
    if all(path.exists() for path in candidates):
        return candidates
    brew = shutil.which("brew")
    if not brew:
        return [path for path in candidates if path.exists()]
    paths: list[Path] = []
    for package in ("qtbase", "qt"):
        try:
            prefix = subprocess.check_output(
                [brew, "--prefix", package], text=True, stderr=subprocess.DEVNULL
            ).strip()
        except (OSError, subprocess.CalledProcessError):
            continue
        lib_path = Path(prefix) / "lib"
        if lib_path.exists():
            paths.append(lib_path)
    return paths


def _split_formats(value: str) -> list[str]:
    formats = [item for item in value.split(",") if item.strip()]
    return list(normalize_export_formats(formats, default=("pdf",)))


def _normalize_export_format(fmt: str) -> str:
    return canonical_export_format(fmt)


def _export_suffix(fmt: str) -> tuple[str, int | None]:
    normalized = _normalize_export_format(fmt)
    if normalized == "tiff_300":
        return "_300dpi.tiff", 300
    if normalized == "png_300":
        return "_300dpi.png", 300
    if normalized == "png_600":
        return "_600dpi.png", 600
    if normalized == "svg":
        return ".svg", None
    if normalized == "pdf":
        return ".pdf", None
    raise AssertionError(f"Unhandled normalized export format: {normalized}")
