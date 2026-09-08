from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from sciplot_core.cli import main
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.studio_core import sample_style_presets as presets
from sciplot_core.studio_core.annotation_schema import AnnotationOperationError, validate_operation_batch
from sciplot_core.studio_core.sample_style import sample_style_targets


def spec(labels=("A", "B")):
    return {"template": "curve", "series": [
        {"name": f"series_{index}", "label": label, "presentation_kind": "curve"}
        for index, label in enumerate(labels, 1)]}


def write_preset(tmp_path):
    value = {"kind": "sciplot_sample_style_preset", "version": 1, "origin": {},
             "styles": [{"sample": "A", "style": {"color": "#C83E4D", "width": "2pt"}},
                        {"sample": "B", "style": {"color": "#3568C0", "width": "1.5pt"}}]}
    path = tmp_path / "sample-styles.json"
    path.write_text(json.dumps(value))
    return {"op": "apply_sample_style_preset", "preset": str(path), "expected_preset_sha256": file_sha256(path)}


@pytest.fixture
def captured(tmp_path, monkeypatch):
    project = tmp_path / "project"
    document, specification = project / "studio/document.vsz", project / "studio/spec.json"
    document.parent.mkdir(parents=True)
    document.write_text("native document")
    specification.write_text(json.dumps(spec()))
    (project / "plot_request.json").write_text(json.dumps({"delivery_output": str(tmp_path / "Visible")}))
    figure = {"figure_id": "f", "document": str(document), "spec": str(specification),
              "document_sha256": file_sha256(document), "spec_sha256": file_sha256(specification),
              "sample_styles": sample_style_targets(spec()), "objects": {}}
    for index in (1, 2):
        path = f"/page1/graph1/series_{index}"
        figure["objects"][path] = {"editable_fields": [
            {"setting_path": path + "/PlotLine/color", "current_value": "#C83E4D" if index == 1 else "#3568C0"},
            {"setting_path": path + "/PlotLine/width", "current_value": "2pt" if index == 1 else "1.5pt"}]}
    def current(*args):
        return {**figure, "document_sha256": file_sha256(document), "spec_sha256": file_sha256(specification)}
    monkeypatch.setattr(presets, "resolve_project_figure", current)
    monkeypatch.setattr(presets, "inspect_project", lambda *a, **k: {"project": str(project), "selected_figure": figure})
    monkeypatch.setattr(presets, "audit_edited_document", lambda *a: {"status": "passed"})
    return project, figure


def test_capture_uses_current_native_styles_and_exact_subset_without_source_writes(captured, tmp_path):
    project, figure = captured
    before = {str(p): p.read_bytes() for p in project.rglob("*") if p.is_file()}
    result = presets.capture_sample_style_preset(project, output_dir=tmp_path / "preset", samples=["B", "A"])
    assert result["samples"] == ["B", "A"]
    assert result["styles"][0] == {"sample": "B", "style": {"color": "#3568C0", "width": "1.5pt"}}
    assert result["origin"]["document_sha256"] == figure["document_sha256"]
    assert result["preset_sha256"] == file_sha256(Path(result["preset"]))
    assert result["ready_to_use"] is None and result["readiness_evaluated"] is False
    assert {str(p): p.read_bytes() for p in project.rglob("*") if p.is_file()} == before


@pytest.mark.parametrize("failure", ["document_drift", "spec_drift", "audit"])
def test_capture_rejects_source_drift_or_failed_scientific_audit(captured, tmp_path, monkeypatch, failure):
    project, figure = captured
    def audit(*args):
        if failure == "audit":
            raise ValueError("Source data audit failed")
        key = "document" if failure == "document_drift" else "spec"
        Path(figure[key]).write_text("changed")
        return {"status": "passed"}
    monkeypatch.setattr(presets, "audit_edited_document", audit)
    with pytest.raises(ValueError):
        presets.capture_sample_style_preset(project, output_dir=tmp_path / "preset")
    assert not (tmp_path / "preset").exists()


def test_preset_matches_reordered_samples_and_ignores_unused_source_samples(tmp_path):
    operation = write_preset(tmp_path)
    target = spec(("B", "A"))
    before = copy.deepcopy(target)
    result = presets.expand_style_presets(target, [operation])
    assert [item["samples"] for item in result] == [["B"], ["A"]]
    assert result[0]["style"]["color"] == "#3568C0" and result[1]["style"]["color"] == "#C83E4D"
    assert target == before
    assert presets.expand_style_presets(spec(("B",)), [operation]) == result[:1]


def test_missing_target_sample_requires_an_explicit_subset(tmp_path):
    operation = write_preset(tmp_path)
    with pytest.raises(AnnotationOperationError) as error:
        presets.expand_style_presets(spec(("B", "new")), [operation])
    assert error.value.reason_code == "preset_samples_missing"
    subset = presets.expand_style_presets(spec(("B", "new")), [{**operation, "samples": ["B"]}])
    assert [item["samples"] for item in subset] == [["B"]]


@pytest.mark.parametrize("target,samples", [(spec(("A", "A")), None), (spec(), ["a"]),
    (spec(), []), (spec(), ["A", "A"]), ({**spec(), "performance_comparison": {}}, None),
    ({**spec(), "scalar_field": {}}, ["A"]), ({**spec(), "template": "heatmap"}, None)])
def test_presets_do_not_guess_sample_aliases_or_recolor_semantic_figures(tmp_path, target, samples):
    operation = write_preset(tmp_path)
    if samples is not None:
        operation["samples"] = samples
    with pytest.raises(AnnotationOperationError):
        presets.expand_style_presets(target, [operation])


def test_preset_file_fingerprint_and_symlink_are_checked(tmp_path):
    operation = write_preset(tmp_path)
    path = tmp_path / "sample-styles.json"
    raw = path.read_bytes()
    path.write_bytes(raw + b"\n")
    with pytest.raises(AnnotationOperationError) as error:
        presets.expand_style_presets(spec(), [operation])
    assert error.value.reason_code == "style_preset_changed"
    path.write_bytes(raw)
    alias = tmp_path / "alias.json"
    alias.symlink_to(path)
    with pytest.raises(ValueError, match="symlink"):
        presets.expand_style_presets(spec(), [{**operation, "preset": str(alias)}])


@pytest.mark.parametrize("patch", [{"version": True}, {"kind": "other"}, {"data": [1, 2]}, {"styles": []},
    {"styles": [{"sample": "A", "style": {"color": "red"}}, {"sample": "A", "style": {"color": "blue"}}]},
    {"styles": [{"sample": "A", "style": {"label": "invented"}}]}])
def test_invalid_preset_content_is_not_applied_even_with_a_matching_hash(tmp_path, patch):
    operation = write_preset(tmp_path)
    path = tmp_path / "sample-styles.json"
    path.write_text(json.dumps({**json.loads(path.read_text()), **patch}))
    operation["expected_preset_sha256"] = file_sha256(path)
    with pytest.raises(AnnotationOperationError):
        presets.expand_style_presets(spec(), [operation])


def test_public_capture_cli_and_operation_shape(captured, tmp_path, capsys):
    project, _ = captured
    assert main(["project", "style-capture", str(project), "--figure", "f", "--sample", "B",
                 "--out", str(tmp_path / "preset"), "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["samples"] == ["B"]
    operation = {"op": "apply_sample_style_preset", "preset": result["preset"],
                 "expected_preset_sha256": result["preset_sha256"]}
    validate_operation_batch([operation])
    with pytest.raises(AnnotationOperationError):
        validate_operation_batch([{**operation, "samples": ["A", "A"]}])

