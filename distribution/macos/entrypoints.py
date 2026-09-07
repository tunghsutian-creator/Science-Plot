"""Generate portable CLI and Finder entrypoints without changing host settings."""

from __future__ import annotations

import plistlib
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path


def write_executable(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)


def write_entrypoints(app: Path, version: str) -> None:
    contents = app / "Contents"
    resources = contents / "Resources"
    script = r'''#!/bin/bash
set -euo pipefail
BUNDLE_RESOURCES="$(cd -- "$(dirname -- "$0")/../Resources" && pwd)"
export PYTHONHOME="$BUNDLE_RESOURCES/runtime"
export PYTHONNOUSERSITE=1
export PYTHONDONTWRITEBYTECODE=1
export SCIPLOT_REPO="$BUNDLE_RESOURCES/app"
export SCIPLOT_RUNTIME_REPO="$SCIPLOT_REPO"
export SCIPLOT_SOURCE_ROOT="$SCIPLOT_REPO/src"
export SCIPLOT_VEUSZ_ROOT="$SCIPLOT_REPO/third_party/veusz"
export VEUSZ_RESOURCE_DIR="$SCIPLOT_VEUSZ_ROOT"
export SCIPLOT_PYTHON="$BUNDLE_RESOURCES/runtime/bin/python3"
export PYTHONPATH="$SCIPLOT_SOURCE_ROOT:$SCIPLOT_VEUSZ_ROOT"
SCIPLOT_SITE="$BUNDLE_RESOURCES/runtime/lib/pythonVERSION/site-packages"
export SCIPLOT_BUNDLED_QT_LIB="$SCIPLOT_SITE/PyQt6/Qt6/lib"
export QT_PLUGIN_PATH="$SCIPLOT_SITE/PyQt6/Qt6/plugins"
export DYLD_FRAMEWORK_PATH="$SCIPLOT_BUNDLED_QT_LIB"
export DYLD_LIBRARY_PATH="$SCIPLOT_BUNDLED_QT_LIB"
export SCIPLOT_STUDIO_QT_RUNTIME=1
export PATH="$(dirname -- "$0"):/usr/bin:/bin:/usr/sbin:/sbin"
unset PYTHONSTARTUP PYTHONUSERBASE QT_QPA_PLATFORM_PLUGIN_PATH QML2_IMPORT_PATH || true
if [[ "${1:-}" == "--welcome" ]]; then
  shift
  exec "$SCIPLOT_PYTHON" "$BUNDLE_RESOURCES/welcome.py" "$@"
fi
exec "$SCIPLOT_PYTHON" -m sciplot_core.cli "$@"
'''.replace("pythonVERSION", "python" + version)
    write_executable(contents / "MacOS" / "sciplot", script)
    write_executable(contents / "MacOS" / "SciPlotLauncher", '''#!/bin/bash
set -euo pipefail
APP_EXECUTABLES="$(cd -- "$(dirname -- "$0")" && pwd)"
exec "$APP_EXECUTABLES/sciplot" --welcome "$@"
''')
    # Doctor and generated delivery launchers retain the public wrapper contract.
    write_executable(resources / "app" / "skill" / "scripts" / "sciplot", '''#!/bin/bash
set -euo pipefail
APP_ROOT="$(cd -- "$(dirname -- "$0")/../.." && pwd)"
exec "$APP_ROOT/../../MacOS/sciplot" "$@"
''')
    with (contents / "Info.plist").open("wb") as stream:
        plistlib.dump({
            "CFBundleName": "SciPlot",
            "CFBundleDisplayName": "SciPlot 本地科研绘图",
            "CFBundleIdentifier": "local.sciplot.desktop",
            "CFBundleVersion": "1",
            "CFBundleShortVersionString": "0.1.0",
            "CFBundleExecutable": "SciPlotLauncher",
            "CFBundlePackageType": "APPL",
            "LSUIElement": True,
            "NSHighResolutionCapable": True,
            **({"LSMinimumSystemVersion": platform.mac_ver()[0]} if platform.mac_ver()[0] else {}),
        }, stream)


def compile_finder_launcher(app: Path) -> None:
    launcher = app / "Contents/MacOS/SciPlotLauncher"
    # Sign the isolated executable; signing it at CFBundleExecutable's path
    # would implicitly attempt to sign the entire (not notarized) app bundle.
    with tempfile.TemporaryDirectory(prefix="sciplot-launcher-") as temporary:
        candidate = Path(temporary) / "SciPlotLauncher"
        subprocess.run([
            "/usr/bin/xcrun", "clang", "-Os", "-Wall", "-Wextra", "-Werror",
            str(Path(__file__).with_name("launcher.c")), "-o", str(candidate),
        ], check=True, capture_output=True)
        subprocess.run(["/usr/bin/codesign", "--force", "--sign", "-", str(candidate)], check=True, capture_output=True)
        shutil.copy2(candidate, launcher)
