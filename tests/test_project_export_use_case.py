from __future__ import annotations

from pathlib import Path

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
