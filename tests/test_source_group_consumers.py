"""Independent literal and metamorphic controls for verified group consumers."""

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path

import pandas as pd
import pytest

from sciplot_core import task_control as control
from sciplot_core.data_mapping import load_data_mapping_execution
from sciplot_core.data_mapping.plan_binding import verify_replicate_source_expansion
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.semantic_sources.impact_sources import _read_impact_source
from sciplot_core.studio_core.series_request import _series_from_request
from sciplot_core.studio_core.source_update_review import scientific_summary
from sciplot_core.studio_core.veusz_spec_series import build_veusz_series_specs
from sciplot_core.studio_render.categorical_plot_spec import _categorical_plot_contract
from sciplot_core.studio_render.models import _VeuszStyleContract
from sciplot_core.studio_render.categorical_series import _reindex_categorical_series
from sciplot_core.veusz_worker.style_transfer import _series_identity
from test_mapping_source_identity import selected
from test_task_raw_replicate_mapping import native_boundary
from test_task_raw_replicate_source_update import project_request


def mapped(tmp_path, monkeypatch, source, selection, choices, name):
    calls = native_boundary(monkeypatch, tmp_path)
    from sciplot_core.foundation.file_hashing import file_sha256

    state = control.start_task({"version": 1, "action": "create", "source": str(source),
        "rule_id": "impact_metric", "template": "box_strip", "summary_statistic": "raw_only",
        "mapping": {"source_sha256": file_sha256(source), "table_selection": selection,
                    "column_mapping": {"replicates": choices}}}, task_dir=tmp_path / name)
    assert state["status"] == "complete", state
    assert len(calls) == 1
    request = project_request(source, calls[0]["expected_plan"])
    request["render_options"]["raw_point_jitter_fraction"] = 0
    return request, calls[0]["expected_plan"]


def specification(request, tmp_path):
    series, info, steps, _ = _series_from_request(request, base_dir=tmp_path)
    options = {"summary_statistic": "raw_only", "raw_point_jitter_fraction": 0}
    categorical = _categorical_plot_contract(series, template_id="box_strip", render_options=options,
                                             source_bindings=info["source_bindings"])
    specs = build_veusz_series_specs(series=series, template_id="box_strip", render_options=options,
        categorical_contract=categorical, categorical_visual_style=categorical["visual_style"],
        style=_VeuszStyleContract(), source_bindings=info["source_bindings"])
    return {"template": "box_strip", "series": specs, "categorical": categorical}, info, steps


def test_three_groups_two_categories_survive_initial_append_and_reopen(tmp_path, monkeypatch):
    source, _, snapshot = selected(tmp_path)
    choices = [{"column_index": 0, "label": "literal/a || b"},
               {"column_index": 1, "label": "A (sheet)"},
               {"column_index": 2, "label": "B/alias"}]
    initial, _ = mapped(tmp_path, monkeypatch, source, snapshot["table_selection"], choices[:2], "initial")
    expanded, plan = mapped(tmp_path, monkeypatch, source, snapshot["table_selection"], choices, "expanded")
    verify_replicate_source_expansion(initial, source, plan["data_mapping"], plan)
    all_at_once, _ = mapped(tmp_path, monkeypatch, source, snapshot["table_selection"], choices, "all")
    before, _, _ = specification(initial, tmp_path)
    after, info, steps = specification(expanded, tmp_path)
    full, _, _ = specification(all_at_once, tmp_path)
    assert info["category_labels"] == ["A", "B"]
    assert info["category_positions"] == [1., 2.]
    assert [s["label"] for s in after["series"]] == ["literal/a || b", "A (sheet)", "B/alias"]
    assert [s["y_values"] for s in after["series"]] == [[1., 3.], [7., 8.], [11., 12., 13.]]
    assert [s["x_values"] for s in after["series"]] == [[.84, .84], [1.16, 1.16], [2., 2., 2.]]
    assert [s["source_binding"]["sample"] for s in after["series"]] == ["A", "A", "B"]
    assert [s["source_binding"]["condition"] for s in after["series"]] == [None, None, None]
    assert after["categorical"]["visual_style"]["category_count"] == 2
    assert len({s["name"] for s in after["series"]}) == 3
    assert all("group_" in s["x_name"] for s in after["series"])
    assert [{k: v for k, v in s.items() if k != "source_artifacts"} for s in before["series"]] == [
        {k: v for k, v in s.items() if k != "source_artifacts"} for s in after["series"][:2]]
    assert len(steps) == 1 and steps[0]["operation"] == "execute_confirmed_data_mapping_proposal"
    # Compare final science/group membership, not per-proposal receipt paths.
    def science(spec):
        return [(s["source_binding"], s["x_values"], s["y_values"]) for s in spec["series"]]
    assert science(after) == science(full)
    reopened = json.loads(json.dumps(expanded))
    assert specification(reopened, tmp_path)[0] == after
    typed, projection, _, _ = _series_from_request(expanded, base_dir=tmp_path)
    ids = [projection["source_bindings"][item.x_name]["source_id"] for item in typed]
    assert projection["semantic_terminal_series_order"] == ids
    canonical = deepcopy(expanded)
    canonical["series_order"] = ids
    canonical.setdefault("study_model", {})["render_defaults"] = {"series_order": ids, "series_include": ids}
    assert specification(json.loads(json.dumps(canonical)), tmp_path)[0] == after
    summary = _categorical_plot_contract(typed, template_id="bar", render_options={},
        source_bindings=projection["source_bindings"])
    assert [group["bar_mean"] for group in summary["groups"]] == [2., 7.5, 12.]
    assert [group["position"] for group in summary["groups"]] == [.84, 1.16, 2.]
    assert [group["source_binding"] for group in summary["groups"]] == [s["source_binding"] for s in after["series"]]
    assert summary["visual_style"]["bar_width_fraction"] < .32
    # The complete null domains survived before the finite display projection.
    execution = load_data_mapping_execution(expanded["data_mapping_execution"])
    assert [pd.read_csv(out["path"]).iloc[:, 0].isna().tolist() for out in execution["outputs"]] == [
        [False, True, False], [False, False, True], [False, False, False]]


def test_late_alias_changes_neither_scientific_summary_nor_style_pairing(tmp_path, monkeypatch):
    source, _, snapshot = selected(tmp_path)
    request, _ = mapped(tmp_path, monkeypatch, source, snapshot["table_selection"],
        [{"column_index": 0, "label": "old"}], "saved")
    spec, _, _ = specification(request, tmp_path)
    before = canonical_json_sha256(scientific_summary(spec))
    changed = deepcopy(spec)
    changed["series"][0]["label"] = changed["series"][0]["legend_key"] = "new/alias || literal"
    changed["categorical"]["groups"][0]["label"] = "new/alias || literal"
    assert canonical_json_sha256(scientific_summary(changed)) == before
    assert _series_identity(changed["series"][0]) == _series_identity(spec["series"][0])
    changed["series"][0]["source_binding"]["condition"] = "another acquisition"
    assert _series_identity(changed["series"][0]) != _series_identity(spec["series"][0])
    assert canonical_json_sha256(scientific_summary(changed)) != before
    with pytest.raises(ValueError, match="complete original correspondence"):
        _series_identity({**spec["series"][0], "source_binding": {"version": 1}})


def test_jitter_is_owned_by_group_not_display_alias(tmp_path, monkeypatch):
    source, _, snapshot = selected(tmp_path)
    request, _ = mapped(tmp_path, monkeypatch, source, snapshot["table_selection"],
        [{"column_index": 2, "label": "first alias"}], "jitter")
    series, info, _, _ = _series_from_request(request, base_dir=tmp_path)
    options = {"raw_point_jitter_fraction": .2}
    before = _reindex_categorical_series(series, render_options=options, source_bindings=info["source_bindings"])
    after = _reindex_categorical_series([replace(series[0], label="new/alias || b")],
        render_options=options, source_bindings=info["source_bindings"])
    assert before[0].x_values == after[0].x_values
    assert set(before[0].x_values) == {.8, 1., 1.2}
    assert before[0].y_values == after[0].y_values == (11., 12., 13.)


def test_original_and_mapped_byte_tampering_cannot_be_hidden_by_group_projection(tmp_path, monkeypatch):
    source, _, snapshot = selected(tmp_path)
    request, _ = mapped(tmp_path, monkeypatch, source, snapshot["table_selection"],
        [{"column_index": 0}], "tamper")
    execution = load_data_mapping_execution(request["data_mapping_execution"])
    output = Path(execution["outputs"][0]["path"])
    output.write_text(output.read_text() + "999\n")
    with pytest.raises(ValueError, match="does not reproduce"):
        _series_from_request(request, base_dir=tmp_path)


def test_whole_impact_noninjective_sample_sheet_names_refuse_merge(tmp_path):
    source = tmp_path / "collision.xlsx"
    with pd.ExcelWriter(source) as writer:
        for sheet, sample, values in [("x", "A", [1, 2]), ("y", "A", [3, 4]), ("z", "A (x)", [5, 6])]:
            pd.DataFrame([["Re"], ["kJ/m²"], [sample], *[[v] for v in values]]).to_excel(
                writer, sheet_name=sheet, index=False, header=False)
    with pytest.raises(ValueError, match="Distinct original impact groups"):
        _read_impact_source(source)


def test_managed_alias_edit_retains_scientific_hash_and_stable_layer_binding(tmp_path):
    from test_managed_source_append import bound_document
    from sciplot_core.plot_ir.figure_document import figure_spec, store_spec

    document = bound_document(tmp_path)
    before = deepcopy(document["scientific"])
    spec = figure_spec(document)
    layer = spec["views"][0]["layers"][0]
    group_id = layer["id"]
    layer["label"] = layer["legend"]["label"] = "literal/a || b"
    changed = store_spec(document, spec)
    assert changed["scientific_hash"] == document["scientific_hash"]
    assert changed["scientific"] == before
    assert figure_spec(changed)["views"][0]["layers"][0]["id"] == group_id
