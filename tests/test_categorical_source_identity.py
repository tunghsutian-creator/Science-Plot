"""Literal factor facts, aliases and exact-source replay at the real spec writer."""

from copy import deepcopy
import json
from pathlib import Path

import pandas as pd
import pytest

from sciplot_core.categorical_plan import build_categorical_preview
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.mapping_contract.categorical_identity import validate_categorical_correspondence
from sciplot_core.plan_preview import verify_expected_plan
from sciplot_core.source_coverage.managed_documents import _verify_prepared_data
from sciplot_core.studio_core import veusz_document
from sciplot_core.studio_core.categorical_display import category_ids, compile_display
from sciplot_core.studio_core.series_request import _series_from_request
from sciplot_core.studio_core.source_update_review import scientific_summary
from sciplot_core.terminal_request import authoritative_terminal_render_request, normalize_terminal_render_request
from sciplot_core.veusz_worker.spec_audit.categorical_identity import categorical_series_labels
from test_source_group_consumers import mapped


def test_raw_axis_label_anchors_are_categories_not_independent_group_slots():
    from sciplot_core.studio_core.veusz_data_import import import_veusz_spec_data

    class Capture:
        def __init__(self):
            self.numeric = {}
            self.text = {}

        def ImportString(self, name, values):
            self.numeric[name] = [float(value) for value in values.splitlines()]

        def SetDataText(self, name, values):
            self.text[name] = values

    native = Capture()
    series = [{"x_name": "x_group_1", "y_name": "y_group_1", "x_values": [.84, .84], "y_values": [1, 2]}]
    axes = {"x": {"category_labels": ["A", "B"], "category_positions": [1., 2.]}}
    categorical = {"presentation_kind": "raw_points", "summary_statistic": "raw_only",
                   "groups": [{"position": .84}, {"position": 1.16}, {"position": 2.}]}
    import_veusz_spec_data(native, series=series, axes=axes, categorical=categorical)
    assert native.numeric["category_axis_x(numeric)"] == [1., 2.]
    assert native.numeric["category_axis_y(numeric)"] == [0., 0.]
    assert native.text["category_axis_labels"] == ["A", "B"]
    assert native.numeric["x_group_1(numeric)"] == [.84, .84]


def written(request, tmp_path, monkeypatch, name):
    monkeypatch.setattr(veusz_document, "_save_veusz_document_from_spec", lambda *a, **k: None)
    series, info, _, _ = _series_from_request(request, base_dir=tmp_path)
    spec_path = veusz_document._write_veusz_document(tmp_path / name / "document.vsz",
        request=request, series=series, axis_info=info)
    return json.loads(spec_path.read_text())


def snapshots(spec):
    paths = list(dict.fromkeys(record["path"] for item in spec["series"] for record in item["source_artifacts"]))
    return [{"path": path, "sha256": file_sha256(Path(path)), "bytes": Path(path).read_bytes()} for path in paths]


@pytest.mark.parametrize("mode", ["given_values", "mean_sample_sd", "mean_sample_sd_n"])
def test_current_categorical_literal_factors_replay_without_label_parsing(tmp_path, monkeypatch, mode):
    source = tmp_path / "literal.csv"
    rows = ["Sample,Condition,Strength (MPa)"]
    for sample, offset in [("A || literal", 0), ("B/identity", 10)]:
        for condition, value in [("wet || bath", 1), ("dry/slash", 3)]:
            rows.append(f"{sample},{condition},{value + offset}")
            if mode != "given_values":
                rows.append(f"{sample},{condition},{value + offset + 1}")
    source.write_text("\n".join(rows) + "\n")
    original = source.read_bytes()
    binding = {"source_sha256": file_sha256(source), "mode": mode,
        "table_selection": {"sheet": None, "header_rows": [0], "data_start_row": 1, "data_end_row": len(rows)},
        "sample_column": 0, "condition_column": 1, "value_columns": [{"column_index": 2, "label": "value || display"}],
        "category_aliases": {"A || literal": "alias/A (q)", "B/identity": "alias || B"},
        "series_styles": [{"label": "wet || bath", "color": "#215977"}]}
    plan = build_categorical_preview(source, request={"categorical_binding": binding})
    assert "source_identity_version" not in binding
    assert plan["source_options"]["categorical_binding"]["source_identity_version"] == 1
    assert verify_expected_plan(source, plan, rule_id=None, template=plan["template"]) == plan
    request = {"input": str(source), "template": plan["template"], **plan["source_options"]}
    spec = written(request, tmp_path, monkeypatch, "current")
    validate_categorical_correspondence(spec)
    assert category_ids(spec) == ["A || literal", "B/identity"]
    assert spec["axes"]["x"]["category_labels"] == ["alias/A (q)", "alias || B"]
    assert spec["legend"].get("presentation_kind") != "factorized_curve"
    assert all(item["name"] == item["source_binding"]["source_id"] for item in spec["series"])
    if mode == "given_values":
        assert [item["y_values"] for item in spec["series"]] == [[1., 11.], [3., 13.]]
        assert [item["source_binding"]["condition"] for item in spec["series"]] == ["wet || bath", "dry/slash"]
    else:
        assert [group["raw_values"] for group in spec["categorical"]["groups"]] == [[1., 2.], [3., 4.], [11., 12.], [13., 14.]]
        assert [group["sample_label"] for group in spec["categorical"]["groups"]] == ["A || literal", "A || literal", "B/identity", "B/identity"]
        labels = categorical_series_labels(spec, {g["y_name"]: g for g in spec["categorical"]["groups"]},
            {s["y_name"]: s for s in spec["series"]}, "grouped_bar_error")
        assert labels == spec["axes"]["x"]["category_labels"]
        assert [g["position"] for g in spec["categorical"]["groups"]] == [.84, 1.16, 1.84, 2.16]
        assert [g["bar_mean"] for g in spec["categorical"]["groups"]] == [1.5, 3.5, 11.5, 13.5]
        assert spec["categorical"]["visual_style"]["bar_width_fraction"] < .32
    assert _verify_prepared_data(spec, snapshots(spec))["status"] == "passed"
    assert written(json.loads(json.dumps(request)), tmp_path, monkeypatch, "reopened")["series"] == spec["series"]
    terminal = authoritative_terminal_render_request(request)
    assert normalize_terminal_render_request(terminal, label="current") == terminal
    assert terminal["categorical_binding"] == request["categorical_binding"]
    updated, _ = compile_display(spec, {"op": "set_category_display_labels", "changes": [
        {"category_id": "A || literal", "expected_label": "alias/A (q)", "label": "another/alias || q"}]})
    assert scientific_summary(updated) == scientific_summary(spec)
    bad = deepcopy(spec)
    bad["series"][0]["source_binding"]["condition"] = "other condition"
    with pytest.raises(ValueError):
        _verify_prepared_data(bad, snapshots(bad))
    assert source.read_bytes() == original


def test_raw_writer_and_captured_snapshot_replay_keep_two_category_anchors(tmp_path, monkeypatch):
    from test_mapping_source_identity import selected

    source, _, selected_columns = selected(tmp_path)
    request, _ = mapped(tmp_path, monkeypatch, source, selected_columns["table_selection"],
        [{"column_index": 0, "label": "a/b || one"}, {"column_index": 1, "label": "a two"},
         {"column_index": 2, "label": "b/third"}], "raw")
    spec = written(request, tmp_path, monkeypatch, "raw_writer")
    assert spec["source_category_ids"] == ["A", "B"]
    assert [item["x_values"] for item in spec["series"]] == [[.84, .84], [1.16, 1.16], [2., 2., 2.]]
    validate_categorical_correspondence(spec)
    assert spec["legend"]["show"] is True
    assert _verify_prepared_data(spec, snapshots(spec))["status"] == "passed"
    terminal = authoritative_terminal_render_request(spec["source_request"])
    assert normalize_terminal_render_request(terminal, label="raw") == terminal
    assert [item["source_id"] for item in terminal["data_mapping_application"]["source_groups"]] == [s["name"] for s in spec["series"]]


def test_whole_impact_collision_has_a_verified_explicit_column_exit(tmp_path, monkeypatch):
    source = tmp_path / "collision.xlsx"
    with pd.ExcelWriter(source) as writer:
        for sheet, sample, values in [("x", "A", [1, 2]), ("y", "A", [3, 4]), ("z", "A (x)", [5, 6])]:
            pd.DataFrame([["Re"], ["kJ/m²"], [sample], *[[value] for value in values]]).to_excel(
                writer, sheet_name=sheet, index=False, header=False)
    selection = {"sheet": "x", "header_rows": [0], "unit_row": 1, "sample_row": 2,
                 "data_start_row": 3, "data_end_row": 5}
    request, _ = mapped(tmp_path, monkeypatch, source, selection, [
        {"column_index": 0, "label": f"group/{sheet}", "table_selection": {**selection, "sheet": sheet}}
        for sheet in ("x", "y", "z")], "collision_choice")
    spec = written(request, tmp_path, monkeypatch, "collision_result")
    assert spec["source_category_ids"] == ["A", "A (x)"]
    assert [item["category_position"] for item in spec["series"]] == [.84, 1.16, 2.]
    assert [item["y_values"] for item in spec["series"]] == [[1., 2.], [3., 4.], [5., 6.]]
    assert all(item["source_binding"]["condition"] is None for item in spec["series"])
    assert spec["legend"]["show"] is True
    assert _verify_prepared_data(spec, snapshots(spec))["status"] == "passed"


def test_namespace_is_written_from_physical_source_and_snapshot_needs_origin_proof(tmp_path):
    from test_task_ordinary_categorical import _binding
    from sciplot_core.studio_render.categorical_bindings import read_categorical_frame

    source = tmp_path / "left.csv"
    source.write_text("Sample,Condition,Value (MPa)\nA,dry,1\nB,dry,2\n")
    other = tmp_path / "right.csv"
    other.write_bytes(source.read_bytes())
    forged = _binding(other, source_namespace=str(source.resolve()))
    one = build_categorical_preview(source, request={"categorical_binding": _binding(source)})
    two = build_categorical_preview(other, request={"categorical_binding": forged})
    left_binding = one["source_options"]["categorical_binding"]
    right_binding = two["source_options"]["categorical_binding"]
    assert left_binding["source_namespace"] == str(source.resolve())
    assert right_binding["source_namespace"] == str(other.resolve())
    with pytest.raises(ValueError, match="physical original"):
        read_categorical_frame(other, left_binding)
    frame = read_categorical_frame(other, left_binding,
        source_artifact_origin={"path": str(source), "sha256": file_sha256(source)})
    assert frame.sha256 == file_sha256(source)


def test_frozen_style_ids_do_not_follow_swapped_aliases(tmp_path, monkeypatch):
    source = tmp_path / "styled.csv"
    source.write_text("Sample,Strength (MPa)\nA,1\nA,2\nB,7\nB,9\n")
    binding = {"source_sha256": file_sha256(source), "mode": "mean_sample_sd", "sample_column": 0,
        "value_columns": [{"column_index": 1}], "table_selection": {
            "sheet": None, "header_rows": [0], "data_start_row": 1, "data_end_row": 5},
        "series_styles": [{"label": "A", "color": "#123456"}]}
    plan = build_categorical_preview(source, request={"categorical_binding": binding})
    request = {"input": str(source), "template": "bar", **plan["source_options"]}
    before = written(request, tmp_path, monkeypatch, "style_before")
    changed = deepcopy(request)
    changed["categorical_binding"]["category_aliases"] = {"A": "B", "B": "A"}
    after = written(changed, tmp_path, monkeypatch, "style_after")
    assert [item["label"] for item in after["series"]] == ["B", "A"]
    assert [item["color"] for item in after["series"]] == [item["color"] for item in before["series"]]
    assert [item["name"] for item in after["series"]] == [item["name"] for item in before["series"]]
    assert scientific_summary(before) == scientific_summary(after)
    forged = deepcopy(changed)
    forged["categorical_binding"]["series_styles"][0]["series_id"] = "unknown_group"
    with pytest.raises(ValueError, match="retained source group"):
        written(forged, tmp_path, monkeypatch, "invalid_style")


def test_new_confirmed_source_version_preserves_ids_slots_and_style_proof(tmp_path, monkeypatch):
    from test_mapping_source_identity import selected
    from sciplot_core.veusz_worker.style_transfer import _series_identity

    source, _, selection = selected(tmp_path)
    choices = [{"column_index": 0, "label": "group/a"}, {"column_index": 1, "label": "group/b"}]
    one, _ = mapped(tmp_path, monkeypatch, source, selection["table_selection"], choices, "old_version")
    before = written(one, tmp_path, monkeypatch, "old_version_spec")
    source.write_text(source.read_text().replace("1,7,11", "2,7,11"))
    two, _ = mapped(tmp_path, monkeypatch, source, selection["table_selection"], choices, "confirmed_fresh_version")
    after = written(two, tmp_path, monkeypatch, "fresh_version_spec")
    assert [item["name"] for item in before["series"]] == [item["name"] for item in after["series"]]
    assert [item["x_values"] for item in before["series"]] == [item["x_values"] for item in after["series"]]
    assert [_series_identity(item) for item in before["series"]] == [_series_identity(item) for item in after["series"]]
    assert before["series"][0]["y_values"] == [1., 3.]
    assert after["series"][0]["y_values"] == [2., 3.]
    assert _verify_prepared_data(after, snapshots(after))["status"] == "passed"
    with pytest.raises(ValueError):
        _series_from_request(one, base_dir=tmp_path)  # The old version receipt remains stale.


def test_saved_absent_marker_keeps_legacy_plan_and_series_names(tmp_path, monkeypatch):
    source = tmp_path / "old.csv"
    source.write_text("Sample,Condition,Strength (MPa)\nA,dry,1\nB,dry,2\n")
    binding = {"source_sha256": file_sha256(source), "mode": "given_values", "sample_column": 0,
        "condition_column": 1, "value_columns": [{"column_index": 2}], "table_selection": {
            "sheet": None, "header_rows": [0], "data_start_row": 1, "data_end_row": 3}}
    plan = build_categorical_preview(source, request={"categorical_binding": binding}, current_identity=False)
    assert verify_expected_plan(source, plan, rule_id=None, template="point_line") == plan
    spec = written({"input": str(source), "template": "point_line", **plan["source_options"]}, tmp_path, monkeypatch, "old")
    assert "source_category_ids" not in spec and "source_binding" not in spec["series"][0]
    assert spec["series"][0]["name"] == "series_1"
    assert _verify_prepared_data(spec, snapshots(spec))["status"] == "passed"


@pytest.mark.parametrize("mode", ["given_values", "mean_sample_sd", "mean_sample_sd_n"])
def test_canonical_terminal_order_persists_ids_through_writer_and_cold_replay(tmp_path, monkeypatch, mode):
    source = tmp_path / "canonical.csv"
    rows = ["Sample,Condition,Strength (MPa)"]
    for sample, offset in [("A", 0), ("B", 10)]:
        for condition, value in [("dry", 1), ("wet", 3)]:
            rows.append(f"{sample},{condition},{value + offset}")
            if mode != "given_values":
                rows.append(f"{sample},{condition},{value + offset + 1}")
    source.write_text("\n".join(rows) + "\n")
    binding = {"source_sha256": file_sha256(source), "mode": mode, "sample_column": 0,
        "condition_column": 1, "value_columns": [{"column_index": 2}],
        "table_selection": {"sheet": None, "header_rows": [0], "data_start_row": 1, "data_end_row": len(rows)}}
    plan = build_categorical_preview(source, request={"categorical_binding": binding})
    request = {"input": str(source), "template": plan["template"], **plan["source_options"]}
    series, info, _, _ = _series_from_request(request, base_dir=tmp_path)
    ids = [info["source_bindings"][item.x_name]["source_id"] for item in series]
    assert info["semantic_terminal_series_order"] == ids
    assert ids != [item.label for item in series]
    # prepare_generated persists this exact projection in both canonical owners.
    request["series_order"] = ids
    request["study_model"] = {"render_defaults": {"series_order": ids, "series_include": ids}}
    spec = written(request, tmp_path, monkeypatch, "canonical_saved")
    cold = json.loads(json.dumps(request))
    assert written(cold, tmp_path, monkeypatch, "canonical_cold")["series"] == spec["series"]
    assert _verify_prepared_data(spec, snapshots(spec))["status"] == "passed"
