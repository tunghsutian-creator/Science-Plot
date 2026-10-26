"""Source revisions preserve existing input namespaces without inventing copies."""
import shutil

import pytest

from sciplot_core.studio_core.source_update_commands import source_mutation
from sciplot_core.studio_core.source_update_files import project_inventory


@pytest.mark.parametrize("existing_inputs", [False, True], ids=["external-versioned-inputs", "missing-existing-inputs"])
def test_source_mutation_requires_only_real_existing_input_namespaces(tmp_path, existing_inputs):
    project, candidate = tmp_path / "project", tmp_path / "candidate"
    (project / "studio").mkdir(parents=True)
    (project / "plot_request.json").write_bytes(b'{"input":"external-versioned.csv"}')
    (project / "studio/document.vsz").write_bytes(b"old native")
    if existing_inputs:
        for name in ("raw", "source"):
            (project / name).mkdir()
            (project / name / "data.csv").write_bytes(b"protected original")
    shutil.copytree(project, candidate)
    if existing_inputs:
        shutil.rmtree(candidate / "raw")
    (candidate / "studio/document.vsz").write_bytes(b"reviewed new native")
    before = project_inventory(project)
    if existing_inputs:
        with pytest.raises(ValueError, match="missing required"):
            source_mutation(project, candidate, {}, expected=before, logical_paths_bound=True)
    else:
        writes, archive = source_mutation(project, candidate, {}, expected=before, logical_paths_bound=True)
        assert set(writes) == set(before) and archive["before/studio/document.vsz"] == b"old native"
        assert not (candidate / "raw").exists() and not (candidate / "source").exists()
    assert project_inventory(project) == before
