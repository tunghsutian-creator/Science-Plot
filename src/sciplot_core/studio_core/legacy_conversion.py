"""One-way conversion of a supported saved XY plot into a new Managed project."""
import csv
import json
from pathlib import Path
from struct import pack
import subprocess
import sys
from typing import Any

from sciplot_core.foundation.canonical_paths import canonical_path
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.research_destination import require_data_destination
from sciplot_core.plot_document import DocumentError
from sciplot_core.studio_core.legacy_saved_plot import _saved_plot


def _inspect(document: Path) -> dict[str, Any]:
    from sciplot_core.native_process import run_worker
    from sciplot_core.plot_backends.managed import _domain_failure
    from sciplot_core.veusz_runtime import veusz_worker_environment

    result = run_worker(
        [sys.executable, "-m", "sciplot_core.veusz_worker", "inspect-legacy-xy", str(document)],
        env=veusz_worker_environment(), cold_runner=subprocess.run, capture_output=True, text=True, timeout=120,
    )
    if result.returncode:
        error = _domain_failure(result.stderr)
        if error:
            raise error
        raise ValueError("Cannot inspect the saved native plot for conversion: " + result.stderr.strip())
    return dict(json.loads(result.stdout))


def _axis_unit(label: str, explicit: str | None) -> str:
    from sciplot_core.studio_core.annotation_axes import axis_unit

    observed = axis_unit({"axes": {"saved": {"label": label}}}, "saved")
    if observed and explicit is not None and explicit != observed:
        raise DocumentError("legacy_conversion_unit_conflict", f"The saved axis label declares {observed!r}, not {explicit!r}.")
    unit = observed or (explicit or "").strip()
    if not unit or "\n" in unit or "\r" in unit:
        raise DocumentError("legacy_conversion_unit_required", "Provide the original unit of each unlabeled axis (use '1' only if dimensionless).")
    return unit


def _request(source: Path, output: Path, saved: dict[str, Any], units: dict[str, str], origin: Path) -> dict[str, Any]:
    dataset, view, layer, template = "saved:xy", "view:main", "layer:curve", "legacy-xy-v1"
    scales = [{"id": f"scale:{axis}", "dimension": axis, "transform": "linear",
               "domain": saved["axes"][axis]["domain"], "direction": "ascending",
               "unit": units[axis], "quantity": axis} for axis in ("x", "y")]
    axes = [{"id": f"axis:{axis}", "scale_id": f"scale:{axis}", "side": side,
             "label": saved["axes"][axis]["label"], "ticks": saved["axes"][axis]["ticks"],
             "visible": True, "label_visible": bool(saved["axes"][axis]["label"]), "style": {}}
            for axis, side in (("x", "bottom"), ("y", "left"))]
    figure = {"kind": "sciplot_figure_spec", "schema_version": 2, "id": "figure:converted",
              "scales": scales, "views": [{"id": view, "panel_label": None, "style": {},
                    "axes": axes, "layers": [{"id": layer, "dataset_id": dataset,
                        "mappings": {"x": "column:0", "y": "column:1"},
                        "mapping_semantics": {"x": "x", "y": "y"}, "x_scale": "scale:x", "y_scale": "scale:y",
                        "marks": saved["marks"], "role": "measurement", "label": "Saved curve",
                        "legend": {"visible": False, "label": ""}, "z_order": 0, "style": {}}]}],
              "composition": {"kind": "single", "rows": 1, "columns": 1,
                    "cells": [{"view_id": view, "row": 0, "column": 0, "row_span": 1, "column_span": 1}],
                    "column_weights": [1], "row_weights": [1], "resolve": []},
              "layout": saved["layout"], "theme": {"project": {}, "figure": {}}, "guides": [], "annotations": []}
    return {"idempotency_key": "legacy-conversion:" + saved["document_sha256"], "out": str(output / "rendered"),
            "template_definition": {"kind": "sciplot_figure_template", "schema_version": 2,
                                    "template_id": template, "figure_spec": figure},
            "rule_id": "ordinary_xy",
            "data_binding": {"kind": "sciplot_binding", "schema_version": 1, "template_id": template,
                "data_sources": [{"source_id": dataset, "path": str(source), "sha256": file_sha256(source),
                    "table_selection": {"sheet": None, "header_rows": [0], "unit_row": 1,
                        "data_start_row": 2, "data_end_row": len(saved["coordinates"]["x"]) + 2}}],
                "slots": {layer: {"series_id": layer, "sample": "Saved curve",
                    "x": {"source_id": dataset, "column": "x", "column_index": 0}, "x_unit": units["x"],
                    "y": {"source_id": dataset, "column": "y", "column_index": 1}, "y_unit": units["y"]}},
                "transforms": [], "guards": {}, "provenance": {"legacy_conversion": {
                    "document": str(origin), "sha256": saved["document_sha256"], "data_authority": "embedded_saved_vsz"}}}}


def convert_legacy_plot(target: Path, *, output: Path, figure_id: str | None = None,
                        x_unit: str | None = None, y_unit: str | None = None) -> dict[str, Any]:
    from sciplot_core.plot_engine.service import PlotService

    root, document = _saved_plot(target, figure_id)
    destination = canonical_path(output)
    if destination.is_relative_to(root):
        raise ValueError("The converted copy must be outside the original project directory.")
    require_data_destination(destination)
    if destination.exists():
        raise FileExistsError("Select a new directory for the converted project.")
    saved = _inspect(document)
    units = {axis: _axis_unit(saved["axes"][axis]["label"], value)
             for axis, value in (("x", x_unit), ("y", y_unit))}
    if file_sha256(document) != saved["document_sha256"]:
        raise ValueError("The original saved VSZ changed before conversion.")
    destination.mkdir()
    source = destination / "saved-coordinates.csv"
    with source.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("x", "y"))
        writer.writerow((units["x"], units["y"]))
        writer.writerows(zip(saved["coordinates"]["x"], saved["coordinates"]["y"], strict=True))
    request = _request(source, destination, saved, units, document)
    service = PlotService()
    try:
        result = service.create(request)
    finally:
        service.close()
    if file_sha256(document) != saved["document_sha256"]:
        raise ValueError("The original saved VSZ changed during conversion.")
    if result.get("ready_to_use"):
        from sciplot_core.plot_engine.storage import load_head, read

        ir = read(Path(load_head(Path(result["plot"]))["binding"]["ir_path"]))
        columns = ir["datasets"]["saved:xy"]["columns"]
        for index, axis in enumerate(("x", "y")):
            column = columns[f"column:{index}"]
            values = column["values"]
            original = saved["coordinates"][axis]
            if (column["unit"] != units[axis] or len(values) != len(original)
                    or any(value is None or pack(">d", value) != pack(">d", expected)
                           for value, expected in zip(values, original, strict=True))):
                raise DocumentError("legacy_conversion_science_changed",
                                    "Managed reconstruction did not preserve the original numeric values and units.")
    return {**result, "kind": "sciplot_legacy_conversion",
            "status": "converted" if result.get("ready_to_use") else "blocked",
            "original_vsz": {"path": str(document), "sha256": saved["document_sha256"]},
            "converted_source": str(source), "units": units,
            "rendering": "Managed rendering of supported saved data, axes and marks; use legacy-redraw for the exact old appearance."}
