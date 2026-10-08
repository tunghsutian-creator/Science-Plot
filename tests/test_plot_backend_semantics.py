"""Closed semantic bindings retain coordinates, units, identities and rollback state."""

from copy import deepcopy
import json

import pytest

from sciplot_core.plot_backends.veusz_import import _presentation
from sciplot_core.plot_backends.veusz_compile import compile_diff
from sciplot_core.plot_backends.veusz_semantic_compile import preflight_hidden_positions
from sciplot_core.plot_document import apply_patch, seal_document
from sciplot_core.studio_core.annotation_batch import compile_annotation_operations
from sciplot_core.studio_core.annotation_schema import AnnotationOperationError, validate_operation_batch


@pytest.fixture
def native_semantics():
    spec = {"template": "curve", "axes": {
        "x": {"label": "Wavelength (nm)", "min": 395, "max": 505, "scale": "linear", "ticks": [400, 450, 500]},
        "y": {"label": "Absorbance (a.u.)", "min": 0, "max": 5, "scale": "linear", "ticks": [1, 2, 3, 4]}},
        "legend": {"show": True}, "series": [{"name": "series_1", "label": "E2", "presentation_kind": "curve",
                                                "x_values": [400, 450, 500], "y_values": [1, 2, 3]}]}
    widgets = {"/page1/graph1/series_1": {"name": "series_1", "type": "xy", "editable_fields": []}}
    for name in ("x", "y"):
        widgets[f"/page1/graph1/{name}"] = {"name": name, "type": "axis", "settings": spec["axes"][name], "editable_fields": []}
    placement = {"horzPosn": "right", "vertPosn": "top", "horzManual": 0.12, "vertManual": 0.25}
    widgets["/page1/graph1/key1"] = {"name": "key1", "type": "key", "settings": {"hide": False, **placement},
        "editable_fields": [{"setting_path": "/page1/graph1/key1/" + key, "current_value": value} for key, value in placement.items()]}
    records = [{"op": "add_annotation", "id": "note", "parent_path": "/page1/graph1", "text": "Measured value",
                "position": {"mode": "axes", "x": 450, "y": 4, "x_unit": "nm", "y_unit": "a.u."},
                "arrow_to": {"mode": "axes", "x": 450, "y": 2, "x_unit": "nm", "y_unit": "a.u."}}]
    widgets["/page1/graph1/sciplot_annotation_note"] = {"name": "sciplot_annotation_note", "type": "label", "editable_fields": []}
    spec["native_annotations"] = {"version": 1, "items": records}
    selected = {"objects": widgets, "annotations": records}
    objects, targets = _presentation(selected, spec)
    document = seal_document({"kind": "sciplot_document", "schema_version": 1, "plot_id": "fixture", "revision": 0,
        "scientific": {"data_sources": [], "transforms": [], "mappings": {}, "guards": {}, "provenance": {}},
        "presentation": {"objects": objects, "theme": {}, "layout": {}, "export_configuration": {}},
        "coverage": {"mode": "legacy_shadow", "limitations": []}, "backend": {}})
    return spec, selected, document, {"targets": targets}


def patch(doc, *changes):
    return apply_patch(doc, {"plot_id": doc["plot_id"], "base_revision": 0, "idempotency_key": "test",
                             "intent_class": "presentation", "changes": [
        {"op": "set", "target": [target], "property": prop, "value": value} for target, prop, value in changes]})


def execute(spec, operations):
    validate_operation_batch(operations)
    return compile_annotation_operations(spec, operations, document_sha256="a" * 64, figure_id="f")


def test_semantic_axes_keep_ticks_units_direction_and_all_data(native_semantics):
    spec, _, doc, binding = native_semantics
    new, diff, risk = patch(doc, ("axis:x", "axis.limits", [390, 510]), ("axis:y", "axis.limits", [-1, 6]))
    assert risk == "review" and new["scientific_hash"] == doc["scientific_hash"]
    _, operations, updates = compile_diff(doc, binding, new, diff)
    _, changed, actual = execute(spec, operations)
    assert len(actual) == 2 and changed["series"] == spec["series"]
    assert operations[0]["unit"] == "nm" and operations[1]["unit"] == "a.u."
    for name in ("x", "y"):
        assert changed["axes"][name]["ticks"] == spec["axes"][name]["ticks"]
        assert changed["axis_data_visibility"]["axes"][name]["clipped_coordinate_count"] == 0
    restored, undo, _ = patch(new, ("axis:x", "axis.limits", [395, 505]), ("axis:y", "axis.limits", [0, 5]))
    _, inverse, _ = compile_diff(new, updates, restored, undo)
    _, final, _ = execute(changed, inverse)
    assert final["axes"]["x"]["ticks"] == [400, 450, 500]
    assert final["axes"]["y"]["ticks"] == [1, 2, 3, 4]


def test_reversed_axis_advertised_without_reordering_bounds_or_ticks(native_semantics):
    spec, selected, _, _ = native_semantics
    spec["axes"]["x"].update(min=505, max=395, ticks=[500, 450, 400])
    objects, targets = _presentation(selected, spec)
    assert objects["axis:x"]["properties"]["axis.limits"] == [505, 395]
    assert objects["axis:x"]["capabilities"]["axis.limits"]["direction"] == "descending"
    op = {"op": "set_axis_limits", "axis": "x", "unit": "nm", "expected_min": 505,
          "expected_max": 395, "min": 510, "max": 390, "allow_clipping": False}
    _, changed, _ = execute(spec, [op])
    assert changed["axes"]["x"]["ticks"] == [500, 450, 400]
    assert targets["axis:x"]["properties"]["axis.limits"]["current_value"] == [505, 395]


@pytest.mark.parametrize("override,code", [({"min": 425}, "axis_clipping_not_authorized"),
    ({"unit": "cm"}, "unit_mismatch"), ({"expected_min": 394}, "stale_axis_range"),
    ({"min": 505, "max": 395}, "invalid_axis_range"), ({"allow_clipping": True}, "axis_clipping_not_authorized")])
def test_limits_reject_clipping_units_staleness_and_direction(native_semantics, override, code):
    spec, _, _, _ = native_semantics
    op = {"op": "set_axis_limits", "axis": "x", "unit": "nm", "expected_min": 395,
          "expected_max": 505, "min": 390, "max": 510, "allow_clipping": False, **override}
    with pytest.raises(AnnotationOperationError) as error:
        compile_annotation_operations(spec, [op], document_sha256="a" * 64, figure_id="f")
    assert error.value.reason_code == code


def test_duplicate_axis_and_second_tick_edit_are_rejected_for_either_axis(native_semantics):
    spec, _, doc, binding = native_semantics
    new, diff, _ = patch(doc, ("axis:x", "axis.limits", [390, 510]), ("axis:y", "axis.limits", [-1, 6]))
    _, operations, _ = compile_diff(doc, binding, new, diff)
    for axis in ("x", "y"):
        extra = {"op": "set_style", "object_path": f"/page1/graph1/{axis}",
                 "setting_path": f"/page1/graph1/{axis}/MajorTicks/manualTicks", "expected_value": [], "value": []}
        with pytest.raises(AnnotationOperationError, match="second style"):
            execute(spec, operations + [extra])
    with pytest.raises(AnnotationOperationError, match="once per batch"):
        execute(spec, operations + [operations[0]])


def test_annotations_keep_absolute_mode_units_anchor_and_hidden_identity(native_semantics):
    spec, _, doc, binding = native_semantics
    cap = doc["presentation"]["objects"]["annotation:note"]["capabilities"]["annotation.position"]
    assert cap["coordinate_mode"] == "axes" and cap["units"] == {"x": "nm", "y": "a.u."}
    hidden, diff, risk = patch(doc, ("annotation:note", "annotation.visible", False))
    _, operations, binding = compile_diff(doc, binding, hidden, diff)
    assert risk == "review" and operations[0]["op"] == "remove_annotation"
    edited, diff, _ = patch(hidden, ("annotation:note", "annotation.text", "New note"),
                           ("annotation:note", "annotation.position", [475, 4.5]))
    changes, operations, binding = compile_diff(hidden, binding, edited, diff)
    assert not changes and operations is None
    visible, diff, _ = patch(edited, ("annotation:note", "annotation.visible", True))
    _, operations, _ = compile_diff(edited, binding, visible, diff)
    record = operations[0]
    assert record["id"] == "note" and record["text"] == "New note"
    assert record["position"] == {"mode": "axes", "x": 475, "y": 4.5, "x_unit": "nm", "y_unit": "a.u."}
    assert record["arrow_to"] == spec["native_annotations"]["items"][0]["arrow_to"]


def test_legend_manual_position_and_null_undo_restore_all_native_fields(native_semantics):
    _, _, doc, binding = native_semantics
    assert doc["presentation"]["objects"]["legend:key1"]["properties"]["legend.position"] is None
    new, diff, risk = patch(doc, ("legend:key1", "legend.position", [0.2, 0.3]), ("legend:key1", "legend.visible", False))
    _, operations, updates = compile_diff(doc, binding, new, diff)
    assert risk == "review" and operations[-1] == {"op": "set_legend_visibility", "expected_visible": True, "visible": False}
    restored, diff, _ = patch(new, ("legend:key1", "legend.position", None), ("legend:key1", "legend.visible", True))
    _, undo, _ = compile_diff(new, updates, restored, diff)
    assert {item["setting_path"].rsplit("/", 1)[-1]: item["value"] for item in undo[:-1]} == {
        "horzPosn": "right", "vertPosn": "top", "horzManual": 0.12, "vertManual": 0.25}


def test_legend_visibility_updates_declaration_without_changing_series(native_semantics):
    spec, _, _, _ = native_semantics
    _, hidden, actual = execute(spec, [{"op": "set_legend_visibility", "expected_visible": True, "visible": False}])
    assert hidden["legend"]["show"] is False and hidden["series"] == spec["series"]
    assert actual == [{"op": "set_legend_visibility", "before": True, "after": False}]
    factorized = deepcopy(spec)
    factorized["legend"]["presentation_kind"] = "factorized_curve"
    with pytest.raises(AnnotationOperationError, match="ordinary native"):
        execute(factorized, [{"op": "set_legend_visibility", "expected_visible": True, "visible": False}])


def test_opaque_and_peak_labels_do_not_gain_guessed_semantic_capabilities(native_semantics):
    spec, selected, _, _ = native_semantics
    selected["annotations"][0]["peak_anchor"] = {"scientific": "opaque"}
    objects, _ = _presentation(selected, spec)
    assert "annotation:note" not in objects


def test_hidden_absolute_position_is_checked_before_a_native_candidate(native_semantics, tmp_path):
    spec, _, doc, binding = native_semantics
    hidden, diff, _ = patch(doc, ("annotation:note", "annotation.visible", False),
                            ("annotation:note", "annotation.position", [900, 4]))
    _, operations, updates = compile_diff(doc, binding, hidden, diff)
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(spec))
    with pytest.raises(AnnotationOperationError) as error:
        preflight_hidden_positions({**binding, "spec": str(path)}, hidden, diff, updates, operations)
    assert error.value.reason_code == "coordinate_out_of_bounds"


def test_existing_clipping_and_unrestorable_legend_placement_stay_opaque(native_semantics):
    spec, selected, _, _ = native_semantics
    spec["axes"]["x"]["min"] = 425
    selected["objects"]["/page1/graph1/key1"]["settings"]["horzManual"] = -0.1
    objects, _ = _presentation(selected, spec)
    assert "axis:x" not in objects
    assert "legend.position" not in objects["legend:key1"]["properties"]
    assert objects["legend:key1"]["properties"]["legend.visible"] is True


def test_limits_leave_missing_values_unchanged_and_count_only_finite_coordinates(native_semantics):
    spec, _, doc, binding = native_semantics
    spec["series"][0]["y_values"][1] = None
    new, diff, _ = patch(doc, ("axis:y", "axis.limits", [-1, 6]))
    _, operations, _ = compile_diff(doc, binding, new, diff)
    _, result, actual = execute(spec, operations)
    assert result["series"] == spec["series"] and actual[0]["outside_display_coordinate_count"] == 0
    assert result["axis_data_visibility"]["axes"]["y"]["finite_coordinate_count"] == 2
