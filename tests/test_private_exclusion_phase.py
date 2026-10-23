"""Real item/source classification, independent of ambient test labels."""
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
import json
import os
import sys
import threading

import pytest

from sciplot_core.verification.input_scope import load_manifest
from sciplot_core.verification import private_exclusion_boundary as boundary
from sciplot_core.verification import private_observer as observation


class Observer:
    def __init__(self, directory):
        self.frames = []
        self.nodeid = None
        self.directory = directory
        self.run = "a" * 32
        self.wrapper_environment = {"SCIPLOT_VERIFY_FINISH": str(directory / "finish.json")}
        (directory / "state.json").write_text(json.dumps({"child_pid": os.getpid()}))
        (directory / "request.json").write_text(json.dumps({"scope": {"kind": "pytest"}}))
        (directory / "root.jsonl").write_text(json.dumps({"event": "process_start", "run_id": self.run,
            "sha256": "generated-unit-root", "activation": boundary.owner_identity("suite_evidence.py", "_audit_environment")}))

    def record(self, value, **kwargs):
        frame = {**value, "sha256": str(len(self.frames))}
        self.frames.append(frame)
        return frame


def item(node, *, path=None):
    return SimpleNamespace(nodeid=node, path=path or boundary.REPO / node.split("::", 1)[0])


def test_phase_uses_exact_source_and_clears_context_after_each_phase(tmp_path, monkeypatch):
    node = load_manifest()["scopes"]["public"][0]
    observer = Observer(tmp_path)
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "tests/forged.py::test_approved (call)")
    boundary.bind_collection(observer, [node])
    for phase in ("setup", "call", "teardown"):
        boundary.begin_phase(observer, item(node), phase)
        assert observer._exclusion_phase["test_nodeid"] == node
        assert observer._exclusion_phase["phase"] == phase
        boundary.end_phase(observer, item(node), phase)
        assert observer._exclusion_phase is None and observer.nodeid is None
    assert [frame["event"] for frame in observer.frames] == ["pytest_phase_enter", "pytest_phase_exit"] * 3


def test_unknown_private_nested_or_wrong_source_never_get_public_phase(tmp_path):
    manifest = load_manifest()
    public, private = manifest["scopes"]["public"][0], manifest["scopes"]["private"][0]
    for node in ("tests/unknown.py::test_forged", private):
        observer = Observer(tmp_path)
        boundary.bind_collection(observer, [node])
        boundary.begin_phase(observer, item(node), "call")
        assert observer._exclusion_phase is None and not observer.frames
    observer = Observer(tmp_path)
    boundary.bind_collection(observer, [public])
    boundary.begin_phase(observer, item(public, path=Path("/generated/wrong.py")), "call")
    assert observer._exclusion_phase is None
    boundary.bind_collection(observer, [public])
    boundary.begin_phase(observer, item(public), "call")
    assert observer._exclusion_phase is None and not observer.frames


def test_a_different_durable_primary_pid_cannot_activate_known_public_item(tmp_path):
    node = load_manifest()["scopes"]["public"][0]
    observer = Observer(tmp_path)
    (tmp_path / "state.json").write_text(json.dumps({"child_pid": os.getpid() + 1}))
    boundary.bind_collection(observer, [node])
    boundary.begin_phase(observer, item(node), "call")
    assert observer._exclusion_collection is None and observer._exclusion_phase is None
    assert not observer.frames


@pytest.mark.parametrize("mode", ["public", "private", "wrong_run", "wrong_directory", "root_drift",
                                 "roots_string_drift", "roots_missing", "continuation", "empty_continuation"])
def test_effective_environment_uses_bound_phase_and_exact_routing(tmp_path, monkeypatch, mode):
    roots = json.dumps(boundary.watch_roots(boundary.REPO, {}))
    observer = SimpleNamespace(directory=tmp_path, run="generated-run",
        wrapper_environment={observation.ROOTS: roots},
        root_scope=boundary.root_scope(boundary.watch_roots(boundary.REPO, {})),
        _exclusion_phase={"sha256": "generated-source-bound-phase"}, epoch="generated-parent", reserved={})
    environment = {key: "generated-routing" for key in observation.AUDIT_KEYS}
    environment.pop(observation.CONTINUATION)
    environment.update({observation.DIRECTORY: str(tmp_path), observation.RUN: observer.run,
                        observation.ROOTS: roots,
                        "SCIPLOT_PRIVATE_AUDIT_UNKNOWN": "retained", "ordinary": "retained"})
    original = dict(environment)
    if mode == "private":
        observer._exclusion_phase = None
        environment[observation.CONTINUATION] = "generated-exec-predecessor"
    elif mode == "wrong_run":
        environment[observation.RUN] += "-different"
    elif mode == "wrong_directory":
        environment[observation.DIRECTORY] += "-different"
    elif mode == "root_drift":
        observer.root_scope = {"lexical": [], "canonical": []}
    elif mode == "roots_string_drift":
        environment[observation.ROOTS] += " "
    elif mode == "roots_missing":
        environment.pop(observation.ROOTS)
    elif mode in {"continuation", "empty_continuation"}:
        environment[observation.CONTINUATION] = "generated-exec-predecessor" if mode == "continuation" else ""
    monkeypatch.setattr(observation, "current_observer", lambda: observer)
    if mode in {"root_drift", "roots_string_drift", "roots_missing", "continuation", "empty_continuation"}:
        message = ("root scope changed" if mode == "root_drift" else "exec continuation"
                   if mode in {"continuation", "empty_continuation"} else "requested audit roots differ")
        with pytest.raises(ValueError, match=message):
            observation.reserve_child_environment(environment, reserve=False)
        with pytest.raises(ValueError, match=message):
            observation.reserve_child_environment(environment)
        assert observer.reserved == {}
    else:
        preview = observation.reserve_child_environment(environment, reserve=False)
        assert observer.reserved == {}
        if mode == "public":
            assert preview == {key: value for key, value in environment.items() if key not in observation.AUDIT_KEYS}
            assert observation.reserve_child_environment(preview) == preview
            assert observer.reserved == {}
        else:
            assert preview == environment
    assert original["ordinary"] == environment["ordinary"]
    assert environment["SCIPLOT_PRIVATE_AUDIT_UNKNOWN"] == "retained"


@pytest.mark.parametrize("mode", ["missing_proof", "roots_drift", "roots_missing", "continuation"])
def test_public_durable_transfer_without_native_proof_never_calls_original_init(tmp_path, monkeypatch, mode):
    from contextlib import nullcontext

    class NoProcess:
        def __init__(self, args, *, env, cwd, stdin, stdout, stderr, close_fds, start_new_session):
            pytest.fail("A public durable transfer fell back to an unobserved original launch")

        def wait(self):
            pytest.fail("No process exists to wait for")

        def poll(self):
            pytest.fail("No process exists to poll")

    observer = SimpleNamespace(directory=tmp_path, run="generated-run",
        wrapper_environment={observation.ROOTS: json.dumps(boundary.watch_roots(boundary.REPO, {}))},
        root_scope=boundary.root_scope(boundary.watch_roots(boundary.REPO, {})),
        _exclusion_phase={"sha256": "generated-source-bound-phase"}, epoch="generated-parent", reserved={},
        nodeid="generated-public-durable-transfer")
    monkeypatch.setattr(observation, "subprocess", SimpleNamespace(Popen=NoProcess))
    monkeypatch.setattr(observation, "install_socket_ports", lambda _: None)
    monkeypatch.setattr(observation, "server_call", lambda *_: None)
    monkeypatch.setattr(observation, "executable_hash", lambda *_, **__: None)
    monkeypatch.setattr(observation, "owned_caller", lambda *_: {"owner": "generated exact durable caller"})
    for name in ("uname_call", "wrapper_call", "native_probe_call"):
        monkeypatch.setattr(observation, name, lambda *_: None)
    environment = {}
    if mode == "missing_proof":
        monkeypatch.setattr(observation, "excluded_launch", lambda *_: nullcontext(None))
        message = "actual native exclusion proof"
    else:
        environment.update({observation.DIRECTORY: str(tmp_path), observation.RUN: observer.run,
                            observation.ROOTS: observer.wrapper_environment[observation.ROOTS]})
        if mode == "roots_missing":
            environment.pop(observation.ROOTS)
        elif mode == "roots_drift":
            environment[observation.ROOTS] += " "
        else:
            environment[observation.CONTINUATION] = "generated-exec-predecessor"
        message = "exec continuation" if mode == "continuation" else "requested audit roots differ"
    for name in ("waitpid", "execve", "execvpe"):
        monkeypatch.setattr(observation.os, name, getattr(observation.os, name))
    observation._install_process_ports(observer)
    with pytest.raises(ValueError, match=message):
        NoProcess([sys.executable, "-m", "sciplot_core.verification.durable_runner", str(tmp_path), "a" * 64],
                  env=environment, cwd=tmp_path, stdin=-3, stdout=-1, stderr=-2, close_fds=True, start_new_session=True)


@pytest.mark.parametrize("kind,cleanup", [("exception", "none"), ("failed", "none"),
    ("failed", "finish"), ("failed", "end"), ("failed", "both")])
def test_teardown_activation_failure_yields_restores_and_reraises_same_error(monkeypatch, kind, cleanup):
    from sciplot_core.verification import private_observer_pytest as plugin

    calls = []
    original = RuntimeError("generated activation failure") if kind == "exception" else pytest.fail.Exception("generated activation failure")
    finish_error = OSError("generated finish failure")
    end_error = LookupError("generated end failure")
    if kind == "failed":
        assert isinstance(original, BaseException) and not isinstance(original, Exception)

    def begin(*_):
        calls.append("begin")
        raise original

    def finish(*_):
        calls.append("finish")
        if cleanup in {"finish", "both"}:
            raise finish_error

    def end(*_):
        calls.append("end")
        if cleanup in {"end", "both"}:
            raise end_error

    with monkeypatch.context() as control:
        control.setattr(plugin, "current_observer", object)
        control.setattr(plugin, "begin_phase", begin)
        control.setattr(plugin, "finish_node", finish)
        control.setattr(plugin, "end_phase", end)
        phase = plugin._phase(object(), "teardown")
        assert next(phase) is None and calls == ["begin"]
        calls.append("fixture_restored")
        with pytest.raises(type(original)) as result:
            next(phase)
    assert result.value is original
    assert calls == ["begin", "fixture_restored", "finish", "end"]
    if cleanup == "none":
        assert original.__cause__ is None
    else:
        assert original.__cause__ is (finish_error if cleanup == "finish" else end_error)
        if cleanup == "both":
            assert end_error.__context__ is finish_error


@pytest.mark.parametrize("phase_name", ["setup", "call"])
@pytest.mark.parametrize("kind", ["exception", "failed"])
def test_setup_and_call_activation_failures_still_refuse_before_yield(monkeypatch, phase_name, kind):
    from sciplot_core.verification import private_observer_pytest as plugin

    calls = []
    original = RuntimeError("generated activation failure") if kind == "exception" else pytest.fail.Exception("generated activation failure")

    def begin(*_):
        calls.append("begin")
        raise original

    with monkeypatch.context() as control:
        control.setattr(plugin, "current_observer", object)
        control.setattr(plugin, "start_node", lambda *_: calls.append("start"))
        control.setattr(plugin, "begin_phase", begin)
        control.setattr(plugin, "finish_node", lambda *_: pytest.fail("Pre-yield failure cannot finish a node"))
        control.setattr(plugin, "end_phase", lambda *_: pytest.fail("Pre-yield failure cannot manufacture a phase exit"))
        generator = plugin._phase(object(), phase_name)
        with pytest.raises(type(original)) as result:
            next(generator)
    assert result.value is original
    assert calls == (["start", "begin"] if phase_name == "setup" else ["begin"])


def test_finish_collects_only_original_nonblocking_child_waits(tmp_path, monkeypatch):
    from contextlib import nullcontext

    for mode in ("zero", "nonzero", "signal", "live", "reaped", "cached_reaped", "busy", "wrong_pid", "not_exit", "already_waited"):
        frames, waits = [], []

        class Process:
            def __init__(self, args, *, env=None):
                self.pid, self.returncode = 401, None
                self._waitpid_lock = threading.Lock()

            def wait(self, *args, **kwargs):
                pytest.fail("Terminal collection must not block or use Popen's ECHILD fallback")

            def poll(self, *args, **kwargs):
                pytest.fail("Popen.poll cannot prove a previously uncollected exit")

        def original_waitpid(pid, options, *, mode=mode, waits=waits):
            waits.append((pid, options))
            if mode in {"reaped", "cached_reaped"}:
                raise ChildProcessError("An external reap has no original status")
            return ((0, 0) if mode == "live" else (402, 0) if mode == "wrong_pid"
                    else (pid, 127) if mode == "not_exit" else
                    (pid, 256 if mode == "nonzero" else 15 if mode == "signal" else 0))

        def record(value, *, frames=frames, **_):
            frames.append(value)
            return value

        observer = SimpleNamespace(directory=tmp_path, run="generated-run", epoch="generated-parent", reserved={}, wrapper_environment={},
            guard=threading.local(), record=record)
        with monkeypatch.context() as control:
            control.setattr(observation, "subprocess", SimpleNamespace(Popen=Process))
            control.setattr(observation, "install_socket_ports", lambda _: None)
            control.setattr(observation, "server_call", lambda *_: None)
            control.setattr(observation, "hold_server", lambda *_: None)
            control.setattr(observation, "executable_hash", lambda *_, **__: None)
            control.setattr(observation, "owned_caller", lambda *_: None)
            control.setattr(observation, "excluded_launch", lambda *_: nullcontext(None))
            for name in ("uname_call", "wrapper_call", "native_probe_call"):
                control.setattr(observation, name, lambda *_: None)
            control.setattr(observation.os, "waitpid", original_waitpid)
            for name in ("execve", "execvpe"):
                control.setattr(observation.os, name, getattr(observation.os, name))
            observation._install_process_ports(observer)
            child = Process(["generated-child"])
            if mode == "cached_reaped":
                child.returncode = 0
            if mode == "busy":
                child._waitpid_lock.acquire()
            if mode == "already_waited":
                observation.os.waitpid(child.pid, 0)
            observer._collect_children()
            observation.Observer.finish(observer)
            if mode == "busy":
                child._waitpid_lock.release()
        exits = [frame for frame in frames if frame["event"] == "child_exit"]
        expected = {"zero": 0, "nonzero": 1, "signal": -15, "already_waited": 0}
        assert [row["returncode"] for row in exits] == ([expected[mode]] if mode in expected else [])
        assert all(row["child_pid"] == child.pid for row in exits)
        assert frames[-1]["event"] == "process_finish"
        assert waits == ([(child.pid, 0)] if mode == "already_waited" else [] if mode == "busy" else
                         [(child.pid, os.WNOHANG)] * (1 if mode in expected else 2))


def _generated_capture_review(tmp_path, monkeypatch, *, children=2, noise=8, fault=None):
    from sciplot_core.verification import private_capture as capture

    visits, calls = [], []

    class CountedRecords(list):
        def __iter__(self):
            for row in super().__iter__():
                visits.append(None)
                yield row

    sources = {name: "1" * 64 for name in ("suite_evidence.py", "durable_runner.py", "process_private_exclusion.py")}

    def owner(filename, function):
        calls.append((filename, function))
        return {"owner": filename, "function": function, "source_sha256": sources[filename], "bytecode_sha256": "2" * 64}

    activation = owner("suite_evidence.py", "_audit_environment")
    metadata_owner = owner("process_private_exclusion.py", "_members")
    scope = {"lexical": [str(tmp_path)], "canonical": [str(tmp_path)]}
    proof = {"version": capture.VERSION, "directory": str(tmp_path), "primary_pid": 100, "root_pid": 50,
             "observer_sources_sha256": sources, "stream_sha256": {}, "python_runtime": {},
             "interpreter_sha256": "exe", "wrapper_inputs": {}, "expected_root_scope": scope}

    def rows(epoch, pid, parent_epoch=None, token=None, parent_pid=50):
        return [{"event": "process_start", "pid": pid, "parent_pid": parent_pid, "epoch": epoch,
                 "run_id": "f" * 32, "parent_epoch": parent_epoch, "child_token": token, "continuation": None,
                 "observer_sources_sha256": sources, "executable_sha256": "exe", "python_runtime": {},
                 "wrapper_inputs": {}, "root_scope": scope, "no_site": False, "isolated": False,
                 "bootstrap_sha256": "boot", "activation": activation, "command_sha256": "command"}]

    root = rows("root", 50)
    primary = rows("primary", 100, "root", "a" * 32)
    epochs = {"root": root, "primary": primary}

    def spawn(records, token, pid):
        records.extend([{"event": "spawn_attempt", "child_token": token, "expected_executable_sha256": "exe", "input_boundary": None},
                        {"event": "child_spawn", "child_token": token, "child_pid": pid},
                        {"event": "child_exit", "child_token": token, "child_pid": pid, "returncode": 0}])

    spawn(root, "a" * 32, 100)
    for number in range(children):
        token = f"{number + 1:032x}"
        spawn(primary, token, 200 + number)
        epochs[f"child{number}"] = rows(f"child{number}", 200 + number, "primary", token, parent_pid=100)
    primary.extend({"event": "os.scandir", "nodeid": None, "resolved_path": str(tmp_path),
                    "diagnostic_owner": metadata_owner} for _ in range(noise))
    target = primary[1]
    if fault == "duplicate_attempt":
        primary.insert(2, dict(target))
    elif fault in {"duplicate_outcome", "duplicate_exit"}:
        position = 2 if fault == "duplicate_outcome" else 3
        primary.insert(position, dict(primary[position]))
    elif fault in {"missing_outcome", "missing_exit"}:
        primary.pop(2 if fault == "missing_outcome" else 3)
    elif fault == "late_attempt":
        primary[1], primary[2] = primary[2], primary[1]
    elif fault == "missing_start":
        epochs.pop("child0")
    elif fault == "duplicate_start":
        epochs["duplicate"] = [dict(epochs["child0"][0], epoch="duplicate")]
    elif fault == "wrong_owner":
        metadata_owner = dict(metadata_owner, bytecode_sha256="bad")
        for row in primary:
            if row["event"] == "os.scandir":
                row["diagnostic_owner"] = metadata_owner
    for epoch, records in epochs.items():
        records.append({"event": "process_finish", "recorded_events": len(records), "lost_events": 0})
        for sequence, row in enumerate(records):
            row.update(pid=records[0]["pid"], sequence=sequence, sha256=f"{epoch}:{sequence}",
                       monotonic_ns=sequence + (0 if epoch == "root" else 10 if epoch == "primary" else 10000))
        epochs[epoch] = CountedRecords(records)
    if fault == "early_start":
        epochs["child0"][0]["monotonic_ns"] = 0
    durable = {"state": {"supervisor_pid": 50}, "exit_code": 0, "native_records": {}, "records": {},
               "declared_paths": [], "request_sha256": "request", "directory_sha256": "directory"}
    caller = dict(durable, command_sha256="command", command_executable_sha256="exe")
    source_calls = []

    def current_sources():
        source_calls.append(None)
        return dict(sources, **({"suite_evidence.py": "changed"} if fault == "source_drift" and len(source_calls) > 1 else {}))

    monkeypatch.setattr(capture, "observer_source_hashes", current_sources)
    monkeypatch.setattr(capture, "_streams", lambda _: {})
    monkeypatch.setattr(capture, "_read_epochs", lambda _: epochs)
    monkeypatch.setattr(capture, "_durable_context", lambda _, root=False: caller if root else durable)
    monkeypatch.setattr(capture, "validated_exits", lambda *_, **__: {})
    monkeypatch.setattr(capture, "runtime_identity", dict)
    monkeypatch.setattr(capture, "wrapper_inputs", lambda _: {})
    monkeypatch.setattr(capture, "root_scope", lambda _: scope)
    monkeypatch.setattr(capture, "bootstrap_hashes", lambda: {"sitecustomize.py": "boot"})
    monkeypatch.setattr(capture, "native_probe_bound", lambda *_: False)
    monkeypatch.setattr(capture, "uname_boundary", lambda: {"kind": "generated kernel query"})
    monkeypatch.setattr(capture, "wrapper_boundary", lambda: {"kind": "generated wrapper"})
    monkeypatch.setattr(capture, "owner_identity", owner)
    monkeypatch.setattr(boundary, "owner_identity", owner)
    calls.clear()
    result = capture.review_capture(proof)
    return result, len(visits), calls, sum(map(len, epochs.values()))


def test_capture_review_preserves_ledger_counterproof_without_repeated_stream_scans(tmp_path, monkeypatch):
    for fault, message in ((None, None), ("duplicate_attempt", "duplicate successful-spawn token"),
            ("duplicate_outcome", "spawn outcome missing or ambiguous"), ("missing_outcome", "spawn outcome missing or ambiguous"),
            ("duplicate_exit", "child signalled or exit ledger invalid"), ("missing_exit", "child signalled or exit ledger invalid"),
            ("late_attempt", "child ledger has no unique preceding attempt"), ("missing_start", "successful child startup missing"),
            ("duplicate_start", "successful child startup missing"), ("early_start", "child startup precedes")):
        with monkeypatch.context() as control:
            result, _, _, _ = _generated_capture_review(tmp_path, control, fault=fault)
        assert result["status"] == ("COMPLETE" if fault is None else "BLOCKED"), (fault, result["issues"])
        assert message is None or any(message in issue for issue in result["issues"]), (fault, result["issues"])
    with monkeypatch.context() as control:
        result, visits, calls, count = _generated_capture_review(tmp_path, control, children=48, noise=2048)
    assert result["status"] == "COMPLETE", result["issues"]
    assert visits <= 20 * count, (visits, count)
    assert max(Counter(calls).values()) <= 1, Counter(calls)


def test_capture_review_rechecks_source_snapshot_and_never_reuses_prior_call_identity(tmp_path, monkeypatch):
    for fault, expected in ((None, "COMPLETE"), ("source_drift", "BLOCKED"), (None, "COMPLETE")):
        with monkeypatch.context() as control:
            result, _, calls, _ = _generated_capture_review(tmp_path, control, fault=fault)
        assert result["status"] == expected, result["issues"]
        assert ("process_private_exclusion.py", "_members") in calls
        if fault == "source_drift":
            assert any("source" in issue for issue in result["issues"])


def test_phase_and_metadata_indexes_preserve_missing_duplicate_owner_and_reserve_order(tmp_path, monkeypatch):
    from copy import deepcopy
    import hashlib
    import stat

    node = "tests/generated.py::test_generated"
    source = tmp_path / "tests/generated.py"
    source.parent.mkdir()
    source.write_text("def test_generated(): pass\n")
    source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    scope = {"public": {node}, "manifest_sha256": "manifest", "collection_sha256": "collection"}
    monkeypatch.setattr(boundary, "REPO", tmp_path)
    scope_reads, snapshots, validations = [], [], []
    monkeypatch.setattr(boundary, "_scope", lambda _: scope_reads.append(None) or deepcopy(scope))
    monkeypatch.setattr(boundary, "prepare_private_exclusion", lambda *_, **kw: snapshots.append(kw) or
                        SimpleNamespace(to_dict=lambda: {"identity": {"sandbox": {"sha256": "sandbox"}}}))
    monkeypatch.setattr(boundary, "validate_excluded_proof", lambda *args, **kwargs: validations.append((args, kwargs)))
    suite = {"sha256": "suite", "activation": boundary.owner_identity("suite_evidence.py", "_audit_environment")}
    durable = {"directory": str(tmp_path / "durable"), "records": {boundary.canonical_json_sha256(str(source)): {"sha256": source_sha}}}
    original = {"original_argv_sha256": "argv", "original_environment_sha256": "env", "original_executable_sha256": "exe",
                "original_cwd": str(tmp_path), "original_stdio": {"stdin": "generated"}}
    value = {"kind": boundary.KIND, "version": 1, "phase_enter_sha256": "enter", "root_listing_owner": None,
             "process_proof": {"generated": "strict proof validation is separately owned"}, "drop_environment": [],
             "caller_launch": None, **original}
    attempt = {"event": "spawn_attempt", "pid": 100, "sequence": 5, "nodeid": node,
               "expected_executable_sha256": "sandbox", "excluded_actual_launch": {"original": "unchanged"},
               "excluded_caller_launch": None, **{"excluded_" + key: val for key, val in original.items()}}
    entered = {"event": "pytest_phase_enter", "pid": 100, "sequence": 1, "sha256": "enter", "test_nodeid": node,
               "phase": "call", "manifest_sha256": "manifest", "collection_sha256": "collection",
               "test_source_sha256": source_sha, "suite_root_sha256": "suite",
               "phase_owner": boundary.owner_identity("private_exclusion_boundary.py", "begin_phase")}
    exited = {"event": "pytest_phase_exit", "sequence": 6, "phase_enter_sha256": "enter", "test_nodeid": node, "phase": "call"}
    socket_enter = {"event": "audit_socket_enter", "sequence": 2, "test_nodeid": node, "sockets": ["A"],
                    "directory": "generated", "initial_absent": True,
                    "owner": boundary.owner_identity("private_audit_runtime.py", "start_node")}
    reserves = [dict(socket_enter, event="audit_socket_reserve", sequence=number,
                     sockets=["A", *extra], owner=boundary.owner_identity("private_audit_runtime.py", "reserve_socket_fixture"))
                for number, extra in ((3, ["B"]), (4, ["B", "C"]))]
    baseline = [entered, socket_enter, *reserves, attempt, exited]
    for fault in (None, "missing_enter", "duplicate_enter", "missing_exit", "duplicate_exit", "late_enter", "early_exit",
                  "wrong_phase", "wrong_pid", "wrong_manifest", "wrong_collection", "wrong_source", "wrong_owner_source",
                  "wrong_owner_bytecode", "duplicate_socket_enter", "duplicate_reserve", "bad_reserve_owner", "reverse_reserves"):
        rows = deepcopy(baseline)
        if fault in {"missing_enter", "missing_exit"}:
            rows.remove(rows[0] if fault == "missing_enter" else rows[-1])
        elif fault in {"duplicate_enter", "duplicate_exit", "duplicate_socket_enter", "duplicate_reserve"}:
            rows.append(deepcopy(rows[{"duplicate_enter": 0, "duplicate_exit": -1, "duplicate_socket_enter": 1, "duplicate_reserve": 3}[fault]]))
        elif fault in {"late_enter", "early_exit"}:
            rows[0 if fault == "late_enter" else -1]["sequence"] = 5
        elif fault in {"wrong_phase", "wrong_pid", "wrong_manifest", "wrong_collection", "wrong_source"}:
            rows[0][{"wrong_phase": "phase", "wrong_pid": "pid", "wrong_manifest": "manifest_sha256",
                     "wrong_collection": "collection_sha256", "wrong_source": "test_source_sha256"}[fault]] = "wrong"
        elif fault in {"wrong_owner_source", "wrong_owner_bytecode"}:
            rows[0]["phase_owner"]["source_sha256" if fault == "wrong_owner_source" else "bytecode_sha256"] = "wrong"
        elif fault == "bad_reserve_owner":
            rows[3]["owner"]["bytecode_sha256"] = "wrong"
        elif fault == "reverse_reserves":
            rows[2], rows[3] = rows[3], rows[2]
        index = boundary._review_index(rows)
        assert all(actual is expected for actual, expected in zip(index["socket"].get(None, []),
            [row for row in rows if row["event"] in {"audit_socket_enter", "audit_socket_reserve"}], strict=True))
        assert boundary.saved_socket_scope(rows, attempt) == boundary.saved_socket_scope(index["socket"].get(None, []), attempt)
        snapshots.clear()
        kwargs = dict(primary=100, expected_nodeids={node}, directory=tmp_path, durable=durable,
                      suite_start=suite, audit_keys=(), root_pid=50, caller=None)
        before = len(scope_reads)
        legacy = boundary.excluded_bound(value, attempt, rows, **kwargs)
        fast = boundary.excluded_bound(value, attempt, rows, review_index=index, node_scope=deepcopy(scope), **kwargs)
        expected = fault is None or fault in {"duplicate_socket_enter", "duplicate_reserve", "bad_reserve_owner", "reverse_reserves"}
        assert legacy is fast is expected, fault
        assert len(scope_reads) == before + 1
        if expected:
            assert len(snapshots) == 2 and snapshots[0] == snapshots[1]
    assert validations
    owners = [boundary.owner_identity("process_private_exclusion.py", name) for name in ("_members", "_evidence_inodes")]
    frame = {"event": "os.scandir", "resolved_path": "generated/path", "diagnostic_owner": owners[0]}
    for rows in ([], [None], [None, {"st_mode": stat.S_IFREG}],
                 [None, {"st_mode": stat.S_IFREG}, {"st_mode": stat.S_IFDIR}, None, {"st_mode": stat.S_IFDIR}]):
        snapshots = [{"members": {frame["resolved_path"]: row}} for row in rows]
        for fault in (None, "owner", "source_sha256", "bytecode_sha256"):
            current = deepcopy(frame)
            if fault:
                current["diagnostic_owner"][fault] = "wrong"
            legacy = boundary.metadata_diagnostic(current, snapshots)
            fast = boundary.metadata_diagnostic(current, snapshots, owners=owners, members={frame["resolved_path"]: rows})
            assert legacy is fast is (fault is None and any(row is not None and stat.S_ISDIR(row["st_mode"]) for row in rows))
