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
