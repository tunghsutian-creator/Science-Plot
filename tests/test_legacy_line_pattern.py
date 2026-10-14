from copy import deepcopy
from types import SimpleNamespace

import pytest

from sciplot_core.plot_backends.veusz_compile import compile_diff
from sciplot_core.plot_backends.veusz_import import _presentation
from sciplot_core.plot_document import DocumentError, apply_patch, seal_document
from sciplot_core.policy import DEFAULT_CURVE_LINE_STYLE_SEQUENCE, DEFAULT_LINE_STYLE_SEQUENCE


def _imported(pattern="solid", *, template="curve", choices=None):
    path = "/page1/graph1/series_1"
    field = {"setting_path": path + "/PlotLine/style", "current_value": pattern,
             "editor": "choice", "choices": list(DEFAULT_LINE_STYLE_SEQUENCE) if choices is None else choices}
    width = {"setting_path": path + "/PlotLine/width", "current_value": "1.2pt"}
    selected = {"objects": {path: {"type": "xy", "editable_fields": [field, width]}}}
    spec = {"template": template, "series": [{"name": "series_1", "label": "sample",
                                             "presentation_kind": "curve"}]}
    return _presentation(selected, spec)


def _document(objects):
    return seal_document({"kind": "sciplot_document", "schema_version": 1,
        "plot_type": "LegacyPlot", "plot_id": "line-pattern-test", "revision": 0,
        "scientific": {"data_sources": [], "transforms": [], "mappings": {}, "guards": {}, "provenance": {}},
        "presentation": {"objects": objects, "layout": {}, "theme": {}, "export_configuration": {}},
        "coverage": {"mode": "legacy_shadow", "limitations": ["Native state remains authoritative"]}})


def _patch(value, *, prop="style.line.pattern"):
    return {"plot_id": "line-pattern-test", "base_revision": 0, "idempotency_key": "pattern",
            "intent_class": "presentation", "changes": [{"op": "set", "target": ["series:sample"],
            "property": prop, "value": value}]}


def test_import_and_compile_uses_current_native_enum_without_changing_science():
    objects, targets = _imported("dotted", choices=["solid", "dotted", "dash-dot", "none"])
    obj = objects["series:sample"]
    assert obj["properties"]["style.line.pattern"] == "dotted"
    assert obj["capabilities"]["style.line.pattern"]["enum"] == ["solid", "dotted", "dash-dot"]
    before = _document(objects)
    after, diff, risk = apply_patch(before, _patch("dash-dot"))
    assert risk == "presentation"
    assert before["scientific_hash"] == after["scientific_hash"]
    assert before["presentation_hash"] != after["presentation_hash"]
    changes, operations, updated = compile_diff(before, {"targets": targets}, after, diff)
    assert operations is None
    assert changes == [{"object_path": "/page1/graph1/series_1",
        "setting_path": "/page1/graph1/series_1/PlotLine/style", "expected_value": "dotted", "value": "dash-dot"}]
    assert updated["targets"]["series:sample"]["properties"]["style.line.pattern"]["current_value"] == "dash-dot"
    assert DEFAULT_CURVE_LINE_STYLE_SEQUENCE == ("solid",)


@pytest.mark.parametrize("pattern,choices", [("dash1", None), ("none", None), ("solid", ["dashed"])])
def test_unrepresented_pattern_remains_opaque(pattern, choices):
    objects, _ = _imported(pattern, choices=choices)
    assert "style.line.pattern" not in objects["series:sample"]["properties"]
    assert objects["series:sample"]["properties"]["style.line.width"] == "1.2pt"


@pytest.mark.parametrize("template", ["bar", "box", "scatter", "polar_curve", "heatmap"])
def test_non_ordinary_encoding_does_not_gain_pattern_authority(template):
    objects, _ = _imported(template=template)
    assert "style.line.pattern" not in objects["series:sample"]["properties"]


@pytest.mark.parametrize("value", ["none", "invented", "dash1", False, ["solid"]])
def test_pattern_patch_rejects_non_advertised_or_hidden_values(value):
    objects, _ = _imported()
    document = _document(objects)
    with pytest.raises(DocumentError) as caught:
        apply_patch(document, _patch(value))
    assert caught.value.reason_code == "document_invalid_value"
    assert document == _document(objects)


@pytest.mark.parametrize("kind", ["axis", "legend", "annotation"])
def test_forged_target_kind_cannot_claim_pattern(kind):
    objects, _ = _imported()
    objects["series:sample"]["kind"] = kind
    with pytest.raises(DocumentError) as caught:
        _document(objects)
    assert caught.value.reason_code == "document_invalid_capability"


def test_forged_capability_and_mixed_scientific_batch_fail_closed():
    objects, _ = _imported()
    forged = deepcopy(objects)
    forged["series:sample"]["capabilities"]["style.line.pattern"]["enum"].append("none")
    with pytest.raises(DocumentError):
        _document(forged)
    document = _document(objects)
    patch = _patch("dashed")
    patch["changes"].append({"op": "set", "target": ["series:sample"], "property": "mapping.x", "value": [7]})
    with pytest.raises(DocumentError) as caught:
        apply_patch(document, patch)
    assert caught.value.reason_code == "document_scientific_edit_unsupported"
    assert document == _document(objects)


def _legend_imported(length="0.40cm", *, inspected=True, path="/page1/graph1/key1", template="curve"):
    fields = [{"setting_path": path + "/Text/size", "current_value": "7pt"}]
    if inspected:
        fields.append({"setting_path": path + "/keyLength", "current_value": length, "editor": "distance"})
    selected = {"objects": {path: {"type": "key", "name": "key1", "settings": {"hide": False},
                                  "editable_fields": fields}}}
    spec = {"template": template, "legend": {"show": True}, "series": []}
    # No declared curves need inspection here; only their ordinary legend scope.
    from sciplot_core.plot_backends.veusz_semantic_import import legend_properties
    obj = {"kind": "legend", "label": "key1", "properties": {}, "capabilities": {}}
    target = {"object_path": path, "properties": {}}
    spec["series"] = [{"name": "series_1", "presentation_kind": "curve"}]
    legend_properties(obj, target, selected["objects"][path], spec)
    return {"legend:key1": obj}, {"legend:key1": target}


def test_inspected_legacy_sample_length_compiles_exact_binding_and_keeps_science():
    objects, targets = _legend_imported()
    before = _document(objects)
    patch = _patch("6mm", prop="legend.sample_length")
    patch["changes"][0]["target"] = ["legend:key1"]
    after, diff, risk = apply_patch(before, patch)
    assert risk == "presentation" and after["scientific_hash"] == before["scientific_hash"]
    changes, operations, updated = compile_diff(before, {"targets": targets}, after, diff)
    assert operations is None
    assert changes == [{"object_path": "/page1/graph1/key1", "setting_path": "/page1/graph1/key1/keyLength",
                        "expected_value": "0.40cm", "value": "6mm"}]
    assert updated["targets"]["legend:key1"]["properties"]["legend.sample_length"]["current_value"] == "6mm"


@pytest.mark.parametrize("kwargs", [{"inspected": False}, {"length": "0mm"}, {"length": "auto"},
                                    {"path": "/page1/graph1/other_key"}, {"template": "bar"}])
def test_uninspected_or_unsupported_legend_sample_length_stays_opaque(kwargs):
    objects, _ = _legend_imported(**kwargs)
    assert "legend.sample_length" not in objects["legend:key1"]["capabilities"]


@pytest.mark.parametrize("value", ["0mm", "-2mm", "NaNmm", "1px", 6])
def test_sample_length_rejects_bad_physical_grammar(value):
    objects, _ = _legend_imported()
    patch = _patch(value, prop="legend.sample_length")
    patch["changes"][0]["target"] = ["legend:key1"]
    with pytest.raises(DocumentError):
        apply_patch(_document(objects), patch)


@pytest.mark.parametrize("bounds", [(0, 0, 100, 20), (-1, 2, 15, 20), (2, -1, 15, 20),
                                     (2, 2, 15, 100), (float("nan"), 2, 15, 20)])
def test_native_key_bounds_reject_overflow_negative_and_nonfinite_before_save(monkeypatch, bounds):
    from sciplot_core.veusz_worker import document_edit
    from sciplot_core.veusz_audit import pages

    widget = object()
    class ControlKey:
        pass
    control = ControlKey()
    control.widget, control.posn, control.dims = widget, bounds[:2], bounds[2:]
    helper = SimpleNamespace(getControlGraph=lambda _widget: [control], states={1: 2}, rootstate=object())
    states = {"/key": {"page": 1, "helper": helper}}
    monkeypatch.setattr(pages, "collect_page_geometry", lambda *_: (states, [{"page": 1, "bounds_mm": [0, 0, 30, 30]}]))
    monkeypatch.setattr(document_edit, "import_module", lambda name: SimpleNamespace(PaintHelper=object, ControlKey=ControlKey))
    loaded = SimpleNamespace(resolveWidgetPath=lambda *_: widget)
    with pytest.raises(ValueError, match="fit inside"):
        document_edit._check_legend_sample_bounds(loaded, [{"object_path": "/key", "setting_path": "/key/keyLength"}])
    assert states == {} and helper.states == {} and helper.rootstate is None


def test_non_color_and_low_grayscale_negative_controls_remain_strict():
    from sciplot_core.qa.accessibility import _series_accessibility_report
    series = [{"path": name, "graph_path": "/graph", "page": 1, "plot_line_visible": True,
               "marker_visible": False, "line_style": "solid", "color": {"rgb": [0.2, 0.2, 0.2]},
               "rendered_colors": [{"role": "line", "color": {"rgb": [0.2, 0.2, 0.2]}}]}
              for name in ("a", "b")]
    profile = {"accessibility": {"non_color_distinction_required": True}}
    pdfs = [{"vector_colors": {"unique_rgb": [[0.2, 0.2, 0.2]]}}]
    audit = {"documents": [{"path": "native", "series": series}]}
    repeated = _series_accessibility_report(audit, pdfs, profile)
    assert not repeated["passed"] and not repeated["pairs"][0]["non_color_distinct"]
    assert not repeated["pairs"][0]["grayscale_accessible"]
    series[1]["line_style"] = "dashed"
    assert _series_accessibility_report(audit, pdfs, profile)["passed"]
    for item in series:
        item.update(plot_line_visible=False, marker_visible=True, marker="circle")
    assert not _series_accessibility_report(audit, pdfs, profile)["passed"]


@pytest.mark.parametrize("case", ["missing-state", "missing-control", "two-controls", "nan-page", "zero-page"])
def test_native_sample_bounds_reject_incomplete_geometry(monkeypatch, case):
    from sciplot_core.veusz_worker import document_edit
    from sciplot_core.veusz_audit import pages

    widget = object()
    class ControlKey:
        pass
    control = ControlKey()
    control.widget, control.posn, control.dims = widget, (2, 2), (15, 20)
    controls = [] if case == "missing-control" else [control, control] if case == "two-controls" else [control]
    helper = SimpleNamespace(getControlGraph=lambda _widget: controls, states={}, rootstate=None)
    states = {} if case == "missing-state" else {"/key": {"page": 1, "helper": helper}}
    page_bounds = [0, 0, float("nan") if case == "nan-page" else 0 if case == "zero-page" else 30, 30]
    monkeypatch.setattr(pages, "collect_page_geometry", lambda *_: (states, [{"page": 1, "bounds_mm": page_bounds}]))
    monkeypatch.setattr(document_edit, "import_module", lambda name: SimpleNamespace(PaintHelper=object, ControlKey=ControlKey))
    with pytest.raises(ValueError):
        document_edit._check_legend_sample_bounds(SimpleNamespace(resolveWidgetPath=lambda *_: widget),
            [{"object_path": "/key", "setting_path": "/key/keyLength"}])
    # All other edit batches retain their existing path, with no geometry query.
    monkeypatch.setattr(pages, "collect_page_geometry", lambda *_: pytest.fail("unexpected geometry audit"))
    document_edit._check_legend_sample_bounds(None, [{"object_path": "/key", "setting_path": "/key/Text/size"}])
