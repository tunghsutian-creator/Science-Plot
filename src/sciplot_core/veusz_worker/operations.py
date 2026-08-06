"""Run export, document audit, state inspection, and label migration operations."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.terminal_source_binding_wire import (
    consume_terminal_source_binding_environment,
)
from sciplot_core.veusz_worker.widget_bindings import (
    _settings_snapshot,
)


def export_request(request_path: Path, *, formats: list[str]) -> dict[str, Any]:
    """Compile one request to VSZ, then export through the production renderer."""

    from sciplot_core.studio_core.export_execution import export_studio_document
    from sciplot_core.studio_core.studio_prepare import prepare_studio_document

    resolved_request = request_path.expanduser().resolve()
    terminal_source_binding = consume_terminal_source_binding_environment(
        resolved_request
    )
    payload = (
        prepare_studio_document(
            resolved_request,
            _terminal_source_binding=terminal_source_binding,
        )
        if terminal_source_binding is not None
        else prepare_studio_document(resolved_request)
    )
    document_path = Path(str(payload["document"]))
    export_payload = export_studio_document(document_path, formats=formats)
    payload["exports"] = export_payload["exports"]
    return payload


def export_document(
    document_path: Path,
    *,
    formats: list[str],
    output_dir: Path | None = None,
) -> dict[str, Any]:
    """Export the exact current VSZ without regenerating it."""

    from sciplot_core.studio_core.export_execution import export_studio_document

    return export_studio_document(
        document_path.expanduser().resolve(),
        formats=formats,
        output_dir=output_dir.expanduser().resolve()
        if output_dir is not None
        else None,
    )


def audit_documents(document_paths: list[Path]) -> dict[str, Any]:
    """Inspect exact current VSZ state through Veusz without rewriting it."""

    from PyQt6 import QtWidgets

    from sciplot_core.studio_core.qt_compat import ensure_veusz_loader_compat
    from sciplot_core.studio_core.runtime import ensure_veusz_runtime_path

    ensure_veusz_runtime_path()
    from veusz import dataimport, document, widgets

    _ = dataimport, document, widgets
    ensure_veusz_loader_compat()
    existing_app = QtWidgets.QApplication.instance()
    app = existing_app or QtWidgets.QApplication([])
    try:
        from sciplot_core.veusz_audit import audit_veusz_documents

        return audit_veusz_documents(
            [path.expanduser().resolve() for path in document_paths]
        )
    finally:
        if existing_app is None:
            app.quit()


def inspect_document_state(document_path: Path) -> dict[str, Any]:
    """Reopen one VSZ and materialize its widget setting state."""

    from PyQt6 import QtWidgets

    from sciplot_core.studio_core.qt_compat import ensure_veusz_loader_compat
    from sciplot_core.studio_core.runtime import ensure_veusz_runtime_path

    resolved_document = document_path.expanduser().resolve()
    if not resolved_document.is_file():
        raise FileNotFoundError(f"Veusz document not found: {resolved_document}")
    ensure_veusz_runtime_path()
    existing_app = QtWidgets.QApplication.instance()
    app = existing_app or QtWidgets.QApplication([])
    try:
        ensure_veusz_loader_compat()
        from veusz import dataimport, document, widgets

        _ = dataimport, widgets
        loaded_document = document.Document()
        loaded_document.load(str(resolved_document))
        materialized_widgets: dict[str, dict[str, Any]] = {}

        def collect(path: str, node: Any) -> None:
            materialized_widgets[str(path)] = {
                "name": str(getattr(node, "name", "")),
                "type": str(getattr(node, "typename", "")),
                "settings": _settings_snapshot(getattr(node, "settings", None)),
            }

        loaded_document.walkNodes(collect, nodetypes=("widget",))
        return {
            "kind": "sciplot_veusz_document_state",
            "version": 1,
            "status": "passed",
            "document": {
                "path": str(resolved_document),
                "sha256": file_sha256(resolved_document),
            },
            "widgets": materialized_widgets,
            "widget_count": len(materialized_widgets),
        }
    finally:
        if existing_app is None:
            app.quit()


def migrate_unit_labels(document_path: Path) -> dict[str, Any]:
    """Apply the global unit-expression contract to one exact-current VSZ."""

    from sciplot_core.studio_core.persistence import (
        migrate_studio_document_unit_labels,
    )

    return migrate_studio_document_unit_labels(document_path.expanduser().resolve())
