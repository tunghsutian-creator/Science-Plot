"""Display edits preserve recoverable source identity and explicit authorization."""

from copy import deepcopy

import pytest
from test_figure_document import request_for_figure

from sciplot_core.plot_ir import create_managed_document
from sciplot_core.plot_ir.figure_document import figure_spec
from sciplot_core.plot_engine.managed_updates import prepare_update
from sciplot_core.studio_core.annotation_batch import compile_annotation_operations
from sciplot_core.studio_core.annotation_schema import validate_operation_batch
from sciplot_core.task_common_edits import compile_common_edit, normalize_common_edit


def test_series_alias_and_membership_preserve_full_source_inventory():
    spec = {"template": "curve", "series": [
        {"name": "series_1", "label": "A", "presentation_kind": "curve", "x_values": [3, 1, 1], "y_values": [5, 4, 2]},
        {"name": "series_2", "label": "B", "presentation_kind": "curve", "x_values": [1, 7], "y_values": [2, 6]}]}
    original = deepcopy(spec)
    operations = [{"op": "set_series_display_label", "sample": "A", "expected_label": "A", "label": "Control [A]"},
                  {"op": "set_series_selection", "expected_order": ["A", "B"], "active_order": ["A"]}]
    validate_operation_batch(operations)
    styles, updated, actual = compile_annotation_operations(spec, operations, document_sha256="a" * 64, figure_id="f")
    assert spec == original and styles == []
    assert updated["series"][0] == original["series"][0] | {"legend_key": "Control [A]"}
    assert updated["series"][1] == original["series"][1]
    assert all(item["authorization"].startswith("explicit_") for item in actual)
    _, restored, _ = compile_annotation_operations(updated, [{"op": "set_series_selection", "expected_order": ["A"], "active_order": ["B", "A"]}], document_sha256="b" * 64, figure_id="f")
    assert restored["series"] == updated["series"]
    for bad in ([], ["C"], ["A", "A"]):
        with pytest.raises(ValueError):
            compile_annotation_operations(updated, [{"op": "set_series_selection", "expected_order": ["A"], "active_order": bad}], document_sha256="b" * 64, figure_id="f")
    with pytest.raises(ValueError):
        compile_annotation_operations(updated, operations, document_sha256="b" * 64, figure_id="f")


def test_managed_series_patch_changes_only_presentation_and_rejects_empty_membership(tmp_path):
    request = request_for_figure(tmp_path)
    doc = create_managed_document(request["template_definition"], request["data_binding"], plot_id="display-test")
    options = normalize_common_edit(series_labels={"layer:modulus": "Control A"}, legend_columns=2)
    patch = compile_common_edit(doc, options, "alias")
    updated, diff, risk, execute = prepare_update(doc, patch)
    assert updated["scientific"] == doc["scientific"] and not execute and risk == "review"
    assert diff[0]["property"] == "series.display_label"
    assert figure_spec(updated)["views"][0]["layers"][0]["legend"]["label"] == "Control A"
    assert figure_spec(updated)["guides"][0]["columns"] == 2
    renamed = compile_common_edit(updated, normalize_common_edit(series_labels={"Modulus": "Another display alias"}), "rename-again")
    assert renamed["changes"] == [{"op": "set", "target": ["layer:modulus"], "property": "series.display_label", "value": "Another display alias"}]
    for value in (0, 33, True, 2.1):
        with pytest.raises(ValueError):
            normalize_common_edit(legend_columns=value)
    bad = compile_common_edit(doc, normalize_common_edit(series_visibility={"layer:modulus": False}), "hide-all")
    with pytest.raises(ValueError, match="At least one"):
        prepare_update(doc, bad)
    for options in ({"series_labels": {"unknown": "A"}}, {"series_visibility": {"unknown": False}}):
        with pytest.raises(ValueError):
            compile_common_edit(doc, normalize_common_edit(**options), "unknown")


def _style_document(tmp_path, *, second=False):
    request = request_for_figure(tmp_path)
    spec = request["template_definition"]["figure_spec"]
    layer = spec["views"][0]["layers"][0]
    layer.update(label="Display A", legend={"visible": True, "label": "Alias A"})
    layer["style"] = {"line": {"line_width_pt": 1.7, "line_color": "#778899"}}
    line, point = layer["marks"]
    line["style"] = {"line_color": "#112233", "line_width_pt": 2.1,
                     "line_style": "dash", "line_join": "bevel", "line_opacity": .65}
    point["style"] = {"marker": "diamond", "marker_color": "#445566",
                      "marker_size_pt": 4.2, "marker_line_width_pt": .3,
                      "marker_opacity": .6, "marker_thin_factor": 3}
    if second:
        other = deepcopy(layer)
        other.update(id="layer:second", label="Display B",
                     legend={"visible": True, "label": "Alias B"}, z_order=2)
        for mark in other["marks"]:
            mark["id"] += ":second"
        spec["views"][0]["layers"].append(other)
        slot = deepcopy(next(iter(request["data_binding"]["slots"].values())))
        slot.update(series_id="layer:second", sample="Source B")
        request["data_binding"]["slots"]["second"] = slot
    return create_managed_document(request["template_definition"], request["data_binding"], plot_id="series-style")


def _selector_error(message, *, code="series_selector_invalid", **details):
    from sciplot_core.plot_engine.errors import EngineError

    return EngineError(code, message, **details)


def _style_patch(document, changes):
    return {"plot_id": document["plot_id"], "base_revision": document["revision"],
            "idempotency_key": "series-style-once", "intent_class": "presentation", "changes": changes}


def test_series_selector_uses_stable_ids_source_and_display_names_without_rebinding(tmp_path):
    from sciplot_core.task_series_edits import resolve_series_targets, series_candidates

    document = _style_document(tmp_path, second=True)
    original = deepcopy(document)
    assert [target for target, _ in series_candidates(document)] == ["layer:modulus", "layer:second"]
    for selector in ("layer:modulus", "Display A", "Alias A", "Modulus"):
        assert [target for target, _ in resolve_series_targets(document, [selector], _selector_error)] == ["layer:modulus"]
    assert [target for target, _ in resolve_series_targets(document, ["Source B", "Alias A"], _selector_error)] == ["layer:second", "layer:modulus"]
    assert document == original


def test_series_selector_id_precedence_and_ambiguous_aliases_are_explicit(tmp_path):
    from sciplot_core.plot_ir.figure_document import store_spec
    from sciplot_core.task_series_edits import resolve_series_targets

    document = _style_document(tmp_path, second=True)
    spec = figure_spec(document)
    spec["views"][0]["layers"][1]["label"] = "layer:modulus"
    document = store_spec(document, spec)
    assert [target for target, _ in resolve_series_targets(document, ["layer:modulus"], _selector_error)] == ["layer:modulus"]
    spec["views"][0]["layers"][1]["legend"]["label"] = "Display A"
    document = store_spec(document, spec)
    original = deepcopy(document)
    for selectors in (["Display A"], ["Alias A", "Modulus"], ["unknown"]):
        with pytest.raises(ValueError):
            resolve_series_targets(document, selectors, _selector_error)
        assert document == original


def test_all_series_selection_retains_hidden_members_in_original_order(tmp_path):
    from sciplot_core.plot_ir.figure_document import store_spec
    from sciplot_core.task_series_edits import compile_series_style, resolve_series_targets

    document = _style_document(tmp_path, second=True)
    spec = figure_spec(document)
    spec["views"][0]["layers"][1]["visible"] = False
    document = store_spec(document, spec)
    original = deepcopy(document)
    assert [target for target, _ in resolve_series_targets(document, None, _selector_error)] == ["layer:modulus", "layer:second"]
    changes = compile_series_style(document, samples=None, all_samples=True, style={"color": "#123456"})
    touched = {target for change in changes for target in change["target"]}
    assert touched == {mark["id"] for layer in spec["views"][0]["layers"] for mark in layer["marks"]}
    updated, _, _, _ = prepare_update(document, _style_patch(document, changes))
    assert figure_spec(updated)["views"][0]["layers"][1]["visible"] is False
    assert updated["scientific"] == original["scientific"] and document == original


@pytest.mark.parametrize("color,expected", [("#abcd1234ef00", "#abcd1234ef00"), ("red", "#ff0000")])
def test_v2_series_style_overrides_only_requested_mark_fields_and_derived_guide_symbols(tmp_path, color, expected):
    from test_figure_grammar import example
    from sciplot_core.plot_grammar import compile_figure
    from sciplot_core.task_series_edits import compile_series_style

    document = _style_document(tmp_path, second=True)
    original, before = deepcopy(document), figure_spec(document)
    source = tmp_path / "figure.csv"
    source_bytes = source.read_bytes()
    changes = compile_series_style(document, samples=["Modulus"], all_samples=False,
                                   style={"color": color, "width": "0.254mm"})
    updated, diff, risk, execute = prepare_update(document, _style_patch(document, changes))
    expected_spec = deepcopy(before)
    line, point = expected_spec["views"][0]["layers"][0]["marks"]
    line["style"].update(line_color=expected, line_width_pt=pytest.approx(.72))
    point["style"]["marker_color"] = expected
    actual = figure_spec(updated)
    assert actual == expected_spec
    assert risk == "presentation" and not execute and diff
    assert updated["scientific"] == original["scientific"]
    assert updated["scientific_hash"] == original["scientific_hash"]
    assert updated["presentation_hash"] != original["presentation_hash"]
    assert document == original and source.read_bytes() == source_bytes
    ir = compile_figure(actual, example()[1], scientific_hash=updated["scientific_hash"],
                        presentation_hash=updated["presentation_hash"])
    marks = ir["views"][0]["layers"][0]["marks"]
    assert ir["guides"][0]["entries"][0]["marks"] == marks
    assert marks[0]["style"]["line_width_pt"] == pytest.approx(.72)
    assert marks[1]["style"]["marker_line_width_pt"] == .3
    assert marks[1]["style"]["marker_size_pt"] == 4.2
    repeated, repeated_diff, _, _ = prepare_update(updated, _style_patch(updated, changes))
    assert repeated == updated and repeated_diff == []


@pytest.mark.parametrize("unsupported", ["reference", "bar", "point_only_width", "unknown_selector", "duplicate_selector", "empty_selection"])
def test_series_style_rejects_unsupported_or_mixed_batches_without_document_mutation(tmp_path, unsupported):
    from sciplot_core.plot_ir.figure_document import store_spec
    from sciplot_core.task_series_edits import compile_series_style

    document = _style_document(tmp_path, second=True)
    spec = figure_spec(document)
    other = spec["views"][0]["layers"][1]
    if unsupported == "reference":
        other["role"] = "reference"
    elif unsupported == "bar":
        other["marks"] = [{"id": "mark:bar", "type": "bar", "baseline": 0, "width_data": 1, "style": {}}]
    elif unsupported == "point_only_width":
        other["marks"] = [other["marks"][1]]
    document = store_spec(document, spec)
    original = deepcopy(document)
    selectors = ([] if unsupported == "empty_selection" else
                 ["Modulus", "unknown"] if unsupported == "unknown_selector" else
                 ["Display A", "Modulus"] if unsupported == "duplicate_selector" else None)
    with pytest.raises(ValueError):
        compile_series_style(document, samples=selectors, all_samples=selectors is None,
                             style={"color": "#123456", "width": "0.7pt"})
    assert document == original


def test_point_only_color_preserves_marker_geometry_and_science(tmp_path):
    from sciplot_core.plot_ir.figure_document import store_spec
    from sciplot_core.task_series_edits import compile_series_style

    document = _style_document(tmp_path)
    spec = figure_spec(document)
    spec["views"][0]["layers"][0]["marks"] = [spec["views"][0]["layers"][0]["marks"][1]]
    document = store_spec(document, spec)
    changes = compile_series_style(document, samples=["Alias A"], all_samples=False, style={"color": "#123456"})
    updated, _, _, _ = prepare_update(document, _style_patch(document, changes))
    expected = deepcopy(spec)
    expected["views"][0]["layers"][0]["marks"][0]["style"]["marker_color"] = "#123456"
    assert figure_spec(updated) == expected and updated["scientific"] == document["scientific"]


def _v1_style_document():
    return {"plot_type": "LegacyPlot", "scientific": {"provenance": {}}, "presentation": {"objects": {
        "series:A": {"kind": "series", "label": "A", "properties": {"series.display_label": "Display A"},
                     "capabilities": {"style.line.width": {"type": "physical_size", "risk": "presentation"},
                                      "style.line.color": {"type": "color", "risk": "presentation"}}},
        "series:B": {"kind": "series", "label": "B", "properties": {},
                     "capabilities": {"style.line.width": {"type": "physical_size", "risk": "presentation"},
                                      "style.line.color": {"type": "color", "risk": "presentation"}}}}}}


def test_v1_style_retains_batch_properties_and_color_values_without_promoting_coverage():
    from sciplot_core.task_series_edits import compile_series_style

    document = _v1_style_document()
    original = deepcopy(document)
    changes = compile_series_style(document, samples=["B", "Display A"], all_samples=False,
                                   style={"width": "0.7pt", "color": "purple"})
    assert changes == [
        {"op": "set", "target": ["series:B", "series:A"], "property": "style.line.width", "value": "0.7pt"},
        {"op": "set", "target": ["series:B", "series:A"], "property": "style.line.color", "value": "purple"},
    ]
    assert document == original
    document["presentation"]["objects"]["series:A"]["scientific_role"] = "condition"
    protected = deepcopy(document)
    with pytest.raises(ValueError):
        compile_series_style(document, samples=None, all_samples=True, style={"color": "purple"})
    assert document == protected
    del document["presentation"]["objects"]["series:B"]["capabilities"]["style.line.width"]
    with pytest.raises(ValueError):
        compile_series_style(document, samples=None, all_samples=True, style={"width": "0.7pt"})


def test_shared_series_selector_preserves_each_entrys_existing_correction_contract(tmp_path):
    from sciplot_core.task_series_edits import compile_series_style

    document = _style_document(tmp_path)
    with pytest.raises(ValueError) as duplicate:
        compile_common_edit(document, {"series_labels": {"Alias A": "X", "Modulus": "Y"}}, "duplicate")
    assert duplicate.value.reason_code == "common_edit_invalid"
    assert duplicate.value.repair["target"] == "layer:modulus"
    assert duplicate.value.repair["property"] == "series.display_label"
    with pytest.raises(ValueError) as unknown:
        compile_common_edit(document, {"series_visibility": {"unknown": False}}, "unknown")
    assert unknown.value.reason_code == "common_edit_unknown_target"
    assert unknown.value.repair["selector"] == "unknown"
    assert unknown.value.repair["property"] == "series.visible"
    with pytest.raises(ValueError) as style:
        compile_series_style(document, samples=["unknown"], all_samples=False, style={"color": "red"})
    assert style.value.reason_code == "document_ambiguous_style_target"
    assert style.value.repair["label"] == "unknown"
    assert style.value.repair["allowed"] == ["layer:modulus"]
