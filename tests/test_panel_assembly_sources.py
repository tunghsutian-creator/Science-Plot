"""Canonical ManagedPlot authority cannot be bypassed through its legacy project."""

from pathlib import Path

import pytest

from sciplot_core.panel_assembly.errors import AssemblyError
from sciplot_core.panel_assembly.sources import assert_source_current, capture_source, project_reference, project_references
from sciplot_core.plot_engine.managed_state import make_binding
from sciplot_core.plot_engine.storage import commit, document_root, load_head


def canonical_managed(tmp_path, project, figure_id):
    from test_panel_assembly_export import managed_source

    old_root, _source = managed_source(tmp_path)
    document = load_head(old_root)["document"]
    root = document_root(project, figure_id)
    binding = make_binding(root, document, output=tmp_path / "canonical-output")
    commit(root, document, binding, "managed-authority-control")
    return root, document


def test_project_capture_and_currentness_require_existing_managed_authority(tmp_path, monkeypatch):
    from sciplot_core.panel_assembly import sources

    project = tmp_path / "registered-project"
    project.mkdir()
    figure_id = "figure-one"
    root, document = canonical_managed(tmp_path, project, figure_id)
    expected = {"kind": "managed", "project": str(root), "plot_id": document["plot_id"]}
    assert project_reference(project, figure_id) == expected
    managed = capture_source(expected)
    assert_source_current(managed)

    def bypass(*_args):
        pytest.fail("A ManagedPlot must not fall through to native project selection.")

    monkeypatch.setattr(sources, "capture_selection", bypass)
    reference = {"kind": "project", "project": str(project), "figure_id": figure_id}
    with pytest.raises(AssemblyError) as error:
        capture_source(reference)
    assert error.value.code == "assembly_managed_reference_required"
    assert error.value.issues[0]["reference"] == expected
    with pytest.raises(AssemblyError) as error:
        assert_source_current({**reference, "binding": {"selection": {}, "files": []}})
    assert error.value.code == "assembly_managed_reference_required"


def test_project_catalogue_returns_managed_reference_without_mutating_source(tmp_path, monkeypatch):
    from sciplot_core.studio_core import project_query_paths

    project = tmp_path / "registered-project"
    project.mkdir()
    root, document = canonical_managed(tmp_path, project, "managed-figure")
    original = (root / "head.json").read_bytes()
    monkeypatch.setattr(project_query_paths, "resolve_project_path", lambda path: Path(path))
    monkeypatch.setattr(project_query_paths, "project_snapshot", lambda _path: ({}, {}, [
        {"title": "Canonical panel", "figure_id": "managed-figure"},
        {"title": "Saved native panel", "figure_id": "legacy-figure"}]))
    rows = project_references(project)
    assert rows[0][1] == {"kind": "managed", "project": str(root), "plot_id": document["plot_id"]}
    assert rows[1][1] == {"kind": "project", "project": str(project), "figure_id": "legacy-figure"}
    assert (root / "head.json").read_bytes() == original
    assert not Path(load_head(root)["binding"]["document"]).exists()
