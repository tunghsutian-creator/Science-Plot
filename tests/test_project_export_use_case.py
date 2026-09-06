from __future__ import annotations

from pathlib import Path

import pytest

from sciplot_core.studio_core.project_export import export_project_document


def test_project_export_publishes_once_and_returns_an_immutable_snapshot(
    tmp_path: Path,
) -> None:
    calls = []
    exported = {"document_sha256": "1" * 64, "exports": [{"path": "figure.pdf"}]}
    published = {
        "ready_to_use": True,
        "state": "ready",
        "exports": [{"path": "delivered.pdf"}],
    }

    def export(document, *, formats):
        calls.append(("export", document, formats))
        return exported

    def publish(**kwargs):
        calls.append(("publish", kwargs))
        return published

    result = export_project_document(
        project_dir=tmp_path,
        formats=["pdf", "tiff_300"],
        export_document=export,
        publish_export=publish,
    )
    assert [call[0] for call in calls] == ["export", "publish"]
    assert calls[1][1]["export_document_sha256"] == exported["document_sha256"]
    assert result.ready_to_use is True
    published["ready_to_use"] = False
    result.run_payload["state"] = "changed"
    assert result.run_payload["state"] == "ready"
    assert result.run_payload["ready_to_use"] is True
    assert result.exports == [{"path": "delivered.pdf"}]


def test_noncanonical_document_cannot_publish_to_a_project(tmp_path: Path) -> None:
    def never(*args, **kwargs):
        pytest.fail("Invalid project identity must fail before exporting")

    with pytest.raises(RuntimeError, match="canonical"):
        export_project_document(
            project_dir=tmp_path,
            document_path=tmp_path / "copy.vsz",
            formats=["pdf"],
            export_document=never,
        )


def test_intake_creates_one_prepared_document_then_exports_it_once(
    tmp_path: Path, monkeypatch
) -> None:
    from sciplot_core.intake import application, run
    from sciplot_core.intake.models import IncomingFile, IntakeGroupInput
    from sciplot_core.project_manifest import edit_intake_project_manifest
    import sciplot_core.studio_core.project_export as export_module
    from sciplot_core.foundation.file_hashing import existing_file_sha256

    calls = []

    def prepare(project_dir: Path):
        calls.append(("prepare", project_dir))
        document = project_dir / "studio" / "document.vsz"
        document.parent.mkdir()
        document.write_bytes(b"prepared once from confirmed source")
        return {"studio": {"status": "ready", "document": str(document)}}

    def export(document: Path, *, formats):
        calls.append(("export", document))
        assert document.read_bytes() == b"prepared once from confirmed source"
        assert formats == ["pdf", "tiff_300"]
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
    monkeypatch.setattr(export_module, "export_studio_document", export)
    monkeypatch.setattr(export_module, "publish_studio_export_run", publish)
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
