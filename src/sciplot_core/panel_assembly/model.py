"""Validated panel layout documents resolved through the central mm solver."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from sciplot_core.plot_document.errors import DocumentError
from sciplot_core.plot_document.validation import validate_wire
from sciplot_core.plot_layout import solve_layout

from .errors import AssemblyError
from .schema import document_schema, operations_schema


def _validate(value: Any, schema: dict[str, Any]) -> None:
    try:
        validate_wire(value, schema, code="assembly_invalid")
    except DocumentError as exc:
        raise AssemblyError("assembly_invalid", str(exc), issues=exc.issues) from exc


def operation_capabilities() -> dict[str, Any]:
    """Return the exact operation schema used by batch validation."""
    return {"operations": operations_schema(), "document": document_schema()}


def new_document(*, rows: int = 2, columns: int = 2, width_mm: float = 180,
                 height_mm: float = 140) -> dict[str, Any]:
    return validate_document({"kind": "sciplot_panel_assembly", "version": 1, "revision": 0,
        "layout": {"rows": rows, "columns": columns, "width_mm": width_mm, "height_mm": height_mm,
                   "gap_x_mm": 4.0, "gap_y_mm": 4.0}, "panels": []})


def _label(index: int) -> str:
    result = ""
    while True:
        index, letter = divmod(index, 26)
        result = chr(97 + letter) + result
        if index == 0:
            return result
        index -= 1


def _resolve(document: dict[str, Any]) -> dict[str, Any]:
    layout = document["layout"]
    ordered = sorted(document["panels"], key=lambda panel: (panel["row"], panel["column"], panel["id"]))
    labels = {panel["id"]: _label(index) if panel["label"] is None else panel["label"]
              for index, panel in enumerate(ordered)}
    physical = {**layout, "capabilities": ["sparse", "spans"],
        "cells": [{"view_id": panel["id"], **{key: panel[key] for key in ("row", "column", "row_span", "column_span")}}
                  for panel in ordered], "row_weights": [1.0] * layout["rows"],
        "column_weights": [1.0] * layout["columns"], "resolve": [],
        "outer_margins_mm": {side: 0.0 for side in ("left", "right", "top", "bottom")},
        "panel_min_height_mm": 1.0, "panel_label_height_mm": 6.0}
    try:
        resolved = solve_layout(physical, [{"id": panel["id"], "panel_label": labels[panel["id"]]}
                                           for panel in ordered], [])
    except DocumentError as exc:
        raise AssemblyError(exc.reason_code, str(exc), issues=exc.issues) from exc
    return {"width_mm": resolved["width_mm"], "height_mm": resolved["height_mm"],
        "panels": [{"id": panel["view_id"], "cell_mm": panel["cell_mm"], "content_mm": panel["plot_mm"],
                    "label": labels[panel["view_id"]], "label_mm": panel["panel_label_mm"]}
                   for panel in resolved["panels"]]}


def validate_document(document: Any) -> dict[str, Any]:
    """Validate all represented state and physical constraints without reading sources."""
    _validate(document, document_schema())
    result: dict[str, Any] = deepcopy(document)
    integers = [result["version"], result["revision"], result["layout"]["rows"], result["layout"]["columns"]]
    integers += [panel[key] for panel in result["panels"] for key in ("row", "column", "row_span", "column_span")]
    if any(type(value) is not int for value in integers):
        raise AssemblyError("assembly_invalid", "Revisions, grid positions and spans require integers without coercion.")
    ids = [panel["id"] for panel in result["panels"]]
    if len(set(ids)) != len(ids):
        raise AssemblyError("assembly_duplicate_id", "Panel IDs must be unique.")
    for panel in result["panels"]:
        crop = panel["crop"]
        if crop is not None:
            if panel["source"]["kind"] != "image":
                raise AssemblyError("assembly_crop_kind", "Only image panels support cropping.")
            if crop[0] >= crop[2] or crop[1] >= crop[3]:
                raise AssemblyError("assembly_crop_bounds", "Image crop bounds must enclose a positive rectangle.")
    _resolve(result)
    return result


def resolve_document(document: Any) -> dict[str, Any]:
    return _resolve(validate_document(document))


def apply_operations(document: Any, operations: Any) -> dict[str, Any]:
    """Apply a complete closed batch atomically; intermediate placement may overlap."""
    from .operations import apply_batch

    candidate = validate_document(document)
    _validate(operations, operations_schema())
    for operation in operations:
        if any(type(value) is not int for key, value in operation.items()
               if key in {"rows", "columns", "row", "column", "row_span", "column_span"}):
            raise AssemblyError("assembly_invalid", "Grid positions and spans require integers without coercion.")
    apply_batch(candidate, deepcopy(operations))
    candidate["revision"] += 1
    return validate_document(candidate)


def load_document(path: str | Path) -> dict[str, Any]:
    from .storage import load

    return load(Path(path))


def save_document(document: Any, path: str | Path, expected_revision: int | None = None) -> Path:
    from .storage import save

    return save(validate_document(document), Path(path), expected_revision=expected_revision)
