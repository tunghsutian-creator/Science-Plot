"""Generated-data current viewport contracts; no native worker or private inputs."""
from copy import deepcopy
import json

import pytest

from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.plot_document import DocumentError, seal_document
from sciplot_core.plot_document.validation import validate_wire
from sciplot_core.plot_engine.errors import EngineError
from sciplot_core.plot_engine.figure_updates import current_edit_value, figure_edit_descriptor, prepare_figure_update
from sciplot_core.plot_grammar import merge_figure_spec, split_figure_spec, validate_figure_spec
from sciplot_core.plot_grammar.current_view import current_view_qa, resolve_current_view
from sciplot_core.plot_grammar.mark_geometry import extent_values, layer_geometry
from sciplot_core.plot_ir import create_managed_document, validate_ir
from sciplot_core.plot_ir.figure_document import figure_spec
from test_figure_document import request_for_figure
from test_figure_grammar import example, resolve


def current():
    spec, data = example()
    spec["domain_semantics"] = "current_view_v1"
    for scale in spec["scales"]:
        scale["domain_rule"] = {name: {"mode": "auto"} for name in ("minimum", "maximum")}
    for view in spec["views"]:
        for layer in view["layers"]:
            layer["visible"] = True
        for axis in view["axes"]:
            axis["ticks_mode"] = "automatic"
    return spec, data


def fixed(spec, x, y):
    for scale, bounds in zip(spec["scales"], (x, y), strict=True):
        scale["domain_rule"] = {name: {"mode": "fixed", "value": value}
                                for name, value in zip(("minimum", "maximum"), bounds, strict=True)}


def second_layer(spec, data):
    layer = deepcopy(spec["views"][0]["layers"][0])
    layer["id"] = "layer:second"
    layer["mappings"]["y"] = "column:2"
    for mark in layer["marks"]:
        mark["id"] += ":second"
    spec["views"][0]["layers"].append(layer)
    data["raw:A"]["columns"]["column:2"] = {"label": "Extreme", "unit": "Pa", "values": [100., 150., 200.]}
    guide = spec["guides"][0]
    guide["layer_ids"].append(layer["id"])
    guide["order"].append(layer["id"])
    return layer


def document(tmp_path):
    from sciplot_core.foundation.file_hashing import file_sha256

    request = request_for_figure(tmp_path)
    spec, data = current()
    second_layer(spec, data)
    source = tmp_path / "figure.csv"
    source.write_text("Frequency,Modulus,Extreme\nHz,Pa,Pa\n0,1,100\n5,5,150\n10,15,200\n")
    request["data_binding"]["data_sources"][0]["sha256"] = file_sha256(source)
    data["raw:A"]["provenance"]["sources"][0]["sha256"] = file_sha256(source)
    data["raw:A"]["provenance"]["sources"][0]["column_indices"]["column:2"] = 2
    request["data_binding"]["slots"]["second"] = deepcopy(request["data_binding"]["slots"]["modulus"])
    request["data_binding"]["slots"]["second"].update(series_id="layer:second")
    request["data_binding"]["slots"]["second"]["y"].update(column="Extreme", column_index=2)
    request["template_definition"]["figure_spec"] = resolve_current_view(spec, data)
    doc = create_managed_document(request["template_definition"], request["data_binding"], plot_id="current")
    doc["scientific"]["provenance"]["datasets"] = data
    return seal_document(doc)


def patch(*changes, intent="presentation"):
    return {"intent_class": intent, "changes": [
        {"op": "set", "target": [target], "property": prop, "value": value} for target, prop, value in changes]}


def test_historical_projections_and_ir_retain_exact_baseline_hashes():
    # Captured from the unchanged f7063a7 owner, not a new golden or fixture rewrite.
    spec, data = example()
    science, presentation = split_figure_spec(spec)
    assert [canonical_json_sha256(value, allow_nan=False) for value in (science, presentation)] == [
        "2afb722738e1ec0fdf4b6bfab69b770d788d7829e9da765478296e59e1b0b053",
        "0629eae9a4b5e629ad779cfa33128d9aa4c8f6e70eaa05201f49d0482d4cd2e0"]
    assert resolve(spec, data)["ir_hash"] == "faebb65f064ce4bf8d8f0c027af848b99d7d82b76755a16d1088d7a7e7f2d2d1"
    assert merge_figure_spec(science, presentation) == spec
    assert resolve_current_view(spec, {}) == spec


def test_legacy_fixed_window_allows_hidden_outlier_without_inventing_auto_mode():
    spec, data = example()
    layer = second_layer(spec, data)
    layer["visible"] = False
    before = deepcopy(spec)
    science, presentation = split_figure_spec(spec)
    ir = resolve(spec, data)
    assert ir["datasets"] == data and ir["scales"] == before["scales"]
    assert "domain_semantics" not in spec and "scales" not in presentation
    assert science["scales"] == before["scales"] and spec == before
    layer["visible"] = True
    with pytest.raises(DocumentError) as error:
        resolve(spec, data)
    assert error.value.reason_code == "figure_empty_visible_layer"


def test_versioned_projection_is_lossless_and_separates_view_from_science():
    spec, data = current()
    extra = second_layer(spec, data)
    spec = resolve_current_view(spec, data)
    before_science, before_presentation = split_figure_spec(spec)
    assert before_science["domain_semantics"] == "current_view_v1"
    assert not {"domain", "domain_rule"} & set(before_science["scales"][0])
    assert set(before_presentation["scales"][0]) == {"id", "domain", "domain_rule"}
    assert merge_figure_spec(before_science, before_presentation) == spec
    hidden = deepcopy(spec)
    hidden["views"][0]["layers"][1]["visible"] = False
    hidden = resolve_current_view(hidden, data)
    science, presentation = split_figure_spec(hidden)
    assert science == before_science and presentation != before_presentation
    assert hidden["scales"][1]["domain"][1] < spec["scales"][1]["domain"][1]
    assert spec["views"][0]["layers"][1]["id"] == extra["id"]
    for mutation in ("missing", "extra", "order"):
        bad = deepcopy(presentation)
        if mutation == "missing":
            bad["scales"].pop()
        elif mutation == "extra":
            bad["scales"][0]["discarded"] = True
        else:
            bad["scales"].reverse()
        with pytest.raises(DocumentError):
            merge_figure_spec(science, bad)


@pytest.mark.parametrize("mutation", ["marker", "rule", "mode", "fixed", "extra", "ticks"])
def test_new_rules_are_closed_and_cannot_be_silently_inferred(mutation):
    spec, data = current()
    spec = resolve_current_view(spec, data)
    if mutation == "marker":
        del spec["domain_semantics"]
    elif mutation == "rule":
        del spec["scales"][0]["domain_rule"]
    elif mutation == "mode":
        del spec["views"][0]["axes"][0]["ticks_mode"]
    elif mutation == "fixed":
        spec["scales"][0]["domain_rule"]["minimum"] = {"mode": "fixed", "value": 4}
    elif mutation == "extra":
        spec["scales"][0]["domain_rule"]["minimum"]["value"] = 0
    else:
        spec["views"][0]["axes"][0]["ticks"].append(999)
    with pytest.raises(DocumentError):
        validate_figure_spec(spec)


def test_pending_rules_resolve_before_store_compile_only_rejects_stale_projection():
    spec, data = current()
    spec["scales"][0]["domain_rule"]["minimum"] = {"mode": "fixed", "value": -3}
    with pytest.raises(DocumentError):
        validate_figure_spec(spec)
    resolved = resolve_current_view(spec, data)
    assert resolved["scales"][0]["domain"][0] == -3
    ir = resolve(resolved, data)
    assert all("domain_rule" not in scale for scale in ir["scales"])
    assert all("ticks_mode" not in axis for view in ir["views"] for axis in view["axes"])
    assert validate_ir(ir) == ir
    stale = deepcopy(resolved)
    stale["scales"][1]["domain"][1] += 100
    original = deepcopy(stale)
    with pytest.raises(DocumentError) as error:
        resolve(stale, data)
    assert error.value.reason_code == "figure_stale_domain_projection" and stale == original
    for target in ("scale", "axis"):
        forged = deepcopy(ir)
        if target == "scale":
            forged["scales"][0]["domain_rule"] = spec["scales"][0]["domain_rule"]
        else:
            forged["views"][0]["axes"][0]["ticks_mode"] = "automatic"
        with pytest.raises(DocumentError):
            validate_ir(forged)


@pytest.mark.parametrize("kind,expected_x,expected_y", [
    ("line", [0, 5, 10], [1, 5, 15]), ("point", [0, 5, 10], [1, 5, 15]),
    ("bar", [-1, 1, 4, 6, 9, 11], [-2, 1, 5, 15]),
    ("errorbar", [0, 5, 10], [-4, 2, 4, 8, 14, 20]),
    ("band", [0, 5, 10], [-4, 2, 4, 8, 14, 20]),
    ("rule", [0, 5, 10], []), ("text", [0, 5, 10], [1, 5, 15]),
])
def test_all_mark_extents_follow_drawable_data_geometry(kind, expected_x, expected_y):
    spec, data = current()
    layer = spec["views"][0]["layers"][0]
    mark = {"id": "mark:test", "type": kind, "style": {}}
    if kind == "bar":
        mark.update(baseline=-2, width_data=2)
    elif kind == "rule":
        mark["orientation"] = "vertical"
    elif kind == "text":
        mark["text"] = "Anchor"
    if kind in {"errorbar", "band"}:
        layer["mappings"].update(y_low="column:2", y_high="column:3")
        data["raw:A"]["columns"].update({
            "column:2": {"label": "Lower", "unit": "Pa", "values": [-4., 4., 14.]},
            "column:3": {"label": "Upper", "unit": "Pa", "values": [2., 8., 20.]}})
    layer["marks"] = [mark]
    geometry = layer_geometry(layer, data)
    assert sorted(set(extent_values(geometry, "x"))) == expected_x
    assert sorted(set(extent_values(geometry, "y"))) == expected_y
    if kind == "rule":
        with pytest.raises(DocumentError) as error:
            resolve_current_view(spec, data)
        assert error.value.reason_code == "figure_empty_auto_extent"
        fixed(spec, [-1, 11], [100, 110])  # mapped y is irrelevant to a vertical span
    resolved = resolve_current_view(spec, data)
    assert current_view_qa(resolved, data) == []
    resolve(resolved, data)


def test_window_intersection_uses_lines_and_polygons_not_only_centre_samples():
    spec, data = current()
    layer = spec["views"][0]["layers"][0]
    layer["marks"] = [layer["marks"][0]]
    fixed(spec, [2, 3], [2, 4])  # segment crosses window, all original points outside
    resolved = resolve_current_view(spec, data)
    resolve(resolved, data)
    layer["marks"] = [{"id": "mark:bar", "type": "bar", "style": {}, "width_data": 20, "baseline": -10}]
    fixed(spec, [2, 3], [2, 4])  # a polygon contains the whole window
    resolve(resolve_current_view(spec, data), data)


def test_band_uses_contiguous_actual_bounds_even_when_centre_is_missing_or_outside():
    spec, data = current()
    layer = spec["views"][0]["layers"][0]
    layer["marks"] = [{"id": "mark:band", "type": "band", "style": {}}]
    layer["mappings"].update(y_low="column:2", y_high="column:3")
    data["raw:A"]["columns"]["column:1"]["values"] = [1., 5., None]
    for column, value in (("column:2", 100.), ("column:3", 110.)):
        data["raw:A"]["columns"][column] = {"label": column, "unit": "Pa", "values": [value]*3}
    resolved = resolve_current_view(spec, data)
    assert resolved["scales"][0]["domain"][1] > 10
    assert resolved["scales"][1]["domain"][0] > 90
    resolve(resolved, data)


def test_line_gaps_are_not_connected_by_window_qa():
    spec, data = current()
    spec["views"][0]["layers"][0]["marks"] = [spec["views"][0]["layers"][0]["marks"][0]]
    data["raw:A"]["columns"]["column:1"]["values"] = [1., None, 15.]
    fixed(spec, [2, 3], [2, 4])
    with pytest.raises(DocumentError) as error:
        resolve(resolve_current_view(spec, data), data)
    assert error.value.reason_code == "figure_empty_visible_layer"


@pytest.mark.parametrize("mutation", ["unit", "log", "baseline", "empty"])
def test_hidden_layers_keep_scientific_validation(mutation):
    spec, data = current()
    layer = second_layer(spec, data)
    layer["visible"] = False
    if mutation == "unit":
        data["raw:A"]["columns"]["column:2"]["unit"] = "MPa"
    elif mutation == "log":
        spec["scales"][1].update(transform="log", domain=[1, 1000])
        data["raw:A"]["columns"]["column:2"]["values"][0] = 0
    elif mutation == "baseline":
        spec["scales"][1].update(transform="log", domain=[1, 1000])
        layer["marks"] = [{"id": "mark:bar", "type": "bar", "style": {}, "baseline": 0, "width_data": 1}]
    else:
        data["raw:A"]["columns"]["column:2"]["values"] = [None]*3
    with pytest.raises(DocumentError):
        resolve_current_view(spec, data)


def test_hide_show_preserves_science_and_fixed_endpoint_reopen_and_legend_order(tmp_path):
    doc = document(tmp_path)
    original = deepcopy(doc)
    spec = figure_spec(doc)
    spec["scales"][0]["domain_rule"]["minimum"] = {"mode": "fixed", "value": -7}
    from sciplot_core.plot_ir.figure_document import store_spec

    doc = store_spec(doc, resolve_current_view(spec, doc["scientific"]["provenance"]["datasets"]))
    hidden, diff, risk, execute = prepare_figure_update(doc, patch(("layer:second", "series.visible", False)))
    assert risk == "review" and not execute and any(item.get("derived") for item in diff)
    assert hidden["scientific_hash"] == doc["scientific_hash"]
    assert figure_spec(hidden)["scales"][0]["domain"][0] == -7
    # JSON round trip represents a saved, reopened document with no creation context.
    reopened = json.loads(json.dumps(hidden))
    shown, _, _, _ = prepare_figure_update(reopened, patch(("layer:second", "series.visible", True)))
    assert shown == doc
    assert figure_spec(shown)["guides"][0]["order"] == ["layer:modulus", "layer:second"]
    assert [layer["id"] for layer in figure_spec(shown)["views"][0]["layers"]] == ["layer:modulus", "layer:second"]
    assert doc["scientific"]["provenance"]["datasets"] == original["scientific"]["provenance"]["datasets"]


def test_domain_array_is_fixed_rules_remain_scientific_and_contract_current_values_apply(tmp_path):
    doc = document(tmp_path)
    change = ("scale:x", "scale.domain", [-10, 30])
    with pytest.raises(EngineError) as error:
        prepare_figure_update(doc, patch(change))
    assert error.value.reason_code == "figure_scientific_intent_required"
    updated, _, risk, execute = prepare_figure_update(doc, patch(change, intent="scientific"))
    assert risk == "scientific" and not execute
    assert updated["scientific_hash"] == doc["scientific_hash"]
    spec = figure_spec(updated)
    assert spec["scales"][0]["domain_rule"] == {"minimum": {"mode": "fixed", "value": -10}, "maximum": {"mode": "fixed", "value": 30}}
    current_value = current_edit_value(spec, "scale:x", "scale.domain")
    descriptor = figure_edit_descriptor(spec, "scale:x", "scale.domain")
    validate_wire(current_value, descriptor["value_schema"], code="test_current_value")
    unchanged, diff, risk, _ = prepare_figure_update(updated, patch(("scale:x", "scale.domain", current_value), intent="scientific"))
    assert unchanged == updated and not diff and risk == "scientific"


def test_fixed_ticks_conflict_is_atomic_and_same_property_can_restore_auto(tmp_path):
    doc = document(tmp_path)
    manual, _, _, _ = prepare_figure_update(doc, patch(("axis:yl", "axis.ticks", [100, 150, 200])))
    before = deepcopy(manual)
    with pytest.raises(DocumentError) as error:
        prepare_figure_update(manual, patch(("layer:second", "series.visible", False)))
    assert error.value.reason_code == "figure_fixed_ticks_domain_conflict" and manual == before
    hidden, _, _, _ = prepare_figure_update(manual, patch(("layer:second", "series.visible", False),
                                                        ("axis:yl", "axis.ticks", {"mode": "automatic"})))
    assert current_edit_value(figure_spec(hidden), "axis:yl", "axis.ticks") == {"mode": "automatic"}
    descriptor = figure_edit_descriptor(figure_spec(hidden), "axis:yl", "axis.ticks")
    validate_wire({"mode": "automatic"}, descriptor["value_schema"], code="test_current_value")
    assert figure_spec(hidden)["scales"][1]["domain"][1] < 20


def test_current_view_edit_requires_resolved_sealed_dataset_content(tmp_path):
    doc = document(tmp_path)
    data = doc["scientific"]["provenance"].pop("datasets")
    doc = seal_document(doc)
    with pytest.raises(EngineError) as error:
        prepare_figure_update(doc, patch(("layer:second", "series.visible", False)))
    assert error.value.reason_code == "figure_current_view_data_required"
    updated, _, _, _ = prepare_figure_update(doc, patch(("layer:second", "series.visible", False)), datasets=data)
    assert updated["scientific_hash"] == doc["scientific_hash"]


def test_initial_and_reopened_extended_spec_resolve_identically_without_creation_intent():
    initial, all_data = current()
    second_layer(initial, all_data)
    together = resolve_current_view(initial, all_data)
    first, first_data = current()
    first = resolve_current_view(first, first_data)
    reopened = json.loads(json.dumps(first))
    second_layer(reopened, first_data)
    appended = resolve_current_view(reopened, first_data)
    assert appended == together
    assert split_figure_spec(appended) == split_figure_spec(together)
    assert resolve(appended, first_data) == resolve(together, all_data)


@pytest.mark.parametrize("endpoint,value", [("minimum", -7), ("maximum", 300)])
def test_hide_show_never_moves_a_fixed_response_endpoint(endpoint, value):
    spec, data = current()
    second_layer(spec, data)
    spec["scales"][1]["domain_rule"][endpoint] = {"mode": "fixed", "value": value}
    original = resolve_current_view(spec, data)
    hidden = deepcopy(original)
    hidden["views"][0]["layers"][1]["visible"] = False
    hidden = resolve_current_view(hidden, data)
    assert hidden["scales"][1]["domain"][0 if endpoint == "minimum" else 1] == value
    hidden["views"][0]["layers"][1]["visible"] = True
    assert resolve_current_view(hidden, data) == original


def test_legacy_visibility_noop_preserves_absent_default_without_unreported_change(tmp_path):
    request = request_for_figure(tmp_path)
    doc = create_managed_document(request["template_definition"], request["data_binding"], plot_id="legacy")
    original = deepcopy(doc)
    updated, diff, _, _ = prepare_figure_update(doc, patch(("layer:modulus", "series.visible", True)))
    assert updated == original and not diff


def test_late_axis_legend_layout_and_label_edits_survive_auto_recomputation(tmp_path):
    doc = document(tmp_path)
    edited, _, _, _ = prepare_figure_update(doc, patch(
        ("axis:yl", "axis.label", "Exact user label"), ("axis:xb", "axis.ticks", [0, 5, 10]),
        ("axis:yl", "style", {"font_size_pt": 11}), ("guide:legend", "legend.order", ["layer:second", "layer:modulus"]),
        ("guide:legend", "legend.location", "bottom-left"), ("figure:main", "layout", {"width_mm": 110}),
        ("layer:second", "series.display_label", "Display alias")))
    before = figure_spec(edited)
    hidden, _, _, _ = prepare_figure_update(edited, patch(("layer:second", "series.visible", False)))
    after = figure_spec(hidden)
    assert after["views"][0]["axes"][0] == before["views"][0]["axes"][0]
    assert after["views"][0]["axes"][1]["label"] == "Exact user label"
    assert after["views"][0]["axes"][1]["style"] == {"font_size_pt": 11}
    assert after["guides"] == before["guides"] and after["layout"] == before["layout"]
    assert [layer["id"] for layer in after["views"][0]["layers"]] == ["layer:modulus", "layer:second"]
    assert edited["scientific_hash"] == hidden["scientific_hash"] == doc["scientific_hash"]


def test_interpolated_log_geometry_retains_original_arrays_and_time_defaults():
    spec, data = current()
    for scale in spec["scales"]:
        scale.update(transform="log", domain=[.1, 100])
    data["raw:A"]["columns"]["column:0"]["values"] = [1., 5., 10.]
    spec["views"][0]["layers"][0]["marks"][0]["interpolation"] = {
        "method": "pchip", "subdivisions": 4, "purpose": "display", "boundary": "preserve_gaps"}
    original = deepcopy(data)
    ir = resolve(resolve_current_view(spec, data), data)
    assert ir["datasets"] == original and ir["display_curves"]
    time, time_data = current()
    time["scales"][0].update(quantity="time", unit="s")
    time["views"][0]["layers"][0]["mapping_semantics"]["x"] = "time"
    time_data["raw:A"]["columns"]["column:0"]["unit"] = "s"
    assert resolve_current_view(time, time_data)["scales"][0]["domain"][0] == 0


def test_errorbar_missing_centre_matches_existing_painter_presence_contract():
    from sciplot_core.plot_backends.figure_marks import mark_geometry

    spec, data = current()
    layer = spec["views"][0]["layers"][0]
    layer["marks"] = [{"id": "mark:error", "type": "errorbar", "style": {}}]
    layer["mappings"].update(y_low="column:2", y_high="column:3")
    data["raw:A"]["columns"]["column:1"]["values"] = [1., None, 15.]
    data["raw:A"]["columns"].update({
        "column:2": {"label": "Lower", "unit": "Pa", "values": [-4., 400., 14.]},
        "column:3": {"label": "Upper", "unit": "Pa", "values": [2., 800., 20.]}})
    resolved = resolve_current_view(spec, data)
    assert resolved["scales"][1]["domain"][1] < 30
    ir = resolve(resolved, data)
    view = ir["views"][0]
    primitives = mark_geometry(ir, view, view["layers"][0], view["layers"][0]["marks"][0])
    assert len(primitives) == 6  # two painted intervals, each with two physical caps
    assert all(400. not in item.get("yPos", []) and 800. not in item.get("yPos2", []) for item in primitives)


@pytest.mark.parametrize("orientation", ["vertical", "horizontal"])
def test_rule_missing_orthogonal_coordinate_matches_existing_painter(orientation):
    from sciplot_core.plot_backends.figure_marks import mark_geometry

    spec, data = current()
    layer = spec["views"][0]["layers"][0]
    layer["marks"] = [{"id": "mark:rule", "type": "rule", "orientation": orientation, "style": {}}]
    orthogonal = "column:1" if orientation == "vertical" else "column:0"
    data["raw:A"]["columns"][orthogonal]["values"][1] = None
    fixed(spec, [-1, 11], [0, 20])
    resolved = resolve_current_view(spec, data)
    ir = resolve(resolved, data)
    view = ir["views"][0]
    primitives = mark_geometry(ir, view, view["layers"][0], view["layers"][0]["marks"][0])
    assert len(primitives) == 2
    assert len(layer_geometry(layer, data)) == 2


def test_single_observation_is_drawable_as_point_but_cannot_invent_a_line_segment():
    spec, data = current()
    data["raw:A"]["columns"]["column:1"]["values"] = [1., None, None]
    layer = spec["views"][0]["layers"][0]
    layer["marks"] = [layer["marks"][0]]
    with pytest.raises(DocumentError) as error:
        resolve_current_view(spec, data)
    assert error.value.reason_code == "figure_empty_auto_extent"
    layer["marks"][0]["type"] = "point"
    resolve(resolve_current_view(spec, data), data)
