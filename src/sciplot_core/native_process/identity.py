"""Byte identities for code and runtime inputs retained by a warm process."""

import hashlib
from importlib import metadata
import json
from pathlib import Path
import sys

from sciplot_core._paths import PACKAGE_ROOT, VEUSZ_ROOT
from sciplot_core.veusz_runtime import veusz_worker_environment


def _files(directory: Path) -> dict[str, str]:
    return {str(path.relative_to(directory)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(directory.rglob("*.py"))}


def _version(package: str) -> str:
    try:
        return metadata.version(package)
    except metadata.PackageNotFoundError:
        return "not-installed"


def current_identity() -> str:
    """Hash actual source bytes each time; timestamps are not an authority."""
    environment = veusz_worker_environment()
    selected_environment = {key: environment.get(key, "") for key in (
        "QT_QPA_PLATFORM", "QT_QPA_FONTDIR", "FONTCONFIG_FILE", "FONTCONFIG_PATH",
        "SCIPLOT_BUNDLED_QT_LIB", "DYLD_FRAMEWORK_PATH", "DYLD_LIBRARY_PATH",
        "SCIPLOT_SOURCE_ROOT", "SCIPLOT_REPO", "SCIPLOT_RUNTIME_REPO", "SCIPLOT_VEUSZ_ROOT", "PYTHONPATH",
    )}
    payload = {"sciplot": _files(PACKAGE_ROOT), "veusz": _files(VEUSZ_ROOT / "veusz"),
               "python": sys.version, "executable": hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest(),
               "installation": str(VEUSZ_ROOT), "environment": selected_environment,
               "versions": {name: _version(name) for name in ("PyQt6", "PyQt6-Qt6", "numpy")}}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
