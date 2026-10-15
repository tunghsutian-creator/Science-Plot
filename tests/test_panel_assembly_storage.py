"""Layout file persistence refuses competing writes and keeps old bytes on failure."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import threading

import pytest

from sciplot_core.panel_assembly import AssemblyError
from sciplot_core.panel_assembly import storage
from sciplot_core.panel_assembly.model import apply_operations, load_document, new_document, save_document


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
    assert not list(tmp_path.glob(".*assembly*"))


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

    monkeypatch.setattr(storage, "atomic_write_json", fail_stage)
    with pytest.raises(AssemblyError) as captured:
        save_document(changed(document), target, expected_revision=0)
    assert captured.value.code == "assembly_file_write"
    assert target.read_bytes() == before
    assert not list(tmp_path.glob(".*assembly*"))


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
