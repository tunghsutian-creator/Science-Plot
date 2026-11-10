from __future__ import annotations

from contextlib import ExitStack
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest

from sciplot_core.verification import development_storage as storage


def _record(base: Path, *, returncode: int | None = 1) -> tuple[Path, int]:
    directory = base / ("run-" + uuid4().hex)
    directory.mkdir(parents=True)
    info = directory.stat()
    (directory / "payload").write_bytes(b"generated" * 4096)
    (directory / "run.json").write_text(json.dumps({
        "kind": "sciplot_disposable_pytest", "version": 1,
        "state": "running" if returncode is None else "completed",
        "inode": [info.st_dev, info.st_ino], "returncode": returncode,
    }))
    lease = os.open(directory / "lease", os.O_RDWR | os.O_CREAT, 0o600)
    return directory, lease


def _prune(base: Path):
    fd = os.open(base, os.O_RDONLY | os.O_DIRECTORY)
    try:
        return storage._prune(fd)
    finally:
        os.close(fd)


def test_completed_failures_are_bounded_and_unknown_or_replaced_records_survive(tmp_path):
    base = tmp_path / "pytest-development"
    unknown, fd = _record(base, returncode=None)
    os.close(fd)
    replaced, fd = _record(base)
    os.close(fd)
    state = json.loads((replaced / "run.json").read_text())
    state["inode"][1] += 1
    (replaced / "run.json").write_text(json.dumps(state))
    failures = []
    for _ in range(4):
        directory, fd = _record(base)
        os.close(fd)
        failures.append(directory)
        _prune(base)
    assert [path.exists() for path in failures] == [False, False, True, True]
    assert unknown.exists() and replaced.exists()
    assert (unknown / "payload").read_bytes() == b"generated" * 4096


def test_kernel_lease_protects_completed_run_even_when_older_than_pytest_lock_timeout(tmp_path):
    base = tmp_path / "pytest-development"
    active, lease = _record(base)
    fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
    old = time.time() - 4 * 86400
    os.utime(active / "lease", (old, old))
    os.utime(active / "run.json", (old, old))
    try:
        for _ in range(3):
            directory, fd = _record(base)
            os.close(fd)
            result = _prune(base)
        assert active.name in result["protected"]
        assert active.exists()
    finally:
        os.close(lease)
    assert active.name in _prune(base)["deleted"]
    assert not active.exists()


@pytest.mark.parametrize("member", ["lease", "run.json"])
def test_unknown_symlink_members_cannot_select_external_data(tmp_path, member):
    base = tmp_path / "pytest-development"
    directory, lease = _record(base, returncode=0)
    os.close(lease)
    external = tmp_path / "external"
    external.write_text("keep this user file")
    (directory / member).unlink()
    (directory / member).symlink_to(external)
    assert directory.name in _prune(base)["protected"]
    assert external.read_text() == "keep this user file"
    assert (directory / "payload").exists()


def test_success_cleanup_unlinks_internal_alias_without_following_it(tmp_path):
    base = tmp_path / "pytest-development"
    directory, lease = _record(base, returncode=0)
    os.close(lease)
    external = tmp_path / "external"
    external.mkdir()
    (external / "original").write_text("user original")
    (directory / "alias").symlink_to(external, target_is_directory=True)
    assert _prune(base)["deleted"] == [directory.name]
    assert not directory.exists()
    assert (external / "original").read_text() == "user original"


def test_name_replacement_after_admission_cannot_redirect_recursive_deletion(tmp_path, monkeypatch):
    base = tmp_path / "pytest-development"
    directory, lease = _record(base, returncode=0)
    os.close(lease)
    original = storage._remove_contents
    moved = base / "moved-owned-run"

    def replace_before_deletion(fd):
        directory.rename(moved)
        directory.mkdir()
        (directory / "user-work").write_text("preserve unknown replacement")
        original(fd)

    monkeypatch.setattr(storage, "_remove_contents", replace_before_deletion)
    result = _prune(base)
    assert directory.name in result["protected"]
    assert (directory / "user-work").read_text() == "preserve unknown replacement"
    assert not (moved / "payload").exists()
    assert result["deleted"] == []


def test_nonpytest_and_explicit_user_choices_do_not_allocate_or_change_environment(tmp_path):
    environment = {"PYTEST_DEBUG_TEMPROOT": "/user/chosen", storage.DEVELOPMENT_ROOT_KEY: "/other"}
    command = [sys.executable, "-m", "ruff", "check", "."]
    with storage.development_pytest_run(command, tmp_path, environment=environment) as run:
        assert run.command == command and run.environment == environment and not run.managed
    for args, extra in [(["--basetemp=chosen"], {}), ([], {"PYTEST_ADDOPTS": "-q"}),
                        (["-o", "tmp_path_retention_policy=all"], {}),
                        ([], {"PYTEST_DEBUG_TEMPROOT": "/user/chosen"})]:
        command = [sys.executable, "-m", "pytest", *args]
        with storage.development_pytest_run(command, tmp_path, environment=extra) as run:
            assert not run.managed and run.command == command and run.environment == extra
    assert not (tmp_path / ".tmp_verify").exists()


@pytest.mark.parametrize("key", [*storage._EVIDENCE_KEYS, "PYTEST_PLUGINS"])
def test_recorded_and_observed_environment_is_not_disposable(tmp_path, key):
    command = [sys.executable, "-m", "pytest"]
    environment = {key: "sciplot_closure_audit" if key == "PYTEST_PLUGINS" else "bound"}
    with storage.development_pytest_run(command, tmp_path, environment=environment) as run:
        assert not run.managed and run.command == command and run.environment == environment
    assert not (tmp_path / ".tmp_verify").exists()


def test_active_observer_is_respected_without_importing_one_for_ordinary_runs(tmp_path, monkeypatch):
    key = "sciplot_core.verification.private_observer"
    actual = sys.modules.get(key)
    if actual is None or actual.current_observer() is None:
        monkeypatch.setitem(sys.modules, key, SimpleNamespace(current_observer=lambda: object()))
    with storage.development_pytest_run([sys.executable, "-m", "pytest"], tmp_path, environment={}) as run:
        assert not run.managed
    assert not (tmp_path / ".tmp_verify").exists()


def test_record_boundary_strips_only_our_temp_override():
    own = {storage.DEVELOPMENT_ROOT_KEY: "/owned", "PYTEST_DEBUG_TEMPROOT": "/owned", "other": "kept"}
    assert storage.without_development_storage(own) == {"other": "kept"}
    own["PYTEST_DEBUG_TEMPROOT"] = "/user/replacement"
    assert storage.without_development_storage(own) == {"PYTEST_DEBUG_TEMPROOT": "/user/replacement", "other": "kept"}


def test_low_space_is_an_observation_and_does_not_reserve_or_delete_bytes(tmp_path, monkeypatch):
    monkeypatch.setattr(storage.shutil, "disk_usage", lambda _path: SimpleNamespace(free=1024))
    result = storage.space_observation(tmp_path)
    assert result["free_bytes"] == 1024 and result["low_space"] and result["warning"]
    assert list(tmp_path.iterdir()) == []


def test_failed_completion_write_leaves_unknown_container_protected(tmp_path, monkeypatch):
    base = tmp_path / "pytest-development"
    directory, lease = _record(base, returncode=None)
    os.close(lease)
    directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    run = storage.DevelopmentPytestRun([], {}, managed=True, directory=directory,
                                       _directory_fd=directory_fd)
    def unavailable(*_args):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(storage, "_write_state", unavailable)
    try:
        with pytest.raises(OSError, match="No space left"):
            run.finish(0)
        assert not run._finished
    finally:
        os.close(directory_fd)
    assert directory.name in _prune(base)["protected"]
    assert (directory / "payload").exists()


@pytest.mark.parametrize("member", ["lease", "run.json"])
def test_nonregular_cleanup_control_never_blocks_or_deletes_unknown_data(tmp_path, member):
    base = tmp_path / "pytest-development"
    directory, lease = _record(base, returncode=0)
    os.close(lease)
    (directory / member).unlink()
    os.mkfifo(directory / member)
    assert directory.name in _prune(base)["protected"]
    assert (directory / "payload").exists()


def test_malformed_nested_metadata_is_unknown_instead_of_hiding_a_test_result(tmp_path):
    base = tmp_path / "pytest-development"
    directory, lease = _record(base, returncode=0)
    os.close(lease)
    (directory / "run.json").write_text("[" * 1100 + "0" + "]" * 1100)
    assert directory.name in _prune(base)["protected"]
    assert (directory / "payload").exists()


def _child_case(project: Path, *, fails: bool, report: Path, release: Path | None = None,
                workspace_root: Path | None = None):
    project.mkdir()
    (project / "pytest.ini").write_text("[pytest]\n")
    pause = ("\n    import time\n    deadline = time.monotonic() + 15\n"
             f"    while not Path({str(release)!r}).exists():\n"
             "        assert time.monotonic() < deadline\n        time.sleep(.02)" if release else "")
    case = project / "test_generated.py"
    case.write_text("from pathlib import Path\ndef test_generated(tmp_path):\n"
                    "    (tmp_path / 'payload').write_bytes(b'x' * 262144)\n"
                    f"    Path({str(report)!r}).write_text(str(tmp_path))" + pause +
                    f"\n    assert {not fails!r}\n")
    environment = dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", PYTHONDONTWRITEBYTECODE="1")
    # A nested observed child receives its own finish destination, not its parent's.
    if environment.get("SCIPLOT_VERIFY_FINISH"):
        environment["SCIPLOT_VERIFY_FINISH"] = str(project / "finish.json")
    command = [sys.executable, "-m", "pytest", "-q", "-c", str(project / "pytest.ini"), str(case)]
    return storage.development_pytest_run(command, workspace_root or project, environment=environment)


@pytest.mark.parametrize("fails", [False, True])
def test_real_pytest_respects_ordinary_or_observed_storage_contract(tmp_path, fails):
    report = tmp_path / "path.txt"
    with _child_case(tmp_path / "child", fails=fails, report=report) as run:
        completed = subprocess.run(run.command, env=run.environment, capture_output=True, text=True, timeout=30)
        assert completed.returncode == int(fails), completed.stdout + completed.stderr
        run.finish(completed.returncode)
        actual = Path(report.read_text())
        directory = run.directory
        managed = run.managed
        if managed:
            assert actual.exists() is fails
        else:
            assert actual.exists()  # no failed-only policy was added at this recorded boundary
    print(json.dumps({"storage_mode": "managed" if managed else "observed_or_user", "child_exit": int(fails)}))
    if managed:
        assert directory is not None and directory.exists() is fails


def test_two_actual_children_get_distinct_storage_and_keep_active_containers(tmp_path):
    processes = []
    runs = []
    reports = [tmp_path / f"path-{n}" for n in range(2)]
    releases = [tmp_path / f"release-{n}" for n in range(2)]
    with ExitStack() as stack:
        try:
            for n in range(2):
                run = stack.enter_context(_child_case(tmp_path / f"child-{n}", fails=False,
                                                      report=reports[n], release=releases[n],
                                                      workspace_root=tmp_path / "shared-worktree"))
                runs.append(run)
                processes.append(subprocess.Popen(run.command, env=run.environment,
                                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
            deadline = time.monotonic() + 15
            while not all(path.exists() for path in reports):
                assert time.monotonic() < deadline
                assert all(process.poll() is None for process in processes)
                time.sleep(.02)
            assert reports[0].read_text() != reports[1].read_text()
            assert all(run.directory is None or run.directory.exists() for run in runs)
            for path in releases:
                path.touch()
            for run, process in zip(runs, processes, strict=True):
                stdout, stderr = process.communicate(timeout=15)
                assert process.returncode == 0, stdout + stderr
                run.finish(process.returncode)
        finally:
            for process in processes:
                if process.poll() is None:
                    process.terminate()
                    process.communicate(timeout=5)
    assert all(run.directory is None or not run.directory.exists() for run in runs)
