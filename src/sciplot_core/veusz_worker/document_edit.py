"""Preview and edit saved documents through native Veusz operations only."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from importlib import import_module
from pathlib import Path
from typing import Any

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.native_settings import editable_fields, validate_native_setting


@contextmanager
def loaded_native_document(path: Path) -> Iterator[Any]:
    """Load an exact saved document with unsafe commands and imports disabled."""
    from sciplot_core.studio_core.runtime import ensure_veusz_runtime_path
    from sciplot_core.studio_core.qt_compat import ensure_veusz_loader_compat

    ensure_veusz_runtime_path()
    ensure_veusz_loader_compat()
    from PyQt6 import QtWidgets
    import_module("veusz.dataimport")
    import_module("veusz.widgets")
    document = import_module("veusz.document")
    existing_app = QtWidgets.QApplication.instance()
    app = existing_app or QtWidgets.QApplication([])
    try:
        loaded = document.Document()
        loaded.load(str(path), callbackunsafe=lambda: False,
                    callbackimporterror=lambda *_args: False)
        yield loaded
    finally:
        if existing_app is None:
            app.quit()


def _preview(loaded: Any, path: Path) -> dict[str, Any]:
    from PyQt6.QtGui import QImage
    CommandInterface = import_module("veusz.document").CommandInterface

    if path.suffix.lower() != ".png":
        raise ValueError("The preview output must be a PNG file.")
    path.parent.mkdir(parents=True, exist_ok=True)
    CommandInterface(loaded).Export(str(path), page=[0], dpi=150, backcolor="white")
    image = QImage(str(path))
    if image.isNull():
        raise ValueError("Native preview rendering did not produce a valid image.")
    return {"path": str(path), "sha256": file_sha256(path),
            "width": image.width(), "height": image.height()}


def _identity(path: Path) -> dict[str, str]:
    return {"path": str(path), "sha256": file_sha256(path)}


def preview_document(document_path: Path, *, output_png: Path) -> dict[str, Any]:
    path, png = document_path.expanduser().resolve(), output_png.expanduser().resolve()
    identity = _identity(path)
    if png == path:
        raise ValueError("A preview cannot overwrite its source document.")
    with loaded_native_document(path) as loaded:
        preview = _preview(loaded, png)
    if file_sha256(path) != identity["sha256"]:
        raise ValueError("The source document changed during native preview.")
    return {"kind": "sciplot_document_preview", "version": 1, "status": "passed",
            "document": identity, "preview": preview}


def prepare_setting_batch(
    loaded: Any, changes: Any,
) -> tuple[list[Any], list[dict[str, Any]]]:
    """Validate the whole batch before constructing one native Undo operation."""
    OperationSettingSet = import_module("veusz.document.operations").OperationSettingSet

    if not isinstance(changes, list) or not 1 <= len(changes) <= 100:
        raise ValueError("Provide between 1 and 100 explicit setting changes.")
    native, actual = [], []
    seen: set[str] = set()
    for change in changes:
        if not isinstance(change, dict) or set(change) != {
            "object_path", "setting_path", "expected_value", "value",
        }:
            raise ValueError("Each change needs object_path, setting_path, expected_value and value.")
        object_path, setting_path = change["object_path"], change["setting_path"]
        if not all(isinstance(path, str) and path.startswith("/")
                   for path in (object_path, setting_path)):
            raise ValueError("Object and setting paths must be absolute native paths.")
        if setting_path in seen:
            raise ValueError("A batch cannot change the same setting twice.")
        seen.add(setting_path)
        widget = loaded.resolveWidgetPath(None, object_path)
        if str(widget.path) != object_path:
            raise ValueError("Use the canonical object path from document inspection.")
        capabilities = editable_fields(loaded, widget, safe_only=True)
        capability = next((field for field in capabilities
                           if field["setting_path"] == setting_path), None)
        if capability is None:
            raise ValueError(f"{setting_path} is outside the advertised safe setting catalog.")
        current, normalized = validate_native_setting(
            loaded, capability, expected_value=change["expected_value"],
            value=change["value"], safe_only=True,
        )
        native.append(OperationSettingSet(setting_path, normalized))
        actual.append({"object_path": object_path, "setting_path": setting_path,
                       "old_value": current, "new_value": json_safe(normalized)})
    return native, actual


def edit_document(
    document_path: Path, changes: Any, *, output_document: Path, preview_png: Path,
) -> dict[str, Any]:
    """Write an isolated candidate; publishing and science audit belong to its caller."""
    path = document_path.expanduser().resolve()
    candidate, png = output_document.expanduser().resolve(), preview_png.expanduser().resolve()
    if candidate == path or png in {path, candidate}:
        raise ValueError("Candidate and preview must be separate from the source document.")
    if candidate.suffix.lower() != ".vsz" or png.suffix.lower() != ".png":
        raise ValueError("Use a VSZ candidate and PNG preview output.")
    if candidate.exists() or png.exists():
        raise ValueError("Candidate and preview outputs must not already exist.")
    identity = _identity(path)
    with loaded_native_document(path) as loaded:
        CommandInterface = import_module("veusz.document").CommandInterface
        OperationMultiple = import_module("veusz.document.operations").OperationMultiple

        native, actual = prepare_setting_batch(loaded, changes)
        loaded.applyOperation(OperationMultiple(native, descr="SciPlot external style edit"))
        candidate.parent.mkdir(parents=True, exist_ok=True)
        try:
            CommandInterface(loaded).Save(str(candidate))
            preview = _preview(loaded, png)
            if file_sha256(path) != identity["sha256"]:
                raise ValueError("The source document changed during native editing.")
        except Exception:
            candidate.unlink(missing_ok=True)
            png.unlink(missing_ok=True)
            raise
    return {"kind": "sciplot_document_edit", "version": 1, "status": "passed",
            "document": identity, "candidate": _identity(candidate),
            "changes": actual, "preview": preview}
