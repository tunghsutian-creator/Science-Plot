"""Check Python, Qt, Veusz, and publication foundations."""

from __future__ import annotations

import ast
import importlib.util
import sys
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
        from veusz.helpers import qtloops  # noqa: F401
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"
    return (
        True,
        f"PyQt {QtCore.PYQT_VERSION_STR}; Qt runtime {QtCore.qVersion()}; Veusz qtloops loaded",
    )


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
    except Exception:
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
