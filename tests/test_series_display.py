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
