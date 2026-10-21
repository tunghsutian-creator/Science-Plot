"""A queued declaration cannot authorize an unrelated process or exit."""
import json
from types import SimpleNamespace

import pytest

from sciplot_core.verification.private_observer import ZERO, frame_digest, source_hashes
from sciplot_core.verification.private_native_exit_port import _live_request, _parent_exit, validated_exits


def producer(tmp_path, pid):
    epoch, token = "a" * 32, "b" * 32
    frame = {"event": "process_start", "pid": pid, "sequence": 0, "previous_sha256": ZERO,
             "observer_sources_sha256": source_hashes()}
    frame["sha256"] = frame_digest(frame)
    (tmp_path / (epoch + ".jsonl")).write_text(json.dumps(frame) + "\n")
    return {"epoch": epoch, "token": token, "generation": epoch + ":" + token, "actor": {}}


def test_unrelated_parent_cannot_register_a_foreign_pid(tmp_path):
    request = producer(tmp_path, 101)
    with pytest.raises(ValueError, match="actual source producer's child"):
        _live_request(tmp_path, request, SimpleNamespace(pid=301, ppid=201))


def test_current_source_hashes_and_parent_pid_are_insufficient_without_actual_server_spawn(tmp_path):
    request = producer(tmp_path, 101)
    with pytest.raises(ValueError, match="actual source-owned server launch"):
        _live_request(tmp_path, request, SimpleNamespace(pid=301, ppid=101))


def test_request_cannot_select_an_external_stream(tmp_path):
    with pytest.raises(ValueError, match="source epoch/token"):
        _live_request(tmp_path, {"epoch": "../outside", "token": "b" * 32}, SimpleNamespace(pid=301, ppid=101))


@pytest.mark.parametrize("primary", [100, 200])
def test_unclosed_or_different_primary_sensor_never_supplies_exit_status(primary):
    declared = {"event": "native_exit_sensor_start", "pid": 100, "binding": {"watcher_identity": {"pid": 100}}}
    assert validated_exits([declared], primary=primary) == {}


@pytest.mark.parametrize("returncode", [None, 0, -15])
def test_orphan_lineage_requires_genuine_finish_and_actual_normal_parent_exit(tmp_path, returncode):
    parent_epoch, ancestor_epoch, token = "a" * 32, "c" * 32, "b" * 32

    def write(epoch, frames):
        previous = ZERO
        for sequence, row in enumerate(frames):
            row.update(sequence=sequence, previous_sha256=previous)
            row["sha256"] = frame_digest(row)
            previous = row["sha256"]
        (tmp_path / (epoch + ".jsonl")).write_text("".join(json.dumps(row) + "\n" for row in frames))

    parent = [{"event": "process_start", "pid": 101, "observer_sources_sha256": source_hashes(),
               "parent_epoch": ancestor_epoch, "child_token": token},
              {"event": "process_finish", "pid": 101, "recorded_events": 1, "lost_events": 0}]
    ancestor = [{"event": "process_start", "pid": 100, "observer_sources_sha256": source_hashes()}]
    if returncode is not None:
        ancestor.append({"event": "child_exit", "child_pid": 101, "child_token": token, "returncode": returncode})
    write(parent_epoch, parent)
    write(ancestor_epoch, ancestor)
    if returncode == 0:
        assert _parent_exit(tmp_path, parent_epoch, 101) == {
            "producer_epoch": parent_epoch, "producer_finish_sha256": parent[-1]["sha256"],
            "ancestor_epoch": ancestor_epoch, "actual_parent_exit_sha256": ancestor[-1]["sha256"]}
    else:
        with pytest.raises(ValueError, match="actual normal parent exit"):
            _parent_exit(tmp_path, parent_epoch, 101)


def _launch_model(tmp_path):
    from dataclasses import replace
    import os
    from pathlib import Path
    import sys
    from sciplot_core.verification import private_native_exit_port as port
    from sciplot_core.verification.native_exit_boundary import ProcessIdentity
    from sciplot_core.verification.private_process_boundaries import executable_hash

    producer_image = str(tmp_path / "modeled-runtime" / "Python")
    producer = ProcessIdentity(os.getpid(), 1, os.getuid(), 1, 1, producer_image, str(tmp_path), "b" * 64)
    entry = ProcessIdentity(31999, producer.pid, producer.uid, 2, 3,
        str(Path(sys.executable).resolve()), str(tmp_path), executable_hash(sys.executable))
    settled = replace(entry, executable=producer.executable, executable_sha256=producer.executable_sha256)
    return port, producer, entry, settled


def test_modeled_launch_resolves_only_the_same_generation_actual_image(tmp_path, monkeypatch):
    import time

    port, producer, entry, settled = _launch_model(tmp_path)
    for identities in ([entry, settled], [settled]):
        reads = list(identities)
        def read(pid, reads=reads):
            return producer if pid == producer.pid else reads.pop(0)
        monkeypatch.setattr(port, "read_identity", read)
        assert port._server_identity(entry.pid, str(tmp_path / "engine.sock"), time.monotonic() + 1) == settled
        assert not reads


def test_modeled_launch_rejects_generation_drift_or_unbound_images(tmp_path, monkeypatch):
    from dataclasses import replace
    import time

    port, producer, entry, settled = _launch_model(tmp_path)
    changes = ({"pid": entry.pid + 1}, {"ppid": entry.ppid + 1}, {"uid": entry.uid + 1},
        {"start_sec": entry.start_sec + 1}, {"start_usec": entry.start_usec + 1},
        {"cwd": str(tmp_path / "other")}, {"executable": str(tmp_path / "other" / "Python")},
        {"executable_sha256": "c" * 64})
    for change in changes:
        reads = [entry, replace(settled, **change)]
        def read(pid, reads=reads):
            return producer if pid == producer.pid else reads.pop(0)
        monkeypatch.setattr(port, "read_identity", read)
        with pytest.raises(ValueError, match="generation or launch image changed"):
            port._server_identity(entry.pid, str(tmp_path / "engine.sock"), time.monotonic() + 1)


def test_unsettled_or_unreadable_launch_cannot_submit_a_registration(tmp_path, monkeypatch):
    port, producer, entry, settled = _launch_model(tmp_path)
    for current in (entry, settled):
        monkeypatch.setattr(port, "read_identity", lambda pid, current=current: producer if pid == producer.pid else current)
        with pytest.raises(ValueError, match="did not settle"):
            port._server_identity(entry.pid, str(tmp_path / "engine.sock"), -1)
    directory = tmp_path / "native-exits"
    directory.mkdir()
    queue = directory / "requests"
    queue.touch()
    recorded = []
    observer = SimpleNamespace(directory=tmp_path, epoch="a" * 32,
        record=lambda value, **kwargs: recorded.append(value))
    for failure in (PermissionError("modeled permission"), ProcessLookupError("modeled exit")):
        def unreadable(pid, failure=failure):
            if pid == producer.pid:
                return producer
            raise failure
        monkeypatch.setattr(port, "read_identity", unreadable)
        assert port.register_server(observer, SimpleNamespace(pid=entry.pid), "b" * 32,
            {"socket": str(tmp_path / "engine.sock")}) is False
        assert queue.read_bytes() == b"" and recorded == []


def test_startup_binding_separates_entrypoint_from_kernel_image():
    from copy import deepcopy
    from sciplot_core.verification.private_native_exit_port import _startup_bound

    runtime = {"loaded_core_sha256": ["b" * 64, "c" * 64], "kind": "modeled pure data"}
    request = {"epoch": "producer", "token": "launch", "identity": {"pid": 3, "ppid": 2,
        "uid": 501, "executable": "/modeled/runtime/Python", "executable_sha256": "b" * 64}}
    binding = {"watcher_identity": {"pid": 1, "uid": 501, "executable": "/modeled/runtime/Python",
        "executable_sha256": "b" * 64}, "native_images": {"python_core": {"sha256": "c" * 64}}}
    frames = [{"event": "process_start", "pid": pid, "epoch": epoch,
        "executable_sha256": "a" * 64, "python_runtime": deepcopy(runtime), **extra}
        for pid, epoch, extra in ((1, "primary", {}), (2, "producer", {}),
            (3, "child", {"parent_epoch": "producer", "child_token": "launch", "continuation": None}))]
    attempt = {"expected_executable_sha256": "a" * 64}
    assert _startup_bound(frames, request, attempt, binding)
    assert not _startup_bound(frames, request, {"expected_executable_sha256": "b" * 64}, binding)
    for missing in (None, "", "entry"):
        assert not _startup_bound(frames, request, {"expected_executable_sha256": missing}, binding)
    for change in ({"executable": "/other/runtime/Python"}, {"executable_sha256": "c" * 64}, {"uid": 502}):
        bad = deepcopy(request)
        bad["identity"].update(change)
        assert not _startup_bound(frames, bad, attempt, binding)
    for change in ({"child_token": "other"}, {"parent_epoch": "other"},
            {"python_runtime": {"loaded_core_sha256": ["b" * 64, "c" * 64], "kind": "other"}},
            {"executable_sha256": "b" * 64}):
        bad = deepcopy(frames)
        bad[-1].update(change)
        assert not _startup_bound(bad, request, attempt, binding)
    assert not _startup_bound([*frames, frames[-1]], request, attempt, binding)
