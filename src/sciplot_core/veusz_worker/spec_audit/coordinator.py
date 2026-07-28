"""Coordinate one exact-current specification data audit."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.veusz_worker.spec_audit.categorical_axis import (
    audit_categorical_axis,
)
from sciplot_core.veusz_worker.spec_audit.closure import (
    audit_closed_document_inventory,
)
from sciplot_core.veusz_worker.spec_audit.inventory import (
    build_spec_audit_inventory,
)
from sciplot_core.veusz_worker.spec_audit.labels import audit_legends_and_labels
from sciplot_core.veusz_worker.spec_audit.overlays import audit_overlay_inventory
from sciplot_core.veusz_worker.spec_audit.scalar_field import audit_scalar_field
from sciplot_core.veusz_worker.spec_audit.series import audit_axes_and_series


def audit_spec_data(document_path: Path, spec_path: Path) -> dict[str, Any]:
    """Prove that an exact-current VSZ still consumes its rendered data spec."""

    from PyQt6 import QtWidgets
    from sciplot_core.studio import (
        _ensure_veusz_loader_compat,
        _ensure_veusz_on_path,
    )

    resolved_document = document_path.expanduser().resolve()
    resolved_spec = spec_path.expanduser().resolve()
    if not resolved_document.is_file():
        raise FileNotFoundError(f"Veusz document not found: {resolved_document}")
    if not resolved_spec.is_file():
        raise FileNotFoundError(f"Veusz specification not found: {resolved_spec}")
    spec = json.loads(resolved_spec.read_text(encoding="utf-8"))
    if not isinstance(spec, dict):
        raise ValueError(f"Expected JSON object: {resolved_spec}")

    _ensure_veusz_on_path()
    existing_app = QtWidgets.QApplication.instance()
    app = existing_app or QtWidgets.QApplication([])
    try:
        _ensure_veusz_loader_compat()
        from veusz import dataimport, document, widgets

        _ = dataimport, widgets
        loaded_document = document.Document()
        loaded_document.load(str(resolved_document))
        inventory = build_spec_audit_inventory(loaded_document, spec)
        series = audit_axes_and_series(inventory, spec)
        audit_legends_and_labels(inventory, spec, series)
        audit_categorical_axis(inventory, spec)
        allowed_scalar_dataset, visual = audit_scalar_field(inventory, spec)
        allowed_polygon_paths = audit_overlay_inventory(
            loaded_document,
            spec,
            visual,
        )
        audit_closed_document_inventory(
            inventory,
            allowed_scalar_dataset=allowed_scalar_dataset,
            allowed_polygon_paths=allowed_polygon_paths,
        )
        return {
            "kind": "sciplot_veusz_spec_data_audit",
            "version": 1,
            "status": "passed",
            "document": {
                "path": str(resolved_document),
                "sha256": file_sha256(resolved_document),
            },
            "spec": {
                "path": str(resolved_spec),
                "sha256": file_sha256(resolved_spec),
            },
            "units": inventory.units,
            "unit_count": len(inventory.units),
        }
    finally:
        if existing_app is None:
            app.quit()
