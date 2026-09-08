from __future__ import annotations

import copy
import json

import pytest

from sciplot_core.cli import main
from sciplot_core.studio_core import annotation_operations as operations, document_edit
from sciplot_core.studio_core.annotation_schema import AnnotationOperationError, validate_operation_batch


def reference():
    return {"op": "add_reference_line", "id": "reference450", "parent_path": "/page1/graph1",
            "axis": "x", "value": 450, "unit": "nm"}


def test_shape_validation_preserves_all_supported_operation_families():
    line = reference()
    note = {"op": "add_annotation", "id": "note", "parent_path": "/page1/graph1", "text": "note",
            "position": {"mode": "relative", "x": 0.5, "y": 0.5}}
    candidate = {"kind": "sciplot_observed_peak", "version": 1,
        "object_path": "/page1/graph1/series_1", "sample": "A", "series_signature": "a" * 64,
        "window": {"min": 400, "max": 500, "unit": "nm"}, "polarity": "maximum",
        "method": "strict_discrete_interior_extremum_v1", "point_index": 1,
        "x": 450, "y": 2, "x_unit": "nm", "y_unit": "a.u.", "candidate_id": "b" * 64,
        "document_sha256": "c" * 64, "figure_id": "f"}
    batch = [line, note, {"op": "add_peak_label", "id": "peak", "candidate": candidate},
             {"op": "remove_annotation", "id": line["id"], "expected_annotation": line},
             {"op": "update_annotation", "id": note["id"], "expected_annotation": note,
              "replacement": {**note, "text": "updated"}},
             {"op": "set_sample_style", "samples": ["A"], "style": {"width": "2pt"}},
             {"op": "set_style", "object_path": "/page1/graph1/series_1",
              "setting_path": "/page1/graph1/series_1/PlotLine/color", "expected_value": "black", "value": "red"}]
    before = copy.deepcopy(batch)
    validate_operation_batch(batch)
    assert batch == before  # No normalization or scientific interpretation here.


@pytest.mark.parametrize("batch", [None, [], [1], [reference()] * 101,
    [{"op": []}], [{**reference(), "extra": "field"}], [{**reference(), "value": True}],
    [{**reference(), "value": float("nan")}], [{**reference(), "value": float("inf")}],
    [{"op": "set_sample_style", "samples": ["A", "A"], "style": {"width": "2pt"}}],
    [{"op": "set_sample_style", "samples": ["A"], "style": {"width": 2}}],
    [{"op": "update_annotation", "id": "note", "expected_annotation": reference(),
      "replacement": {"op": "add_annotation", "id": "note"}}],
])
def test_malformed_preview_fails_before_project_or_native_io(tmp_path, monkeypatch, batch):
    def unnecessary(*args, **kwargs):
        pytest.fail("Malformed batch reached project/native I/O")
    monkeypatch.setattr(operations, "resolve_project_figure", unnecessary)
    monkeypatch.setattr(operations, "inspect_project", unnecessary)
    monkeypatch.setattr(document_edit, "preview_document_edit", unnecessary)
    with pytest.raises(AnnotationOperationError):
        operations.preview_document_operations(tmp_path / "missing", batch,
            output_dir=tmp_path / "preview", expected_document_sha256="a" * 64)
    assert not list(tmp_path.iterdir())


def test_invalid_field_error_is_specific_and_bounded():
    with pytest.raises(AnnotationOperationError) as failure:
        validate_operation_batch([{"op": "set_sample_style", "samples": ["A"], "style": {"width": 2}}])
    assert failure.value.field == "operations/0/style/width"
    assert "string" in str(failure.value)
    with pytest.raises(AnnotationOperationError) as failure:
        validate_operation_batch([{**reference(), "unexpected_" + "x" * 10000: "field"}])
    assert len(str(failure.value)) < 600


def test_structurally_valid_scientific_errors_still_reach_existing_owner(tmp_path, monkeypatch):
    batch = [{**reference(), "unit": "wrong but string-shaped"}]
    calls = []
    def native(*args, **kwargs):
        calls.append(kwargs["operations"])
        raise AnnotationOperationError("unit_mismatch", "Existing scientific owner rejected units")
    monkeypatch.setattr(document_edit, "preview_document_edit", native)
    with pytest.raises(AnnotationOperationError) as failure:
        operations.preview_document_operations(tmp_path, batch, output_dir=tmp_path / "preview",
                                              expected_document_sha256="a" * 64)
    assert failure.value.reason_code == "unit_mismatch" and calls == [batch]


def test_cli_operations_preview_returns_shape_error_before_missing_project(tmp_path, capsys):
    path = tmp_path / "operations.json"
    path.write_text(json.dumps([{"op": "set_style"}]))
    assert main(["project", "operations-preview", str(tmp_path / "missing"),
                 "--operations", str(path), "--expected-document", "a" * 64,
                 "--out", str(tmp_path / "preview"), "--json"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["reason_code"] == "invalid_operation"
    assert "required property" in result["message"] and "Traceback" not in result["message"]
    assert not (tmp_path / "preview").exists()
