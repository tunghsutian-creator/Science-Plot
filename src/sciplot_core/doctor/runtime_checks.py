"""Check Python, Qt, Veusz, and publication foundations."""

from __future__ import annotations

import ast
import importlib
import importlib.util
import os
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from sciplot_core._paths import REPO_ROOT, VEUSZ_ROOT
from sciplot_core.publication import (
    get_publication_profile,
)


def _check(
    check_id: str, label: str, passed: bool, *, required: bool = True, detail: str = ""
) -> dict[str, Any]:
    return {
        "id": check_id,
        "label": label,
        "status": "passed" if passed else "failed",
        "required": required,
        "detail": detail,
    }


def _module_available(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def _veusz_qt_runtime_status() -> tuple[bool, str]:
    if not _module_available("PyQt6"):
        return False, "PyQt6 is not importable."
    veusz_root = str(VEUSZ_ROOT)
    if veusz_root not in sys.path:
        sys.path.insert(0, veusz_root)
    try:
        from PyQt6 import QtCore, QtGui, QtWidgets  # noqa: F401
    except Exception as exc:  # noqa: BLE001 - Report any Qt runtime-load failure.
        return False, f"PyQt6/Qt runtime cannot load: {type(exc).__name__}: {exc}"
    helpers = ("qtloops", "qtmml", "recordpaint", "threed", "_nc_cntr")
    for name in helpers:
        try:
            importlib.import_module("veusz.helpers." + name)
        except Exception as exc:  # noqa: BLE001 - Report every native-load failure.
            helper = VEUSZ_ROOT / "veusz" / "helpers" / name
            built = any(
                candidate.is_file() and candidate.suffix in {".so", ".pyd"}
                for candidate in helper.parent.glob(name + "*")
            )
            if not built:
                return False, (
                    f"Vendored Veusz {name} compiled helper is absent under {helper.parent}; "
                    f"import failed: {type(exc).__name__}: {exc}"
                )
            return False, (
                f"Vendored Veusz {name} compiled helper is present but cannot load "
                f"in this Python/PyQt6/Qt runtime: {type(exc).__name__}: {exc}"
            )
    return (
        True,
        f"PyQt {QtCore.PYQT_VERSION_STR}; Qt runtime {QtCore.qVersion()}; "
        f"Veusz native helpers loaded: {', '.join(helpers)}",
    )


def _qt_build_prerequisite_status(*, needed: bool) -> tuple[bool, str]:
    """Describe source-build tools only when the native helper cannot load."""

    if not needed:
        return True, "Compiled Veusz Qt helper loads; a build toolchain is not needed for use."
    qmake = shutil.which(os.environ.get("QMAKE_EXE") or "qmake-qt6")
    if qmake is None and not os.environ.get("QMAKE_EXE"):
        qmake = shutil.which("qmake6") or shutil.which("qmake")
    sip_build = shutil.which("sip-build")
    compiler = shutil.which("c++") or shutil.which("g++") or shutil.which("clang++")
    problems: list[str] = []
    if qmake is None:
        problems.append("Qt 6 qmake is absent (qmake-qt6/qmake6/qmake or QMAKE_EXE)")
    else:
        try:
            query = subprocess.run(
                [qmake, "-query", "QT_VERSION"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            problems.append(f"qmake at {qmake} cannot run: {type(exc).__name__}: {exc}")
        else:
            version = query.stdout.strip()
            if query.returncode != 0 or not version.startswith("6."):
                reason = query.stderr.strip() or version or f"exit {query.returncode}"
                problems.append(f"qmake at {qmake} does not report Qt 6: {reason}")
    if sip_build is None:
        problems.append("sip-build is absent from PATH")
    if compiler is None:
        problems.append("a C++ compiler is absent from PATH")
    if problems:
        return False, "; ".join(problems) + ". Needed only to build the vendored Qt helper."
    return True, (
        f"Qt 6 qmake ({qmake}), sip-build ({sip_build}), and C++ compiler "
        f"({compiler}) found for a source build; this does not prove the helper compiles."
    )


def _local_socket_status() -> tuple[bool, str]:
    """Probe the local plot-engine transport without contacting a service."""

    if not hasattr(socket, "AF_UNIX"):
        return False, "AF_UNIX is unavailable on this platform; local plot-engine transport needs it."
    try:
        with tempfile.TemporaryDirectory(prefix="sp-doctor-") as temporary:
            path = Path(temporary) / "s"
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
                    listener.bind(str(path))
                    listener.listen(1)
            except PermissionError as exc:
                return False, (
                    f"AF_UNIX socket creation/bind denied by OS or sandbox "
                    f"(errno {exc.errno}: {exc.strerror}); no SciPlot service was contacted."
                )
            except OSError as exc:
                return False, (
                    f"AF_UNIX local socket creation/bind failed "
                    f"({type(exc).__name__}, errno {exc.errno}: {exc.strerror}); "
                    "no SciPlot service was contacted."
                )
    except OSError as exc:
        return False, f"Cannot create private socket probe directory: {type(exc).__name__}: {exc}"
    return True, "AF_UNIX local socket creation/bind succeeded; no service was contacted."


def _top_level_symbols(path: Path) -> set[str]:
    """Read a module or package facade without importing its runtime graph."""

    contract_path = path / "__init__.py" if path.is_dir() else path
    try:
        tree = ast.parse(
            contract_path.read_text(encoding="utf-8"),
            filename=str(contract_path),
        )
    except (OSError, UnicodeError, SyntaxError):
        return set()
    symbols = {
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
    }
    symbols.update(
        alias.asname or alias.name
        for node in tree.body
        if isinstance(node, ast.ImportFrom | ast.Import)
        for alias in node.names
    )
    return symbols


def _vsz_lifecycle_available() -> bool:
    studio_symbols = _top_level_symbols(
        REPO_ROOT / "src" / "sciplot_core" / "studio.py"
    )
    delivery_symbols = _top_level_symbols(
        REPO_ROOT / "src" / "sciplot_core" / "delivery"
    )
    return {
        "prepare_studio_document",
        "export_studio_document",
        "publish_studio_export_run",
        "_studio_document_state",
        "_archive_manual_document_if_needed",
    }.issubset(studio_symbols) and "build_delivery_package" in delivery_symbols


def _publication_foundation_available() -> bool:
    """Check the active single-panel publication and QA contract."""

    try:
        profile = get_publication_profile("sciplot_single_panel_v1")
    except Exception:  # noqa: BLE001 - A broken profile is a failed readiness check.
        return False
    publication_symbols = _top_level_symbols(
        REPO_ROOT / "src" / "sciplot_core" / "publication"
    )
    qa_symbols = _top_level_symbols(REPO_ROOT / "src" / "sciplot_core" / "qa")
    return (
        profile.get("id") == "sciplot_single_panel_v1"
        and profile.get("required_formats") == ["pdf", "tiff_300"]
        and profile.get("integrity", {}).get("scientific_outcome_agnostic") is True
        and profile.get("integrity", {}).get("significance_required") is False
        and {
            "build_publication_intent",
            "build_transform_ledger",
            "write_publication_artifacts",
        }.issubset(publication_symbols)
        and "run_qa" in qa_symbols
    )
