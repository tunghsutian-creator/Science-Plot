from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from sciplot_core._paths import REPO_ROOT
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.studio_core.annotation_operations import inspect_annotation_state, preview_document_operations
from sciplot_core.studio_core.document_edit import apply_document_edit
from sciplot_core.studio_core.document_edit_state import audit_edited_document, edit_state
from sciplot_core.studio_core.peak_analysis import inspect_peak_candidates
from sciplot_core.studio_core.project_query import inspect_project, resolve_project_figure
from sciplot_core.studio_core.annotation_schema import AnnotationOperationError


def cli(*arguments):
    result = subprocess.run([str(REPO_ROOT / "skill/scripts/sciplot"), *map(str, arguments), "--json"],
                            cwd=REPO_ROOT, capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


@pytest.mark.comprehensive
def test_native_semantic_batch_preview_commit_export_cold_resume_and_remove(tmp_path):
    source = tmp_path / "UVvis.csv"
    source.write_text("Wavelength,Absorbance\nnm,a.u.\nA,A\n400,1\n425,3\n450,1\n475,4\n500,2\n525,1\n")
    source_bytes = source.read_bytes()
    created = cli("studio", source, "--rule", "uvvis_spectrum", "--export", "pdf,tiff_300")
    project = Path(created["project_dir"])
    figure = inspect_project(project)["primary_figure_id"]
    selected = resolve_project_figure(project, figure)
    document, spec_path = Path(selected["document"]), Path(selected["spec"])
    before = edit_state(project)
    x_object = inspect_project(project, figure_id=figure)["selected_figure"]["objects"]["/page1/graph1/x"]
    size_field = next(f for f in x_object["editable_fields"] if f["setting_path"].endswith("/Label/size"))
    state = inspect_annotation_state(project, figure_id=figure)
    peaks = inspect_peak_candidates(project, figure_id=figure, object_path="/page1/graph1/series_1",
                                    window={"min": 400, "max": 525, "unit": state["axes"]["x"]["unit"]},
                                    polarity="maximum", expected_document_sha256=file_sha256(document))
    assert [candidate["x"] for candidate in peaks["candidates"]] == [425, 475]
    operation = {"op": "add_peak_label", "id": "peak425", "candidate": peaks["candidates"][0],
                 "position": {"mode": "axes", "x": 440, "y": 3.5,
                              "x_unit": state["axes"]["x"]["unit"], "y_unit": state["axes"]["y"]["unit"]}}
    operations = [operation, {"op": "add_reference_line", "id": "reference", "parent_path": "/page1/graph1",
                              "axis": "x", "value": 475, "unit": state["axes"]["x"]["unit"]},
                  {"op": "add_annotation", "id": "note", "parent_path": "/page1/graph1",
                   "text": "Observed maxima", "position": {"mode": "relative", "x": 0.1, "y": 0.95}}]
    operations.append({"op": "set_style", "object_path": "/page1/graph1/x",
                       "setting_path": size_field["setting_path"],
                       "expected_value": size_field["current_value"], "value": "9pt"})
    preview = preview_document_operations(project, operations, figure_id=figure,
                                           expected_document_sha256=file_sha256(document), output_dir=tmp_path / "preview")
    assert preview["scientific_audit"]["status"] == "passed"
    assert edit_state(project) == before
    assert Path(preview["preview"]["path"]).is_file()
    applied = apply_document_edit(project, preview)
    assert applied["status"] == "applied" and applied["export_required"] is True
    assert apply_document_edit(project, preview)["status"] == "already_applied"
    after = inspect_annotation_state(project, figure_id=figure)
    assert [a["id"] for a in after["annotations"]] == ["peak425", "reference", "note"]
    assert audit_edited_document(document, spec_path)["status"] == "passed"
    result = cli("studio", project, "--export", "pdf,tiff_300")
    assert result["studio_run"]["ready_to_use"] is True
    resumed = cli("project", "inspect", project, "--figure", figure)
    assert resumed["qa"]["current"] is True
    assert "/page1/graph1/sciplot_annotation_peak425_arrow" in resumed["selected_figure"]["objects"]
    update = {"op": "update_annotation", "id": "note", "expected_annotation": after["annotations"][2],
              "replacement": {"op": "add_annotation", "id": "note", "parent_path": "/page1/graph1",
                              "text": "Reviewed maxima", "position": {"mode": "relative", "x": 0.08, "y": 0.93}}}
    updated = preview_document_operations(project, [update], figure_id=figure,
                                          expected_document_sha256=file_sha256(document), output_dir=tmp_path / "update")
    apply_document_edit(project, updated)
    after = inspect_annotation_state(project, figure_id=figure)
    assert after["annotations"][2]["text"] == "Reviewed maxima"
    with pytest.raises(AnnotationOperationError, match="exact saved figure"):
        preview_document_operations(project, [{**operation, "id": "new_stale_peak"}], figure_id=figure,
                                      expected_document_sha256=file_sha256(document), output_dir=tmp_path / "stale")
    # Adding arbitrary labels to the specification does not disable existing science closure.
    current_spec = json.loads(spec_path.read_text())
    current_spec["native_annotations"]["items"][0]["peak_anchor"]["x"] = 426
    altered = tmp_path / "altered-spec.json"
    altered.write_text(json.dumps(current_spec))
    with pytest.raises(ValueError, match="no longer matches"):
        audit_edited_document(document, altered)
    removals = [{"op": "remove_annotation", "id": record["id"], "expected_annotation": record}
                for record in after["annotations"]]
    removal = preview_document_operations(project, removals, figure_id=figure,
                                           expected_document_sha256=file_sha256(document), output_dir=tmp_path / "remove")
    apply_document_edit(project, removal)
    assert "native_annotations" not in json.loads(spec_path.read_text())
    assert cli("studio", project, "--export", "pdf,tiff_300")["studio_run"]["ready_to_use"] is True
    assert source.read_bytes() == source_bytes


@pytest.mark.comprehensive
def test_native_display_window_preserves_measurements_through_export(tmp_path):
    source = tmp_path / "UVvis.csv"
    source.write_text("Wavelength,Absorbance\nnm,a.u.\nA,A\n400,1\n425,3\n450,1\n475,4\n500,2\n525,1\n")
    source_bytes = source.read_bytes()
    created = cli("studio", source, "--rule", "uvvis_spectrum", "--export", "pdf,tiff_300")
    project = Path(created["project_dir"])
    selected = resolve_project_figure(project, None)
    document, spec_path = Path(selected['document']), Path(selected['spec'])
    baseline = json.loads(spec_path.read_text())
    before = edit_state(project)
    axis = baseline['axes']['x']
    operation = {'op':'set_axis_range','axis':'x','unit':'nm',
        'expected_min':axis['min'],'expected_max':axis['max'],
        'min':425,'max':500,'ticks':[425,450,475,500],'allow_clipping':True}
    preview = preview_document_operations(project, [operation], figure_id=selected['figure_id'],
        expected_document_sha256=file_sha256(document), output_dir=tmp_path/'window')
    assert preview['scientific_audit']['status'] == 'passed'
    assert edit_state(project) == before
    apply_document_edit(project, preview)
    after = json.loads(spec_path.read_text())
    assert after['series'] == baseline['series']
    assert after['axes']['y'] == baseline['axes']['y']
    assert after['axis_data_visibility']['axes']['x']['clipped_coordinate_count'] == 2
    assert after['axis_data_visibility']['finite_coordinate_count'] == 12
    assert cli('studio', project, '--export', 'pdf,tiff_300')['studio_run']['ready_to_use'] is True
    state = inspect_annotation_state(project, figure_id=selected['figure_id'])
    assert (state['axes']['x']['min'],state['axes']['x']['max']) == (425,500)
    assert source.read_bytes() == source_bytes
    assert audit_edited_document(document,spec_path)['status'] == 'passed'
    # A later amplitude-window edit must retain the already cropped X viewport
    # and still pass prepared-source and native audits with every point intact.
    y = state['axes']['y']
    y_operation = {'op':'set_axis_range','axis':'y','unit':y['unit'],
        'expected_min':y['min'],'expected_max':y['max'],
        'min':-1,'max':9,'ticks':[-1,0,4,9],'allow_clipping':False}
    label = {'op':'add_annotation','id':'height','parent_path':'/page1/graph1',
        'text':'Peak','position':{'mode':'axes','x':475,'y':7,'x_unit':'nm','y_unit':y['unit']}}
    preview = preview_document_operations(project, [y_operation,label], figure_id=selected['figure_id'],
        expected_document_sha256=file_sha256(document), output_dir=tmp_path/'height')
    assert preview['scientific_audit']['status'] == 'passed'
    apply_document_edit(project, preview)
    raised = json.loads(spec_path.read_text())
    assert raised['series'] == baseline['series'] and raised['axes']['x'] == after['axes']['x']
    assert raised['axes']['y']['display_window']['source_axis'] == baseline['axes']['y']
    assert raised['axis_data_visibility']['axes']['y']['clipped_coordinate_count'] == 0
    assert cli('studio', project, '--export', 'pdf,tiff_300')['studio_run']['ready_to_use'] is True
    cold = cli('project', 'annotations', project, '--figure', selected['figure_id'])
    assert (cold['axes']['y']['min'],cold['axes']['y']['max']) == (-1,9)
    assert source.read_bytes() == source_bytes
    assert audit_edited_document(document,spec_path)['status'] == 'passed'


@pytest.mark.comprehensive
def test_initial_crop_can_be_reviewed_and_exported_without_regeneration(tmp_path):
    source = tmp_path / 'spectrum.csv'
    source.write_text('ppm,intensity\n10,1\n5,2\n4,30\n3,5\n2,50\n1,3\n0,100\n-2,1\n')
    original = source.read_bytes()
    project = tmp_path / 'project'
    project.mkdir()
    (project / 'plot_request.json').write_text(json.dumps({
        'input': str(source), 'output': str(project), 'template': 'curve',
        'delivery_output': str(tmp_path / 'delivery'), 'exports': ['pdf', 'tiff_300'],
        'render_options': {'size': '120x55', 'reverse_x': True,
            'x_min': -.5, 'x_max': 5, 'y_min': -3, 'y_max': 203,
            'x_label_override': 'Chemical shift (ppm)', 'y_label_override': 'Intensity (%)'}}))
    cli('studio', project)
    selected = resolve_project_figure(project, None)
    document, spec_path = Path(selected['document']), Path(selected['spec'])
    baseline = json.loads(spec_path.read_text())
    assert any(item['id'] == 'visual_extent_outside_explicit_axis'
               for item in baseline['layout_issues'])
    axis = baseline['axes']['x']
    operation = {'op': 'set_axis_range', 'axis': 'x', 'unit': 'ppm',
        'expected_min': axis['min'], 'expected_max': axis['max'],
        'min': 5, 'max': -.5, 'ticks': [-.5,0,1,2,3,4,5], 'allow_clipping': True}
    preview = preview_document_operations(project, [operation], figure_id=selected['figure_id'],
        expected_document_sha256=file_sha256(document), output_dir=tmp_path/'review')
    assert preview['scientific_audit']['status'] == 'passed'
    apply_document_edit(project, preview)
    final_hash = file_sha256(document)
    result = cli('studio', project, '--export', 'pdf,tiff_300')['studio_run']
    assert result['ready_to_use'] is True
    issues = result['qa']['studio_layout']['documents'][0]['issues']
    assert issues and all(item['severity'] == 'info' for item in issues)
    assert file_sha256(document) == final_hash and source.read_bytes() == original
    final_spec = json.loads(spec_path.read_text())
    assert final_spec['series'] == baseline['series']
    assert final_spec['layout_issues'] == baseline['layout_issues']
    assert final_spec['axis_data_visibility']['axes']['x']['clipped_coordinate_count'] == 2
