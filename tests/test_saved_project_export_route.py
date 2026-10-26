"""A saved project exports its current native bytes through the existing owner."""
import pytest

from test_project_export_use_case import publication as publication
from sciplot_core.studio_core import native_export_adapter, project_creation
from sciplot_core.studio_core.project_command_scope import project_store


def test_saved_export_never_reprepares_the_observed_native(publication, monkeypatch):
    project, calls, _ = publication
    store = project_store(project)
    before = store.snapshot(import_legacy=True)
    native = project / "studio/document.vsz"
    observed = native.read_bytes() + b"\ncontrolled manual presentation save"
    native.write_bytes(observed)
    source, spec = project / "source/data.csv", project / "studio/spec.json"
    scientific = source.read_bytes(), spec.read_bytes()
    monkeypatch.setattr(project_creation, "prepare_studio_document", lambda *_a, **_k:
                        pytest.fail("Saved export must not enter creation/preparation."))

    result = project_creation.export_project(project)

    assert result["status"] == "exported" and result["studio_run"]["ready_to_use"] is True
    assert result["document"] == str(native) and result["request"] == str(project / "plot_request.json")
    assert [call[0] for call in calls] == ["export", "publish"]
    assert native.read_bytes() == observed and (source.read_bytes(), spec.read_bytes()) == scientific
    after = store.snapshot()
    records = store.commands()
    assert after["generation"] != before["generation"] and not after["outside_changes"]
    assert len(records) == 1 and records[0]["phase"] == "complete"
    assert records[0]["metadata"]["kind"] == "native_import"
    assert records[0]["draft"]["writes"]["studio/document.vsz"]["sha256"] == after["files"]["studio/document.vsz"]["sha256"]


def test_saved_export_preserves_inline_scientific_audit_refusal(publication, monkeypatch):
    project, calls, _ = publication
    store = project_store(project)
    before = store.snapshot(import_legacy=True)
    native = project / "studio/document.vsz"
    observed = native.read_bytes() + b"\ncontrolled invalid scientific native save"
    native.write_bytes(observed)
    monkeypatch.setattr(project_creation, "prepare_studio_document", lambda *_a, **_k:
                        pytest.fail("Saved export must not regenerate rejected native state."))

    def failed_audit(*_args, **_kwargs):
        raise ValueError("Exact-current scientific audit refused the observed native")

    monkeypatch.setattr(native_export_adapter, "export_studio_document", failed_audit)
    with pytest.raises(ValueError, match="scientific audit refused"):
        project_creation.export_project(project)
    assert not calls and not store.commands() and native.read_bytes() == observed
    assert store.snapshot()["generation"] == before["generation"]
    assert not (project / "runs").exists()


def test_missing_saved_native_cannot_be_recreated_by_export(publication, monkeypatch):
    project, calls, _ = publication
    native = project / "studio/document.vsz"
    native.unlink()
    monkeypatch.setattr(project_creation, "prepare_studio_document", lambda *_a, **_k:
                        pytest.fail("A missing saved native is not an implicit creation request."))
    with pytest.raises(ValueError, match="no saved canonical document"):
        project_creation.export_project(project)
    assert not calls and not native.exists()
