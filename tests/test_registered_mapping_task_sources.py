"""Generated raw-domain publication controls; only native document saving is stubbed."""

from copy import deepcopy
import json
from pathlib import Path

import pandas as pd
import pytest

from sciplot_core import task_control as control
from sciplot_core.data_mapping import load_data_mapping_execution, resolve_data_mapping_request
from sciplot_core.figure_plan import FigureTask, ResolvedFigurePlan, request_for_figure_task
from sciplot_core.source_coverage.managed_task_sources import registered_task_snapshot_sources
from sciplot_core.studio_core import veusz_document
from sciplot_core.studio_core.series_request import _series_from_request
from test_task_raw_replicate_mapping import native_boundary, original


@pytest.fixture
def mapped_spec(tmp_path, monkeypatch):
    source, request, mapping = original(tmp_path)
    native_boundary(monkeypatch, tmp_path)
    result = control.start_task({**request, "mapping": mapping}, task_dir=tmp_path / "choice")
    assert result["status"] == "complete", result
    execution = load_data_mapping_execution(result["data_mapping"]["data_mapping_execution"])
    seed = json.loads(Path(execution["request_seed"]).read_text())
    task = FigureTask(figure_id="impact_strength_by_sample", order=1, title="Impact strength",
                      x_metric="sample", y_metric="impact_strength", template="box",
                      artifact_stem="impact_strength_by_sample", document_stem="impact_strength_by_sample")
    plan = ResolvedFigurePlan.planned(rule_id="impact_metric", selection_policy="generated_raw",
                                     primary_figure_id=task.figure_id, tasks=(task,))
    seed["resolved_figure_plan"] = plan.to_payload()
    projected = request_for_figure_task(seed, task)
    _, application = resolve_data_mapping_request(seed, base_dir=tmp_path)
    series, axes, _, _ = _series_from_request(projected, base_dir=tmp_path)
    project = tmp_path / "project"
    document = project / "studio" / "document.vsz"
    monkeypatch.setattr(veusz_document, "_save_veusz_document_from_spec", lambda *_a, **_k: None)
    spec_path = veusz_document._write_veusz_document(document, request=projected, series=series, axis_info=axes)
    spec = json.loads(spec_path.read_text())
    return source, seed, application, execution, project, document, spec_path, spec


def publish(fixture):
    _, request, application, execution, project, document, *_ = fixture
    return registered_task_snapshot_sources(request=request, project_dir=project,
        documents=[document], existing_sources=[Path(execution["effective_input"])],
        data_mapping_application=application)


def test_complete_verified_groups_publish_literal_values_masks_and_source_identity(mapped_spec):
    source, _, application, execution, _, _, _, spec = mapped_spec
    original_bytes = source.read_bytes()
    groups = application["source_groups"]
    assert [item["y_values"] for item in spec["series"]] == [[1., 1., 3., 5.], [7., 8., 9.]]
    assert [pd.read_csv(item["path"]).iloc[:, 0].isna().tolist() for item in groups] == [
        [False, True, False, False, True, False, True],
        [False, False, True, True, False, True, True]]
    assert publish(mapped_spec) == [Path(execution["effective_input"]), *(Path(group["path"]) for group in groups)]
    assert source.read_bytes() == original_bytes
    # The complete proof also survives JSON reopening; no private worker seal.
    reopened = deepcopy(mapped_spec)
    assert publish(reopened) == publish(mapped_spec)


@pytest.mark.parametrize("change", ["missing_group", "equal_bytes_other_path", "wrong_hash", "scientific_values",
                                  "physical_binding", "request_receipt", "request_input", "rows_claim"])
def test_source_inventory_or_scientific_forgery_cannot_grant_extra_sources(mapped_spec, tmp_path, change):
    source, _, application, _, _, _, spec_path, original_spec = mapped_spec
    original_bytes = source.read_bytes()
    spec = deepcopy(original_spec)
    if change == "missing_group":
        spec["series"].pop()
    elif change == "equal_bytes_other_path":
        artifact = spec["series"][0]["source_artifacts"][0]
        copied = tmp_path / "equal_bytes.csv"
        copied.write_bytes(Path(artifact["path"]).read_bytes())
        artifact["path"] = str(copied)
    elif change == "wrong_hash":
        spec["series"][0]["source_artifacts"][0]["sha256"] = "0" * 64
    elif change == "scientific_values":
        spec["series"][0]["y_values"][1] = 99.
    elif change == "physical_binding":
        spec["series"][0]["source_binding"]["source_id"] = application["source_groups"][1]["source_id"]
    elif change == "request_receipt":
        spec["source_request"]["data_mapping_application"]["confirmation_id"] = "other"
    elif change == "request_input":
        copied = tmp_path / "equal_raw.csv"
        copied.write_bytes(source.read_bytes())
        spec["source_request"]["input"] = str(copied)
    else:
        spec["source_request"]["data_mapping_application"]["source_groups"][0]["rows"] = 4
    spec_path.write_text(json.dumps(spec))
    with pytest.raises(ValueError):
        publish(mapped_spec)
    assert source.read_bytes() == original_bytes


@pytest.mark.parametrize("change", ["raw_value", "raw_mask", "mapped_mask", "composite", "receipt_rows", "receipt_selector"])
def test_mapping_receipt_reproduces_complete_raw_domains_before_publication(mapped_spec, change):
    source, _, application, execution, *_ = mapped_spec
    if change in {"raw_value", "raw_mask"}:
        source.write_text(source.read_text().replace("1,7,11", "2,7,11" if change == "raw_value" else ",7,11"))
    elif change == "mapped_mask":
        path = Path(application["source_groups"][0]["path"])
        path.write_text(path.read_text().replace('""\n', '0\n', 1))
    elif change == "composite":
        Path(execution["effective_input"]).write_text("Impact strength\n99\n")
    elif change == "receipt_rows":
        path = Path(application["execution"])
        payload = json.loads(path.read_text())
        payload["outputs"][0]["rows"] = 4
        path.write_text(json.dumps(payload))
    else:
        path = Path(execution["proposal"])
        payload = json.loads(path.read_text())
        payload["sources"][0]["data_start_row"] = 4
        path.write_text(json.dumps(payload))
    with pytest.raises(ValueError):
        publish(mapped_spec)


def test_current_application_claim_cannot_rename_verified_group_domain(mapped_spec):
    application = mapped_spec[2]
    application["source_groups"][0]["rows"] = 4
    spec_path, spec = mapped_spec[-2:]
    spec["source_request"]["data_mapping_application"] = deepcopy(application)
    spec_path.write_text(json.dumps(spec))
    with pytest.raises(ValueError, match="verified mapping receipt"):
        publish(mapped_spec)


def test_legacy_processed_table_guard_still_refuses_unproved_external_groups(mapped_spec):
    _, request, _, execution, project, document, *_ = mapped_spec
    with pytest.raises(ValueError, match="inventory disagree"):
        registered_task_snapshot_sources(request=request, project_dir=project,
            documents=[document], existing_sources=[Path(execution["effective_input"])])


def test_existing_private_registered_table_still_requires_exact_scientific_replay(tmp_path, monkeypatch):
    project = tmp_path / "project"
    source = project / "studio" / "processed" / "terminal.csv"
    source.parent.mkdir(parents=True)
    source.write_text("Time,Stress\ns,Pa\n,A\n0,10\n1,11\n")
    task = FigureTask(figure_id="curve", order=1, title="Curve", x_metric="time", y_metric="stress",
                      template="curve", artifact_stem="curve", document_stem="curve")
    plan = ResolvedFigurePlan.planned(rule_id="generated", selection_policy="generated",
                                     primary_figure_id=task.figure_id, tasks=(task,))
    request = {"input": str(source), "template": "curve", "resolved_figure_plan": plan.to_payload()}
    projected = request_for_figure_task(request, task)
    series, axes, _, _ = _series_from_request(projected, base_dir=tmp_path)
    monkeypatch.setattr(veusz_document, "_save_veusz_document_from_spec", lambda *_a, **_k: None)
    document = project / "studio" / "document.vsz"
    spec_path = veusz_document._write_veusz_document(document, request=projected, series=series, axis_info=axes)
    assert registered_task_snapshot_sources(request=request, project_dir=project,
        documents=[document], existing_sources=[]) == [source]
    spec = json.loads(spec_path.read_text())
    spec["series"][0]["y_values"][0] = 99.
    spec_path.write_text(json.dumps(spec))
    with pytest.raises(ValueError, match="reproduce"):
        registered_task_snapshot_sources(request=request, project_dir=project,
            documents=[document], existing_sources=[])


@pytest.fixture
def revision_science(mapped_spec, monkeypatch):
    from sciplot_core.source_coverage import managed_documents
    from sciplot_core.studio_core import source_update_staging

    _, request, _, _, project, document, spec_path, _ = mapped_spec
    (project / "plot_request.json").write_text(json.dumps(request))
    # Registry topology and native VSZ auditing are unchanged owners. All source
    # permission, execution reproduction and data signatures below remain real.
    monkeypatch.setattr(source_update_staging, "project_figures", lambda _p: {"impact_strength_by_sample": (document, spec_path)})
    monkeypatch.setattr(managed_documents, "_audit_exact_document_data",
                        lambda **_k: ({"status": "passed"}, json.loads(spec_path.read_text())))
    return project, source_update_staging.verify_project_science


def test_revision_science_reuses_complete_registered_group_permission_after_json_reopen(mapped_spec, revision_science):
    source, _, application, _, _, _, spec_path, _ = mapped_spec
    project, verify = revision_science
    before = {path: path.read_bytes() for path in [source, spec_path, project / "plot_request.json",
              *(Path(group["path"]) for group in application["source_groups"])]}
    result = verify(project)
    assert result["mapping_source_coverage"]["coverage_mode"] == "exact_per_output"
    assert result["mapping_source_coverage"]["expected_output_count"] == 2
    assert result["documents"][0]["prepared_source_derivation"]["unit_count"] == 2
    assert verify(project) == result
    assert {path: path.read_bytes() for path in before} == before


@pytest.mark.parametrize("change", ["unrelated_file", "missing_group", "scientific_values", "raw_mask", "execution_rows"])
def test_revision_permission_forwarding_does_not_admit_unconfirmed_or_stale_data(mapped_spec, revision_science, tmp_path, change):
    source, _, application, _, _, _, spec_path, spec = mapped_spec
    project, verify = revision_science
    spec = deepcopy(spec)
    if change == "unrelated_file":
        artifact = spec["series"][0]["source_artifacts"][0]
        unrelated = tmp_path / "same_bytes_unconfirmed.csv"
        unrelated.write_bytes(Path(artifact["path"]).read_bytes())
        artifact["path"] = str(unrelated)
    elif change == "missing_group":
        spec["series"].pop()
    elif change == "scientific_values":
        spec["series"][0]["y_values"][0] = 42.
    elif change == "raw_mask":
        source.write_text(source.read_text().replace("1,7,11", ",7,11"))
    else:
        execution_path = Path(application["execution"])
        execution = json.loads(execution_path.read_text())
        execution["outputs"][0]["rows"] = 4
        execution_path.write_text(json.dumps(execution))
    spec_path.write_text(json.dumps(spec))
    before = spec_path.read_bytes()
    with pytest.raises(ValueError):
        verify(project)
    assert spec_path.read_bytes() == before


def test_verified_xy_pairs_keep_actual_semantic_prepared_table_proof(tmp_path, monkeypatch):
    from sciplot_core.data_mapping.source_projection import verified_mapping_source_groups
    from sciplot_core.source_coverage.managed_documents import source_records
    from test_task_initial_mapping import request_for

    request = request_for(tmp_path)
    source = Path(request["source"])
    original_bytes = source.read_bytes()
    native_boundary(monkeypatch, tmp_path)
    result = control.start_task({**request, "template": "curve"}, task_dir=tmp_path / "xy_choice")
    assert result["status"] == "complete", result
    execution = load_data_mapping_execution(result["data_mapping"]["data_mapping_execution"])
    seed = json.loads(Path(execution["request_seed"]).read_text())
    _, application = resolve_data_mapping_request(seed, base_dir=tmp_path)
    assert len(verified_mapping_source_groups({"data_mapping_application": application})) == 2
    assert verified_mapping_source_groups({"data_mapping_application": application}, replicates=True) == []
    task = FigureTask(figure_id="spectrum", order=1, title="Spectrum", x_metric="wavelength", y_metric="absorbance",
                      template="curve", artifact_stem="spectrum", document_stem="spectrum")
    plan = ResolvedFigurePlan.planned(rule_id="uvvis_spectrum", selection_policy="generated",
                                     primary_figure_id=task.figure_id, tasks=(task,))
    seed["resolved_figure_plan"] = plan.to_payload()
    projected = request_for_figure_task(seed, task)
    project = tmp_path / "xy_project"
    project.mkdir()
    series, axes, _, _ = _series_from_request(projected, base_dir=project)
    prepared = Path(series[0].source_artifacts[0][0])
    assert prepared.is_relative_to(project / "studio" / "processed")
    assert prepared.is_file()
    assert [item.y_values for item in series] == [(1., 4., 2.), (3., 5.)]
    # The actual semantic adapter has materialized this table. Replaying its
    # terminal spec must use that exact prepared table, not the raw-group path.
    terminal = {**projected, "input": str(prepared), "data_mapping_application": application}
    terminal.pop("data_mapping_execution")
    terminal.pop("data_mapping_proposal_id")
    monkeypatch.setattr(veusz_document, "_save_veusz_document_from_spec", lambda *_a, **_k: None)
    document = project / "studio" / "document.vsz"
    spec_path = veusz_document._write_veusz_document(document, request=terminal, series=series, axis_info=axes)
    spec = json.loads(spec_path.read_text())
    assert len(source_records(spec)) == 1
    assert registered_task_snapshot_sources(request=seed, project_dir=project, documents=[document],
        existing_sources=[], data_mapping_application=application) == [prepared]
    spec["series"][0]["y_values"][0] = 99.
    spec_path.write_text(json.dumps(spec))
    with pytest.raises(ValueError, match="reproduce"):
        registered_task_snapshot_sources(request=seed, project_dir=project, documents=[document],
            existing_sources=[], data_mapping_application=application)
    assert source.read_bytes() == original_bytes


@pytest.mark.parametrize("selected", ["directory", "file"])
def test_cold_registered_originals_do_not_become_extra_tables_through_physical_views(tmp_path, selected):
    from sciplot_core.foundation.file_hashing import file_sha256
    from sciplot_core.foundation.source_locations import resolve_source_path
    from sciplot_core.project_store import FileProjectStore
    from sciplot_core.project_store.runtime import project_runtime

    root = tmp_path / "project"
    source = root / "source/A.csv"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"Time,Stress\ns,Pa\n0,1\n1,2\n")
    document = root / "studio/document.vsz"
    document.parent.mkdir()
    document.write_bytes(b"generated native placeholder")
    spec = {"series": [{"source_artifacts": [{"path": str(source), "sha256": file_sha256(source)}]}],
            "source_request": {"input": str(source.parent)}}
    spec_bytes = json.dumps(spec).encode()
    document.with_name("spec.json").write_bytes(spec_bytes)
    store = FileProjectStore(root)
    before = store.snapshot(import_legacy=True)
    cold = FileProjectStore.import_bundle(store.export_bundle(tmp_path / "bundle"), tmp_path / "cold")
    root.rename(tmp_path / "original-offline")
    with project_runtime(cold):
        actual = resolve_source_path(source.parent if selected == "directory" else source)
        assert actual.exists() and not source.exists()
        result = registered_task_snapshot_sources(request={}, project_dir=cold.root,
            documents=[document], existing_sources=[actual])
        assert result == [actual]
    assert cold.read_bytes("studio/spec.json") == spec_bytes
    assert cold.snapshot()["generation"] == before["generation"]


def test_cold_directory_membership_does_not_admit_same_name_unregistered_group(tmp_path):
    from sciplot_core.foundation.file_hashing import file_sha256
    from sciplot_core.foundation.source_locations import resolve_source_path
    from sciplot_core.project_store import FileProjectStore
    from sciplot_core.project_store.runtime import project_runtime

    root = tmp_path / "project"
    source = root / "source/A.csv"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"x,y\n1,2\n")
    outside = root / "other/A.csv"
    outside.parent.mkdir()
    outside.write_bytes(source.read_bytes())
    document = root / "studio/document.vsz"
    document.parent.mkdir()
    document.write_bytes(b"generated placeholder")
    spec = {"series": [{"source_artifacts": [{"path": str(outside), "sha256": file_sha256(outside)}]}]}
    document.with_name("spec.json").write_text(json.dumps(spec))
    store = FileProjectStore(root)
    store.snapshot(import_legacy=True)
    cold = FileProjectStore.import_bundle(store.export_bundle(tmp_path / "bundle"), tmp_path / "cold")
    root.rename(tmp_path / "original-offline")
    with project_runtime(cold), pytest.raises(ValueError, match="registered FigureTask"):
        registered_task_snapshot_sources(request={}, project_dir=cold.root,
            documents=[document], existing_sources=[resolve_source_path(source.parent)])


def test_cold_inventory_does_not_read_an_unrelated_absent_optional_root(tmp_path):
    from sciplot_core.foundation.source_locations import resolve_source_path
    from sciplot_core.project_store import FileProjectStore
    from sciplot_core.project_store.runtime import project_runtime
    from sciplot_core.source_coverage.inventory_paths import source_inventory_contains
    root = tmp_path / "project"
    source = root / "source/A.csv"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"x,y\n1,2\n")
    store = FileProjectStore(root)
    store.snapshot(import_legacy=True)
    cold = FileProjectStore.import_bundle(store.export_bundle(tmp_path / "bundle"), tmp_path / "cold")
    root.rename(tmp_path / "original-offline")
    with project_runtime(cold):
        roots = [cold.root / "studio/processed-optional", resolve_source_path(source.parent)]
        assert source_inventory_contains(source, roots)
        assert not source_inventory_contains(source.with_name("foreign.csv"), [roots[0]])
    assert not roots[0].exists()
