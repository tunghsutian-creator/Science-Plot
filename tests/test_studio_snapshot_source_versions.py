"""Publication workbook IO retains the exact registered table version."""
import json
from pathlib import Path

import pandas as pd
import pytest

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.project_commands import PreparedSource, ProjectCommand, ProjectCommands, ProjectMutation
from sciplot_core.project_store import FileProjectStore
from sciplot_core.project_store.runtime import project_runtime
from sciplot_core.studio_core.request_overrides import _write_studio_data_snapshots
from sciplot_core.studio_render.models import StudioPreparationBlocked
from test_registered_mapping_task_sources import mapped_spec as mapped_spec


def cold_tables(tmp_path):
    origin, project = tmp_path / "origin", tmp_path / "project"
    origin.mkdir()
    project.mkdir()
    paths = [origin / "Amber.csv", origin / "Blue.csv"]
    for path, data in zip(paths, ("value\n1\n\n3\n", "value\n7\n8\n9\n"), strict=True):
        path.write_text(data)
    versions = {path: file_sha256(path) for path in paths}
    store = FileProjectStore(project)
    before = store.snapshot(import_legacy=True)
    command = ProjectCommand.create("figure_set", "source-evidence", project_id=before["project_id"],
        expected_generation=before["generation"], read_set={}, write_set=[], request={})
    sources = tuple(PreparedSource(f"77c907b660ba4e6cb5c56dc6c48fd10{index}", str(path),
        versions[path], path.read_bytes()) for index, path in enumerate(paths))
    ProjectCommands(store).execute(command, lambda: ProjectMutation({}, {}, prepared_sources=sources))
    cold = FileProjectStore.import_bundle(store.export_bundle(tmp_path / "bundle"), tmp_path / "cold")
    origin.rename(tmp_path / "original-offline")
    return cold, paths, versions


def test_registered_cold_tables_write_original_named_workbook_without_original_paths(tmp_path):
    cold, paths, versions = cold_tables(tmp_path)
    before = cold.snapshot()
    with project_runtime(cold):
        workbook = _write_studio_data_snapshots(paths, tmp_path / "run", source_versions=versions)
    sheets = pd.read_excel(workbook, sheet_name=None)
    assert list(sheets) == ["Amber_Amber", "Blue_Blue"]
    assert sheets["Amber_Amber"]["value"].tolist() == [1, 3]
    assert sheets["Blue_Blue"]["value"].tolist() == [7, 8, 9]
    assert all(not path.exists() for path in paths)
    assert cold.snapshot() == before


@pytest.mark.parametrize("proof", ["missing", "wrong"])
def test_workbook_does_not_guess_a_registered_external_version(tmp_path, proof):
    cold, paths, versions = cold_tables(tmp_path)
    versions = {} if proof == "missing" else {**versions, paths[0]: "0" * 64}
    before = cold.snapshot()
    with project_runtime(cold), pytest.raises(StudioPreparationBlocked, match="exact registered version|do not resolve uniquely"):
        _write_studio_data_snapshots(paths, tmp_path / "run", source_versions=versions)
    assert not (tmp_path / "run/processed/studio_export_data.xlsx").exists()
    assert cold.snapshot() == before


def test_registered_task_inventory_passes_exact_verified_group_versions(mapped_spec):
    from sciplot_core.source_coverage.managed_task_sources import registered_task_snapshot_sources

    _raw, request, application, execution, project, document, spec_path, _spec = mapped_spec
    versions = {}
    paths = registered_task_snapshot_sources(request=request, project_dir=project, documents=[document],
        existing_sources=[Path(execution["effective_input"])], data_mapping_application=application,
        source_versions=versions)
    expected = {Path(group["path"]): group["sha256"] for group in application["source_groups"]}
    assert versions == expected
    assert paths[1:] == list(expected)
    spec = json.loads(spec_path.read_bytes())
    assert {Path(item["path"]): item["sha256"] for series in spec["series"]
            for item in series["source_artifacts"]} == versions


def test_unbound_legacy_workbook_parser_and_all_sheet_selection_stay_identical(tmp_path):
    source = tmp_path / "original.xlsx"
    with pd.ExcelWriter(source) as writer:
        pd.DataFrame({"x": [1, 2], "y": [3, 4]}).to_excel(writer, sheet_name="First", index=False)
        pd.DataFrame({"x": [7, 8], "y": [9, 10]}).to_excel(writer, sheet_name="Second", index=False)
    legacy = _write_studio_data_snapshots([source], tmp_path / "legacy")
    exact = _write_studio_data_snapshots([source], tmp_path / "exact", source_versions={source: file_sha256(source)})
    before, after = pd.read_excel(legacy, sheet_name=None), pd.read_excel(exact, sheet_name=None)
    assert list(before) == list(after)
    for name in before:
        pd.testing.assert_frame_equal(before[name], after[name])
