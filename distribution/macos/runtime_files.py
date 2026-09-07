"""Copy only application, interpreter and declared dependency files."""

from __future__ import annotations

import importlib.metadata
import shutil
import sys
import sysconfig
import tomllib
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

QT_MODULES = {
    "QtCore", "QtGui", "QtWidgets", "QtSvg", "QtSvgWidgets", "QtPrintSupport",
    "QtXml", "QtNetwork", "QtDBus", "QtOpenGL", "QtOpenGLWidgets", "QtTest",
}


def trim_unused_qt(site: Path) -> None:
    """Keep the native Widgets stack used by Veusz; no QML/multimedia editor."""
    pyqt = site / "PyQt6"
    for path in pyqt.glob("Qt*.so"):
        if path.name.split(".")[0] not in QT_MODULES:
            path.unlink()
    qml = pyqt / "Qt6" / "qml"
    if qml.exists():
        shutil.rmtree(qml)
    plugins = pyqt / "Qt6" / "plugins"
    for path in plugins.iterdir():
        if path.name not in {"platforms", "imageformats", "iconengines", "styles", "tls"}:
            shutil.rmtree(path)
    for path in (pyqt / "Qt6" / "lib").glob("Qt*.framework"):
        if path.stem not in QT_MODULES:
            shutil.rmtree(path)


def remove_install_location_metadata(site: Path) -> None:
    """Do not disclose editable checkout or temporary wheel-build locations."""
    for path in site.glob("*.dist-info/direct_url.json"):
        path.unlink()


def dependency_inventory(repo: Path) -> list[dict[str, str]]:
    """Resolve installed runtime requirements, including their selected extras."""
    config = tomllib.loads((repo / "pyproject.toml").read_text())
    project = config["project"]
    pending = [
        *project["dependencies"],
        *project["optional-dependencies"]["studio"],
        *project["optional-dependencies"].get("mcp", []),
        "matplotlib",  # Used by the vendored Veusz export/runtime.
        "setuptools",  # Preserve the installed runtime's metadata support.
    ]
    found: dict[str, dict[str, str]] = {}
    visited: set[tuple[str, tuple[str, ...]]] = set()
    while pending:
        requirement = Requirement(pending.pop())
        key = canonicalize_name(requirement.name)
        extras = tuple(sorted(requirement.extras))
        if (key, extras) in visited:
            continue
        visited.add((key, extras))
        distribution = importlib.metadata.distribution(requirement.name)
        if requirement.specifier and distribution.version not in requirement.specifier:
            raise ValueError(f"Installed dependency violates {requirement}")
        found[key] = {"name": distribution.metadata["Name"], "version": distribution.version}
        for text in distribution.requires or ():
            child = Requirement(text)
            if child.marker is None or any(
                child.marker.evaluate({"extra": extra}) for extra in ("", *extras)
            ):
                pending.append(text)
    return [found[key] for key in sorted(found)]


def _copy_tree(source: Path, target: Path) -> None:
    shutil.copytree(
        source,
        target,
        symlinks=False,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.egg-info", ".DS_Store", ".git"),
    )


def copy_runtime(repo: Path, resources: Path) -> tuple[dict[Path, Path], list[dict[str, str]]]:
    """Return original-to-bundled roots for native dependency relocation."""
    runtime = resources / "runtime"
    version = f"python{sys.version_info.major}.{sys.version_info.minor}"
    stdlib = Path(sysconfig.get_path("stdlib")).resolve()
    bundled_stdlib = runtime / "lib" / version
    shutil.copytree(
        stdlib,
        bundled_stdlib,
        symlinks=False,
        ignore=shutil.ignore_patterns("site-packages", "__pycache__", "*.pyc", "test", "idlelib"),
    )
    framework_executable = Path(sys.base_prefix) / "Resources/Python.app/Contents/MacOS/Python"
    # A framework's bin/python is a launcher which respawns Python.app by path.
    # Embed the actual interpreter so no framework layout or host path is needed.
    executable = framework_executable.resolve() if framework_executable.is_file() else Path(sys.executable).resolve()
    bundled_python = runtime / "bin" / "python3"
    bundled_python.parent.mkdir(parents=True)
    shutil.copy2(executable, bundled_python)
    roots = {stdlib: bundled_stdlib, executable: bundled_python}
    site = bundled_stdlib / "site-packages"
    site.mkdir()
    inventory = dependency_inventory(repo)
    copied: set[Path] = set()
    for item in inventory:
        distribution = importlib.metadata.distribution(item["name"])
        location = Path(distribution.locate_file("")).resolve()
        for file in distribution.files or ():
            if not file.parts or file.parts[0] in {"..", "."}:
                continue
            source = location / file.parts[0]
            if source in copied or not source.exists() or source.suffix == ".pth":
                continue
            copied.add(source)
            target = site / source.name
            if source.is_dir():
                _copy_tree(source, target)
            else:
                shutil.copy2(source, target)
            roots[source.resolve()] = target
    trim_unused_qt(site)
    own_distribution = importlib.metadata.distribution("sciplot-core")
    for file in own_distribution.files or ():
        if file.parts and file.parts[0].endswith(".dist-info"):
            metadata = Path(own_distribution.locate_file(file.parts[0]))
            _copy_tree(metadata, site / metadata.name)
            break
    remove_install_location_metadata(site)
    app = resources / "app"
    _copy_tree(repo / "src", app / "src")
    _copy_tree(repo / "skill", app / "skill")
    vendor = repo / "third_party" / "veusz"
    _copy_tree(vendor / "veusz", app / "third_party" / "veusz" / "veusz")
    for name in ("icons", "ui", "translation", "src"):
        _copy_tree(vendor / name, app / "third_party" / "veusz" / name)
    for name in ("COPYING", "AUTHORS", "VERSION", "setup.py", "setup.cfg", "pyproject.toml", "install_data.py", "pyqt_setuptools.py"):
        source = vendor / name
        if source.is_file():
            shutil.copy2(source, app / "third_party" / "veusz" / name)
    roots[vendor.resolve()] = app / "third_party" / "veusz"
    for name in ("pyproject.toml", "README.md"):
        shutil.copy2(repo / name, app / name)
    notices = app / "docs"
    notices.mkdir()
    shutil.copy2(repo / "docs" / "THIRD_PARTY_NOTICES.md", notices)
    for parent in executable.parents:
        license_path = parent / "LICENSE"
        if license_path.is_file():
            licenses = resources / "licenses"
            licenses.mkdir(exist_ok=True)
            shutil.copy2(license_path, licenses / "Python-LICENSE")
            break
    # Do not ship editable .pth files, user configuration, raw data or test fixtures.
    return roots, inventory
