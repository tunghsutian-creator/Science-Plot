from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

from sciplot_gui import studio_project
from sciplot_gui import studio_project_status


class _Document:
    changeset = 7

    def isModified(self) -> bool:
        return False


def test_status_module_has_no_qt_import() -> None:
    module_path = Path(studio_project_status.__file__).resolve()
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    imported_roots = {
        alias.name.partition(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported_roots.update(
        (node.module or "").partition(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    )
    assert "PyQt6" not in imported_roots
    assert "veusz" not in imported_roots


def test_status_export_aliases_use_the_shared_contract() -> None:
    assert studio_project_status._normalized_export_format("png") == "png_300"
    assert studio_project_status._normalized_export_format("tif_300") == "tiff_300"
    assert studio_project_status._normalized_export_format("tiff300") == "tiff_300"
    assert studio_project_status._normalized_export_format("unknown") == ""


def test_qt_bridge_delegates_to_pure_status_builders(tmp_path: Path) -> None:
    document_path = tmp_path / "document.vsz"
    document_path.write_text("# minimal test document\n", encoding="utf-8")
    expected = studio_project_status.build_studio_project_status(
        document_path=document_path,
        document=_Document(),
        project_dir=None,
        request_path=None,
    )
    actual = studio_project.build_studio_project_status(
        document_path=document_path,
        document=_Document(),
        project_dir=None,
        request_path=None,
    )
    assert actual == expected
    assert studio_project.export_result_message is (
        studio_project_status.export_result_message
    )


def test_qt_bridge_injects_the_live_figure_scope_builder(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    project_dir = tmp_path / "project"
    document_path = project_dir / "studio" / "document.vsz"
    request_path = project_dir / "plot_request.json"
    document_path.parent.mkdir(parents=True)
    document_path.write_text("# minimal test document\n", encoding="utf-8")
    request_path.write_text(
        json.dumps({"input": "missing.csv"}),
        encoding="utf-8",
    )
    calls: list[tuple[Path, dict[str, Any], dict[str, Any]]] = []

    def _resolver(
        *,
        project_dir: Path,
        request: dict[str, Any],
        latest_run: dict[str, Any],
    ) -> tuple[None, str]:
        calls.append((project_dir, request, latest_run))
        return None, "not_applicable"

    monkeypatch.setattr(
        studio_project,
        "_resolve_figure_set_export_scope",
        _resolver,
    )
    status = studio_project.build_studio_project_status(
        document_path=document_path,
        document=_Document(),
        project_dir=project_dir,
        request_path=request_path,
    )
    assert len(calls) == 1
    assert calls[0][0] == project_dir.resolve()
    assert status["provenance"]["figure_set_export_scope_status"] == ("not_applicable")
