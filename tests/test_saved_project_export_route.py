"""A saved project exports its current native bytes through the existing owner."""
import json

import pytest

from test_project_export_use_case import publication as publication
from sciplot_core.studio_core import native_export_adapter, project_creation, publication_prepare
from sciplot_core.studio_core.project_command_scope import project_store
from sciplot_core.studio_figure_set_contract import STUDIO_FIGURE_SET_KIND
from sciplot_core.project_commands import ProjectCommand, ProjectCommands, ProjectMutation


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


@pytest.mark.parametrize("target_kind", ["project", "canonical-request"])
def test_studio_saved_export_publishes_current_native_without_preparation(publication, monkeypatch, capsys, target_kind):
    from sciplot_core.studio_core import studio_command

    project, calls, _ = publication
    store = project_store(project)
    before = store.snapshot(import_legacy=True)
    native = project / "studio/document.vsz"
    observed = native.read_bytes() + b"\nmanual presentation save"
    native.write_bytes(observed)
    inputs = {name: (project / name).read_bytes() for name in ("plot_request.json", "source/data.csv", "studio/spec.json")}
    monkeypatch.setattr(studio_command, "maybe_reexec_with_qt_runtime", lambda *_a: None)
    monkeypatch.setattr(studio_command, "prepare_studio_document", lambda *_a, **_k:
                        pytest.fail("Saved native-only export must not prepare or publish another generation first."))
    target = project if target_kind == "project" else project / "plot_request.json"

    assert studio_command.run_studio_command(target=target, export="pdf,tiff_300", json_output=True) == 0

    result = json.loads(capsys.readouterr().out)
    assert result["project_dir"] == str(project) and result["document"] == str(native)
    assert result["preserved_existing_document"] is True and result["studio_run"]["ready_to_use"] is True
    assert result["figure_set"] == result["studio_run"]["figure_set"]
    assert [call[0] for call in calls] == ["export", "publish"]
    assert native.read_bytes() == observed and all((project / name).read_bytes() == data for name, data in inputs.items())
    records = store.commands()
    assert len(records) == 1 and records[0]["metadata"]["kind"] == "native_import" and records[0]["phase"] == "complete"
    assert store.snapshot()["generation"] != before["generation"] and not store.snapshot()["outside_changes"]


@pytest.mark.parametrize("options", [{"rule_id": "uvvis_spectrum"}, {"template": "curve"}, {"project_name": "Requested name"},
                                     {"output_root": "output"}, {"delivery_root": "delivery"}, {"prepare_only": True}])
def test_studio_explicit_preparation_intent_cannot_take_saved_export_shortcut(publication, monkeypatch, options):
    from sciplot_core.studio_core import studio_command

    project, calls, _ = publication
    class PreparationSelected(Exception):
        pass
    def prepare(target, **kwargs):
        assert target == project
        assert all(kwargs.get(name) == value for name, value in options.items() if name != "prepare_only")
        raise PreparationSelected
    monkeypatch.setattr(studio_command, "maybe_reexec_with_qt_runtime", lambda *_a: None)
    monkeypatch.setattr(studio_command, "prepare_studio_document", prepare)
    with pytest.raises(PreparationSelected):
        studio_command.run_studio_command(target=project, export="pdf", json_output=True, **options)
    assert not calls


@pytest.mark.parametrize("target_kind", ["raw-source", "standalone-vsz", "secondary-vsz", "other-request"])
def test_studio_saved_project_export_does_not_claim_other_target_modes(publication, monkeypatch, target_kind):
    from sciplot_core.studio_core import studio_command

    project, calls, _ = publication
    target = {"raw-source": project / "source/data.csv", "standalone-vsz": project.parent / "standalone.vsz",
              "secondary-vsz": project / "studio/figures/secondary.vsz", "other-request": project / "other.json"}[target_kind]
    if target_kind != "raw-source":
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"{}" if target_kind == "other-request" else b"separate native")
    class OtherPreparationSelected(Exception):
        pass
    def prepare(value, **_kwargs):
        assert value == target
        raise OtherPreparationSelected
    monkeypatch.setattr(studio_command, "maybe_reexec_with_qt_runtime", lambda *_a: None)
    monkeypatch.setattr(studio_command, "prepare_studio_document", prepare)
    with pytest.raises(OtherPreparationSelected):
        studio_command.run_studio_command(target=target, export="pdf", json_output=True)
    assert not calls


def test_export_receipt_uses_the_published_generation_not_an_earlier_projection(publication, monkeypatch):
    project, calls, _ = publication
    path = project / "studio/figure_set.json"
    registry = {"kind": STUDIO_FIGURE_SET_KIND, "version": 1, "primary_figure_id": "primary",
                "figures": [{"figure_id": "primary", "title": "Earlier title", "status": "ready"}]}
    path.write_text(json.dumps(registry))
    store = project_store(project)
    before = store.snapshot(import_legacy=True)
    publish = project_creation._publish

    def update_then_publish(payload):
        registry["figures"][0]["title"] = "Published title"
        command = ProjectCommand.create("figure_set", "independent-registry-update",
            project_id=before["project_id"], expected_generation=before["generation"],
            read_set={"studio/figure_set.json": before["files"]["studio/figure_set.json"]["sha256"]},
            write_set=["studio/figure_set.json"], request={"controlled_registry_update": True})
        ProjectCommands(store).execute(command, lambda: ProjectMutation(
            {"studio/figure_set.json": json.dumps(registry).encode()}, {}))
        return publish(payload)

    monkeypatch.setattr(project_creation, "_publish", update_then_publish)
    result = project_creation.export_project(project)
    publication = next(item for item in store.commands() if item["metadata"]["kind"] == "publish")
    assert result["figures"][0]["title"] == "Published title"
    assert publication["result"]["figure_set"]["figures"][0]["title"] == "Published title"
    assert result["primary_figure_id"] == publication["result"]["figure_set"]["primary_figure_id"]
    assert result["status"] == "exported" and len(store.commands()) == 2
    assert [call[0] for call in calls] == ["export", "publish"]
