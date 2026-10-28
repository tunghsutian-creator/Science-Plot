"""Actual task producers retain generated intermediate reads in their command."""

import json
from pathlib import Path
import subprocess

import pytest

from sciplot_core.figure_plan import resolve_figure_plan
from sciplot_core.project_commands import ProjectCommand, ProjectCommands, ProjectMutation
from sciplot_core.project_store import FileProjectStore, ProjectConflict
from sciplot_core.publication import build_transform_ledger
from sciplot_core.studio_core.figure_requests import (
    _impact_condition_figure_queue, _impact_condition_figure_request,
)
from sciplot_core.studio_core.preparation_candidate import studio_preparation_candidate
from sciplot_core.studio_core.preparation_commands import audit_studio_candidate
from sciplot_core.studio_core.preparation_original_sources import capture_original_input
from sciplot_core.studio_core.series_request import _series_from_request
from test_impact_condition_figure_set import _write_two_condition_impact_source


@pytest.fixture
def generated_project(tmp_path, monkeypatch):
    def no_process(*args, **kwargs):
        raise AssertionError("This contract counter must not start a native process")

    monkeypatch.setattr(subprocess, "Popen", no_process)
    project = tmp_path / "project"
    source = project / "source" / "impact.xlsx"
    source.parent.mkdir(parents=True)
    _write_two_condition_impact_source(source)
    request = {"recipe": "auto", "input": str(source.parent), "rule_id": "impact_metric", "template": "bar"}
    (project / "plot_request.json").write_text(json.dumps(request))
    store = FileProjectStore(project)
    before = store.snapshot(import_legacy=True)
    return store, before, request, source.read_bytes()


def _prepare_pure_figures(candidate, request, monkeypatch, *, template="bar"):
    request = {**request, "template": template}
    original = capture_original_input(request, base_dir=candidate.project_dir, snapshot=candidate.snapshot)
    candidate.original_inputs["plot_request.json"] = original
    plan = resolve_figure_plan(rule_id="impact_metric", template=template, study_model={},
                              input_path=Path(request["input"]), request=request)
    request["resolved_figure_plan"] = plan.to_payload()
    queue = _impact_condition_figure_queue(request, base_dir=candidate.project_dir,
                                         project_dir=candidate.project_dir, figure_plan=plan)
    figures, steps, selected_source = [], None, None
    for index, figure in enumerate(queue):
        child = _impact_condition_figure_request(request, figure)
        series, _axes, current_steps, current_source = _series_from_request(child, base_dir=candidate.project_dir)
        if steps is None:
            steps, selected_source = current_steps, current_source
        document = candidate.project_dir / "studio" / f"figure-{index}.vsz"
        spec = document.with_suffix(".spec.json")
        document.write_bytes(b"Synthetic fixture: native audit is outside this pure source-admission counter")
        spec.write_text(json.dumps({"series": [{"source_artifacts": [
            {"path": path, "sha256": digest} for path, digest in item.source_artifacts]} for item in series]}))
        figures.append({"status": "ready", "document": str(document), "spec": str(spec)})
    request["transform_ledger"] = build_transform_ledger({}, request=request, input_path=selected_source, steps=steps)
    candidate.write_request(request)

    def native_audit_outside_this_counter(*, document_path, spec_path, check_presentation):
        return {"status": "passed", "pure_fixture": True}, json.loads(spec_path.read_bytes())

    monkeypatch.setattr("sciplot_core.source_coverage.document_audit._audit_exact_document_data",
                        native_audit_outside_this_counter)
    return queue, {"figure_set": {"figures": figures}}, request


@pytest.mark.parametrize("template", ["bar", "box", "box_strip"])
def test_generated_intermediate_sources_are_captured_by_the_actual_producer(generated_project, monkeypatch, template):
    store, before, request, original = generated_project
    with studio_preparation_candidate(store, snapshot=before) as candidate:
        queue, payload, request = _prepare_pure_figures(candidate, request, monkeypatch, template=template)
        _audits, sources = audit_studio_candidate(candidate, payload)
        inputs = {item["path"]: item["sha256"] for step in request["transform_ledger"]["steps"]
                  for item in step["input_artifacts"] if item["kind"] == "file"}
        captured = {item.locator: item for item in sources}
        assert inputs and all(path in captured and captured[path].version == digest for path, digest in inputs.items())
        generated = [item for item in sources if item.produced_resource and "impact_conditions/" in item.produced_resource]
        assert len(generated) == len(queue) == 2
        assert all(item.locator == str(store.root / item.produced_resource) for item in generated)
        assert all(str(candidate.project_dir) not in item.locator for item in generated)
    assert (store.root / "source/impact.xlsx").read_bytes() == original
    assert store.snapshot()["generation"] == before["generation"]
    assert not (store.root / "studio").exists()


@pytest.mark.parametrize("change", ["unknown_same_bytes", "outside_same_bytes", "bytes", "mode"])
def test_generated_input_capture_does_not_authorize_other_locators_or_late_drift(generated_project, monkeypatch, tmp_path, change):
    store, before, request, original = generated_project
    with studio_preparation_candidate(store, snapshot=before) as candidate:
        queue, payload, request = _prepare_pure_figures(candidate, request, monkeypatch)
        actual = Path(queue[0]["condition_source"])
        if change in {"bytes", "mode"}:
            if change == "bytes":
                actual.write_bytes(actual.read_bytes() + b"\n")
            else:
                actual.chmod(0o600)
        else:
            unknown = (actual.parent / "unknown.csv" if change == "unknown_same_bytes" else tmp_path / "outside.csv")
            unknown.write_bytes(actual.read_bytes())
            artifact = request["transform_ledger"]["steps"][0]["input_artifacts"][0]
            artifact["path"] = str(unknown)
            candidate.write_request(request)
        with pytest.raises(ProjectConflict):
            audit_studio_candidate(candidate, payload)
    assert store.snapshot()["generation"] == before["generation"]
    assert not (store.root / "studio").exists()
    assert (store.root / "source/impact.xlsx").read_bytes() == original


def test_failed_producer_does_not_register_or_publish_partial_generated_inputs(generated_project, monkeypatch):
    import sciplot_core.studio_core.impact_task_sources as producer

    store, before, request, original = generated_project
    calls = 0
    writer = producer.pd.DataFrame.to_csv

    def fail_second_write(frame, path, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("controlled producer write failure")
        return writer(frame, path, **kwargs)

    with studio_preparation_candidate(store, snapshot=before) as candidate:
        monkeypatch.setattr(producer.pd.DataFrame, "to_csv", fail_second_write)
        with pytest.raises(OSError, match="controlled producer"):
            _impact_condition_figure_queue(request, base_dir=candidate.project_dir, project_dir=candidate.project_dir)
        assert candidate.generated_inputs == {}
        assert not list((candidate.project_dir / "studio").rglob("*.csv"))
    assert calls == 2
    assert store.snapshot()["generation"] == before["generation"]
    assert (store.root / "source/impact.xlsx").read_bytes() == original


@pytest.mark.parametrize("member", ["outside", "missing", "original", "alias"])
def test_generated_capture_only_reads_exact_new_ordinary_candidate_members(generated_project, tmp_path, member):
    from sciplot_core.studio_core.preparation_generated_inputs import record_generated_preparation_inputs

    store, before, _request, original = generated_project
    with studio_preparation_candidate(store, snapshot=before) as candidate:
        first = candidate.project_dir / "studio/generated.csv"
        candidate.write_member("studio/generated.csv", b"exact producer bytes")
        if member == "outside":
            other = tmp_path / "outside.csv"
            other.write_bytes(first.read_bytes())
        elif member == "missing":
            other = first.with_name("missing.csv")
        elif member == "original":
            other = candidate.project_dir / "source/impact.xlsx"
        else:
            other = first.with_name("alias.csv")
            other.symlink_to(first)
        with pytest.raises((ProjectConflict, OSError)):
            record_generated_preparation_inputs(candidate.project_dir, [first, other])
        assert candidate.generated_inputs == {}  # A failed batch grants no partial input.
    assert store.snapshot()["generation"] == before["generation"]
    assert not (store.root / "studio").exists()
    assert (store.root / "source/impact.xlsx").read_bytes() == original


def test_point_line_retains_its_existing_verified_workbook_contract(generated_project, monkeypatch):
    store, before, request, original = generated_project
    with studio_preparation_candidate(store, snapshot=before) as candidate:
        queue, payload, request = _prepare_pure_figures(candidate, request, monkeypatch, template="point_line")
        assert len(queue) == 1 and candidate.generated_inputs == {}
        _audits, sources = audit_studio_candidate(candidate, payload)
        inputs = {item["path"]: item["sha256"] for step in request["transform_ledger"]["steps"]
                  for item in step["input_artifacts"] if item["kind"] == "file"}
        captured = {item.locator: item.version for item in sources}
        assert inputs and all(captured.get(path) == digest for path, digest in inputs.items())
    assert store.snapshot()["generation"] == before["generation"]
    assert (store.root / "source/impact.xlsx").read_bytes() == original


def test_generated_capture_uses_the_same_nested_candidate_and_resets_after_failure(generated_project, tmp_path):
    from sciplot_core.studio_core.preparation_candidate import active_preparation_candidate, private_preparation_scope
    from sciplot_core.studio_core.preparation_generated_inputs import record_generated_preparation_inputs

    store, before, _request, _original = generated_project
    other = tmp_path / "other-project"
    other.mkdir()
    other_store = FileProjectStore(other)
    other_before = other_store.snapshot(import_legacy=True)
    assert active_preparation_candidate(store.root) is None
    with studio_preparation_candidate(store, snapshot=before) as first:
        first.write_member("studio/generated.csv", b"first exact output")
        with pytest.raises(ValueError, match="cannot expand to another candidate"):
            with studio_preparation_candidate(other_store, snapshot=other_before):
                pytest.fail("A nested manifest cannot borrow a different project")
        assert active_preparation_candidate(first.project_dir) is first
        with pytest.raises(RuntimeError, match="controlled nested failure"):
            with private_preparation_scope(first):
                assert active_preparation_candidate(first.project_dir) is first
                with pytest.raises(ProjectConflict, match="another candidate context"):
                    record_generated_preparation_inputs(other, [first.project_dir / "studio/generated.csv"])
                assert not first.generated_inputs
                raise RuntimeError("controlled nested failure")
        assert active_preparation_candidate(first.project_dir) is first
        record_generated_preparation_inputs(first.project_dir, [first.project_dir / "studio/generated.csv"])
        assert set(first.generated_inputs) == {"studio/generated.csv"}
    assert active_preparation_candidate(first.project_dir) is None
    assert store.snapshot()["generation"] == before["generation"]
    assert other_store.snapshot()["generation"] == other_before["generation"]
    assert not (store.root / "studio").exists() and not (other / "studio").exists()


def test_generated_source_bytes_must_equal_the_same_command_output_seal(generated_project, monkeypatch):
    store, before, request, original = generated_project
    with studio_preparation_candidate(store, snapshot=before) as candidate:
        _queue, payload, _request = _prepare_pure_figures(candidate, request, monkeypatch)
        _audits, sources = audit_studio_candidate(candidate, payload)
        generated = tuple(item for item in sources if item.produced_resource)
        selected = generated[0].produced_resource
        candidate.write_member(selected, b"changed after successful audit")
        writes = {item.produced_resource: candidate.read_member(item.produced_resource) for item in generated}
        reads = {name: value["sha256"] for name, value in before["files"].items()}
        reads.update({name: None for name in writes})
        command = ProjectCommand.create("figure_set", "changed-produced-source", project_id=before["project_id"],
            expected_generation=before["generation"], read_set=reads, write_set=list(writes), request={"fixture": "late-drift"})
        with pytest.raises(ProjectConflict):
            ProjectCommands(store).execute(command, lambda: ProjectMutation(writes, {}, prepared_sources=generated))
    assert store.snapshot()["generation"] == before["generation"]
    assert not (store.root / "studio").exists()
    assert (store.root / "source/impact.xlsx").read_bytes() == original


def test_generated_inputs_publish_once_and_reopen_from_an_official_cold_bundle(generated_project, monkeypatch, tmp_path):
    from sciplot_core.project_store.runtime import project_runtime
    from sciplot_core.foundation.source_locations import resolve_source_path

    store, before, request, original = generated_project
    with studio_preparation_candidate(store, snapshot=before) as candidate:
        _queue, payload, _request = _prepare_pure_figures(candidate, request, monkeypatch)
        _audits, sources = audit_studio_candidate(candidate, payload)
        generated = tuple(item for item in sources if item.produced_resource)
        writes = {item.produced_resource: candidate.read_member(item.produced_resource) for item in generated}
        reads = {name: value["sha256"] for name, value in before["files"].items()}
        reads.update({name: None for name in writes})
        command = ProjectCommand.create("figure_set", "pure-generated-sources", project_id=before["project_id"],
            expected_generation=before["generation"], read_set=reads, write_set=list(writes), request={"fixture": "generated-inputs"})
        record = ProjectCommands(store).execute(command, lambda: ProjectMutation(writes, {}, prepared_sources=generated))
    assert record["phase"] == "complete"
    assert not store.snapshot().get("input_resources")
    cold = FileProjectStore.import_bundle(store.export_bundle(tmp_path / "bundle"), tmp_path / "cold")
    store.root.rename(tmp_path / "original-offline")
    with project_runtime(cold):
        for item in generated:
            actual = resolve_source_path(item.locator, expected_sha256=item.version, source_id=item.source_id)
            assert actual.read_bytes() == item.data
        assert ProjectCommands(cold).resume(command)["generation"] == record["generation"]
    assert (tmp_path / "original-offline/source/impact.xlsx").read_bytes() == original
