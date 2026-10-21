"""Generated public CLI/native/cold continuation for ordinary categories."""

import csv
import json
from pathlib import Path
import subprocess

import pytest

from sciplot_core._paths import REPO_ROOT
from sciplot_core.foundation.file_hashing import file_sha256


def _cli(*args, success=True):
    result = subprocess.run([str(REPO_ROOT / "skill/scripts/sciplot"), *map(str, args), "--json"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=180, check=False)
    if success:
        assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


def _request(tmp_path, source, binding, **extra):
    request = {"version": 1, "action": "create", "source": str(source), "categorical": binding, **extra}
    path = tmp_path / "request.json"
    path.write_text(json.dumps(request, ensure_ascii=False))
    return path


def _binding(source, mode="given_values", **extra):
    return {"source_sha256": file_sha256(source), "mode": mode, "sample_column": 0,
        "condition_column": 1, "value_columns": [{"column_index": 2}],
        "table_selection": {"sheet": None, "header_rows": [0], "data_start_row": 1,
                            "data_end_row": len(source.read_text().splitlines())}, **extra}


def _document(created):
    from sciplot_core.studio_core.registry_state import _veusz_spec_path
    document = Path(created["current_project"]["figures"][0]["document"])
    spec_path = _veusz_spec_path(document)
    return document, spec_path, json.loads(spec_path.read_text())


def _cold_export(tmp_path, project):
    request = tmp_path / "export_request.json"
    request.write_text(json.dumps({"version": 1, "action": "export", "project": project}))
    return _cli("task", "start", "--request", request, "--task-dir", tmp_path / "cold")


def _assert_final_native_legend_geometry(spec, loaded):
    import math

    diagnostic = spec["legend"]["placement_diagnostics"]
    measured = diagnostic["measurement_axes"]
    for axis in ("x", "y"):
        actual = [float(loaded.resolveSettingPath(None, f"/page1/graph1/{axis}/{bound}").get())
                  for bound in ("min", "max")]
        assert actual == pytest.approx(measured[axis])
        assert actual == pytest.approx([spec["axes"][axis]["min"], spec["axes"][axis]["max"]])
    left, right, bottom, top = diagnostic["candidates"][diagnostic["position"]]["rectangle_fraction"]
    graph = diagnostic["footprint"]
    for item in spec["series"]:
        coordinates = []
        for x, y in zip(item["x_values"], item["y_values"], strict=True):
            values = []
            for axis, value in (("x", x), ("y", y)):
                low, high = measured[axis]
                scaled_value = value
                if spec["axes"][axis]["scale"] == "log":
                    low, high = math.log10(low), math.log10(high)
                    scaled_value = math.log10(value)
                values.append((scaled_value - low) / (high - low))
            coordinates.append(values)
        for start, end in zip(coordinates, coordinates[1:], strict=False):
            for step in range(101):
                x, y = [a + (b - a) * step / 100 for a, b in zip(start, end, strict=True)]
                dx = max(left - x, 0, x - right) * graph["graph_width_mm"]
                dy = max(bottom - y, 0, y - top) * graph["graph_height_mm"]
                assert math.hypot(dx, dy) + 1e-5 >= diagnostic["required_curve_clearance_mm"]


@pytest.mark.comprehensive
def test_public_managed_curve_compile_retains_pinned_algorithms_with_categorical_frontdoor(tmp_path):
    from sciplot_core.plot_backends.managed_audit import scientific_audit
    from sciplot_core.plot_backends.native_primitives import dataset_name
    from sciplot_core.plot_engine.storage import load_head, read
    from sciplot_core.veusz_worker.document_edit import loaded_native_document

    source = tmp_path / "cooling.csv"
    source.write_text("Temperature,Heat Flow\nC,W/g\nResin C,Resin C\n71,-0.02\n64,0.007\n55,-0.013\n")
    original = file_sha256(source)
    request = tmp_path / "managed_request.json"
    request.write_text(json.dumps({"version": 1, "action": "create", "sources": [str(source)],
        "intent": {"x": {"quantity": "temperature"}, "y": {"quantity": "heat_flow"},
            "source_context": "Original cooling values without adjustment."},
        "summary_statistic": "raw_only", "curve_display": "raw_overlay"}))
    created = _cli("task", "start", "--request", request, "--task-dir", tmp_path / "managed_task")
    assert created["status"] == "complete", created
    head = load_head(Path(created["project"]))
    ir = read(Path(head["binding"]["ir_path"]))
    layer = ir["views"][0]["layers"][0]
    with loaded_native_document(Path(head["binding"]["document"])) as loaded:
        assert scientific_audit(ir, loaded)["status"] == "passed"
        assert loaded.data[dataset_name(layer["dataset_id"], "x")].data.tolist() == [71., 64., 55.]
        assert loaded.data[dataset_name(layer["dataset_id"], "y")].data.tolist() == [-.02, .007, -.013]
    cold = _cli("plot", "export", created["project"])
    assert cold["ready_to_use"], cold
    assert {item["format"] for item in cold["exports"]} >= {"pdf", "tiff_300", "vsz"}
    assert all(Path(item["path"]).is_file() for item in cold["exports"])
    assert file_sha256(source) == original


@pytest.mark.comprehensive
def test_public_given_category_log_alias_styles_columns_and_cold_export(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from sciplot_core.studio_core.document_edit_state import run_document_worker
    from sciplot_core.veusz_worker.document_edit import loaded_native_document
    source = tmp_path / "counts.csv"
    source.write_text("样品,工况,Cell density,Run\nB,dry,0.12345678901234567,91\nA,wet,1.0000000000000002,92\nB,wet,2.3400000000000003,93\nA,dry,0.025,94\n")
    original = file_sha256(source)
    declaration = {"source_sha256": original, "sheet": None, "column_index": 2,
        "field": "unit", "value": "cells cm⁻³", "evidence": {"kind": "user_statement",
        "asserted_by": "data owner", "statement": "Cell density is measured in cells cm⁻³."}}
    binding = _binding(source, category_order=["A", "B"], condition_order=["dry", "wet"],
        category_aliases={"A": "Control", "B": "Modified"}, metadata_confirmations=[declaration],
        yscale="log", legend_position="upper_left", legend_columns=2,
        series_styles=[{"label": "dry", "color": "#215977", "marker": "circle"},
                       {"label": "wet", "color": "#B65B43", "marker": "square", "marker_fill_mode": "open"}])
    request = _request(tmp_path, source, binding)
    task = tmp_path / "task"
    created = _cli("task", "start", "--request", request, "--task-dir", task)
    assert created["status"] == "complete", created
    assert created["scientific_presentation"]["rule_id"] is None
    document, spec_path, spec = _document(created)
    assert spec["source_request"].get("rule_id") is None
    expected_binding = {**binding, "source_identity_version": 1, "source_namespace": str(source.resolve()),
        "series_styles": [{**style, "series_id": item["source_binding"]["source_id"]}
                          for style, item in zip(binding["series_styles"], spec["series"], strict=True)]}
    assert [item["source_binding"]["condition"] for item in spec["series"]] == ["dry", "wet"]
    assert len({item["source_binding"]["source_id"] for item in spec["series"]}) == 2
    assert spec["source_request"]["categorical_binding"] == expected_binding
    assert spec["axes"]["x"]["category_labels"] == ["Control", "Modified"]
    assert spec["legend"]["columns"] == 2
    assert spec["axes"]["y"]["scale"] == "log"
    expected = [[.025, float("0.12345678901234567")], [float("1.0000000000000002"), float("2.3400000000000003")]]
    assert [item["y_values"] for item in spec["series"]] == expected
    assert all(not item.get("error_values") for item in spec["series"])
    with loaded_native_document(document) as loaded:
        assert loaded.resolveSettingPath(None, "/page1/graph1/key1/columns").get() == 2
        _assert_final_native_legend_geometry(spec, loaded)
        for item, values in zip(spec["series"], expected, strict=True):
            assert [float(value).hex() for value in loaded.data[item["y_name"]].data] == [value.hex() for value in values]
    assert run_document_worker("audit-spec-data", document, spec_path)["status"] == "passed"
    cold = _cold_export(tmp_path, created["project"])
    assert cold["status"] == "complete", cold
    assert all(Path(image).is_file() for image in cold["next_step"]["images"])
    recovered = _cli("task", "start", "--request", request, "--task-dir", task)
    assert recovered["project"] == created["project"] and recovered["status"] == "complete"
    assert file_sha256(source) == original


@pytest.mark.comprehensive
def test_public_long_replicates_missing_confirmation_delivers_audited_n_and_exact_fill(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from sciplot_core.studio_core.document_edit_state import run_document_worker
    from sciplot_core.veusz_worker.document_edit import loaded_native_document
    from sciplot_core.veusz_worker.numeric_evidence import _text_dataset_values
    source = tmp_path / "repeats.csv"
    source.write_text("Sample,Condition,Strength (MPa),Replicate\nB,dry,2,1\nA,wet,10,2\nB,wet,8,3\nA,dry,4,4\nB,dry,2,5\nA,wet,14,6\nB,wet,12,7\nA,dry,,8\nA,dry,8,9\nB,dry,5,10\n")
    original = file_sha256(source)
    binding = _binding(source, "mean_sample_sd_n", category_order=["A", "B"], condition_order=["dry", "wet"],
        category_aliases={"A": "Control"}, series_styles=[{"label": "dry", "color": "#215977"}, {"label": "wet", "color": "#B65B43"}])
    request = _request(tmp_path, source, binding)
    task = tmp_path / "task"
    first = _cli("task", "start", "--request", request, "--task-dir", task)
    assert first["status"] == "needs_input" and first["question"]["field"] == "missing_values", first
    assert [group["valid_n"] for group in first["question"]["evidence"]["groups"]] == [2, 2, 3, 2]
    assert not (tmp_path / "repeats_SciPlot").exists()
    answer = tmp_path / "answer.json"
    answer.write_text(json.dumps(first["question"]["response_template"]))
    created = _cli("task", "resume", task, "--response", answer)
    assert created["status"] == "complete", created
    document, spec_path, spec = _document(created)
    groups = spec["categorical"]["groups"]
    assert [group["sample_label"] for group in groups] == ["A", "A", "B", "B"]
    assert [group["replicate_count"] for group in groups] == [2, 2, 3, 2]
    assert [group["raw_values"] for group in groups] == [[4., 8.], [10., 14.], [2., 2., 5.], [8., 12.]]
    assert groups[0]["bar_mean"] == 6. and groups[0]["bar_error"] == pytest.approx(2 ** .5 * 2)
    with loaded_native_document(document) as loaded:
        assert _text_dataset_values(loaded, dataset_name="category_axis_labels") == ["Control", "B"]
        for index, color in enumerate(["#215977", "#B65B43"] * 2, start=1):
            assert loaded.resolveSettingPath(None, f"/page1/graph1/categorical_bar_fill_{index}/Fill/color").get() == color
    assert run_document_worker("audit-spec-data", document, spec_path)["status"] == "passed"
    summaries = [path for path in Path(tmp_path / "repeats_SciPlot").rglob("*.csv") if "valid_n" in path.read_text().splitlines()[0]]
    assert summaries, created
    rows = list(csv.DictReader(summaries[0].open()))
    assert [int(row["valid_n"]) for row in rows] == [2, 2, 3, 2]
    assert [int(row["excluded_missing_count"]) for row in rows] == [1, 0, 0, 0]
    assert all(row["unit"] == "MPa" and row["missing_policy"] == "exclude" for row in rows)
    cold = _cold_export(tmp_path, created["project"])
    assert cold["status"] == "complete", cold
    import fitz
    with fitz.open(tmp_path / "repeats_SciPlot/figures/document.pdf") as pdf:
        visible = pdf[0].get_text().splitlines()
        assert "Control" in visible and "B" in visible and "A" not in visible
    assert [group["sample"] for group in spec["source_request"]["replicate_summary_disclosure"]["groups"]] == ["A", "A", "B", "B"]
    assert file_sha256(source) == original


@pytest.mark.comprehensive
def test_public_selected_excel_table_and_context_guards_create_no_fake_experiment(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    import pandas as pd
    from sciplot_core.studio_core.document_edit_state import run_document_worker
    source = tmp_path / "workbook.xlsx"
    with pd.ExcelWriter(source) as writer:
        pd.DataFrame([["unselected", "sheet"]]).to_excel(writer, sheet_name="Other", header=False, index=False)
        pd.DataFrame([["note", None, None], ["Unit °C", None, None], [None, None, None],
            ["Sample", "Tm alpha", "Tm beta"], ["Z", 163.7, 259.8], ["Q", 164.1, 260.2]]).to_excel(writer, sheet_name="Summary", header=False, index=False)
    original = file_sha256(source)
    confirmations = [{"source_sha256": original, "sheet": "Summary", "column_index": col, "field": "unit", "value": "°C",
        "evidence": {"kind": "source_cell", "sheet": "Summary", "row_index": 1, "column_index": 0, "text": "Unit °C"}} for col in (1, 2)]
    binding = {"source_sha256": original, "mode": "given_values", "sample_column": 0,
        "value_columns": [{"column_index": 1}, {"column_index": 2}], "metadata_confirmations": confirmations,
        "table_selection": {"sheet": "Summary", "header_rows": [3], "data_start_row": 4, "data_end_row": 6}}
    request = _request(tmp_path, source, binding)
    created = _cli("task", "start", "--request", request, "--task-dir", tmp_path / "task")
    assert created["status"] == "complete", created
    document, spec_path, spec = _document(created)
    assert [item["y_values"] for item in spec["series"]] == [[163.7, 164.1], [259.8, 260.2]]
    assert run_document_worker("audit-spec-data", document, spec_path)["status"] == "passed"
    assert file_sha256(source) == original


@pytest.mark.comprehensive
def test_public_explicit_corner_uses_bounded_default_axis_reserve_with_original_values(tmp_path):
    from sciplot_core.veusz_worker.document_edit import loaded_native_document

    source = tmp_path / "levels.csv"
    source.write_text("Sample,Alpha (°C),Beta (°C)\nZ,163.7,259.8\nQ,164.1,260.2\n")
    original = file_sha256(source)
    binding = _binding(source, condition_column=None, value_columns=[{"column_index": 1}, {"column_index": 2}], legend_position="upper_right")
    result = _cli("task", "start", "--request", _request(tmp_path, source, binding), "--task-dir", tmp_path / "task")
    assert result["status"] == "complete", result
    document, _, spec = _document(result)
    assert spec["render_options"]["legend_position"] == "upper_right"
    assert spec["legend"]["placement_diagnostics"]["axis_reserve"]["side"] == "top"
    assert [item["y_values"] for item in spec["series"]] == [[163.7, 164.1], [259.8, 260.2]]
    with loaded_native_document(document) as loaded:
        _assert_final_native_legend_geometry(spec, loaded)
    assert file_sha256(source) == original


@pytest.mark.comprehensive
def test_public_dense_explicit_legend_still_blocks_after_bounded_reserve(tmp_path):
    source = tmp_path / "dense.csv"
    source.write_text(",".join(["Sample", *[f"Metric {index} (°C)" for index in range(32)]]) + "\n"
        + ",".join(["Z", *[str(index + 1) for index in range(32)]]) + "\n"
        + ",".join(["Q", *[str(index + 2) for index in range(32)]]) + "\n")
    original = file_sha256(source)
    binding = _binding(source, condition_column=None,
        value_columns=[{"column_index": index} for index in range(1, 33)],
        legend_position="upper_right", legend_columns=1)
    result = _cli("task", "start", "--request", _request(tmp_path, source, binding),
        "--task-dir", tmp_path / "task", success=False)
    assert result["status"] == "blocked" and result["phase"] == "exporting", result
    manifest = json.loads(Path(result["result"]["studio_run"]["manifest"]).read_text())
    assert any(issue["id"] == "legend_curve_clearance_below_target"
               for issue in manifest["qa"]["studio_layout"]["critical_issues"])
    project = Path(result["project"])
    spec = json.loads((project / "studio/spec.json").read_text())
    assert spec["render_options"]["legend_position"] == "upper_right"
    assert [item["y_values"] for item in spec["series"]] == [[float(index + 1), float(index + 2)] for index in range(32)]
    assert not (tmp_path / "dense_SciPlot").exists() and file_sha256(source) == original
