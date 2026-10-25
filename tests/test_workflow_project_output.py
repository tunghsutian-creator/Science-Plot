"""Private managed-output replacement preserves failures and unrelated members."""

import json

import pytest

from sciplot_core.project_store import FileProjectStore
from sciplot_core.studio_core.preparation_candidate import studio_preparation_candidate
from sciplot_core.workflow.project_output import private_run_output, output_replacements


@pytest.mark.parametrize("external", [False, True], ids=["primary-output", "selected-external-output"])
def test_private_run_retires_only_prior_managed_members(external, tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    output = tmp_path / "selected-output" if external else project / "runs/current"
    (output / "figures").mkdir(parents=True)
    (output / "figures/old.pdf").write_bytes(b"old exported PDF")
    (output / "manifest.json").write_text('{"state":"ready"}')
    (output / "notes.txt").write_bytes(b"unrelated user notes")
    (project / "plot_request.json").write_text(json.dumps({"output": str(output)}))
    store = FileProjectStore(project, locations={"run": output} if external else {})
    before = store.snapshot(import_legacy=True)
    protected = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in output.rglob("*") if path.is_file()}
    logical = "@run" if external else "runs/current"
    with studio_preparation_candidate(store) as candidate:
        with private_run_output(candidate, logical) as private:
            assert not (private / "figures/old.pdf").exists()
            assert not (private / "manifest.json").exists()
            (private / "manifest.json").write_text('{"state":"new"}')
        writes = output_replacements(candidate, logical, dict(candidate.capture()))
        assert writes[logical + "/figures/old.pdf"] is None
        assert writes[logical + "/manifest.json"].data == b'{"state":"new"}'
        assert logical + "/notes.txt" not in writes
    assert store.snapshot()["generation"] == before["generation"]
    assert {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in protected} == protected


def test_failed_private_retry_restores_its_prior_run_and_leaves_active_generation_untouched(tmp_path):
    project = tmp_path / "project"
    output = project / "runs/current"
    output.mkdir(parents=True)
    (output / "manifest.json").write_bytes(b"previous complete run")
    store = FileProjectStore(project)
    before = store.snapshot(import_legacy=True)
    with studio_preparation_candidate(store) as candidate:
        with pytest.raises(RuntimeError, match="failed before native result"):
            with private_run_output(candidate, "runs/current") as private:
                (private / "manifest.json").write_bytes(b"unknown partial run")
                raise RuntimeError("failed before native result")
        assert candidate.capture() == {}
    assert (output / "manifest.json").read_bytes() == b"previous complete run"
    assert store.snapshot()["generation"] == before["generation"]
