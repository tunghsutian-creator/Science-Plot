"""Current native reads use finite document roles without adopting outside bytes."""
import json
import stat
import subprocess
from contextlib import contextmanager
from pathlib import Path

import pytest

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.source_locations import resolve_source_path
from sciplot_core.project_host_factory import project_store
from sciplot_core.project_store import ProjectConflict, ProjectStoreError
from sciplot_core.project_store.native_artifacts import resolve_native_artifact
from sciplot_core.project_store.runtime import project_runtime
from sciplot_core.plot_backends.veusz_identity import fingerprint
from sciplot_core.studio_core import project_query as query
from sciplot_core.studio_core.annotation_operations import require_edit_source_current
from sciplot_core.studio_core.observed_figure_binding import observed_figure_binding
from sciplot_core.studio_core.project_command_scope import figure_binding
from sciplot_core.studio_core import document_edit
from sciplot_core.project_lifecycle.backend_paths import RepositoryBackendPaths
from sciplot_core.project_lifecycle.backend_paths import _retain_preview
from sciplot_core.project_lifecycle.errors import EngineError
from sciplot_core.plot_backends.veusz import VeuszBackend
from sciplot_core.project_store import FileProjectStore

from test_project_query import project as legacy_project


def observed_project(tmp_path):
    project = legacy_project.__wrapped__(tmp_path)
    store = project_store(project)
    store.snapshot(import_legacy=True)
    native = project / "studio/document.vsz"
    native.write_bytes(b"human saved presentation; preserved native bytes")
    return project, store, native


def inventory(root):
    return {str(path.relative_to(root)): (path.read_bytes(), path.stat().st_mode,
            path.stat().st_mtime_ns) for path in root.rglob("*") if path.is_file()}


def native_reader(monkeypatch, native, *, during=None):
    calls = []

    def worker(command, **_options):
        assert command[3:] == ["inspect-document-state", str(native)]
        actual = resolve_native_artifact(native, role="document")
        assert actual == native
        data, digest = actual.read_bytes(), file_sha256(actual)
        calls.append((data, digest))
        if during is not None:
            during()
        payload = {"kind": "sciplot_veusz_document_state", "version": 1,
                   "status": "passed", "document": {"path": str(native), "sha256": digest},
                   "widgets": {}}
        return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")

    monkeypatch.setattr(query, "run_worker", worker)
    return calls


def test_current_native_inspection_reads_saved_bytes_without_adopting_them(tmp_path, monkeypatch):
    project, store, native = observed_project(tmp_path)
    before, files = store.snapshot(), inventory(project)
    calls = native_reader(monkeypatch, native)
    result = query.inspect_project(project, native=True)
    assert result["selected_figure"]["document_sha256"] == file_sha256(native)
    assert result["source"]["prepared"]["current"] is True
    assert calls == [(native.read_bytes(), file_sha256(native))]
    assert store.snapshot() == before and inventory(project) == files


def test_current_native_role_cannot_read_a_foreign_or_scientific_argument(tmp_path, monkeypatch):
    project, store, native = observed_project(tmp_path)
    foreign = tmp_path / "foreign/document.vsz"
    foreign.parent.mkdir()
    foreign.write_bytes(native.read_bytes())
    before, files = store.snapshot(), inventory(project)

    def check_roles():
        for path in (foreign, project / "source/data.csv"):
            with pytest.raises(ProjectConflict, match="frozen role"):
                resolve_native_artifact(path, role="document")
        with pytest.raises(ProjectConflict):
            resolve_source_path(native)

    calls = native_reader(monkeypatch, native, during=check_roles)
    query.inspect_project(project, native=True)
    assert len(calls) == 1
    assert store.snapshot() == before and inventory(project) == files


@pytest.mark.parametrize("change", ["bytes", "mode", "replacement"])
def test_current_native_observation_refuses_changes_during_the_worker(tmp_path, monkeypatch, change):
    project, store, native = observed_project(tmp_path)
    before = store.snapshot()

    def mutate():
        if change == "bytes":
            native.write_bytes(b"another native save during inspection")
        elif change == "mode":
            native.chmod(stat.S_IMODE(native.stat().st_mode) ^ stat.S_IWUSR)
        else:
            replacement = native.with_name("replacement.vsz")
            replacement.write_bytes(native.read_bytes())
            replacement.chmod(stat.S_IMODE(native.stat().st_mode))
            replacement.replace(native)

    calls = native_reader(monkeypatch, native, during=mutate)
    with pytest.raises((ValueError, ProjectConflict, ProjectStoreError)):
        query.inspect_project(project, native=True)
    assert len(calls) == 1
    assert store.snapshot()["generation"] == before["generation"]
    assert (project / "source/data.csv").read_bytes() == b"x,y\n1,2\n"


@pytest.mark.parametrize("change", ["raw", "spec"])
def test_current_native_observation_does_not_turn_scientific_drift_into_readiness(tmp_path, monkeypatch, change):
    project, store, native = observed_project(tmp_path)
    if change == "raw":
        (project / "source/data.csv").write_bytes(b"x,y\n1,9\n")
    else:
        spec = project / "studio/spec.json"
        payload = json.loads(spec.read_bytes())
        payload["series"][0]["source_artifacts"][0]["sha256"] = "0" * 64
        spec.write_text(json.dumps(payload))
    before, files = store.snapshot(), inventory(project)
    native_reader(monkeypatch, native)
    result = query.inspect_project(project, native=True)
    if change == "raw":
        assert result["source"]["current"] is False
        with pytest.raises(ValueError, match="Recorded scientific sources changed"):
            require_edit_source_current(result)
    else:
        # The legacy indicator cannot authenticate a substituted spec. It keeps
        # that evidence unknown; observing native bytes supplies no source proof.
        assert result["source"]["current"] is None
        assert result["source"]["prepared"]["current"] is None
        assert result["source"]["prepared"]["error"]
    assert store.snapshot() == before and inventory(project) == files


@pytest.mark.parametrize("member", ["document.vsz", "spec.json"])
def test_current_native_inspection_refuses_aliased_project_members(tmp_path, monkeypatch, member):
    project, store, native = observed_project(tmp_path)
    before = inventory(project / ".sciplot_store")
    path = project / "studio" / member
    foreign = tmp_path / member
    foreign.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(foreign)
    calls = native_reader(monkeypatch, native)
    with pytest.raises((ValueError, ProjectConflict, ProjectStoreError)):
        query.inspect_project(project, native=True)
    assert not calls
    assert path.is_symlink()
    assert inventory(project / ".sciplot_store") == before


def selected_audit(project):
    selected = query.resolve_project_figure(project)
    audit = {"status": "passed", "document_sha256": selected["document_sha256"],
             "spec_sha256": selected["spec_sha256"]}
    return selected, audit


def test_observed_binding_keeps_canonical_cas_and_actual_native_fingerprint_separate(tmp_path):
    project, store, native = observed_project(tmp_path)
    before, files = store.snapshot(), inventory(project)
    selected, audit = selected_audit(project)
    with project_runtime(store):
        with pytest.raises(ValueError, match="unregistered outside changes"):
            figure_binding(project, selected)
        binding = observed_figure_binding(project, selected, audit)
    assert binding["files"]["studio/document.vsz"] == before["files"]["studio/document.vsz"]["sha256"]
    assert binding["files"]["studio/document.vsz"] != selected["document_sha256"]
    actual = {"project": str(project), "document": str(native),
        "files": {str(native): selected["document_sha256"],
                  str(project / "source/data.csv"): file_sha256(project / "source/data.csv")}, "source_trees": {}}
    assert fingerprint(actual)["files"] == actual["files"]
    assert store.snapshot() == before and inventory(project) == files


@pytest.mark.parametrize("failure", ["failed-audit", "native-hash", "spec-hash", "mode", "raw", "spec", "request", "membership", "unknown"])
def test_observed_binding_requires_exact_selected_science_and_registered_identity(tmp_path, failure):
    project, store, native = observed_project(tmp_path)
    selected, audit = selected_audit(project)
    if failure == "failed-audit":
        audit["status"] = "failed"
    elif failure in {"native-hash", "spec-hash"}:
        audit["document_sha256" if failure == "native-hash" else "spec_sha256"] = "0" * 64
    elif failure == "mode":
        native.chmod(stat.S_IMODE(native.stat().st_mode) ^ stat.S_IWUSR)
    elif failure == "raw":
        (project / "source/data.csv").write_bytes(b"changed raw")
    elif failure in {"spec", "request"}:
        path = project / ("studio/spec.json" if failure == "spec" else "plot_request.json")
        path.write_text(path.read_text() + "\n")
    elif failure == "membership":
        path = project / "studio/figure_set.json"
        payload = json.loads(path.read_bytes())
        payload["figures"][0]["title"] = "replaced selected identity"
        path.write_text(json.dumps(payload))
    else:
        unknown = project / "studio/unknown.vsz"
        unknown.write_bytes(native.read_bytes())
        selected["document"] = str(unknown)
    before = inventory(project)
    with project_runtime(store), pytest.raises((ValueError, ProjectConflict, ProjectStoreError)):
        observed_figure_binding(project, selected, audit)
    assert inventory(project) == before


def test_current_native_preview_has_exact_document_and_single_fresh_output_roles(tmp_path, monkeypatch):
    project, store, native = observed_project(tmp_path)
    before = store.snapshot()
    output = tmp_path / "new-review"
    calls = []
    def worker(*arguments):
        assert arguments == ("preview-document", native, "--out", output / "current.png")
        actual = resolve_native_artifact(native, role="document")
        target = resolve_native_artifact(output / "current.png", role="out", output=True)
        with pytest.raises(ProjectConflict, match="frozen role"):
            resolve_native_artifact(output / "other.png", role="out", output=True)
        calls.append(actual.read_bytes())
        target.write_bytes(b"pure preview placeholder")
        return {"document": {"path": str(native), "sha256": file_sha256(native)},
                "preview": {"path": str(target), "sha256": file_sha256(target)}}
    monkeypatch.setattr(document_edit, "run_document_worker", worker)
    result = document_edit.preview_project_document(project, output_dir=output)
    assert result["document"]["sha256"] == file_sha256(native)
    assert calls == [native.read_bytes()]
    assert store.snapshot() == before


@pytest.mark.parametrize("failure", ["foreign", "alias", "hash"])
def test_retained_native_preview_refuses_a_substituted_artifact(tmp_path, failure):
    workspace = tmp_path / "owned-workspace"
    workspace.mkdir()
    image = workspace / "current.png"
    image.write_bytes(b"owned preview bytes")
    preview = {"path": str(image), "sha256": file_sha256(image)}
    if failure == "foreign":
        foreign = tmp_path / "foreign.png"
        foreign.write_bytes(image.read_bytes())
        preview["path"] = str(foreign)
    elif failure == "alias":
        alias = workspace / "alias.png"
        alias.symlink_to(image)
        preview["path"] = str(alias)
    else:
        preview["sha256"] = "0" * 64
    destination = tmp_path / "derived-preview"
    with pytest.raises((ValueError, EngineError)):
        _retain_preview({"preview": preview}, workspace, destination)
    assert not destination.exists() and image.read_bytes() == b"owned preview bytes"


@pytest.mark.parametrize("attached_marker", [False, True])
def test_attached_observed_native_render_uses_external_workspace_and_retains_exact_preview(tmp_path, monkeypatch, attached_marker):
    project, store, native = observed_project(tmp_path)
    before = store.snapshot()
    selected, _audit = selected_audit(project)
    destination = project / ".sciplot_store/semantic-derived/owned/reimport-preview"
    class Repository:
        @contextmanager
        def binding_scope(self, _binding):
            with project_runtime(store):
                yield
        def runtime_path(self, _path):
            return destination
    def worker(*arguments):
        assert arguments[:2] == ("preview-document", native)
        image = arguments[3]
        assert not image.is_relative_to(project)
        actual = resolve_native_artifact(native, role="document")
        assert actual.read_bytes() == native.read_bytes()
        target = resolve_native_artifact(image, role="out", output=True)
        target.write_bytes(b"pure reviewed native pixels")
        return {"document": {"path": str(native), "sha256": file_sha256(native)},
                "preview": {"path": str(target), "sha256": file_sha256(target)}}
    monkeypatch.setattr(document_edit, "run_document_worker", worker)
    binding = {"kind": "sciplot_veusz_binding",
        "project": str(project), "document": str(native), "figure_id": selected["figure_id"],
        "files": {str(native): file_sha256(native)}, "source_trees": {}}
    if attached_marker:
        binding["_semantic_attachment_id"] = "a" * 32
    binding["fingerprint"] = fingerprint(binding)
    backend = VeuszBackend(warm=False)
    result = RepositoryBackendPaths(backend, Repository()).render(binding, tmp_path / "logical-preview")
    image = Path(result["preview"]["path"])
    assert image.parent == destination
    assert image.read_bytes() == b"pure reviewed native pixels"
    assert file_sha256(image) == result["preview"]["sha256"]
    assert store.snapshot() == before


def test_reimport_preview_role_maps_through_the_real_registered_repository_without_writes(tmp_path):
    from managed_plot_helpers import request_for_source
    from test_attached_semantic_repository import application

    project = tmp_path / "project"
    project.mkdir()
    wire = request_for_source(project)
    store = FileProjectStore(project)
    store.snapshot(import_legacy=True)
    app = application()
    with project_runtime(store):
        created = app.create(wire)
    root = Path(created["plot"])
    before, files = store.snapshot(), inventory(project)
    output = root / "transactions" / ("a" * 64) / "preview-reimport"
    expected = project / ".sciplot_store/semantic-derived" / root.name / "state" / output.relative_to(root)
    with app.repository.invocation_scope(), project_runtime(store):
        assert app.repository.runtime_path(output) == expected
        assert app.repository.runtime_path(output.with_name("reimport-preview")) == output.with_name("reimport-preview")
    assert not expected.exists()
    assert store.snapshot() == before and inventory(project) == files
