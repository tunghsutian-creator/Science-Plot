"""Current source indicators bind immutable domain evidence and exact IO versions."""
import hashlib
import json

import pytest

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.source_locations import resolve_source_path
from sciplot_core.foundation.source_tree import source_tree_sha256
from sciplot_core.project_commands import PreparedSource, ProjectCommand, ProjectCommands, ProjectMutation
from sciplot_core.project_store import FileProjectStore
from sciplot_core.project_store.runtime import project_runtime
from sciplot_core.studio_core.project_query_evidence import source_indicators


def generation(tmp_path, *, directory):
    source = tmp_path / ("raw-selected" if directory else "raw-selected.csv")
    if directory:
        source.mkdir()
        (source / "nested").mkdir()
        paths = [source / "a.csv", source / "nested/b.csv"]
    else:
        paths = [source]
    for index, path in enumerate(paths):
        path.write_text(f"x,y\n1,{index}\n")
    files = {path.relative_to(source).as_posix() if directory else path.name: file_sha256(path) for path in paths}
    root = tmp_path / "project"
    (root / "studio").mkdir(parents=True)
    request = {"input": str(source), "resolved_figure_plan": {"source_sha256": source_tree_sha256(source)},
        "transform_ledger": {"steps": [{"input_artifacts": [
            {"kind": "file", "path": str(path), "sha256": file_sha256(path)} for path in paths]}]}}
    (root / "plot_request.json").write_text(json.dumps(request))
    (root / "studio/spec.json").write_text(json.dumps({"series": [{"source_artifacts": [
        {"path": str(path), "sha256": file_sha256(path)} for path in paths]}]}))
    store = FileProjectStore(root)
    before = store.snapshot(import_legacy=True)
    review = {"source": str(source), "source_kind": "directory" if directory else "file", "source_files": files}
    command = ProjectCommand.create("source_update", "current-source-revision", project_id=before["project_id"],
        expected_generation=before["generation"], read_set={"source_update.json": None}, write_set=["source_update.json"], request={})
    ProjectCommands(store).execute(command, lambda: ProjectMutation({"source_update.json": json.dumps(review).encode()}, {},
        prepared_sources=tuple(PreparedSource(hashlib.sha256(str(path).encode()).hexdigest()[:32], str(path), file_sha256(path), path.read_bytes())
                               for path in paths)))
    return store, request, source, paths


def indicator(store, request):
    with project_runtime(store):
        return source_indicators(store.root, request, [{"status": "ready", "spec": str(store.root / "studio/spec.json")}])


@pytest.mark.parametrize("directory", [False, True])
def test_current_input_version_survives_cold_import_without_default_no_sha_permission(tmp_path, directory):
    store, request, source, _paths = generation(tmp_path, directory=directory)
    assert indicator(store, request)["current"] is True
    cold = FileProjectStore.import_bundle(store.export_bundle(tmp_path / "bundle"), tmp_path / "cold")
    store.root.rename(tmp_path / "original-offline")
    source.rename(tmp_path / "raw-offline")
    current = indicator(cold, request)
    assert current["current"] is True and current["input"]["sha256"] == request["resolved_figure_plan"]["source_sha256"]
    if not directory:
        with project_runtime(cold), pytest.raises(ValueError, match="exact registered version"):
            resolve_source_path(source)
    assert not source.exists()


@pytest.mark.parametrize("directory", [False, True])
def test_live_current_input_drift_is_stale_and_never_reads_the_old_sealed_cache(tmp_path, directory):
    store, request, _source, paths = generation(tmp_path, directory=directory)
    paths[0].write_bytes(b"manual raw version outside the current command")
    result = indicator(store, request)
    assert result["current"] is False and result["input"]["current"] is False
    assert "registered version" in result["input"]["error"]


def test_current_directory_extra_member_and_alias_are_stale(tmp_path):
    store, request, source, _paths = generation(tmp_path, directory=True)
    extra = source / "extra.csv"
    extra.write_bytes(b"new unconfirmed member")
    assert indicator(store, request)["current"] is False
    extra.unlink()
    extra.symlink_to(tmp_path / "private-not-readable.csv")
    assert indicator(store, request)["current"] is False


def test_conflicting_current_review_and_ledger_do_not_choose_a_newer_version(tmp_path):
    store, request, _source, _paths = generation(tmp_path, directory=False)
    snapshot = store.snapshot()
    review = json.loads(store.read_bytes("source_update.json"))
    review["source_files"] = {name: "a" * 64 for name in review["source_files"]}
    command = ProjectCommand.create("source_update", "contradictory-current-review", project_id=snapshot["project_id"],
        expected_generation=snapshot["generation"], read_set={"source_update.json": snapshot["files"]["source_update.json"]["sha256"]},
        write_set=["source_update.json"], request={})
    ProjectCommands(store).execute(command, lambda: ProjectMutation({"source_update.json": json.dumps(review).encode()}, {}))
    result = indicator(store, request)
    assert result["current"] is False and "disagree" in result["input"]["error"]
