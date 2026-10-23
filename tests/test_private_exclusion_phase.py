"""Real item/source classification, independent of ambient test labels."""
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
