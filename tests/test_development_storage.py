from __future__ import annotations

from contextlib import ExitStack, contextmanager
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


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path_factory, monkeypatch):
    cache = tmp_path_factory.mktemp("sciplot-cache")
    monkeypatch.setattr(storage, "user_cache_path", lambda _app: cache)
    return cache


def _record(base: Path, *, returncode: int | None = 1) -> tuple[Path, int]:
    directory = base / ("run-" + uuid4().hex)
    directory.mkdir(parents=True)
    info = directory.stat()
    (directory / "payload").write_bytes(b"generated" * 4096)
    (directory / "run.json").write_text(json.dumps({
        "kind": storage._KIND, "version": 1,
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


def test_unsupported_commands_and_explicit_user_choices_do_not_allocate_or_change_environment(tmp_path):
    environment = {"PYTEST_DEBUG_TEMPROOT": "/user/chosen", storage.DEVELOPMENT_ROOT_KEY: "/other"}
    command = [sys.executable, "-m", "compileall", "."]
    with storage.development_check_run(command, tmp_path, environment=environment) as run:
        assert run.command == command and run.environment == environment and not run.managed
    for args, extra in [(["--basetemp=chosen"], {}), ([], {"PYTEST_ADDOPTS": "-q"}),
                        (["-o", "tmp_path_retention_policy=all"], {}),
                        (["--lf"], {}),
                        (["--input-scope", "public-focused"], {}),
                        ([], {"PYTEST_DEBUG_TEMPROOT": "/user/chosen"})]:
        command = [sys.executable, "-m", "pytest", *args]
        with storage.development_check_run(command, tmp_path, environment=extra) as run:
            assert not run.managed and run.command == command and run.environment == extra
    assert not (tmp_path / ".tmp_verify").exists()


@pytest.mark.parametrize("tool,key", (("mypy", "MYPY_CACHE_DIR"), ("ruff", "RUFF_CACHE_DIR"),
                                     ("swift", "CLANG_MODULE_CACHE_PATH")))
def test_explicit_tool_caches_keep_caller_ownership(tmp_path, tool, key):
    command = ["xcrun", "swiftc", "generated.swift"] if tool == "swift" else [sys.executable, "-m", tool]
    environment = {key: str(tmp_path / "user-specified")}
    with storage.development_check_run(command, tmp_path, environment=environment) as run:
        assert not run.managed and run.command == command and run.environment == environment
    assert not (tmp_path / "user-specified").exists()


@pytest.mark.parametrize("key", [*storage._EVIDENCE_KEYS, "PYTEST_PLUGINS"])
def test_recorded_and_observed_environment_is_not_disposable(tmp_path, key):
    command = [sys.executable, "-m", "pytest"]
    environment = {key: "sciplot_closure_audit" if key == "PYTEST_PLUGINS" else "bound"}
    with storage.development_check_run(command, tmp_path, environment=environment) as run:
        assert not run.managed and run.command == command and run.environment == environment
    assert not (tmp_path / ".tmp_verify").exists()


def test_active_observer_is_respected_without_importing_one_for_ordinary_runs(tmp_path, monkeypatch):
    key = "sciplot_core.verification.private_observer"
    actual = sys.modules.get(key)
    if actual is None or actual.current_observer() is None:
        monkeypatch.setitem(sys.modules, key, SimpleNamespace(current_observer=lambda: object()))
    with storage.development_check_run([sys.executable, "-m", "pytest"], tmp_path, environment={}) as run:
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
    run = storage.DevelopmentCheckRun([], {}, managed=True, directory=directory,
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
    return storage.development_check_run(command, workspace_root or project, environment=environment)


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
            assert not actual.is_relative_to(tmp_path)
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
                                                      workspace_root=tmp_path / f"worktree-{n}"))
                runs.append(run)
                processes.append(subprocess.Popen(run.command, env=run.environment,
                                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
            deadline = time.monotonic() + 15
            while not all(path.exists() for path in reports):
                assert time.monotonic() < deadline
                assert all(process.poll() is None for process in processes)
                time.sleep(.02)
            assert reports[0].read_text() != reports[1].read_text()
            if all(run.directory is not None for run in runs):
                assert runs[0].directory.parent == runs[1].directory.parent
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


def test_legacy_mixed_worktree_and_old_owned_scratch_are_not_cleanup_inputs(tmp_path):
    evidence = tmp_path / ".tmp_verify" / "workflow-reliability"
    names = ("private-input", "mechanical-data", "paper-delivery", "deliveries", "originals")
    for name in names:
        directory = evidence / name
        directory.mkdir(parents=True)
        (directory / "protected.txt").write_text(name)
    old_run, lease = _record(tmp_path / ".tmp_verify" / "pytest-development", returncode=0)
    os.close(lease)
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    with storage.development_check_run([sys.executable, "-m", "pytest"], tmp_path, environment={}) as run:
        if run.managed:
            assert run.directory is not None and not run.directory.is_relative_to(tmp_path)
        run.finish(0)
    assert old_run.exists()
    assert {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()} == before


@pytest.mark.parametrize("location", ("inside", "ancestor", "other_checkout", "alias"))
def test_unsafe_cache_location_is_rejected_before_allocation(tmp_path, monkeypatch, location):
    monkeypatch.setattr(storage, "_observer_active", lambda: False)
    project = tmp_path / "project"
    project.mkdir()
    cache = tmp_path / "cache"
    if location == "inside":
        cache = project / "cache"
    elif location == "ancestor":
        project = cache / "development" / "source"
    elif location == "other_checkout":
        (cache / ".git").mkdir(parents=True)
    else:
        target = tmp_path / "user-data"
        target.mkdir()
        cache.symlink_to(target, target_is_directory=True)
    monkeypatch.setattr(storage, "user_cache_path", lambda _app: cache)
    with pytest.raises(ValueError, match="outside source|symlinks"):
        with storage.development_check_run([sys.executable, "-m", "pytest"], project, environment={}):
            pytest.fail("Unsafe cache entered")
    assert not (cache / "development").exists()


def test_completed_cache_budget_and_expiry_do_not_apply_to_active_or_unknown(tmp_path, monkeypatch):
    base = tmp_path / "cache"
    unknown, lease = _record(base, returncode=None)
    os.close(lease)
    active, lease = _record(base)
    fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
    expired, fd = _record(base)
    os.close(fd)
    old = time.time() - storage.RETAINED_SECONDS - 1
    os.utime(expired / "run.json", (old, old))
    oversized, fd = _record(base)
    os.close(fd)
    monkeypatch.setattr(storage, "RETAINED_BYTES", 1024)
    try:
        result = _prune(base)
        assert result["retained_bytes"] <= 1024
        assert not expired.exists() and not oversized.exists()
        assert unknown.exists() and active.exists()
        assert (unknown / "payload").read_bytes() == b"generated" * 4096
    finally:
        os.close(lease)


@pytest.mark.parametrize("purpose", ("mypy", "swift", "ruff"))
def test_completed_tool_cache_reuses_bytes_but_busy_or_unknown_cache_is_not_admitted(tmp_path, monkeypatch, purpose):
    monkeypatch.setattr(storage, "_observer_active", lambda: False)
    command = ["xcrun", "swiftc", "generated.swift"] if purpose == "swift" else [sys.executable, "-m", purpose]
    with storage.development_check_run(command, tmp_path, environment={}) as first:
        directory = first.directory
        assert directory is not None
        (directory / "cache" / "generated").write_text("cached compiler input")
        with storage.development_check_run(command, tmp_path, environment={}) as concurrent:
            assert concurrent.directory != directory
            concurrent.finish(0)
        assert directory.exists()
        first.finish(0)
    with storage.development_check_run(command, tmp_path, environment={}) as second:
        assert second.directory == directory
        assert (directory / "cache" / "generated").read_text() == "cached compiler input"
        assert second.command[-2:] == ["-module-cache-path" if purpose == "swift" else "--cache-dir", str(directory / "cache")]
        second.finish(0)
    with storage.development_check_run(command, tmp_path, environment={}) as unfinished:
        assert unfinished.directory == directory
    with storage.development_check_run(command, tmp_path, environment={}) as replacement:
        assert replacement.directory != directory
        replacement.finish(0)
    assert directory.exists()  # Missing original child exit is not repaired by a later run.


def test_real_mypy_rechecks_changed_source_in_reused_cache(tmp_path):
    source = tmp_path / "generated.py"
    source.write_text("answer: int = 1\n")
    config = tmp_path / "mypy.ini"
    config.write_text("[mypy]\nstrict = True\n")
    command = [sys.executable, "-m", "mypy", "--config-file", str(config), str(source)]
    directories = []
    for expected in (0, 1):
        if expected:
            source.write_text("answer: int = 'changed'\n")
        with storage.development_check_run(command, tmp_path) as run:
            result = subprocess.run(run.command, cwd=tmp_path, env=run.environment, capture_output=True, text=True, timeout=30)
            assert result.returncode == expected, result.stdout + result.stderr
            run.finish(result.returncode)
            directories.append(run.directory)
            if expected:
                assert "Incompatible types" in result.stdout
    if directories[0] is not None:
        assert directories[0] == directories[1]


@pytest.mark.parametrize("purpose", (None, [], {}, 42, "private_input"))
def test_unknown_cache_role_is_protected_before_accounting(tmp_path, purpose):
    directory, lease = _record(tmp_path, returncode=0)
    os.close(lease)
    path = directory / "run.json"
    payload = json.loads(path.read_bytes())
    payload["purpose"] = purpose
    path.write_text(json.dumps(payload))
    result = _prune(tmp_path)
    assert result["deleted"] == [] and directory.name in result["protected"]
    assert (directory / "payload").exists()


@pytest.mark.parametrize("exit_code", (0, 3))
@pytest.mark.parametrize("failure", ("finish", "cleanup"))
def test_tool_entry_keeps_actual_exit_when_cache_finalization_fails(monkeypatch, capsys, exit_code, failure):
    @contextmanager
    def generated(*args, **kwargs):
        def finish(_code):
            if failure == "finish":
                raise OSError("generated cache completion failure")
        try:
            yield SimpleNamespace(command=["generated"], environment={}, managed=False, cleanup={}, finish=finish)
        finally:
            if failure == "cleanup":
                raise OSError("generated cache cleanup failure")
    monkeypatch.setattr(storage, "development_check_run", generated)
    monkeypatch.setattr(storage.subprocess, "call", lambda *a, **k: exit_code)
    monkeypatch.setattr(storage.sys, "argv", ["cache", sys.executable, "-m", "mypy"])
    assert storage.main() == exit_code
    assert "Development cache finalization failed" in capsys.readouterr().err


@pytest.mark.parametrize("purpose", ("mypy", "ruff", "swift"))
def test_tool_cache_child_alias_is_not_passed_to_the_tool(tmp_path, monkeypatch, purpose):
    monkeypatch.setattr(storage, "_observer_active", lambda: False)
    command = ["xcrun", "swiftc", "generated.swift"] if purpose == "swift" else [sys.executable, "-m", purpose]
    with storage.development_check_run(command, tmp_path, environment={}) as original:
        directory = original.directory
        assert directory is not None
        original.finish(0)
    target = tmp_path / "research"
    target.mkdir()
    protected = target / "original.txt"
    protected.write_bytes(b"unchanged research control")
    (directory / "cache").rmdir()
    (directory / "cache").symlink_to(target, target_is_directory=True)
    with storage.development_check_run(command, tmp_path, environment={}) as replacement:
        assert replacement.directory != directory
        assert not Path(replacement.command[-1]).is_symlink()
        replacement.finish(0)
    assert protected.read_bytes() == b"unchanged research control"
