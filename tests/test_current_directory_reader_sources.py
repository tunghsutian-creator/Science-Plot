"""Actual sweep readers use the current source port and keep literal identity."""
from __future__ import annotations

from contextlib import closing

import pytest
from openpyxl import load_workbook

from sciplot_core.project_store import FileProjectStore, ProjectStoreError
from sciplot_core.project_store.runtime import project_runtime
from sciplot_core.semantic import prepare_semantic_source
from sciplot_core.semantic_sources.scientific_source import resolve_scientific_source
from sciplot_core.studio_core.preparation_source_runtime import current_preparation_runtime
from test_current_preparation_sources import current_revision


def _resolve(source):
    return resolve_scientific_source(source, rule_id="rheology_frequency_sweep", request={},
                                     template="point_line", study_model={})


def _prepare(source, resolved, output):
    prepared = prepare_semantic_source(source, output_dir=output,
        semantic={"rule_id": "rheology_frequency_sweep", "semantic_family": "rheology_frequency"},
        resolved_scientific_source=resolved)
    assert prepared["processed"] is True
    with closing(load_workbook(prepared["source"], read_only=True)) as workbook:
        values = list(workbook.active.values)
    step = prepared["transform_steps"][0]
    assert step["parameters"]["source_sample_files"] == [str(path) for path in resolved.domain.selected_sources]
    return values, step["input_artifacts"], step["parameters"]


def test_actual_current_directory_reader_has_identical_live_and_explicit_cold_domain(tmp_path):
    store, source, paths, _old, expected = current_revision(tmp_path, directory=True, rheology=True)
    snapshot = store.snapshot()
    with current_preparation_runtime(store, snapshot):
        live = _resolve(source)
        live_prepared = _prepare(source, live, tmp_path / "live-derived")
    assert live is not None and live.source == source and live.source_sha256 == expected
    # The registered sweep reader selects immediate exports only. The nested
    # CSV and unused note remain in the complete tree without becoming curves.
    assert live.domain.selected_sources == (paths[0],)
    for index, sample in enumerate(live.domain.raw_samples):
        assert sample.source == paths[index]
        assert [row["x"] for row in sample.rows] == [1, 10, 100]
        assert [row["storage_modulus"] for row in sample.rows] == [10 + index, 20 + index, 30 + index]
    cold = FileProjectStore.import_bundle(store.export_bundle(tmp_path / "bundle"), tmp_path / "cold")
    source.rename(tmp_path / "original-offline")
    with project_runtime(cold):
        # The existing adapter declines a non-directory; a cold tree is not
        # silently admitted by the default project resolver.
        assert _resolve(source) is None
    with current_preparation_runtime(cold, cold.snapshot()):
        imported = _resolve(source)
        cold_prepared = _prepare(source, imported, tmp_path / "cold-derived")
    assert imported == live
    assert imported.figure_plan.plan_sha256 == live.figure_plan.plan_sha256
    assert cold_prepared == live_prepared
    assert cold.snapshot()["sources"] == snapshot["sources"]


@pytest.mark.parametrize("cold", [False, True])
def test_actual_current_directory_reader_rejects_changed_live_or_imported_member(tmp_path, cold):
    store, source, paths, _old, _expected = current_revision(tmp_path, directory=True, rheology=True)
    if cold:
        selected = FileProjectStore.import_bundle(store.export_bundle(tmp_path / "bundle"), tmp_path / "cold")
        source.rename(tmp_path / "original-offline")
        record = selected.query("exact-current-v1")
        tree = selected.prepared_tree_path("exact-current-v1", record["command_digest"],
            decision_id=record["decision_id"], locator=str(source), tree_sha256=record["metadata"]["source_trees"][0]["tree_sha256"])
        assert tree is not None
        member = tree / paths[0].name
        member.chmod(0o600)
    else:
        selected, member = store, paths[0]
    member.write_bytes(b"unconfirmed replacement of a scientific source")
    before = selected.snapshot()
    with pytest.raises(ProjectStoreError):
        with current_preparation_runtime(selected, before):
            _resolve(source)
    assert selected.snapshot() == before
