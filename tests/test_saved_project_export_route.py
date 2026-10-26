"""A saved project exports its current native bytes through the existing owner."""
import json

import pytest

from test_project_export_use_case import publication as publication
from sciplot_core.studio_core import native_export_adapter, project_creation, publication_prepare
from sciplot_core.studio_core.project_command_scope import project_store
from sciplot_core.studio_figure_set_contract import STUDIO_FIGURE_SET_KIND


@pytest.mark.parametrize("identifiers", [("primary",), ("primary", "secondary")], ids=["single", "multiple"])
def test_saved_export_never_reprepares_the_observed_native(publication, monkeypatch, identifiers):
    project, calls, _ = publication
    native = project / "studio/document.vsz"
    if len(identifiers) > 1:
        figures = project / "studio/figures"
        figures.mkdir()
        (figures / "secondary.vsz").write_bytes(native.read_bytes())
        (figures / "secondary.spec.json").write_bytes((project / "studio/spec.json").read_bytes())
    registry = {"kind": STUDIO_FIGURE_SET_KIND, "version": 1, "primary_figure_id": "primary",
                "figures": [{"figure_id": identifier, "title": identifier.title(), "status": "ready"}
                            for identifier in identifiers]}
    (project / "studio/figure_set.json").write_text(json.dumps(registry))
    prepare = publication_prepare.prepare_studio_export_run

    def prepare_with_figure_receipts(**kwargs):
        result = prepare(**kwargs)
        result["delivery_package"]["figures"] = [{"figure_id": identifier, "format": "pdf",
            "path": str(kwargs["delivery_dir"] / "delivered.pdf")} for identifier in identifiers]
        return result

    monkeypatch.setattr(publication_prepare, "prepare_studio_export_run", prepare_with_figure_receipts)
    store = project_store(project)
    before = store.snapshot(import_legacy=True)
    observed = native.read_bytes() + b"\ncontrolled manual presentation save"
    native.write_bytes(observed)
    source, spec = project / "source/data.csv", project / "studio/spec.json"
    scientific = source.read_bytes(), spec.read_bytes()
    monkeypatch.setattr(project_creation, "prepare_studio_document", lambda *_a, **_k:
                        pytest.fail("Saved export must not enter creation/preparation."))

    result = project_creation.export_project(project)

    assert result["status"] == "exported" and result["studio_run"]["ready_to_use"] is True
    assert result["document"] == str(native) and result["request"] == str(project / "plot_request.json")
    assert result["primary_figure_id"] == "primary"
    assert [item["figure_id"] for item in result["figures"]] == list(identifiers)
    assert [item["title"] for item in result["figures"]] == [name.title() for name in identifiers]
    assert all(item["exports"] == [{"format": "pdf", "path": str(project / "delivery/delivered.pdf")}]
               for item in result["figures"])
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
