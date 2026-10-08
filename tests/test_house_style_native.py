"""Independent legacy/Managed native rendering of portable synthetic CSV data.

These arrays are test fixtures, not measurements or historical user figures.
The old renderer receives the original table through its production API; the
new renderer receives explicit source bindings and an empty default layout.
Neither renderer consumes the other's style or native widget specification.
"""

import csv
import json
from pathlib import Path
import shutil

import pytest

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.plot_backends.managed import ManagedVeuszCompiler
from sciplot_core.plot_engine.managed_sources import load_sources
from sciplot_core.plot_ir import compile_document, create_managed_document
from sciplot_core.plot_transforms import resolve_transforms
from sciplot_core.qa.rendering_regression import compare_rasters
from sciplot_core.render import render_to_dir
from sciplot_core.studio_core.document_edit_state import run_document_worker


def _synthetic_table(path, scale):
    xs = [1., 2., 3., 4., 5.] if scale == "linear" else [1., 2., 4., 8., 16.]
    first, second = [1., 3., 5., 7., 9.], [9., 7., 5., 3., 1.]
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerows([
            ["Wavelength", "Absorbance", "Wavelength", "Absorbance"],
            ["nm", "a.u.", "nm", "a.u."], ["A", "A", "B", "B"],
        ])
        writer.writerows((x, a, x, b) for x, a, b in zip(xs, first, second, strict=True))
    return xs, first, second


def _science(scale):
    if scale == "linear":
        return {"x": [0., 6.], "y": [0., 12.],
                "x_ticks": [0., 2., 4., 6.], "y_ticks": [0., 4., 8., 12.]}
    return {"x": [.1, 100.], "y": [.1, 100.],
            "x_ticks": [.1, 1., 10., 100.], "y_ticks": [.1, 1., 10., 100.]}


def _managed_document(source, scale, template, science):
    labels = {"x": "Wavelength (nm)", "y": "Signal (a.u.)"}
    columns = {"x": "Wavelength", "y": "Absorbance"}
    units = {"x": "nm", "y": "a.u."}
    marks = ["line", "point"] if template == "point_line" else ["line"]
    layers, slots = [], {}
    for index, sample in enumerate(("A", "B")):
        identifier = "layer:" + sample
        layers.append({
            "id": identifier, "dataset_id": "raw:synthetic",
            "mappings": {"x": f"column:{2 * index}", "y": f"column:{2 * index + 1}"},
            "mapping_semantics": columns, "x_scale": "scale:x", "y_scale": "scale:y",
            "marks": [{"id": f"mark:{sample}:{kind}", "type": kind, "style": {}} for kind in marks],
            "role": "measurement", "label": sample,
            "legend": {"visible": True, "label": sample},
            # Legacy graph children paint backwards: first input series is topmost.
            "z_order": -index, "style": {},
        })
        slots[sample] = {
            "series_id": identifier, "sample": sample,
            **{axis: {"source_id": "raw:synthetic", "column": columns[axis],
                      "column_index": 2 * index + offset}
               for offset, axis in enumerate(("x", "y"))},
            "x_unit": units["x"], "y_unit": units["y"],
        }
    figure = {
        "kind": "sciplot_figure_spec", "schema_version": 2, "id": "figure:synthetic",
        "scales": [{"id": "scale:" + axis, "dimension": axis, "transform": scale,
                    "domain": science[axis], "unit": units[axis], "quantity": columns[axis],
                    "direction": "ascending"} for axis in ("x", "y")],
        "views": [{"id": "view:main", "panel_label": None, "style": {}, "layers": layers,
                   "axes": [{"id": "axis:" + axis, "scale_id": "scale:" + axis,
                             "side": side, "label": labels[axis], "visible": True,
                             "label_visible": True, "ticks": science[axis + "_ticks"], "style": {}}
                            for axis, side in (("x", "bottom"), ("y", "left"))]}],
        "composition": {"kind": "single", "rows": 1, "columns": 1,
                        "cells": [{"view_id": "view:main", "row": 0, "column": 0,
                                   "row_span": 1, "column_span": 1}],
                        "column_weights": [1], "row_weights": [1], "resolve": []},
        "layout": {}, "theme": {"project": {}, "figure": {}}, "annotations": [],
        "guides": [{"id": "guide:main", "type": "legend", "scope": "view", "view_id": "view:main",
                    "layer_ids": [], "order": [], "labels": {}, "visible": True,
                    "location": "inside-best", "columns": 1, "style": {}}],
    }
    definition = {"kind": "sciplot_figure_template", "schema_version": 2,
                  "template_id": "synthetic-regression", "figure_spec": figure}
    binding = {
        "kind": "sciplot_binding", "schema_version": 1, "template_id": definition["template_id"],
        "data_sources": [{"source_id": "raw:synthetic", "path": str(source), "sha256": file_sha256(source),
                          "table_selection": {"sheet": None, "header_rows": [0], "unit_row": 1,
                                              "sample_row": 2, "data_start_row": 3, "data_end_row": 8}}],
        "slots": slots, "transforms": [], "guards": {}, "provenance": {"fixture": "synthetic-test-data"},
    }
    canonical = create_managed_document(definition, binding, plot_id="synthetic-house-regression")
    return resolve_transforms(canonical, load_sources(canonical, "uvvis_spectrum"))["document"]


@pytest.mark.comprehensive
@pytest.mark.parametrize("scale,template", [("linear", "curve"), ("log", "curve"), ("log", "point_line")],
                         ids=["linear-two-curves", "log-two-curves", "log-lines-and-markers"])
def test_house_default_matches_independent_legacy_and_rebuilds(tmp_path, scale, template):
    source = tmp_path / "synthetic.csv"
    xs, first, second = _synthetic_table(source, scale)
    source_hash, science = file_sha256(source), _science(scale)
    options = {"xscale": scale, "yscale": scale, "legend_position": "auto",
               "x_min": science["x"][0], "x_max": science["x"][1],
               "y_min": science["y"][0], "y_max": science["y"][1],
               "x_ticks": science["x_ticks"], "y_ticks": science["y_ticks"],
               "x_label_override": "Wavelength (nm)", "y_label_override": "Signal (a.u.)"}
    legacy = render_to_dir(source, template=template, output_dir=tmp_path / "legacy",
                           options=options, export_formats=("pdf", "tiff_300"))
    old_document = Path(legacy["veusz_documents"][0])
    old_spec = json.loads(Path(legacy["veusz_specs"][0]).read_text())
    assert [(item["x_values"], item["y_values"]) for item in old_spec["series"]] == [(xs, first), (xs, second)]
    for axis in ("x", "y"):
        assert [old_spec["axes"][axis]["min"], old_spec["axes"][axis]["max"]] == science[axis]
        assert old_spec["axes"][axis]["ticks"] == science[axis + "_ticks"]
    preview = run_document_worker("preview-document", old_document, "--out", tmp_path / "legacy-preview.png")
    document = _managed_document(source, scale, template, science)
    state_path = tmp_path / "canonical-document.json"
    state_path.write_text(json.dumps(document), encoding="utf-8")
    ir = compile_document(document)
    assert [ir["layout"][dimension] for dimension in ("width_mm", "height_mm")] == [60., 55.]
    assert ir["layout"]["panels"][0]["plot_mm"] == [14., 5.5, 41.5, 38.5]
    assert ir["datasets"]["raw:synthetic"]["columns"]["column:1"]["values"] == first
    assert ir["datasets"]["raw:synthetic"]["columns"]["column:3"]["values"] == second
    compiler = ManagedVeuszCompiler()
    artifacts = tmp_path / "managed-artifacts"
    try:
        result = compiler.compile_ir(ir, artifacts)
        assert result["publication_qa"]["status"] == "passed"
        assert result["publication_qa"]["native_text_checked"]
        # This is the independent old/new gate, before any self-rebuild test.
        comparison = compare_rasters(Path(preview["preview"]["path"]), Path(result["preview"]["path"]),
                                     output_dir=tmp_path / "legacy-vs-managed")
        assert comparison["status"] == "passed", comparison
        assert compiler.export_ir(ir, Path(result["document"]), artifacts / "exports")["ready_to_use"]
        pixels = Path(result["preview"]["path"]).read_bytes()
        shutil.rmtree(artifacts)
        # No saved IR, VSZ, preview or exports survive. Re-resolve from source
        # and the saved canonical document, not an in-memory backend object.
        saved = json.loads(state_path.read_text(encoding="utf-8"))
        rebuilt_document = resolve_transforms(saved, load_sources(saved, "uvvis_spectrum"))["document"]
        rebuilt_ir = compile_document(rebuilt_document)
        assert rebuilt_ir == ir
        rebuilt = compiler.compile_ir(rebuilt_ir, artifacts)
        assert rebuilt["scientific_audit"] == result["scientific_audit"]
        assert rebuilt["native_state_hash"] == result["native_state_hash"]
        assert Path(rebuilt["preview"]["path"]).read_bytes() == pixels
        assert file_sha256(source) == source_hash
    finally:
        compiler.close()
