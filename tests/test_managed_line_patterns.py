"""Managed line patterns share the existing visible native style authority."""

from copy import deepcopy
import json

import pytest

from sciplot_core.plot_backends.figure_marks import line_settings
from sciplot_core.plot_backends.managed_plan import drawing_plan
from sciplot_core.plot_document import DocumentError, seal_document
from sciplot_core.plot_grammar.styles import style_schema as figure_style_schema
from sciplot_core.plot_ir import compile_document, create_managed_document, seal_ir, validate_ir, validate_managed
from sciplot_core.plot_ir.schema import style_schema as cartesian_style_schema
from sciplot_core.policy.frame_export import DEFAULT_LINE_STYLE_SEQUENCE
from sciplot_core.style_values import LINE_STYLE_VALUES, normalize_line_style
from test_figure_grammar import example, resolve
from test_managed_backend import managed_ir


def pattern_ir(mode, pattern):
    if mode == "v1":
        ir = managed_ir()
        ir["series"][0]["style"]["line_style"] = pattern
        return seal_ir(ir)
    spec, datasets = example()
    if mode == "v2-house":
        from sciplot_core.rendering_contract import contract_binding
        spec["rendering_contract"] = contract_binding()
    line = next(mark for mark in spec["views"][0]["layers"][0]["marks"] if mark["type"] == "line")
    line["style"]["line_style"] = pattern
    return resolve(spec, datasets)


def test_managed_schemas_derive_the_existing_catalog_and_only_historical_aliases():
    expected = [*DEFAULT_LINE_STYLE_SEQUENCE, "dash", "dot"]
    assert list(LINE_STYLE_VALUES) == expected
    assert len(set(expected)) == len(expected) == 9
    assert cartesian_style_schema()["properties"]["line_style"]["enum"] == expected
    for kind in ("line", "rule"):
        assert figure_style_schema(kind)["properties"]["line_style"]["enum"] == expected


@pytest.mark.parametrize("pattern", LINE_STYLE_VALUES)
def test_every_visible_pattern_compiles_identically_in_v1_v2_and_both_legend_paths(pattern):
    expected = {"dash": "dashed", "dot": "dotted"}.get(pattern, pattern)
    assert normalize_line_style(pattern) == expected
    for mode in ("v1", "v2", "v2-house"):
        ir = pattern_ir(mode, pattern)
        assert validate_ir(json.loads(json.dumps(ir))) == ir
        nodes = drawing_plan(ir)
        curve_patterns = [node["settings"]["PlotLine/style"] for node in nodes
                          if "PlotLine/style" in node["settings"]]
        assert curve_patterns and set(curve_patterns) == {expected}
        if mode == "v2":
            symbols = [node["settings"]["Line/style"] for node in nodes if "Line/style" in node["settings"]]
            assert symbols and set(symbols) == {expected}
        if mode == "v2-house":
            assert len(curve_patterns) == 2  # original curve and native key symbol provider
        style = {"line_color": "#123456", "line_width_pt": .7, "line_style": pattern}
        assert line_settings(style)["Line/style"] == expected
        assert line_settings(style, "PlotLine")["PlotLine/style"] == expected


@pytest.mark.parametrize("mode", ["v1", "v2", "v2-house"])
@pytest.mark.parametrize("alias,canonical", [("dash", "dashed"), ("dot", "dotted")])
def test_historical_ir_aliases_replay_without_rewriting_their_stored_value(mode, alias, canonical):
    historical = pattern_ir(mode, alias)
    restored = validate_ir(json.loads(json.dumps(historical)))
    assert restored == historical
    assert drawing_plan(restored) == drawing_plan(pattern_ir(mode, canonical))
    style = (restored["series"][0]["style"] if mode == "v1"
             else next(mark["style"] for mark in restored["views"][0]["layers"][0]["marks"] if mark["type"] == "line"))
    assert style["line_style"] == alias


@pytest.mark.parametrize("invalid", ["none", "dash1", "dashdot", "invented", "", None, False, ["dash-dot"]])
def test_unknown_or_hidden_patterns_are_rejected_by_both_schemas_before_native(invalid):
    with pytest.raises(ValueError):
        normalize_line_style(invalid)
    for mode in ("v1", "v2", "v2-house"):
        with pytest.raises(DocumentError):
            pattern_ir(mode, invalid)


def test_cartesian_style_creation_keeps_scientific_authority_and_source_masks():
    from sciplot_core.plot_transforms import resolve_transforms
    from test_plot_ir import managed_example
    template, binding, datasets = managed_example()
    before = resolve_transforms(create_managed_document(template, binding, plot_id="patterns"), datasets)["document"]
    template["presentation"]["layout"]["series_styles"]["slot:A"]["line_style"] = "dash-dot"
    after = resolve_transforms(create_managed_document(template, binding, plot_id="patterns"), datasets)["document"]
    assert after["scientific"] == before["scientific"]
    assert after["scientific_hash"] == before["scientific_hash"]
    assert after["presentation_hash"] != before["presentation_hash"]
    assert compile_document(after)["datasets"] == compile_document(before)["datasets"]
    assert compile_document(after)["series"][0]["y"] == [.5, None, 1]


def test_existing_figure_style_patch_and_rebuild_preserve_science_and_other_styles(tmp_path):
    from sciplot_core.plot_engine.managed_updates import prepare_update
    from test_figure_document import request_for_figure
    request = request_for_figure(tmp_path)
    document = create_managed_document(request["template_definition"], request["data_binding"], plot_id="patterns")
    document["scientific"]["provenance"]["datasets"] = example()[1]
    document = seal_document(document)
    mark = next(mark for mark in request["template_definition"]["figure_spec"]["views"][0]["layers"][0]["marks"]
                if mark["type"] == "line")
    style = {**mark["style"], "line_style": "dash-dot"}
    patch = {"plot_id": "patterns", "base_revision": 0, "idempotency_key": "pattern", "intent_class": "presentation",
             "changes": [{"op": "set", "target": [mark["id"]], "property": "style", "value": style}]}
    changed, diff, risk, execute = prepare_update(document, patch)
    assert risk == "presentation" and not execute and len(diff) == 1
    assert changed["scientific"] == document["scientific"]
    assert changed["scientific_hash"] == document["scientific_hash"]
    assert changed["presentation_hash"] != document["presentation_hash"]
    before, after = compile_document(document), compile_document(changed)
    assert before["datasets"] == after["datasets"]
    restored = validate_managed(json.loads(json.dumps(changed)))
    assert compile_document(restored) == after
    repeated, repeated_diff, repeated_risk, _execute = prepare_update(changed, patch)
    assert repeated == changed and repeated_diff == [] and repeated_risk == "presentation"
    new_line = next(mark for mark in after["views"][0]["layers"][0]["marks"] if mark["type"] == "line")
    old_line = next(mark for mark in before["views"][0]["layers"][0]["marks"] if mark["type"] == "line")
    assert new_line["style"] == {**old_line["style"], "line_style": "dash-dot"}


@pytest.mark.parametrize("mode", ["v1", "v2", "v2-house"])
def test_existing_complete_native_comparison_detects_dash_dot_changed_to_dashed(mode, monkeypatch):
    from sciplot_core.plot_backends import managed_audit
    ir = pattern_ir(mode, "dash-dot")
    expected = {"widgets": {node["path"]: {"type": node["type"], "children": [], "settings": deepcopy(node["settings"])}
                            for node in drawing_plan(ir)},
                "datasets": deepcopy(ir["datasets"]), "customs": {}, "setting_bindings": {}}
    actual = deepcopy(expected)
    path = next(path for path, widget in actual["widgets"].items()
                if widget["settings"].get("PlotLine/style") == "dash-dot" and widget["settings"].get("xData"))
    actual["widgets"][path]["settings"]["PlotLine/style"] = "dashed"
    monkeypatch.setattr(managed_audit, "native_state", deepcopy)
    assert managed_audit.compare_native(ir, expected, expected)["status"] == "unchanged"
    compared = managed_audit.compare_native(ir, expected, actual)
    assert compared["status"] == "external_mutation" and compared["opaque_native_change"]
    assert compared["native_differences"] == [{"path": path, "setting": "PlotLine/style", "before": "dash-dot", "after": "dashed"}]
    assert actual["datasets"] == expected["datasets"]
