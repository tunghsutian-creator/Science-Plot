from __future__ import annotations

from pathlib import Path
import json

import pytest

from sciplot_core.studio_core.project_export import export_project_document


@pytest.fixture
def publication(tmp_path, monkeypatch):
    import json
    from sciplot_core.foundation.file_hashing import file_sha256
    from sciplot_core.studio_core import native_export_adapter, publication_prepare, categorical_display_preflight
    project = tmp_path / "project"
    native = project / "studio/document.vsz"
    native.parent.mkdir(parents=True)
    native.write_bytes(b"saved current native")
    source = project / "source/data.csv"
    source.parent.mkdir()
    source.write_text("x,y\n1,2\n")
    native.with_name("spec.json").write_text(json.dumps({"series": [{"source_artifacts": [
        {"path": str(source), "sha256": file_sha256(source)}]}]}))
    (project / "plot_request.json").write_text(json.dumps({"input": str(source)}))
    calls, published = [], {}
    monkeypatch.setattr(categorical_display_preflight, "require_categorical_display_current", lambda *_a: None)
    def export(document, *, formats, output_dir, audit_spec_path):
        calls.append(("export", document, formats, audit_spec_path))
        output_dir.mkdir()
        path = output_dir / "figure.pdf"
        path.write_bytes(b"controlled export of exact current native")
        return {"document_sha256": file_sha256(document), "exports": [{"path": str(path), "format": "pdf",
            "sha256": file_sha256(path)}], "document_audit": {"kind": "current call native evidence"}}
    def prepare(**kwargs):
        calls.append(("publish", kwargs))
        delivery = kwargs["delivery_dir"]
        delivery.mkdir()
        (delivery / "delivered.pdf").write_bytes(b"controlled delivery")
        manifest = {"result": {"scientific_data_verification": {"status": "passed"}}}
        (kwargs["output_dir"] / "manifest.json").write_text(json.dumps(manifest))
        published.update(ready_to_use=True, state="ready", exports=kwargs["exports"], delivery_package={"complete": True})
        return published
    monkeypatch.setattr(native_export_adapter, "export_studio_document", export)
    monkeypatch.setattr(publication_prepare, "prepare_studio_export_run", prepare)
    return project, calls, published


def test_project_export_publishes_once_and_returns_an_immutable_snapshot(publication):
    from sciplot_core.project_store import FileProjectStore
    project, calls, published = publication
    before = (project / "studio/document.vsz").read_bytes()
    result = export_project_document(project_dir=project, formats=["pdf", "tiff_300"])
    assert [call[0] for call in calls] == ["export", "publish"]
    assert calls[1][1]["export_document_sha256"] == result.document_sha256
    assert result.ready_to_use is True
    published["ready_to_use"] = False
    result.run_payload["state"] = "changed"
    assert result.run_payload["state"] == "ready" and result.run_payload["ready_to_use"] is True
    assert result.exports[0]["path"] == str(project / "studio/exports/figure.pdf")
    assert (project / "studio/document.vsz").read_bytes() == before
    records = FileProjectStore(project).commands()
    assert len(records) == 1 and records[0]["phase"] == "complete"
    assert {"studio/exports/figure.pdf", "runs/studio_001/manifest.json"} <= set(records[0]["draft"]["writes"])


def test_noncanonical_document_cannot_publish_to_a_project(tmp_path, monkeypatch):
    from sciplot_core.studio_core import project_publication_commands
    monkeypatch.setattr(project_publication_commands, "publish_project_exports", lambda **_k: pytest.fail("invalid identity published"))
    with pytest.raises(RuntimeError, match="canonical"):
        export_project_document(project_dir=tmp_path, document_path=tmp_path / "copy.vsz", formats=["pdf"])


def test_managed_export_requests_inline_science_and_passes_only_this_call_evidence(publication):
    project, calls, _ = publication
    result = export_project_document(project_dir=project, formats=["pdf", "tiff_300"])
    assert result.ready_to_use
    assert calls[0][1:] == (project / "studio/document.vsz", ["pdf", "tiff_300"], project / "studio/spec.json")
    assert calls[1][1]["primary_native_audit"] == {"kind": "current call native evidence"}


def test_failed_inline_export_audit_never_enters_publication(publication, monkeypatch):
    from sciplot_core.studio_core import native_export_adapter
    from sciplot_core.project_store import FileProjectStore
    project, calls, _ = publication
    before = {str(p.relative_to(project)): p.read_bytes() for p in project.rglob("*") if p.is_file()}
    def export(*_a, **_k):
        raise ValueError("Exact-current Veusz data-consumption audit did not pass.")
    monkeypatch.setattr(native_export_adapter, "export_studio_document", export)
    with pytest.raises(ValueError, match="audit did not pass"):
        export_project_document(project_dir=project, formats=["pdf", "tiff_300"])
    assert not calls and not FileProjectStore(project).commands()
    assert {str(p.relative_to(project)): p.read_bytes() for p in project.rglob("*")
            if p.is_file() and ".sciplot_store" not in p.parts} == before


def test_worker_export_forwards_optional_audit_without_changing_standalone_calls(tmp_path, monkeypatch):
    from sciplot_core.veusz_worker import cli

    calls = []
    monkeypatch.setattr(cli, "export_document", lambda *args, **kwargs: calls.append((args, kwargs)) or {})
    document, spec = tmp_path / "document.vsz", tmp_path / "spec.json"
    assert cli.main(["export-document", str(document)]) == 0
    assert "audit_spec_path" not in calls[-1][1]
    assert cli.main(["export-document", str(document), "--audit-spec", str(spec)]) == 0
    assert calls[-1][1]["audit_spec_path"] == spec


def test_intake_creates_one_prepared_document_then_exports_it_once(
    tmp_path: Path, monkeypatch
) -> None:
    from sciplot_core.intake import application, run
    from sciplot_core.intake.models import IncomingFile, IntakeGroupInput
    from sciplot_core.project_manifest import edit_intake_project_manifest
    import sciplot_core.studio_core.project_publication_commands as export_module
    from sciplot_core.foundation.file_hashing import existing_file_sha256

    calls = []

    def prepare(project_dir: Path, *, _new_creation: bool = False):
        assert _new_creation is True
        calls.append(("prepare", project_dir))
        document = project_dir / "studio" / "document.vsz"
        document.parent.mkdir()
        document.write_bytes(b"prepared once from confirmed source")
        return {"studio": {"status": "ready", "document": str(document)}}

    def export(document: Path, *, formats, audit_spec_path):
        calls.append(("export", document))
        assert document.read_bytes() == b"prepared once from confirmed source"
        assert formats == ["pdf", "tiff_300"]
        assert audit_spec_path == document.with_name("spec.json")
        return {"document_sha256": existing_file_sha256(document), "exports": []}

    def publish(**kwargs):
        calls.append(("publish", kwargs["document_path"]))
        project = kwargs["project_dir"]
        assert kwargs["document_path"] == project / "studio" / "document.vsz"
        assert kwargs["request_path"] == project / "plot_request.json"
        result = {
            "output": str(project / "runs" / "studio_001"),
            "ready_to_use": True,
            "state": "ready",
            "exports": [],
        }
        with edit_intake_project_manifest(project, require_existing=True) as manifest:
            assert manifest is not None
            manifest["last_run"] = result
        return result

    monkeypatch.setattr(application, "prepare_studio_document", prepare)
    def composite(**kwargs):
        current = kwargs["document_path"]
        exported = export(current, formats=kwargs["formats"], audit_spec_path=current.with_name("spec.json"))
        return {**publish(**kwargs), "document_sha256": exported["document_sha256"]}
    monkeypatch.setattr(export_module, "publish_project_exports", composite)
    result = run.create_and_run_intake_project(
        project_name="Single preparation",
        data_type_id="thermal",
        experiment_type_id="dsc_curve",
        groups=[
            IntakeGroupInput(
                sample="sample",
                files=(
                    IncomingFile(
                        name="dsc.csv",
                        content=b"Temperature (C),Heat flow (W/g)\n10,1\n20,2\n",
                    ),
                ),
            )
        ],
        output_root=tmp_path,
    )
    assert [name for name, _ in calls] == ["prepare", "export", "publish"]
    assert result["last_run"]["ready_to_use"] is True
    assert Path(result["last_run"]["output"]).name == "studio_001"
    assert result.get("run_failed") is not True


def _visible_publication(publication, tmp_path, monkeypatch, *, complete=True, existing=False, during=None, visible=None):
    from sciplot_core.studio_core import publication_prepare, native_export_adapter

    project, calls, published = publication
    visible = visible or tmp_path / "visible"
    if existing:
        visible.mkdir()
    request = project / "plot_request.json"
    request.write_text(json.dumps({**json.loads(request.read_text()), "delivery_output": str(visible)}))
    prepare, export = publication_prepare.prepare_studio_export_run, native_export_adapter.export_studio_document

    def render(*args, **kwargs):
        assert visible.exists() is existing
        return export(*args, **kwargs)

    def finish(**kwargs):
        assert kwargs["delivery_root"] == visible and visible.exists() is existing
        result = prepare(**kwargs)
        result.update(ready_to_use=complete, state="ready" if complete else "blocked",
                      manifest=str(kwargs["output_dir"] / "manifest.json"))
        result["delivery_package"]["complete"] = complete
        if during is not None:
            during(project, visible)
        return result

    monkeypatch.setattr(native_export_adapter, "export_studio_document", render)
    monkeypatch.setattr(publication_prepare, "prepare_studio_export_run", finish)
    return project, visible, calls, published


@pytest.mark.parametrize("existing", [False, True])
def test_failed_publication_keeps_diagnostics_without_allocating_or_removing_visible_root(publication, tmp_path, monkeypatch, existing):
    from sciplot_core.project_host_factory import project_store

    project, visible, calls, _published = _visible_publication(
        publication, tmp_path, monkeypatch, complete=False, existing=existing)
    identity = visible.stat().st_ino if existing else None
    result = export_project_document(project_dir=project, formats=["pdf"])
    assert not result.ready_to_use and visible.exists() is existing
    assert (visible.stat().st_ino if existing else None) == identity
    assert not existing or list(visible.iterdir()) == []
    assert (project / "runs/studio_001/failed_delivery/delivered.pdf").read_bytes() == b"controlled delivery"
    assert Path(result.run_payload["manifest"]).is_file()
    snapshot = project_store(project).snapshot()
    assert ("delivery" in snapshot["resource_roots"]) is existing
    assert not any(name.startswith("@delivery/") for name in snapshot["files"])
    assert [call[0] for call in calls] == ["export", "publish"]


def test_successful_publication_binds_new_delivery_once_and_retains_finite_snapshot_cap(publication, tmp_path, monkeypatch):
    from sciplot_core.project_store import FileProjectStore, ResourceRoot
    from sciplot_core.studio_core import project_publication_commands

    project, visible, calls, _published = _visible_publication(publication, tmp_path, monkeypatch)
    archive = tmp_path / "historic.zip"
    archive.write_bytes(b"previous finite snapshot")
    store = FileProjectStore(project, locations={"snapshot": ResourceRoot(tmp_path, (archive.name,))})
    before = store.snapshot(import_legacy=True)
    monkeypatch.setattr(project_publication_commands, "_publication_store", lambda _project: store)
    result = export_project_document(project_dir=project, formats=["pdf"])
    reopened = FileProjectStore(project, locations={"snapshot": ResourceRoot(tmp_path, (archive.name,)), "delivery": visible})
    after = reopened.snapshot()
    assert result.ready_to_use and (visible / "delivered.pdf").read_bytes() == b"controlled delivery"
    assert after["resource_roots"]["snapshot"] == before["resource_roots"]["snapshot"]
    assert after["files"]["@snapshot/historic.zip"] == before["files"]["@snapshot/historic.zip"]
    assert after["resource_roots"]["delivery"]["inode"] == visible.stat().st_ino
    assert [call[0] for call in calls] == ["export", "publish"]


@pytest.mark.parametrize("change", ["empty", "foreign", "alias", "existing_replaced", "ancestor", "source", "request", "spec"])
def test_publication_refuses_late_root_or_source_changes_before_new_root_registration(publication, tmp_path, monkeypatch, change):
    from sciplot_core.project_host_factory import project_store

    def during(project, visible):
        if change == "source":
            (project / "source/data.csv").write_bytes(b"changed scientific input")
        elif change in {"request", "spec"}:
            path = project / ("plot_request.json" if change == "request" else "studio/spec.json")
            path.write_text(path.read_text() + "\n")
        elif change == "ancestor":
            visible.parent.rename(tmp_path / "original-parent")
            visible.parent.mkdir()
        elif change == "alias":
            foreign = tmp_path / "foreign"
            foreign.mkdir()
            visible.symlink_to(foreign, target_is_directory=True)
        else:
            if change == "existing_replaced":
                visible.rename(tmp_path / "original-visible")
            visible.mkdir()
            if change == "foreign":
                (visible / "unrelated.txt").write_bytes(b"user content")

    target = tmp_path / "visible"
    if change == "ancestor":
        parent = tmp_path / "delivery-parent"
        parent.mkdir()
        target = parent / "visible"
    project, visible, _calls, _published = _visible_publication(publication, tmp_path, monkeypatch,
        existing=change == "existing_replaced", during=during, visible=target)
    store = project_store(project)
    before = store.snapshot(import_legacy=True)
    with pytest.raises(ValueError):
        export_project_document(project_dir=project, formats=["pdf"])
    assert not store.commands()
    if change in {"source", "request", "spec", "ancestor"}:
        assert not visible.exists()
    elif change == "foreign":
        assert (visible / "unrelated.txt").read_bytes() == b"user content"
    elif change == "alias":
        assert visible.is_symlink() and list((tmp_path / "foreign").iterdir()) == []
    else:
        assert visible.is_dir() and list(visible.iterdir()) == []
    assert not (project / "runs").exists()
    assert json.loads((project / ".sciplot_store/head.json").read_text())["generation"] == before["generation"]


def test_created_delivery_identity_cannot_be_substituted_before_core_registration(publication, tmp_path, monkeypatch):
    from sciplot_core.project_host_factory import project_store
    from sciplot_core.studio_core import project_publication_commands

    project, visible, _calls, _published = _visible_publication(publication, tmp_path, monkeypatch)
    original_store = project_publication_commands.FileProjectStore

    def substitute(*args, **kwargs):
        visible.rename(tmp_path / "created-original")
        visible.mkdir()
        return original_store(*args, **kwargs)

    monkeypatch.setattr(project_publication_commands, "FileProjectStore", substitute)
    with pytest.raises(ValueError, match="Core identity"):
        export_project_document(project_dir=project, formats=["pdf"])
    assert list(visible.iterdir()) == list((tmp_path / "created-original").iterdir()) == []
    assert not project_store(project).commands() and not (project / "runs").exists()


def test_new_delivery_root_uses_existing_frozen_recovery_after_committed_head(publication, tmp_path, monkeypatch):
    from sciplot_core.project_store import state
    from sciplot_core.project_host_factory import project_store

    project, visible, calls, _published = _visible_publication(publication, tmp_path, monkeypatch)

    def interrupted(boundary):
        if boundary == "before_projection":
            raise OSError("controlled committed publication")

    monkeypatch.setattr(state, "boundary", interrupted)
    with pytest.raises(OSError, match="committed publication"):
        export_project_document(project_dir=project, formats=["pdf"])
    identity = visible.stat().st_ino
    monkeypatch.setattr(state, "boundary", lambda _boundary: None)
    project_store(project).recover()
    assert visible.stat().st_ino == identity
    assert (visible / "delivered.pdf").read_bytes() == b"controlled delivery"
    assert [call[0] for call in calls] == ["export", "publish"]
