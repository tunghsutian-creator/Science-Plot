"""Owned subprocess faults across complete project/head/derived-view boundaries."""

from pathlib import Path
import select
import signal
import subprocess
import sys

import pytest

from sciplot_core.project_store import FileProjectStore, ProjectRecoveryRequired
from sciplot_core.foundation.project_session_lease import ProjectSessionBusy, ProjectSessionLease

pytestmark = pytest.mark.comprehensive

_CHILD = r"""
from pathlib import Path
import signal, sys
from sciplot_core.project_store import FileProjectStore, state
root, delivery, fault = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
store = FileProjectStore(root, locations={'delivery':delivery})
snapshot = store.snapshot()
names = ['document.vsz','spec.json','@delivery/native.vsz','intake_manifest.json']
def stop(name):
 if name == fault:
  print('holding',flush=True)
  signal.pause()
state.boundary = stop
store.reserve('owned-fault','digest',expected_generation=snapshot['generation'],
 read_set={name:snapshot['files'][name]['sha256'] for name in names},write_set=names)
store.mark_applying('owned-fault','digest')
store.publish('owned-fault','digest',writes={name:b'new' for name in names},result={'committed':True},
 artifacts={'before.vsz':b'old','after.vsz':b'new'})
"""


def roots(tmp_path):
    root, delivery = tmp_path / "project", tmp_path / "delivery"
    root.mkdir()
    delivery.mkdir()
    for name in ("document.vsz", "spec.json", "intake_manifest.json"):
        (root / name).write_bytes(b"old")
    (delivery / "native.vsz").write_bytes(b"old")
    store = FileProjectStore(root, locations={"delivery": delivery})
    return store, store.snapshot(import_legacy=True), delivery


def start(store, delivery, fault):
    process = subprocess.Popen([sys.executable, "-u", "-c", _CHILD, str(store.root), str(delivery), fault],
        cwd=store.root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert process.stdout is not None
        assert select.select([process.stdout], [], [], 10)[0], "Child never reached its owned fault boundary."
        line = process.stdout.readline().strip()
        if line != "holding":
            _out, err = process.communicate(timeout=5)
            pytest.fail(err)
        return process
    except BaseException:
        process.kill()
        process.communicate(timeout=5)
        raise


@pytest.mark.parametrize("fault", ["before_native", "before_storage", "after_generation", "before_head",
                                    "after_head", "before_projection", "after_projection", "before_reply"])
def test_actual_sigkill_recovers_old_complete_new_or_explicit_unknown(tmp_path, fault):
    store, before, delivery = roots(tmp_path)
    process = start(store, delivery, fault)
    try:
        with pytest.raises(ProjectSessionBusy):
            FileProjectStore(store.root, locations={"delivery": delivery}).snapshot()
    finally:
        process.kill()
        process.communicate(timeout=5)
    assert process.returncode == -signal.SIGKILL
    recovered = FileProjectStore(store.root, locations={"delivery": delivery})
    recovery = recovered.recover()
    snapshot = recovered.snapshot()
    expected = b"old" if fault in {"before_native", "before_storage", "after_generation", "before_head"} else b"new"
    observed = [(store.root / name).read_bytes() for name in ("document.vsz", "spec.json", "intake_manifest.json")]
    observed.append((delivery / "native.vsz").read_bytes())
    assert observed == [expected] * 4
    assert snapshot["projection_status"] == "current"
    if expected == b"old":
        assert snapshot["generation"] == before["generation"]
        if fault == "before_native":
            assert recovery["phase"] == "unknown" and recovered.query("owned-fault")["phase"] == "unknown"
        else:
            assert recovered.query("owned-fault")["phase"] == "accepted"
            receipt = recovered.publish_staged("owned-fault", "digest")
            assert receipt["phase"] == "complete"
            assert (store.root / "document.vsz").read_bytes() == (delivery / "native.vsz").read_bytes() == b"new"
    else:
        assert snapshot["generation"] != before["generation"]
        receipt = recovered.query("owned-fault")
        assert receipt["phase"] == "complete" and receipt["result"] == {"committed": True}
        assert Path(receipt["artifact_paths"]["before.vsz"]).read_bytes() == b"old"


def test_foreign_bytes_after_head_are_explicit_recovery_and_never_overwritten(tmp_path):
    store, _before, delivery = roots(tmp_path)
    process = start(store, delivery, "after_head")
    process.kill()
    process.communicate(timeout=5)
    target = delivery / "native.vsz"
    target.write_bytes(b"outside edits after interruption")
    with pytest.raises(ProjectRecoveryRequired):
        store.recover()
    assert target.read_bytes() == b"outside edits after interruption"
    assert (store.root / "document.vsz").read_bytes() == b"old"


def test_unidentified_live_native_window_excludes_store_even_without_file_changes(tmp_path):
    store, _before, _delivery = roots(tmp_path)
    with ProjectSessionLease(store.root, native=True):
        with pytest.raises(ProjectSessionBusy):
            store.reserve("unsafe-window", "digest", expected_generation=None, read_set={}, write_set=[])


def test_readonly_query_commands_snapshot_never_repair_interrupted_active_files(tmp_path):
    store, _before, delivery = roots(tmp_path)
    process = start(store, delivery, "after_head")
    process.kill()
    process.communicate(timeout=5)
    members = [path for root in (store.root, delivery) for path in root.rglob("*") if path.is_file()]
    before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in members}
    for inspect in (lambda: store.query("owned-fault"), store.commands, store.snapshot):
        with pytest.raises(ProjectRecoveryRequired):
            inspect()
        assert {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in members} == before
    assert store.recover()["phase"] == "complete"
    assert (store.root / "document.vsz").read_bytes() == (delivery / "native.vsz").read_bytes() == b"new"
