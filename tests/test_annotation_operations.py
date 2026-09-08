from __future__ import annotations

import copy
import json

import pytest

from sciplot_core.studio_core.annotation_contracts import annotation_records, normalize_annotation
from sciplot_core.studio_core.annotation_geometry import annotation_widgets
from sciplot_core.studio_core.annotation_operations import compile_annotation_operations
from sciplot_core.studio_core.annotation_schema import AnnotationOperationError
from sciplot_core.studio_core.peak_analysis import peak_candidates_for_spec, validate_peak_candidate
from sciplot_core.studio_core.document_edit_state import edit_state, preview_identity, history_directory
from sciplot_core.studio_core import document_edit_commit as commit
from sciplot_core.studio_core.sample_style import expand_sample_styles, sample_style_targets


@pytest.fixture
def spec():
    return {"template": "curve", "axes": {
        "x": {"label": "Wavelength (nm)", "min": 400, "max": 500, "scale": "linear"},
        "y": {"label": "Absorbance (a.u.)", "min": 0, "max": 5, "scale": "linear"}},
        "series": [{"name": "series_1", "label": "A", "x_name": "x", "y_name": "y",
                    "x_values": [400, 425, 450, 475, 500], "y_values": [1, 3, 1, 4, 2],
                    "presentation_kind": "curve", "source_artifacts": []}]}


def note(identifier="note"):
    return {"op": "add_annotation", "id": identifier, "parent_path": "/page1/graph1",
            "text": "Observed peak", "position": {"mode": "axes", "x": 450, "y": 4.5,
                                                     "x_unit": "nm", "y_unit": "a.u."},
            "arrow_to": {"mode": "axes", "x": 425, "y": 3, "x_unit": "nm", "y_unit": "a.u."}}


def compile_ops(spec, operations):
    return compile_annotation_operations(spec, operations, document_sha256="d" * 64, figure_id="f")


def _sample_objects(*names):
    return {f"/page1/graph1/{name}": {"editable_fields": [
        {"setting_path": f"/page1/graph1/{name}/PlotLine/color", "current_value": "#222222"},
        {"setting_path": f"/page1/graph1/{name}/PlotLine/width", "current_value": "1.2pt"},
    ]} for name in names}


def test_sample_batch_binds_exact_labels_to_current_fields_and_keeps_other_ops(spec):
    spec["series"].append({**spec["series"][0], "name": "series_2", "label": "B"})
    before = copy.deepcopy(spec)
    request = {"op": "set_sample_style", "samples": ["B", "A"],
               "style": {"color": "#3568C0", "width": "1.5pt"}}
    operations = [request, note()]
    expanded = expand_sample_styles(spec, _sample_objects("series_1", "series_2"), operations)
    assert [op["object_path"] for op in expanded[:-1]] == [
        "/page1/graph1/series_2", "/page1/graph1/series_2",
        "/page1/graph1/series_1", "/page1/graph1/series_1"]
    assert [op["expected_value"] for op in expanded[:-1]] == ["#222222", "1.2pt"] * 2
    assert expanded[-1] == note() and operations[0] == request
    assert spec == before
    assert compile_ops(spec, expanded)[2][-1]["id"] == "note"


@pytest.mark.parametrize("samples,style", [([], {"color": "red"}), (["A", "A"], {"color": "red"}),
                                         (["A"], {}), (["A"], {"label": "Wrong sample"}),
                                         ([None], {"width": "2pt"})])
def test_sample_batch_rejects_invalid_or_scientific_fields(spec, samples, style):
    with pytest.raises(AnnotationOperationError, match="unique exact"):
        expand_sample_styles(spec, _sample_objects("series_1"), [
            {"op": "set_sample_style", "samples": samples, "style": style}])


def test_sample_batch_does_not_guess_aliases_or_edit_ambiguous_semantic_curves(spec):
    operation = {"op": "set_sample_style", "samples": ["a"], "style": {"color": "red"}}
    with pytest.raises(AnnotationOperationError, match="exact sample label"):
        expand_sample_styles(spec, _sample_objects("series_1"), [operation])
    operation["samples"] = ["A"]
    spec["series"].append({**spec["series"][0], "name": "series_2"})
    assert sample_style_targets(spec) == [{"sample": "A", "object_paths": [
        "/page1/graph1/series_1", "/page1/graph1/series_2"], "unique": False}]
    with pytest.raises(AnnotationOperationError, match="multiple curves"):
        expand_sample_styles(spec, _sample_objects("series_1", "series_2"), [operation])
    spec["performance_comparison"] = {"kind": "semantic"}
    assert sample_style_targets(spec) == []
    with pytest.raises(AnnotationOperationError, match="No ordinary curve"):
        expand_sample_styles(spec, _sample_objects("series_1", "series_2"), [operation])


def test_sample_batch_requires_native_capability_and_bounds_expansion(spec):
    request = {"op": "set_sample_style", "samples": ["A"], "style": {"color": "red"}}
    with pytest.raises(AnnotationOperationError, match="does not advertise"):
        expand_sample_styles(spec, {}, [request])
    request["style"]["width"] = "2pt"
    with pytest.raises(AnnotationOperationError, match="exceeds 100"):
        expand_sample_styles(spec, _sample_objects("series_1"), [request] * 51)


def test_sample_preview_binds_mapping_hash_before_native_transaction(tmp_path, monkeypatch, spec):
    from sciplot_core.studio_core import annotation_operations as service, document_edit
    from sciplot_core.foundation.file_hashing import file_sha256

    path = tmp_path / "spec.json"
    path.write_text(json.dumps(spec))
    selected = {"figure_id": "f", "document_sha256": "d" * 64, "spec": str(path),
                "spec_sha256": file_sha256(path), "objects": _sample_objects("series_1")}
    monkeypatch.setattr(service, "resolve_project_figure", lambda *a: selected)
    monkeypatch.setattr(service, "inspect_project", lambda *a, **k: {"selected_figure": selected})
    calls = []
    monkeypatch.setattr(document_edit, "preview_document_edit", lambda *a, **k: calls.append(k) or {})
    operation = {"op": "set_sample_style", "samples": ["A"], "style": {"color": "red"}}
    service.preview_document_operations(tmp_path, [operation], output_dir=tmp_path / "preview",
                                        expected_document_sha256="d" * 64)
    assert calls[0]["expected_spec_sha256"] == file_sha256(path)
    assert calls[0]["operations"][0]["expected_value"] == "#222222"
    path.write_text(json.dumps({**spec, "series": []}))
    with pytest.raises(AnnotationOperationError, match="mapping changed"):
        service.preview_document_operations(tmp_path, [operation], output_dir=tmp_path / "preview2",
                                            expected_document_sha256="d" * 64)
    assert len(calls) == 1


def test_mixed_batch_preserves_science_and_expands_arrow(spec):
    baseline = copy.deepcopy(spec)
    style = {"op": "set_style", "object_path": "/page1/graph1/x", "setting_path": "/page1/graph1/x/Label/size",
             "expected_value": "8pt", "value": "9pt"}
    styles, after, changes = compile_ops(spec, [style, note()])
    assert spec == baseline
    assert styles == [{k: v for k, v in style.items() if k != "op"}]
    assert {k: v for k, v in after.items() if k != "native_annotations"} == baseline
    widgets = annotation_widgets(after)
    assert [w["type"] for w in widgets] == ["label", "line"]
    assert widgets[1]["settings"]["arrowright"] == "arrow"
    assert changes[0]["after"] == annotation_records(after)[0]


@pytest.mark.parametrize("patch,code", [
    ({"x_unit": "cm"}, "unit_mismatch"), ({"x": float("nan")}, "invalid_coordinate"),
    ({"x": 900}, "coordinate_out_of_bounds"), ({"x": "x[2]"}, "invalid_coordinate"),
])
def test_bad_units_coordinates_and_expressions_fail_before_mutation(spec, patch, code):
    operation = note()
    operation["position"].update(patch)
    with pytest.raises(AnnotationOperationError) as error:
        compile_ops(spec, [operation])
    assert error.value.reason_code == code
    assert "native_annotations" not in spec


def test_closed_schema_and_semantic_scope(spec):
    operation = note()
    operation["python"] = "print('no')"
    with pytest.raises(AnnotationOperationError, match="unadvertised"):
        compile_ops(spec, [operation])
    spec["scalar_field"] = {}
    with pytest.raises(AnnotationOperationError, match="Cartesian"):
        compile_ops(spec, [note()])


def test_update_remove_require_exact_current_record(spec):
    _, added, _ = compile_ops(spec, [note()])
    record = annotation_records(added)[0]
    wrong = {**record, "text": "old"}
    with pytest.raises(AnnotationOperationError, match="exact annotation"):
        compile_ops(added, [{"op": "remove_annotation", "id": "note", "expected_annotation": wrong}])
    replacement = {**note(), "text": "Reviewed peak"}
    _, updated, _ = compile_ops(added, [{"op": "update_annotation", "id": "note",
                                       "expected_annotation": record, "replacement": replacement}])
    current = annotation_records(updated)[0]
    assert current["text"] == "Reviewed peak"
    _, removed, _ = compile_ops(updated, [{"op": "remove_annotation", "id": "note", "expected_annotation": current}])
    assert removed == spec


def test_peak_candidates_preserve_observed_index_and_reject_stale_source(spec):
    candidates = peak_candidates_for_spec(spec, object_path="/page1/graph1/series_1",
                                         window={"min": 400, "max": 500, "unit": "nm"}, polarity="maximum")
    assert [(c["point_index"], c["x"], c["y"]) for c in candidates] == [(1, 425, 3), (3, 475, 4)]
    selected = {**candidates[0], "document_sha256": "d" * 64, "figure_id": "f"}
    _, annotated, _ = compile_ops(spec, [{"op": "add_peak_label", "id": "peak", "candidate": selected}])
    annotation_records(annotated)
    annotated["series"][0]["y_values"][1] = 2.9
    with pytest.raises(AnnotationOperationError, match="no longer matches"):
        annotation_records(annotated)
    wrong = {**selected, "document_sha256": "e" * 64}
    with pytest.raises(AnnotationOperationError, match="exact saved figure"):
        compile_ops(spec, [{"op": "add_peak_label", "id": "peak", "candidate": wrong}])
    wrong = {**candidates[0], "x": 426}
    with pytest.raises(AnnotationOperationError, match="no longer matches"):
        validate_peak_candidate(spec, wrong)


def test_plateaus_boundaries_and_duplicate_x_never_silently_select(spec):
    spec["series"][0]["y_values"] = [5, 1, 3, 3, 5]
    kwargs = {"object_path": "/page1/graph1/series_1", "window": {"min": 400, "max": 500, "unit": "nm"}, "polarity": "maximum"}
    assert peak_candidates_for_spec(spec, **kwargs) == []
    spec["series"][0]["x_values"][1] = 400
    with pytest.raises(AnnotationOperationError, match="Duplicate"):
        peak_candidates_for_spec(spec, **kwargs)


def test_peak_selection_excludes_hidden_series_and_clipped_points(spec):
    from sciplot_core.studio_core.series_presentation import series_selection_payload

    kwargs = {"object_path": "/page1/graph1/series_1", "window": {"min": 400, "max": 500, "unit": "nm"}, "polarity": "maximum"}
    spec["axes"]["y"]["max"] = 3.5
    assert [p["x"] for p in peak_candidates_for_spec(spec, **kwargs)] == [425]
    second = {**spec["series"][0], "name": "series_2", "label": "B"}
    spec["series"].append(second)
    spec["presentation_series_selection"] = series_selection_payload(["A", "B"], ["B"])
    with pytest.raises(AnnotationOperationError, match="excluded"):
        peak_candidates_for_spec(spec, **kwargs)


def test_reference_line_exact_value_and_log_domain(spec):
    record = normalize_annotation(spec, {"op": "add_reference_line", "id": "ref",
                                        "parent_path": "/page1/graph1", "axis": "x", "value": 450, "unit": "nm"})
    spec["native_annotations"] = {"version": 1, "items": [record]}
    settings = annotation_widgets(spec)[0]["settings"]
    assert settings["xPos"] == settings["xPos2"] == [450]
    spec["axes"]["y"].update(scale="log", min=0.1)
    operation = note()
    operation["position"]["y"] = 0
    with pytest.raises(AnnotationOperationError, match="range"):
        normalize_annotation(spec, operation)


def test_spec_and_document_rollback_and_pending_recovery(tmp_path, monkeypatch):
    project = tmp_path / "managed"
    document = project / "studio/document.vsz"
    document.parent.mkdir(parents=True)
    document.write_bytes(b"old")
    spec = document.with_name("spec.json")
    spec.write_bytes(b"old spec")
    (project / "plot_request.json").write_text(json.dumps({"input": str(project / "source")}))
    candidate, new_spec = tmp_path / "new.vsz", tmp_path / "new.json"
    candidate.write_bytes(b"new")
    new_spec.write_bytes(b"new spec")
    review = {"base_state": edit_state(project), "changes": []}
    review["operation_id"] = preview_identity(review)
    original = commit._replace_current_document
    def fail(*_):
        raise OSError("replace fault")
    monkeypatch.setattr(commit, "_replace_current_document", fail)
    with pytest.raises(OSError):
        commit.commit_document_edit(project, document, candidate, review, spec=spec, candidate_spec=new_spec)
    assert document.read_bytes() == b"old" and spec.read_bytes() == b"old spec"
    monkeypatch.setattr(commit, "_replace_current_document", original)
    commit.commit_document_edit(project, document, candidate, review, spec=spec, candidate_spec=new_spec)
    root = history_directory(project, review["operation_id"])
    record = json.loads((root / "outcome.json").read_text())
    record["status"] = "pending"
    (root / "outcome.json").write_text(json.dumps(record))
    document.write_bytes(b"old")  # Stop after spec install but before VSZ replacement.
    assert commit.prior_edit_result(project, review) is None
    assert edit_state(project) == review["base_state"]
    commit.commit_document_edit(project, document, candidate, review, spec=spec, candidate_spec=new_spec)
    assert commit.prior_edit_result(project, review)["status"] == "already_applied"
    spec.write_bytes(b"unexpected spec")
    assert commit.read_edit_operation(project, review["operation_id"])["result_is_current"] is False


def test_source_update_blocks_before_preparing_or_losing_annotations(tmp_path, monkeypatch):
    from sciplot_core.studio_core import source_update

    project = tmp_path / "managed"
    project.mkdir()
    (project / "plot_request.json").write_text("{}")
    spec = project / "spec.json"
    spec.write_text(json.dumps({"native_annotations": {"version": 1, "items": [note()]}}))
    source = tmp_path / "new.csv"
    source.write_text("x,y\n1,2\n")
    monkeypatch.setattr(source_update, "project_figures", lambda _: {"f": (project / "document.vsz", spec)})
    monkeypatch.setattr(source_update, "prepare_candidate", lambda *a, **k: pytest.fail("must not prepare source"))
    result = source_update.preview_project_source_update(project, source)
    assert result["status"] == "blocked"
    assert "annotation_source_revision_required" in result["reason"]
    assert json.loads(spec.read_text())["native_annotations"]["items"] == [note()]
