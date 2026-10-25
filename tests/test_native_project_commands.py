"""Real shared-store native edit callers with controlled candidate rendering."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import shutil

import pytest

from test_project_query import project as project
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.project_commands import ProjectCommand, ProjectCommands, ProjectMutation, ProjectionRead
from sciplot_core.project_commands.read_projections import projection_digest
from sciplot_core.project_store import FileProjectStore
from sciplot_core.studio_core import document_edit as native
from sciplot_core.studio_core.document_edit_commit import prior_edit_result
from sciplot_core.studio_core.document_edit_state import edit_state, preview_identity


@pytest.fixture
def edit(project, tmp_path, monkeypatch):
    calls = []

    def candidate(document, spec, changes, output, **_kwargs):
        calls.append(str(document))
        saved, image = output / "candidate.vsz", output / "candidate.png"
        saved.write_bytes(document.read_bytes() + b"\nselected native style")
        image.write_bytes(b"controlled preview")
        return {"changes": changes, "candidate": {"path": str(saved), "sha256": file_sha256(saved)},
                "preview": {"path": str(image), "sha256": file_sha256(image), "width": 20, "height": 20},
                "scientific_audit": {"status": "passed"}}

    monkeypatch.setattr(native, "_candidate", candidate)
    monkeypatch.setattr(native, "audit_edited_document", lambda *_args: {"status": "passed"})
    document = project / "studio/document.vsz"
    changes = [{"object_path": "/page1/graph1/x", "setting_path": "/page1/graph1/x/Label/size",
                "expected_value": "8pt", "value": "9pt"}]
    review = native.preview_document_edit(project, changes, output_dir=tmp_path / "preview",
        figure_id="first", expected_document_sha256=file_sha256(document))
    return project, document, review, calls


def publish_other_figure(project):
    store = FileProjectStore(project)
    snapshot = store.snapshot()
    registry_path = "studio/figure_set.json"
    registry = json.loads(store.read_bytes(registry_path))
    registry["figures"][1]["document_state"] = {"current_hash": "unrelated export witness"}
    selected = ProjectionRead(registry_path, "studio_figure_v1", "second",
        projection_digest(store.read_bytes(registry_path), kind="studio_figure_v1", key="second"))
    command = ProjectCommand.create("export", "figure-b-export", project_id=snapshot["project_id"],
        expected_generation=snapshot["generation"], read_set={"studio/exports/second.pdf": None},
        write_set=[registry_path, "studio/exports/second.pdf"], request={"figure_id": "second"},
        projected_reads=[selected], projected_writes=[selected])
    return ProjectCommands(store).execute(command, lambda: ProjectMutation({
        registry_path: json.dumps(registry).encode(), "studio/exports/second.pdf": b"new-b-export"}, {}))


def test_candidate_native_failure_after_private_write_is_unknown_and_never_retried(project, tmp_path, monkeypatch):
    from sciplot_core.project_commands import ProjectCommandUnknown
    from sciplot_core.studio_core.project_command_scope import project_store

    calls = []
    before = (project / "studio/document.vsz").read_bytes()
    def fail_after_write(document, _spec, _changes, output, **_kwargs):
        calls.append(str(document))
        (output / "candidate.vsz").write_bytes(b"private native partial result")
        raise RuntimeError("controlled native failure after private write")
    monkeypatch.setattr(native, "audit_edited_document", lambda *_args: {"status": "passed"})
    monkeypatch.setattr(native, "_candidate", fail_after_write)
    arguments = dict(output_dir=tmp_path / "failed-preview", figure_id="first",
                     expected_document_sha256=file_sha256(project / "studio/document.vsz"))
    with pytest.raises(RuntimeError, match="controlled native failure"):
        native.preview_document_edit(project, [], **arguments)
    records = ProjectCommands(project_store(project)).commands()
    assert len(records) == 1 and records[0]["phase"] == "unknown" and "draft" not in records[0]
    with pytest.raises(ProjectCommandUnknown):
        native.preview_document_edit(project, [], **arguments)
    with pytest.raises(ProjectCommandUnknown):
        ProjectCommands(project_store(project)).resume(ProjectCommand.from_payload(records[0]["metadata"]))
    assert len(calls) == 1
    assert (project / "studio/document.vsz").read_bytes() == before
    assert not (project.parent / ".document_edit_history").exists()


def test_identified_window_preserves_its_draft_witness_across_unrelated_figure_export(project):
    from types import SimpleNamespace
    from sciplot_core.studio_core.project_session import (
        ProjectSessionLease, close_window_session, window_document_session,
    )

    target = project / "studio/document.vsz"
    window = SimpleNamespace(filename="", document=SimpleNamespace(isModified=lambda: True, save=lambda *_args: None))
    with window_document_session(window, target, loading=True):
        window.filename = str(target)
    binding = window.document._sciplot_project_read_set
    with ProjectSessionLease(project, native=False):
        pass
    other = publish_other_figure(project)
    with window_document_session(window, target):
        assert window.document._sciplot_project_read_set is binding
    assert binding["generation"] != other["generation"]
    assert "studio/figures/second.vsz" not in binding["files"]
    close_window_session(window)


@pytest.mark.parametrize("registered", [True, False])
def test_whole_source_preview_rejects_new_members_without_overwriting_either_revision(project, tmp_path, registered):
    from sciplot_core.studio_core.source_update_commands import stage_source_update, decide_source_update
    from sciplot_core.studio_core.source_update_commit import file_inventory, project_inventory
    from sciplot_core.studio_core.source_update_review import payload_hash
    from sciplot_core.studio_core.project_command_scope import project_store

    (project / "raw").mkdir()
    (project / "raw/instrument.csv").write_bytes((project / "source/data.csv").read_bytes())
    candidate = tmp_path / "whole-candidate"
    shutil.copytree(project, candidate)
    new_source = tmp_path / "new.csv"
    new_source.write_text("x,y\n1,7\n")
    (candidate / "source/data.csv").write_bytes(new_source.read_bytes())
    review = {"kind": "sciplot_source_update_preview", "version": 1, "status": "ready",
        "source": str(new_source), "source_files": file_inventory(new_source),
        "project_sha256": payload_hash(project_inventory(project)), "delivery_sha256": payload_hash(None),
        "changes": [], "styles": []}
    supplied = stage_source_update(project, candidate, review)
    store = project_store(project)
    late = project / "studio/exports/late-b.pdf"
    if registered:
        before = store.snapshot()
        command = ProjectCommand.create("native_export", "new-member", project_id=before["project_id"],
            expected_generation=before["generation"], read_set={"studio/exports/late-b.pdf": None},
            write_set=["studio/exports/late-b.pdf"], request={"figure_id": "second"})
        ProjectCommands(store).execute(command, lambda: ProjectMutation({"studio/exports/late-b.pdf": b"new B export"}, {}))
    else:
        late.parent.mkdir(parents=True)
        late.write_bytes(b"unregistered native output")
    native = (project / "studio/document.vsz").read_bytes()
    raw = (project / "source/data.csv").read_bytes()
    late_bytes = late.read_bytes()
    with pytest.raises(ValueError, match="member|namespace"):
        decide_source_update(project, supplied)
    assert (project / "studio/document.vsz").read_bytes() == native
    assert (project / "source/data.csv").read_bytes() == raw
    assert late.read_bytes() == late_bytes


def test_actual_native_edit_accepts_independent_other_export_and_replays_without_render(edit):
    project, document, review, calls = edit
    before = document.read_bytes()
    other = publish_other_figure(project)
    result = native.apply_document_edit(project, review)
    assert result["status"] == "applied" and result["result_is_current"]
    assert document.read_bytes() != before and Path(result["archive"]).read_bytes() == before
    assert (project / "studio/exports/second.pdf").read_bytes() == b"new-b-export"
    assert json.loads((project / "studio/figure_set.json").read_text())["figures"][1]["document_state"]
    assert result["project_command"]["generation"] != other["generation"]
    assert native.apply_document_edit(project, review)["status"] == "already_applied"
    assert len(calls) == 1
    assert not (project.parent / ".document_edit_history").exists()


def test_pending_native_preview_moves_through_explicit_host_projection_only(edit, tmp_path, monkeypatch):
    from sciplot_core.studio_core.document_edit_commands import rebind_document_edit_review

    project, document, review, calls = edit
    before = document.read_bytes()
    store = FileProjectStore(project)
    bundle = store.export_bundle(tmp_path / "pending-bundle")
    cold = FileProjectStore.import_bundle(bundle, tmp_path / "pending-moved")
    project.rename(tmp_path / "original-offline")
    monkeypatch.setattr(native, "_candidate", lambda *_args, **_kwargs: pytest.fail("frozen preview rerendered"))
    with pytest.raises(ValueError, match="unchanged stored"):
        native.apply_document_edit(cold.root, review)
    forged = json.loads(json.dumps(review))
    forged["scientific_audit"]["status"] = "forged"
    with pytest.raises(ValueError, match="sealed intent"):
        rebind_document_edit_review(cold.root, forged)
    rebound = rebind_document_edit_review(cold.root, review)
    assert rebound["operation_id"] == review["operation_id"] and rebound["decision_id"] == review["decision_id"]
    assert rebound["scientific_audit"] == review["scientific_audit"]
    assert Path(rebound["candidate"]["path"]).is_relative_to(cold.root)
    result = native.apply_document_edit(cold.root, rebound)
    assert result["status"] == "applied" and Path(result["archive"]).read_bytes() == before
    assert len(calls) == 1


@pytest.mark.parametrize("changed", ["native", "source", "selected_membership"])
def test_actual_native_edit_rejects_true_read_conflicts_without_losing_external_bytes(edit, changed):
    project, document, review, calls = edit
    before = document.read_bytes()
    if changed == "selected_membership":
        store = FileProjectStore(project)
        snapshot = store.snapshot()
        path = "studio/figure_set.json"
        value = json.loads(store.read_bytes(path))
        value["figures"][0]["document"] = "remapped.vsz"
        command = ProjectCommand.create("figure_set", "remap-selected", project_id=snapshot["project_id"],
            expected_generation=snapshot["generation"], read_set={path: snapshot["files"][path]["sha256"]},
            write_set=[path], request={"selected_remap": True})
        ProjectCommands(store).execute(command, lambda: ProjectMutation({path: json.dumps(value).encode()}, {}))
    else:
        target = document if changed == "native" else project / "source/data.csv"
        target.write_bytes(b"external current version must survive")
    with pytest.raises(ValueError):
        native.apply_document_edit(project, review)
    assert len(calls) == 1
    if changed == "native":
        assert document.read_bytes() == b"external current version must survive"
    else:
        assert document.read_bytes() == before


@pytest.mark.comprehensive
def test_native_commit_hard_exit_recovers_shared_generation_without_old_outcome_journal(project, tmp_path):
    document, candidate = project / "studio/document.vsz", tmp_path / "candidate.vsz"
    source = (project / "source/data.csv").read_bytes()
    original = document.read_bytes()
    candidate.write_bytes(b"new controlled native")
    review = {"base_state": edit_state(project), "changes": []}
    review["operation_id"] = preview_identity(review)
    saved = tmp_path / "review.json"
    saved.write_text(json.dumps(review))
    code = '''
import json, os, sys
from pathlib import Path
from sciplot_core.project_store import state
from sciplot_core.studio_core.document_edit_commit import commit_document_edit
def boundary(name):
    if name == 'after_projection':
        os._exit(86)
state.boundary = boundary
project, document, candidate, review = map(Path, sys.argv[1:])
commit_document_edit(project, document, candidate, json.loads(review.read_text()))
'''
    result = subprocess.run([sys.executable, "-c", code, str(project), str(document), str(candidate), str(saved)],
                            capture_output=True, timeout=20)
    assert result.returncode == 86, result.stderr
    recovered = prior_edit_result(project, review)
    assert recovered["status"] == "already_applied" and recovered["result_is_current"]
    assert document.read_bytes() == candidate.read_bytes()
    assert Path(recovered["archive"]).read_bytes() == original
    assert (project / "source/data.csv").read_bytes() == source
    assert not (project.parent / ".document_edit_history").exists()


def test_host_factory_rejects_unadmitted_delivery_root_before_selecting_it(project, tmp_path, monkeypatch):
    from sciplot_core.project_store import ProjectConflict
    from sciplot_core.studio_core import project_command_scope as scope
    selected = scope.project_store(project)
    selected.snapshot(import_legacy=True)
    foreign = tmp_path / "foreign-root"
    foreign.mkdir()
    (foreign / "preserve.txt").write_bytes(b"unrelated outside files")
    request = json.loads((project / "plot_request.json").read_text())
    request["delivery_output"] = str(foreign)
    (project / "plot_request.json").write_text(json.dumps(request))
    monkeypatch.setattr(scope, "requested_delivery_root", lambda *_a, **_kw: pytest.fail("unadmitted root was selected"))
    with pytest.raises(ProjectConflict, match="canonical request differs"):
        scope.project_store(project, create_delivery=True, with_snapshot=True)
    assert (foreign / "preserve.txt").read_bytes() == b"unrelated outside files"


def test_pending_factory_accepts_only_sealed_parent_or_head_request_before_cap_selection(project, tmp_path, monkeypatch):
    from sciplot_core.project_store import ProjectConflict, state
    from sciplot_core.studio_core import project_command_scope as scope
    store = scope.project_store(project)
    before = store.snapshot(import_legacy=True)
    path = project / "plot_request.json"
    parent_bytes = path.read_bytes()
    request = {**json.loads(parent_bytes), "review_notes": ["sealed new head request"]}
    command = ProjectCommand.create("source_update", "pending-canonical-request", project_id=before["project_id"],
        expected_generation=before["generation"], read_set={"plot_request.json": file_sha256(path)},
        write_set=["plot_request.json"], request={"source_revision": "generated request guard"})
    boundary = state.boundary
    def stop(name):
        if name == "before_projection":
            raise OSError("generated pending request")
        boundary(name)
    monkeypatch.setattr(state, "boundary", stop)
    with pytest.raises(OSError, match="generated pending request"):
        ProjectCommands(store).execute(command, lambda: ProjectMutation({"plot_request.json": json.dumps(request).encode()}, {}))
    monkeypatch.setattr(state, "boundary", boundary)
    assert scope._admitted_request(project) == request and path.read_bytes() == parent_bytes
    foreign = tmp_path / "never-selected"
    path.write_text(json.dumps({**request, "delivery_output": str(foreign)}))
    monkeypatch.setattr(scope, "requested_delivery_root", lambda *_a, **_kw: pytest.fail("foreign pending root was selected"))
    with pytest.raises(ProjectConflict, match="canonical request differs"):
        scope.project_store(project, create_delivery=True)
    assert not foreign.exists()
    path.write_bytes(parent_bytes)
    store.recover()
    assert json.loads(path.read_bytes()) == request


def test_external_canonical_run_output_has_stable_host_cap_and_cold_mapping(project, tmp_path):
    from sciplot_core.studio_core.project_command_scope import project_store
    output = tmp_path / "dedicated-run"
    request_path = project / "plot_request.json"
    request_path.write_text(json.dumps({**json.loads(request_path.read_text()), "output": str(output)}))
    selected = project_store(project, create_output=True)
    key = next(key for key, root in selected.locations.items() if root == output)
    assert key.startswith("run_")
    before = selected.snapshot(import_legacy=True)
    resource = selected.logical_path(output / "manifest.json")
    command = ProjectCommand.create("export", "external-canonical-run", project_id=before["project_id"],
        expected_generation=before["generation"], read_set={resource: None}, write_set=[resource], request={"run": "external"})
    ProjectCommands(selected).execute(command, lambda: ProjectMutation({resource: b'{"complete":true}'}, {}))
    assert project_store(project).logical_path(output / "manifest.json") == resource
    cold = FileProjectStore.import_bundle(selected.export_bundle(tmp_path / "run-bundle"), tmp_path / "run-cold")
    project.rename(tmp_path / "project-offline")
    output.rename(tmp_path / "external-run-offline")
    reopened = project_store(cold.root, create_output=True)
    assert not output.exists() and reopened.locations[key] == cold.root / ".sciplot_resources" / key
    assert reopened.read_bytes(resource) == b'{"complete":true}'


def test_external_run_root_cannot_overlap_raw_input_or_project_parent(project, tmp_path):
    from sciplot_core.studio_core.project_command_scope import project_store
    path = project / "plot_request.json"
    original = json.loads(path.read_text())
    for output in (project.parent, project / "source"):
        path.write_text(json.dumps({**original, "output": str(output)}))
        with pytest.raises(ValueError, match="contain its source project|overlap"):
            project_store(project, create_output=True)
    external = tmp_path / "raw-directory"
    external.mkdir()
    path.write_text(json.dumps({**original, "input": str(external), "output": str(external / "must-not-create")}))
    with pytest.raises(ValueError, match="overlap"):
        project_store(project, create_output=True)
    assert not (external / "must-not-create").exists()
