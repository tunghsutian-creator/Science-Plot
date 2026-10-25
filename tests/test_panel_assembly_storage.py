"""Layout file persistence refuses competing writes and keeps old bytes on failure."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import threading

import pytest

from sciplot_core.panel_assembly import AssemblyError
from sciplot_core.panel_assembly import storage
from sciplot_core.panel_assembly.history import AssemblyHistory
from sciplot_core.panel_assembly.model import apply_operations, load_document, new_document, save_document, validate_document


def changed(document, width=190):
    return apply_operations(document, [{"op": "set_page", "width_mm": width, "height_mm": 140}])


def test_new_save_load_and_revision_cas_round_trip(tmp_path):
    target = tmp_path / "figure.assembly.json"
    document = new_document()
    assert save_document(document, target) == target
    assert load_document(target) == document
    before = target.read_bytes()
    with pytest.raises(AssemblyError, match="expected saved revision"):
        save_document(changed(document), target)
    assert target.read_bytes() == before
    save_document(changed(document), target, expected_revision=0)
    assert load_document(target)["revision"] == 1
    assert list(tmp_path.glob(".*assembly*")) == [tmp_path / f".{target.name}.assembly-lock"]


def test_two_readers_of_one_revision_cannot_overwrite_each_other(tmp_path):
    target = tmp_path / "figure.json"
    save_document(new_document(), target)
    first, second = load_document(target), load_document(target)
    save_document(changed(first), target, expected_revision=first["revision"])
    before = target.read_bytes()
    with pytest.raises(AssemblyError) as captured:
        save_document(changed(second, 200), target, expected_revision=second["revision"])
    assert captured.value.code == "assembly_file_conflict"
    assert target.read_bytes() == before


def test_same_revision_foreign_file_edit_is_not_overwritten(tmp_path):
    target = tmp_path / "figure.json"
    document = new_document()
    save_document(document, target)
    observed = load_document(target)
    foreign = deepcopy(document)
    foreign["layout"]["width_mm"] = 250
    target.write_text(json.dumps(foreign))
    before = target.read_bytes()
    with pytest.raises(AssemblyError, match="reopen"):
        save_document(changed(observed), target, expected_revision=0)
    assert target.read_bytes() == before


def test_second_reader_cannot_refresh_an_earlier_readers_file_baseline(tmp_path):
    target = tmp_path / "figure.json"
    save_document(new_document(), target)
    first = load_document(target)
    foreign = dict(first)
    foreign["layout"] = {**foreign["layout"], "width_mm": 250}
    target.write_text(json.dumps(foreign))
    second = load_document(target)
    before = target.read_bytes()
    with pytest.raises(AssemblyError) as captured:
        save_document(changed(first), target, expected_revision=0)
    assert captured.value.code == "assembly_file_conflict"
    assert target.read_bytes() == before
    save_document(changed(second, 260), target, expected_revision=0)
    assert load_document(target)["layout"]["width_mm"] == 260


@pytest.mark.parametrize("rebuild", [dict, lambda value: json.loads(json.dumps(value)),
                                   lambda value: validate_document(json.loads(json.dumps(value)))])
def test_plain_or_revalidated_json_cannot_replace_a_file_using_only_its_revision(tmp_path, rebuild):
    target = tmp_path / "figure.json"
    document = new_document()
    save_document(document, target)
    unbound = rebuild(load_document(target))
    before = target.read_bytes()
    with pytest.raises(AssemblyError, match="editing session"):
        save_document(changed(unbound), target, expected_revision=0)
    assert target.read_bytes() == before


def test_deepcopy_and_validation_preserve_a_loaded_session_without_serializing_it(tmp_path):
    target = tmp_path / "figure.json"
    save_document(new_document(), target)
    loaded = load_document(target)
    copied = validate_document(deepcopy(loaded))
    first = changed(copied)
    save_document(first, target, expected_revision=0)
    second = changed(first, 210)
    save_document(second, target, expected_revision=1)
    assert load_document(target) == second
    assert set(json.loads(target.read_text())) == {"kind", "version", "revision", "layout", "panels"}
    assert json.loads(json.dumps(second)) == dict(second)


def test_new_document_history_keeps_its_session_across_save_undo_save_redo_save(tmp_path):
    target = tmp_path / "figure.json"
    document = new_document()
    history = AssemblyHistory(document)
    save_document(document, target)
    history.apply([{"op": "set_page", "width_mm": 200, "height_mm": 140}])
    save_document(history.document, target, expected_revision=0)
    undone = history.undo()
    save_document(undone, target, expected_revision=1)
    assert load_document(target)["layout"]["width_mm"] == 180
    redone = history.redo()
    save_document(redone, target, expected_revision=2)
    assert load_document(target)["layout"]["width_mm"] == 200
    assert redone["revision"] == 3


def test_save_as_and_reopen_have_independent_path_and_session_baselines(tmp_path):
    original, alternate = tmp_path / "original.json", tmp_path / "alternate.json"
    document = new_document()
    save_document(document, original)
    first = changed(load_document(original))
    save_document(first, alternate)
    second = changed(first, 210)
    save_document(second, alternate, expected_revision=1)
    assert load_document(original)["layout"]["width_mm"] == 180
    save_document(second, original, expected_revision=0)
    reopened = load_document(alternate)
    save_document(changed(reopened, 220), alternate, expected_revision=2)
    assert load_document(original)["layout"]["width_mm"] == 210
    assert load_document(alternate)["layout"]["width_mm"] == 220


def test_nonadvancing_changed_revision_cannot_replace_valid_file(tmp_path):
    target = tmp_path / "figure.json"
    document = new_document()
    save_document(document, target)
    document["layout"]["width_mm"] = 200
    before = target.read_bytes()
    with pytest.raises(AssemblyError, match="advance"):
        save_document(document, target, expected_revision=0)
    assert target.read_bytes() == before


def test_validation_and_atomic_stage_failure_preserve_original_bytes(tmp_path, monkeypatch):
    target = tmp_path / "figure.json"
    document = new_document()
    save_document(document, target)
    before = target.read_bytes()
    invalid = changed(document)
    invalid["layout"]["height_mm"] = float("nan")
    with pytest.raises(AssemblyError):
        save_document(invalid, target, expected_revision=0)
    assert target.read_bytes() == before

    def fail_stage(*args):
        raise OSError("disk unavailable")

    atomic = storage.atomic_write_json
    monkeypatch.setattr(storage, "atomic_write_json", fail_stage)
    with pytest.raises(AssemblyError) as captured:
        save_document(changed(document), target, expected_revision=0)
    assert captured.value.code == "assembly_file_write"
    assert target.read_bytes() == before
    assert list(tmp_path.glob(".*assembly*")) == [tmp_path / f".{target.name}.assembly-lock"]
    monkeypatch.setattr(storage, "atomic_write_json", atomic)
    save_document(changed(document), target, expected_revision=0)
    assert load_document(target)["revision"] == 1


def test_foreign_edit_during_staging_refuses_before_replace(tmp_path, monkeypatch):
    target = tmp_path / "figure.json"
    document = new_document()
    save_document(document, target)
    atomic = storage.atomic_write_json
    foreign = {**document, "revision": 5}

    def change_while_staging(path, payload):
        result = atomic(path, payload)
        target.write_text(json.dumps(foreign))
        return result

    monkeypatch.setattr(storage, "atomic_write_json", change_while_staging)
    with pytest.raises(AssemblyError, match="while the save"):
        save_document(changed(document), target, expected_revision=0)
    assert json.loads(target.read_text()) == foreign


def test_new_destination_created_during_staging_is_preserved(tmp_path, monkeypatch):
    target = tmp_path / "figure.json"
    atomic = storage.atomic_write_json

    def create_while_staging(path, payload):
        result = atomic(path, payload)
        target.write_text("foreign content")
        return result

    monkeypatch.setattr(storage, "atomic_write_json", create_while_staging)
    with pytest.raises(AssemblyError, match="appeared"):
        save_document(new_document(), target)
    assert target.read_text() == "foreign content"


def test_simultaneous_writer_lease_refuses_without_waiting(tmp_path, monkeypatch):
    target = tmp_path / "figure.json"
    document = new_document()
    save_document(document, target)
    atomic = storage.atomic_write_json
    started, release = threading.Event(), threading.Event()

    def wait_stage(path, payload):
        started.set()
        assert release.wait(5)
        return atomic(path, payload)

    monkeypatch.setattr(storage, "atomic_write_json", wait_stage)
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(save_document, changed(document), target, 0)
        assert started.wait(5)
        try:
            with pytest.raises(AssemblyError) as captured:
                save_document(changed(document, 210), target, expected_revision=0)
            assert captured.value.code == "assembly_file_busy"
        finally:
            release.set()
        assert first.result() == target
    assert load_document(target)["layout"]["width_mm"] == 190


@pytest.mark.parametrize("expected", [-1, True, 0.0, "0"])
def test_invalid_expected_revision_and_missing_expected_file_are_refused(tmp_path, expected):
    target = tmp_path / "figure.json"
    with pytest.raises(AssemblyError):
        save_document(new_document(), target, expected_revision=expected)
    assert not target.exists()


def test_missing_expected_or_symlink_target_is_not_created_or_followed(tmp_path):
    target = tmp_path / "figure.json"
    with pytest.raises(AssemblyError, match="missing"):
        save_document(new_document(), target, expected_revision=0)
    original = tmp_path / "original.json"
    save_document(new_document(), original)
    target.symlink_to(original)
    before = original.read_bytes()
    with pytest.raises(AssemblyError, match="symbolic"):
        save_document(changed(new_document()), target, expected_revision=0)
    with pytest.raises(AssemblyError, match="symbolic"):
        load_document(target)
    assert original.read_bytes() == before
