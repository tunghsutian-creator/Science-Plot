"""Public owners consume the same absence proof without mutating their sources."""
from pathlib import Path
import subprocess

import pytest

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.project_commands import ProjectCommand, ProjectCommandUnknown
from sciplot_core.project_store import FileProjectStore, ProjectConflict
from sciplot_core.studio_core.project_export import export_project_document
from sciplot_core.studio_core.native_export_commands import export_saved_native
from sciplot_core.studio_core.external_native_export import export_external_native

from test_project_export_use_case import publication as publication


@pytest.fixture
def rendered(publication, monkeypatch):
    from sciplot_core.studio_core import native_export_adapter, publication_prepare
    project, _old_calls, _published = publication
    calls = []

    def render(document, *, formats, output_dir, audit_spec_path):
        calls.append((str(document), tuple(formats)))
        output_dir.mkdir(parents=True)
        exports = []
        for fmt in formats:
            output = output_dir / ("figure.pdf" if fmt == "pdf" else "figure_300dpi.png")
            output.write_bytes(("fresh-%d-%s" % (len(calls), fmt)).encode())
            exports.append({"format": fmt, "path": str(output), "sha256": file_sha256(output),
                            "exists": True, "size_bytes": output.stat().st_size})
        return {"kind": "sciplot_studio_export", "document": str(document),
            "document_sha256": file_sha256(document), "export_dir": str(output_dir), "exports": exports,
            "document_audit": {"status": "passed", "document": {"path": str(document), "sha256": file_sha256(document)},
                               "spec": {"path": str(audit_spec_path), "sha256": file_sha256(audit_spec_path)}}}

    def publish(**kwargs):
        import json
        from sciplot_core.policy import DELIVERY_PDF_DIR
        delivery = kwargs["delivery_dir"]
        target = delivery / DELIVERY_PDF_DIR / "figure.pdf"
        target.parent.mkdir(parents=True)
        target.write_bytes(Path(kwargs["exports"][0]["path"]).read_bytes())
        manifest = {"result": {"scientific_data_verification": {"status": "passed"}}}
        (kwargs["output_dir"] / "manifest.json").write_text(json.dumps(manifest))
        return {"kind": "sciplot_studio_export_run", "ready_to_use": True, "state": "ready",
            "exports": kwargs["exports"], "delivery_package": {"complete": True,
                "figures": [{"format": "pdf", "path": str(target), "sha256": file_sha256(target)}]}}

    monkeypatch.setattr(native_export_adapter, "export_studio_document", render)
    monkeypatch.setattr(publication_prepare, "prepare_studio_export_run", publish)
    monkeypatch.setattr(subprocess, "Popen", lambda *_a, **_k: pytest.fail("Pure export owner started a process"))
    return project, calls


def execute(owner, project, tmp_path):
    document = project / "studio/document.vsz"
    if owner == "selected":
        return export_saved_native(document, formats=["pdf"], audit_spec_path=project / "studio/spec.json")
    if owner == "standalone":
        return export_external_native(document, formats=["png_300"], output_root=tmp_path / "output")
    return export_project_document(project_dir=project, formats=["pdf"]).run_payload


@pytest.mark.parametrize("owner", ["selected", "standalone", "whole"])
def test_public_export_regenerates_fresh_missing_output_and_keeps_original_history(rendered, tmp_path, owner):
    project, calls = rendered
    scientific = {str(path): path.read_bytes() for path in [project / "studio/document.vsz",
        project / "studio/spec.json", project / "source/data.csv", project / "plot_request.json"]}
    original = execute(owner, project, tmp_path)
    output = Path(original["exports"][0]["path"])
    before_bytes = output.read_bytes()
    store = FileProjectStore(tmp_path / "output") if owner == "standalone" else FileProjectStore(project)
    first = store.commands()
    source_head = (project / ".sciplot_store/head.json").read_bytes() if (project / ".sciplot_store/head.json").exists() else None
    output.unlink()
    fresh = execute(owner, project, tmp_path)
    assert output.read_bytes() != before_bytes and len(calls) == 2
    assert fresh["exports"][0]["sha256"] == file_sha256(output)
    records = store.commands()
    reconstructed, = [record for record in records if record["metadata"].get("missing_outputs")]
    assert reconstructed["phase"] == "complete"
    assert all(store.query(record["command_id"])["result"] == record["result"] for record in first)
    assert {name: Path(name).read_bytes() for name in scientific} == scientific
    if owner == "standalone":
        assert (project / ".sciplot_store/head.json").read_bytes() == source_head if source_head else not (project / ".sciplot_store").exists()


@pytest.mark.parametrize("owner", ["selected", "standalone", "whole"])
def test_foreign_present_output_is_never_classified_as_reconstructable(rendered, tmp_path, owner):
    project, calls = rendered
    original = execute(owner, project, tmp_path)
    artifact = Path(original["exports"][0]["path"])
    artifact.write_bytes(b"foreign manual output")
    before_calls = len(calls)
    store = FileProjectStore(tmp_path / "output") if owner == "standalone" else FileProjectStore(project)
    head = (store.root / ".sciplot_store/head.json").read_bytes()
    with pytest.raises((ProjectConflict, ValueError)):
        execute(owner, project, tmp_path)
    assert artifact.read_bytes() == b"foreign manual output"
    # Whole-publication calculation is disposable private work; its final
    # unchanged CAS guard still refuses any active/canonical replacement.
    assert len(calls) == before_calls + (1 if owner == "whole" else 0)
    assert (store.root / ".sciplot_store/head.json").read_bytes() == head


@pytest.mark.parametrize("owner", ["selected", "standalone", "whole"])
def test_old_unknown_cannot_be_hidden_by_missing_output_or_new_automatic_key(rendered, tmp_path, owner):
    project, calls = rendered
    original = execute(owner, project, tmp_path)
    artifact = Path(original["exports"][0]["path"])
    store = FileProjectStore(tmp_path / "output") if owner == "standalone" else FileProjectStore(project)
    before = store.snapshot()
    name = store.logical_path(artifact)
    old = store.commands()[0]
    metadata = old["metadata"]
    request = dict(metadata["request"])
    request["formats"] = ["pdf", "tiff_300"]
    unknown = ProjectCommand.create(metadata["kind"], "old-unknown", project_id=before["project_id"],
        expected_generation=before["generation"], read_set={name: before["files"][name]["sha256"]},
        write_set=[name], request=request)
    store.reserve(unknown.key, unknown.command_digest, expected_generation=unknown.expected_generation,
                  read_set=dict(unknown.read_set), write_set=unknown.write_set, metadata=unknown.to_payload())
    store.mark_applying(unknown.key, unknown.command_digest)
    artifact.unlink()
    before_calls = len(calls)
    with pytest.raises(ProjectCommandUnknown):
        execute(owner, project, tmp_path)
    assert len(calls) == before_calls and not artifact.exists()
