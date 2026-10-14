from copy import deepcopy

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
