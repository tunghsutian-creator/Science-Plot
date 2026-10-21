"""Closed, atomic layout editing and history with source science kept opaque."""

from copy import deepcopy

import pytest

from sciplot_core.panel_assembly import AssemblyError
from sciplot_core.panel_assembly.history import AssemblyHistory
from sciplot_core.panel_assembly.model import (
    apply_operations, new_document, operation_capabilities, resolve_document, validate_document,
)
from sciplot_core.rendering_contract import COMPOSITION_CONTRACT_ID, contract_binding, contract_value


def source(kind="image", name="one"):
    fields = {"path": f"/{name}.png"} if kind == "image" else {
        "project": f"/{name}", "figure_id" if kind == "project" else "plot_id": "figure:one"}
    return {"kind": kind, **fields, "binding": {"snapshot": {"sha256": "a" * 64}}}


def panel(identity="panel:a", row=0, column=0, **fields):
    return {"id": identity, "source": source(), "row": row, "column": column,
            "row_span": 1, "column_span": 1, "label": None, "crop": None, **fields}


def add(*panels, document=None):
    return apply_operations(new_document() if document is None else document,
                            [{"op": "add_panel", "panel": item} for item in panels])


def test_sparse_empty_document_resolves_without_source_reads():
    document = new_document(rows=3, columns=2, width_mm=180, height_mm=140)
    assert resolve_document(document) == {"width_mm": 180.0, "height_mm": 140.0, "panels": []}
    assert document["revision"] == 0
    copy = validate_document(document)
    copy["layout"]["rows"] = 2
    assert document["layout"]["rows"] == 3


def test_new_assembly_spacing_uses_the_existing_composition_contract():
    binding = contract_binding(COMPOSITION_CONTRACT_ID)
    layout = new_document()["layout"]
    assert layout["gap_x_mm"] == contract_value("gap_x_mm", binding) == 6
    assert layout["gap_y_mm"] == contract_value("gap_y_mm", binding) == 6


def test_reading_order_labels_custom_case_and_physical_spans_are_deterministic():
    document = add(panel("panel:b", 1, 0, column_span=2, label="BETA"), panel("panel:a"))
    result = resolve_document(document)
    assert result == resolve_document(deepcopy(document))
    assert [item["id"] for item in result["panels"]] == ["panel:a", "panel:b"]
    first, second = result["panels"]
    assert [first["label"], second["label"]] == ["a", "BETA"]
    assert first["cell_mm"] == [0, 0, 87, 67]
    assert first["content_mm"] == [2, 8, 83, 57]
    assert first["label_mm"] == [1, 3]
    assert second["cell_mm"] == [0, 73, 180, 67]
    assert second["content_mm"][2] == 176
    blank = apply_operations(document, [{"op": "set_label", "id": "panel:a", "label": ""}])
    assert resolve_document(blank)["panels"][0]["label_mm"] is None


def test_automatic_labels_extend_beyond_the_alphabet():
    document = add(*(panel(f"panel:{index}", index // 7, index % 7) for index in range(28)),
                   document=new_document(rows=4, columns=7, width_mm=300, height_mm=200))
    assert [item["label"] for item in resolve_document(document)["panels"]][-3:] == ["z", "aa", "ab"]


@pytest.mark.parametrize("label", ["é", "中", "A\n", "\n", "\t", "\x7f", "A" * 17])
def test_outer_panel_labels_reject_nonprintable_and_nonascii_text_before_resolution(label):
    document = add(panel())
    with pytest.raises(AssemblyError):
        apply_operations(document, [{"op": "set_label", "id": "panel:a", "label": label}])
    with pytest.raises(AssemblyError):
        add(panel(label=label))


def test_outer_panel_labels_preserve_printable_ascii_punctuation_and_case():
    document = add(panel(label=" (A)-1 "))
    assert resolve_document(document)["panels"][0]["label"] == " (A)-1 "


def test_whole_batch_can_pass_through_overlap_then_swap_without_mutating_input():
    document = add(panel("panel:a"), panel("panel:b", 0, 1))
    before = deepcopy(document)
    changed = apply_operations(document, [
        {"op": "move_panel", "id": "panel:a", "row": 0, "column": 1},
        {"op": "move_panel", "id": "panel:b", "row": 0, "column": 0}])
    assert document == before
    assert changed["revision"] == before["revision"] + 1
    assert [item["column"] for item in changed["panels"]] == [1, 0]
    restored = apply_operations(changed, [{"op": "move_panel", "id": "panel:a", "row": 0, "column": 0, "swap": True}])
    assert restored["panels"] == document["panels"]


def test_grid_reduction_is_validated_after_the_entire_batch():
    document = add(panel("panel:a", 1, 1))
    changed = apply_operations(document, [{"op": "set_grid", "rows": 1, "columns": 1},
        {"op": "move_panel", "id": "panel:a", "row": 0, "column": 0},
        {"op": "set_spacing", "gap_x_mm": 0, "gap_y_mm": 0},
        {"op": "set_page", "width_mm": 90, "height_mm": 70}])
    assert resolve_document(changed)["panels"][0]["cell_mm"] == [0, 0, 90, 70]


@pytest.mark.parametrize("operation", [
    {"op": "set_spacing", "gap_x_mm": float("nan"), "gap_y_mm": 1},
    {"op": "set_page", "width_mm": float("inf"), "height_mm": 100},
    {"op": "set_page", "width_mm": 0, "height_mm": 100},
    {"op": "set_grid", "rows": True, "columns": 2},
    {"op": "set_grid", "rows": 1.0, "columns": 2},
    {"op": "set_spacing", "gap_x_mm": -1, "gap_y_mm": 1},
    {"op": "set_grid", "rows": 17, "columns": 2},
    {"op": "set_label", "id": "panel:a", "label": "x", "unsupported": 1},
    {"op": "fit_scientific_data", "id": "panel:a"},
])
def test_closed_operations_reject_nonfinite_implicit_and_unknown_state(operation):
    document = add(panel())
    before = deepcopy(document)
    with pytest.raises(AssemblyError):
        apply_operations(document, [operation])
    assert document == before


@pytest.mark.parametrize("operation,code", [
    ({"op": "set_span", "id": "panel:a", "row_span": 2, "column_span": 2}, "figure_layout_cell"),
    ({"op": "move_panel", "id": "panel:a", "row": 2, "column": 0}, "figure_layout_cell"),
    ({"op": "set_grid", "rows": 1, "columns": 1}, "figure_layout_cell"),
    ({"op": "set_page", "width_mm": 5, "height_mm": 5}, "figure_layout_no_space"),
    ({"op": "set_spacing", "gap_x_mm": 180, "gap_y_mm": 1}, "figure_layout_no_space"),
    ({"op": "remove_panel", "id": "panel:absent"}, "assembly_panel_missing"),
])
def test_invalid_result_refuses_the_complete_batch(operation, code):
    document = add(panel(), panel("panel:b", 1, 1))
    before = deepcopy(document)
    with pytest.raises(AssemblyError) as captured:
        apply_operations(document, [{"op": "set_label", "id": "panel:a", "label": "Changed"}, operation])
    assert captured.value.code == captured.value.reason_code == code
    assert document == before


@pytest.mark.parametrize("crop", [[0, 0, 1, 0], [0.8, 0, 0.2, 1], [-0.1, 0, 1, 1], [0, 0, 1.1, 1], (0, 0, 1, 1)])
def test_crop_requires_a_normalized_positive_json_rectangle(crop):
    with pytest.raises(AssemblyError):
        apply_operations(add(panel()), [{"op": "set_crop", "id": "panel:a", "crop": crop}])


@pytest.mark.parametrize("kind", ["project", "managed"])
def test_crop_never_applies_to_scientific_panels_or_replacement(kind):
    document = add(panel(source=source(kind)))
    with pytest.raises(AssemblyError, match="Only image"):
        apply_operations(document, [{"op": "set_crop", "id": "panel:a", "crop": [0.1, 0.2, 0.8, 0.9]}])
    cropped = add(panel(crop=[0.1, 0.2, 0.8, 0.9]))
    with pytest.raises(AssemblyError, match="Only image"):
        apply_operations(cropped, [{"op": "replace_panel", "id": "panel:a", "source": source(kind)}])


def test_source_replacement_preserves_stable_layout_crop_and_label():
    document = add(panel(column_span=2, label="KeepCase", crop=[0.1, 0.2, 0.8, 0.9]))
    changed = apply_operations(document, [{"op": "replace_panel", "id": "panel:a", "source": source(name="other")}])
    expected = {**document["panels"][0], "source": source(name="other")}
    assert changed["panels"] == [expected]
    assert document["panels"][0]["source"]["path"] == "/one.png"
    assert resolve_document(changed) == resolve_document(document)


def test_source_binding_and_document_are_closed_finite_and_detached():
    document = add(panel())
    for change in (
        lambda value: value.update(unknown=1),
        lambda value: value["layout"].update(unknown=1),
        lambda value: value["panels"][0]["source"].update(unknown=1),
        lambda value: value["panels"][0]["source"].update(binding={}),
        lambda value: value["panels"][0]["source"]["binding"].update(bad=float("nan")),
        lambda value: value.update(revision=1.0),
        lambda value: value["panels"].append(deepcopy(value["panels"][0])),
    ):
        invalid = deepcopy(document)
        change(invalid)
        with pytest.raises(AssemblyError):
            validate_document(invalid)
    cloned = validate_document(document)
    cloned["panels"][0]["source"]["binding"]["snapshot"]["sha256"] = "b" * 64
    assert document["panels"][0]["source"]["binding"]["snapshot"]["sha256"] == "a" * 64


def test_swap_rejects_an_interior_span_anchor_and_invalid_span_after_exchange():
    document = add(panel(), panel("panel:b", 1, 0, column_span=2))
    with pytest.raises(AssemblyError, match="starting cell"):
        apply_operations(document, [{"op": "move_panel", "id": "panel:a", "row": 1, "column": 1, "swap": True}])
    with pytest.raises(AssemblyError):
        apply_operations(document, [{"op": "move_panel", "id": "panel:b", "row": 0, "column": 1, "swap": True}])


def test_history_keeps_monotonic_revisions_detached_snapshots_and_branch_semantics():
    original = add(panel())
    history = AssemblyHistory(original)
    assert not history.can_undo and not history.can_redo
    applied = history.apply([{"op": "set_label", "id": "panel:a", "label": "X"}])
    applied["panels"].clear()
    assert history.document["panels"][0]["label"] == "X"
    undone = history.undo()
    assert undone["panels"] == original["panels"] and undone["revision"] == original["revision"] + 2
    assert history.can_redo and not history.can_undo
    redone = history.redo()
    assert redone["panels"][0]["label"] == "X" and redone["revision"] == undone["revision"] + 1
    history.undo()
    history.apply([{"op": "set_label", "id": "panel:a", "label": "Branch"}])
    assert not history.can_redo
    with pytest.raises(AssemblyError, match="history"):
        history.redo()


def test_failed_apply_keeps_history_and_future_redo_unchanged():
    history = AssemblyHistory(add(panel()))
    history.apply([{"op": "remove_panel", "id": "panel:a"}])
    history.undo()
    before = history.document
    with pytest.raises(AssemblyError):
        history.apply([{"op": "set_span", "id": "panel:a", "row_span": 3, "column_span": 1}])
    assert history.document == before and history.can_redo and not history.can_undo
    assert history.redo()["panels"] == []


def test_operation_capabilities_are_a_detached_exact_closed_contract():
    schema = operation_capabilities()
    names = {branch["properties"]["op"]["const"] for branch in schema["operations"]["items"]["oneOf"]}
    assert names == {"add_panel", "remove_panel", "move_panel", "set_span", "set_grid", "set_spacing", "set_page",
                     "set_label", "set_crop", "replace_panel"}
    schema["operations"]["items"]["oneOf"].clear()
    assert len(operation_capabilities()["operations"]["items"]["oneOf"]) == 10
