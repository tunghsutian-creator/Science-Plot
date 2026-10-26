"""Early exact-byte guards preserve public roles without hiding other failures."""

from pathlib import Path
import subprocess

import pytest

from sciplot_core import task_discovery
from sciplot_core.data_mapping import original_tables, table_choice, execution_loading
from sciplot_core.data_mapping.execution_inputs import mapping_file_path
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.source_errors import SourceVersionMismatch
from sciplot_core.project_store import FileProjectStore, ProjectConflict
from sciplot_core.project_store.errors import ProjectSourceVersionMismatch
from sciplot_core.project_store.runtime import project_runtime
from sciplot_core.studio_core.series_request import _series_from_request
from sciplot_core.studio_render import categorical_bindings
from sciplot_core.studio_render.models import StudioPreparationBlocked

from test_mapping_source_identity import proposal, selected
from test_project_query_readonly_sources import inventory, no_views
from test_project_query_source_versions import generation
from test_source_group_consumers import mapped
from test_task_discovery import record
from test_task_ordinary_categorical import _binding


def test_actual_byte_mismatch_is_typed_before_sheet_cells_or_cache_reads(tmp_path, monkeypatch):
    source = tmp_path / "not-parsed.xlsx"
    source.write_bytes(b"Exact mismatch is rejected before a workbook parser runs.")
    before = inventory(tmp_path)
    monkeypatch.setattr(original_tables, "read_sheet_names", lambda *_args, **_kwargs: pytest.fail("Read sheets after mismatch"))
    with pytest.raises(SourceVersionMismatch) as error:
        original_tables.source_table_catalog(source, expected_sha256="0" * 64)
    assert error.value.literal == str(source)
    assert error.value.expected_sha256 == "0" * 64
    assert error.value.observed_sha256 == file_sha256(source)
    assert inventory(tmp_path) == before


def test_mapping_byte_mismatch_retains_project_conflict_type_and_actual_proof(tmp_path):
    source = tmp_path / "source.csv"
    source.write_bytes(b"x,y\n1,2\n")
    with pytest.raises(ProjectConflict) as error:
        mapping_file_path(source, expected_sha256="0" * 64)
    assert isinstance(error.value, SourceVersionMismatch)
    assert isinstance(error.value, ProjectSourceVersionMismatch)
    assert error.value.reason_code == "project_generation_conflict"
    assert error.value.literal == str(source)
    assert error.value.expected_sha256 == "0" * 64
    assert error.value.observed_sha256 == file_sha256(source)


@pytest.mark.parametrize("error", [PermissionError("denied"), FileNotFoundError("missing"),
    ProjectConflict("unbound source"), ValueError("The original table changed from its exact declared byte version.")])
def test_categorical_boundary_never_relabels_nonbyte_errors(tmp_path, monkeypatch, error):
    source = tmp_path / "source.csv"
    source.write_text("Sample,Condition,Value (MPa)\nA,dry,1\nB,dry,2\n")
    binding = _binding(source)

    def reject(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(categorical_bindings, "source_table_snapshot", reject)
    with pytest.raises(type(error)) as result:
        categorical_bindings.categorical_table_facts(source, binding)
    assert result.value is error and not isinstance(result.value, StudioPreparationBlocked)


def test_categorical_byte_mismatch_keeps_reason_before_any_cells_native_or_write(tmp_path, monkeypatch):
    source = tmp_path / "source.csv"
    source.write_text("Sample,Condition,Value (MPa)\nA,dry,1\nB,dry,2\n")
    binding = _binding(source, source_sha256="0" * 64)
    before = inventory(tmp_path)
    monkeypatch.setattr(subprocess, "Popen", lambda *_args, **_kwargs: pytest.fail("Invalid source started native work"))
    monkeypatch.setattr(categorical_bindings, "select_table", lambda *_args, **_kwargs: pytest.fail("Read cells after mismatch"))
    with pytest.raises(StudioPreparationBlocked) as error:
        categorical_bindings.read_categorical_frame(source, binding)
    assert error.value.reason_code == "categorical_source_changed"
    assert isinstance(error.value.__cause__, SourceVersionMismatch)
    assert inventory(tmp_path) == before


@pytest.mark.parametrize("role", ["selection", "confirmation"])
def test_table_roles_do_not_translate_unrelated_scope_conflicts(tmp_path, monkeypatch, role):
    source, receipt = proposal(tmp_path, [{"column_index": 0}])
    snapshot = table_choice.source_table_snapshot(source)
    error = ProjectConflict("The selected source has no host capability")

    def reject(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(table_choice, "source_table_snapshot", reject)
    with pytest.raises(ProjectConflict) as result:
        if role == "selection":
            table_choice.select_table(snapshot, receipt.table_confirmation["selection"])
        else:
            table_choice.verify_table_confirmation(receipt, source)
    assert result.value is error


@pytest.mark.parametrize("target", ["output", "original"])
def test_mapping_role_mismatch_rejects_before_numeric_replay_without_writing(tmp_path, monkeypatch, target):
    source, _request, facts = selected(tmp_path)
    request, _plan = mapped(tmp_path, monkeypatch, source, facts["table_selection"], [{"column_index": 0}], "bound")
    execution = execution_loading.load_data_mapping_execution(request["data_mapping_execution"])
    path = Path(execution["outputs"][0]["path"]) if target == "output" else source
    path.write_bytes(path.read_bytes() + b"999,999,999\n")
    before = inventory(tmp_path)
    monkeypatch.setattr(execution_loading, "_prepare_mapping_frames", lambda *_args, **_kwargs: pytest.fail("Replayed tampered data"))
    with pytest.raises(ValueError) as error:
        _series_from_request(request, base_dir=tmp_path)
    expected = f"Mapped data output hash mismatch: {path}" if target == "output" else "Data mapping source hash changed: original.csv"
    assert str(error.value) == expected
    assert isinstance(error.value.__cause__, ProjectSourceVersionMismatch)
    assert error.value.__cause__.literal == str(path)
    assert inventory(tmp_path) == before


def test_missing_standalone_is_false_but_unreadable_and_exact_cold_scope_stay_unknown(tmp_path, monkeypatch):
    store, _request, source, _paths = generation(tmp_path, directory=False)
    history = tmp_path / "history"
    record(history, "receipt", source)
    before = inventory(tmp_path)
    original = task_discovery._tree_hash

    def unreadable(_source):
        raise PermissionError("Exact source bytes unavailable")

    monkeypatch.setattr(task_discovery, "_tree_hash", unreadable)
    unknown = task_discovery.find_tasks(source, tasks_root=history)
    assert unknown["matches"][0]["source_current"] is None
    assert "unavailable" in unknown["source_error"] and inventory(tmp_path) == before
    monkeypatch.setattr(task_discovery, "_tree_hash", original)
    cold = FileProjectStore.import_bundle(store.export_bundle(tmp_path / "bundle"), tmp_path / "cold")
    source.rename(tmp_path / "source-offline")
    original_state = inventory(tmp_path)
    no_views(monkeypatch)
    with project_runtime(cold):
        found = task_discovery.find_tasks(source, tasks_root=history)
        assert found["matches"][0]["source_current"] is None
    assert task_discovery.find_tasks(source, tasks_root=history)["matches"][0]["source_current"] is False
    assert inventory(tmp_path) == original_state
