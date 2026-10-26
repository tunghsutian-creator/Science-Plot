"""Publication carries the canonical exact external source scope to archival."""
import json
from pathlib import Path

import pytest

from test_project_export_use_case import publication as publication

from sciplot_core.project_commands import PreparedSource, ProjectCommand, ProjectCommands, ProjectMutation
from sciplot_core.project_store.io import sha
from sciplot_core.project_store import FileProjectStore
from sciplot_core.studio_core.project_command_scope import project_store
from sciplot_core.studio_core.project_export import export_project_document
from sciplot_core.studio_core import publication_prepare
from sciplot_core.studio_core.request_paths import _archive_studio_input


@pytest.fixture
def external_publication(publication, tmp_path, monkeypatch):
    project, calls, _published = publication
    source = tmp_path / "external.csv"
    original = (project / "source/data.csv").read_bytes()
    source.write_bytes(original)
    request = project / "plot_request.json"
    request.write_text(json.dumps({"input": str(source)}))
    spec_path = project / "studio/spec.json"
    spec = json.loads(spec_path.read_text())
    spec["series"][0]["source_artifacts"][0]["path"] = str(source)
    spec_path.write_text(json.dumps(spec))
    store = project_store(project)
    before = store.snapshot(import_legacy=True)
    mutation = ProjectMutation({}, {}, prepared_sources=(PreparedSource("a" * 32,
        str(source), sha(original), original, (), 0o644),))
    command = ProjectCommand.create("attachment_import", "register-external",
        project_id=before["project_id"], expected_generation=before["generation"],
        read_set={}, write_set=[], request={"prepared_digest": mutation.prepared_digest})
    ProjectCommands(store).publish_prepared(command, mutation)
    prepare = publication_prepare.prepare_studio_export_run

    def archive_before_prepare(**kwargs):
        archived = _archive_studio_input(source, kwargs["output_dir"])
        assert archived["source"] == str(source)
        assert (kwargs["output_dir"] / "raw/external.csv").read_bytes() == original
        return prepare(**kwargs)

    monkeypatch.setattr(publication_prepare, "prepare_studio_export_run", archive_before_prepare)
    return project, source, original, calls, store


def test_publication_archives_the_exact_registered_external_source(external_publication):
    project, source, original, calls, _store = external_publication
    result = export_project_document(project_dir=project, formats=["pdf"])
    assert result.ready_to_use and [call[0] for call in calls] == ["export", "publish"]
    assert (project / "runs/studio_001/raw/external.csv").read_bytes() == original
    assert source.read_bytes() == original


@pytest.mark.parametrize("when", ["before_export", "after_private_prepare"])
def test_publication_refuses_external_source_drift_before_head(external_publication, monkeypatch, when):
    project, source, original, calls, store = external_publication
    before = store.snapshot()["generation"]
    active = {str(path.relative_to(project)): path.read_bytes() for path in project.rglob("*")
              if path.is_file() and ".sciplot_store" not in path.parts}
    if when == "before_export":
        source.write_bytes(original + b"2,999\n")
    else:
        prepare = publication_prepare.prepare_studio_export_run

        def change_after_prepare(**kwargs):
            result = prepare(**kwargs)
            source.write_bytes(original + b"2,999\n")
            return result

        monkeypatch.setattr(publication_prepare, "prepare_studio_export_run", change_after_prepare)
    with pytest.raises(ValueError):
        export_project_document(project_dir=project, formats=["pdf"])
    assert calls == [] if when == "before_export" else [call[0] for call in calls] == ["export", "publish"]
    assert store.snapshot()["generation"] == before
    assert {str(path.relative_to(project)): path.read_bytes() for path in project.rglob("*")
            if path.is_file() and ".sciplot_store" not in path.parts} == active


def test_publication_refuses_same_bytes_foreign_locator_before_native_export(external_publication, tmp_path):
    project, _source, original, calls, store = external_publication
    foreign = tmp_path / "foreign/external.csv"
    foreign.parent.mkdir()
    foreign.write_bytes(original)
    request = project / "plot_request.json"
    value = json.loads(request.read_text())
    value["input"] = str(foreign)
    request.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="canonical request differs"):
        export_project_document(project_dir=project, formats=["pdf"])
    assert not calls and not (project / "runs").exists()
    assert store.commands()[-1]["command_id"] == "register-external"


def test_publication_uses_only_the_complete_imported_external_version(external_publication, tmp_path):
    project, source, original, calls, store = external_publication
    bundle = store.export_bundle(tmp_path / "bundle")
    source.rename(tmp_path / "source-offline.csv")
    project.rename(tmp_path / "project-offline")
    cold = FileProjectStore.import_bundle(bundle, tmp_path / "cold")
    result = export_project_document(project_dir=cold.root, formats=["pdf"])
    assert result.ready_to_use and [call[0] for call in calls] == ["export", "publish"]
    assert (cold.root / "runs/studio_001/raw/external.csv").read_bytes() == original
    assert not source.exists() and not project.exists()
    manifest = cold.root / "runs/studio_001/manifest.json"
    assert Path(result.run_payload["exports"][0]["path"]).is_file() and manifest.is_file()
