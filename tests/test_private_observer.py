"""Real tiny processes distinguish stream evidence from declared completeness."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import time
from typing import Any
from uuid import uuid4

import pytest

from sciplot_core.verification.private_capture import capture_proof, review_capture
from sciplot_core.verification.private_observer import CHILD, CONTINUATION, PARENT, RUN, frame_digest, write_bootstrap
from private_observer_support import execute_observed, launch_generated_suite
from sciplot_core.verification.durable_runner import run_status
from sciplot_core.verification.evidence_identity import DOMAINS

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.comprehensive


def _suite_environment(root: Path, parent: dict[str, str]) -> dict[str, str]:
    environment = dict(parent, PYTHONPATH=os.pathsep.join((str(root / "src"), parent.get("PYTHONPATH", ""))))
    for key in ("SCIPLOT_PRIVATE_AUDIT_DIR", "SCIPLOT_PRIVATE_AUDIT_ROOTS", RUN, PARENT, CHILD, CONTINUATION, "PYTEST_CURRENT_TEST"):
        environment.pop(key, None)
    return environment


def test_generated_suite_environment_retains_public_stage_reference_rejection(tmp_path: Path) -> None:
    from sciplot_core.verification.public_stage import assert_private_absent

    stage = tmp_path / "source"
    public = {
        "SCIPLOT_REPO": str(stage), "SCIPLOT_SOURCE_ROOT": str(stage / "src"),
        "SCIPLOT_RUNTIME_REPO": str(stage), "SCIPLOT_VEUSZ_ROOT": str(stage / "third_party/veusz"),
        "SCIPLOT_PUBLIC_INPUT_GUARD": json.dumps([str(stage / "tests/fixtures")]),
        "SCIPLOT_PUBLIC_GUARD_BOOTSTRAP": str(stage / "bootstrap"),
        "SCIPLOT_PUBLIC_GUARD_WRAPPER_BOOTSTRAP": str(stage / "bootstrap/sitecustomize.py"),
    }
    for reference in (None, "", str(tmp_path / "inherited-reference")):
        parent = {**public, "PYTHONPATH": "earlier-source", RUN: "old-routing", "PYTEST_CURRENT_TEST": "outer (call)"}
        if reference is not None:
            parent["SCIPLOT_REFERENCE_DATA"] = reference
        original = dict(parent)
        environment = _suite_environment(stage, parent)
        assert parent == original
        assert all(environment[key] == value for key, value in public.items())
        assert environment["PYTHONPATH"].split(os.pathsep) == [str(stage / "src"), "earlier-source"]
        assert RUN not in environment and "PYTEST_CURRENT_TEST" not in environment
        if reference is None:
            assert "SCIPLOT_REFERENCE_DATA" not in environment
            assert_private_absent(stage, environment)
            injected = {**environment, "SCIPLOT_REFERENCE_DATA": str(tmp_path / "child-reference")}
            with pytest.raises(ValueError, match="inherited reference-data"):
                assert_private_absent(stage, injected)
        else:
            assert environment["SCIPLOT_REFERENCE_DATA"] == reference
            with pytest.raises(ValueError, match="inherited reference-data"):
                assert_private_absent(stage, environment)


def test_archived_metadata_reads_keep_actual_root_and_node_boundaries(tmp_path: Path) -> None:
    """Real producer frames and OS waits, without a scientific acceptance claim."""
    plugin = tmp_path / ".tmp_verify/bootstrap"
    plugin.parent.mkdir()
    write_bootstrap(plugin)
    audit, durable = tmp_path / ".tmp_verify/raw", tmp_path / ".tmp_verify/execution"
    archived = tmp_path / "tests/fixtures/rendering_profiles/generated/capture-runner.py"
    archived.parent.mkdir(parents=True)
    archived.write_text("# generated archived source; no measurements\n")
    original_sha = hashlib.sha256(archived.read_bytes()).hexdigest()
    inputs = {}
    for domain in DOMAINS:
        path = tmp_path / f"generated-{domain}"
        path.write_text("generated metadata observation identity")
        inputs[domain] = {"paths": [str(path)]}
    inputs["tests"]["paths"].append(str(archived))
    inputs["implementation"]["paths"].append(str(ROOT / "src/sciplot_core/verification/durable_runner.py"))
    environment = _suite_environment(ROOT, dict(os.environ))
    code = ("import os,sys;from pathlib import Path;"
            "from sciplot_core.verification.suite_evidence import _audit_environment;"
            "from sciplot_core.verification.durable_runner import start_run;"
            "from sciplot_core.verification.private_corpus_audit import test_sources_sha256;"
            "from sciplot_core.verification.evidence_runtime import qt_import_bindings;"
            "from sciplot_core.verification.private_observer import current_observer;"
            f"root=Path({str(tmp_path)!r});target=Path({str(archived)!r});"
            "os.environ['SCIPLOT_REFERENCE_DATA']=str(root/'.local/reference_data');"
            f"env,audit=_audit_environment(root,Path({str(durable)!r}),Path({str(plugin)!r}),Path({str(audit)!r}));"
            "test_sources_sha256(root);qt_import_bindings([root/'tests']);"
            "o=current_observer();o.nodeid='synthetic:body (call)';"
            "test_sources_sha256(root);qt_import_bindings([root/'tests']);o.nodeid=None;target.read_bytes();"
            "spec=dict(repo_root=str(root),command=[sys.executable,'-c','pass'],"
            "scope=dict(kind='process',closure_policy='generated metadata-boundary control'),selected_tests=['synthetic:metadata'],"
            f"inputs={inputs!r},environment=env,corpus=dict(mode='synthetic',complete=True,policy='generated control'));"
            f"launched=start_run(directory=Path({str(durable)!r}),spec=spec);os.waitpid(launched['supervisor_pid'],0)")
    pid, returncode, log, witness = launch_generated_suite([sys.executable, "-c", code], environment, tmp_path)
    assert returncode == 0, log.decode()
    state = json.loads((durable / "state.json").read_bytes())
    proof = capture_proof(audit, root_pid=pid, primary_pid=state["child_pid"], durable_directory=durable,
                          root_execution_directory=witness,
                          expected_roots=[str(tmp_path / "tests/fixtures"), str(tmp_path / ".local/reference_data")])
    result = review_capture(proof)
    assert result["status"] == "COMPLETE", result["issues"]
    assert result["root_actual_exit"] == 0 and run_status(durable)["status"] == "PASS"
    producers = {"test_sources_sha256", "qt_import_bindings"}
    reads = [row for row in result["frames"] if row["event"] == "open" and row["resolved_path"] == str(archived)]
    metadata = [row for row in reads if (row.get("diagnostic_owner") or {}).get("function") in producers]
    diagnostic_keys = {(row["epoch"], row["sequence"]) for row in result["diagnostic_observations"]}
    assert len(metadata) == 6
    for row in metadata:
        assert ((row["epoch"], row["sequence"]) in diagnostic_keys) is (not row["nodeid"])
    direct = [row for row in reads if row["pid"] == pid and row.get("diagnostic_owner") is None]
    assert len(direct) == 1 and (direct[0]["epoch"], direct[0]["sequence"]) not in diagnostic_keys
    assert hashlib.sha256(archived.read_bytes()).hexdigest() == original_sha


@pytest.mark.parametrize("late_fault", [False, True])
def test_suite_parent_collector_and_supervisor_share_actual_scope(tmp_path: Path, late_fault: bool) -> None:
    plugin = tmp_path / ".tmp_verify/bootstrap"
    plugin.parent.mkdir()
    write_bootstrap(plugin)
    audit = tmp_path / ".tmp_verify/raw"
    durable = tmp_path / ".tmp_verify/execution"
    fake = tmp_path / "test_generated.py"
    fake.write_text("def test_generated():pass\n")
    inputs = {}
    for domain in DOMAINS:
        path = tmp_path / f"generated-{domain}"
        path.write_text("generated observation identity")
        inputs[domain] = {"paths": [str(path)]}
    inputs["implementation"]["paths"].append(str(ROOT / "src/sciplot_core/verification/durable_runner.py"))
    environment = _suite_environment(ROOT, dict(os.environ))
    code = ("import json,os,sys,subprocess;from pathlib import Path;"
            "from sciplot_core.verification.suite_evidence import _audit_environment;"
            "from sciplot_core.verification.durable_runner import start_run;"
            f"root=Path({str(tmp_path)!r});"
            "os.environ['SCIPLOT_REFERENCE_DATA']=str(root/'.local/reference_data');"
            f"env,audit=_audit_environment(root,Path({str(durable)!r}),Path({str(plugin)!r}),Path({str(audit)!r}));"
            f"subprocess.run([sys.executable,'-m','pytest','--rootdir',{str(tmp_path)!r},'--confcutdir',{str(tmp_path)!r},'--collect-only','-q',{str(fake)!r}],env=env,check=True);"
            f"spec=dict(repo_root={str(tmp_path)!r},command=[sys.executable,'-c','pass'],"
            "scope=dict(kind='process',closure_policy='generated suite-observation contract'),selected_tests=['synthetic:scope'],"
            f"inputs={inputs!r},environment=env,corpus=dict(mode='synthetic',complete=True,policy='generated controls'));"
            f"launched=start_run(directory=Path({str(durable)!r}),spec=spec);os.waitpid(launched['supervisor_pid'],0)")
    if late_fault:
        code += (";from sciplot_core.verification.private_observer import current_observer;"
                 "o=current_observer();o.finish();"
                 "fail=lambda *a:(_ for _ in ()).throw(OSError('generated combined channel failure'));"
                 "o._mark_pending=fail;o.writer=fail;"
                 f"Path({str(tmp_path / 'tests/fixtures/generated-canary')!r}).read_bytes()")
    pid, returncode, stderr, witness = launch_generated_suite([sys.executable, "-c", code], environment, tmp_path)
    assert returncode == (79 if late_fault else 0), stderr.decode()
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if run_status(durable)["status"] != "RUNNING" and not list(audit.glob("*.pending")):
            break
        time.sleep(.02)
    assert run_status(durable)["status"] == "PASS"
    state = json.loads((durable / "state.json").read_bytes())
    proof = capture_proof(audit, root_pid=pid, primary_pid=state["child_pid"], durable_directory=durable,
                          root_execution_directory=witness,
                          expected_roots=[str(tmp_path / "tests/fixtures"), str(tmp_path / ".local/reference_data")])
    result = review_capture(proof)
    assert result["root_actual_exit"] == returncode
    if late_fault:
        assert result["status"] == "BLOCKED" and result["genuine_finish_count"] == 3, result["issues"]
    else:
        assert result["status"] == "COMPLETE", result["issues"]
        assert result["genuine_finish_count"] == result["epoch_count"] == 4


@pytest.mark.parametrize("mode", ["owned", "owned_cwd", "wrong_cwd", "shell_environment", "wrong_python", "shadow_source"])
def test_only_owned_wrapper_has_bound_python_exec_bridge(tmp_path: Path, mode: str) -> None:
    options = {"SCIPLOT_REPO": str(ROOT), "SCIPLOT_SOURCE_ROOT": str(ROOT / "src")}
    if mode == "shell_environment":
        shell = tmp_path / "generated-bash-env"
        shell.write_text(":\n")
        options["BASH_ENV"] = str(shell)
    elif mode == "wrong_python":
        options["SCIPLOT_PYTHON"] = "/usr/bin/true"
    elif mode == "shadow_source":
        source = tmp_path / "generated-source"
        source.mkdir()
        options["SCIPLOT_SOURCE_ROOT"] = str(source)
    code = f"env=dict(os.environ,**{options!r});env.setdefault('SCIPLOT_PYTHON',sys.executable)\n"
    cwd = str(ROOT) if mode == "owned_cwd" else str(tmp_path) if mode == "wrong_cwd" else None
    code += f"subprocess.run([{str(ROOT / 'skill/scripts/sciplot')!r},'--help'],env=env,cwd={cwd!r},check=True)\n"
    _, result = observed(tmp_path, code)
    assert (result["status"] == "COMPLETE") is (mode in {"owned", "owned_cwd"}), result["issues"]
    if mode in {"owned", "owned_cwd"}:
        assert any(row["event"] == "spawn_attempt" and row.get("input_boundary", {}).get("kind") == "owned_sciplot_python_exec"
                   for row in result["frames"] if row.get("input_boundary"))


@pytest.mark.parametrize("helper", ["bash", "dirname", "uname", "otool", "awk", "realpath", "mkdir"])
def test_wrapper_path_helper_shadow_cannot_hide_native_private_read(tmp_path: Path, helper: str) -> None:
    native_marker = tmp_path / "native-read-proof.txt"
    sentinel = tmp_path / "watched/input.txt"
    folder = tmp_path / "shadow-bin"
    folder.mkdir()
    originals = {"bash": "/bin/bash", "dirname": "/usr/bin/dirname", "uname": "/usr/bin/uname",
                 "otool": "/usr/bin/otool", "awk": "/usr/bin/awk", "realpath": "/bin/realpath", "mkdir": "/bin/mkdir"}
    shadow = folder / helper
    shadow.write_text(f"#!/bin/sh\n/bin/cat '{sentinel}' > '{native_marker}'\nexec '{originals[helper]}' \"$@\"\n")
    shadow.chmod(0o755)
    code = f"env=dict(os.environ,SCIPLOT_REPO={str(ROOT)!r},SCIPLOT_SOURCE_ROOT={str(ROOT / 'src')!r},SCIPLOT_PYTHON=sys.executable)\n"
    code += f"env['PATH']={str(folder)!r}+os.pathsep+env['PATH']\n"
    code += f"subprocess.run([{str(ROOT / 'skill/scripts/sciplot')!r},'--help'],env=env,check=True)\n"
    _, result = observed(tmp_path, code)
    assert result["status"] == "BLOCKED"
    assert any("child executable differs" in issue for issue in result["issues"])
    if native_marker.exists():
        assert native_marker.read_bytes() == sentinel.read_bytes()
    if helper == "uname":
        assert native_marker.is_file()  # The exact original A4 native read occurred.
        assert not any(frame["event"] == "open" and frame.get("resolved_path") == str(sentinel)
                       for frame in result["frames"])


@pytest.mark.parametrize("mode", ["veusz_root", "qtloops_input", "runtime_root", "configuration_output", "framework_loader", "developer_toolchain"])
def test_wrapper_native_inputs_and_environment_cannot_drift(tmp_path: Path, mode: str) -> None:
    code = f"env=dict(os.environ,SCIPLOT_REPO={str(ROOT)!r},SCIPLOT_SOURCE_ROOT={str(ROOT / 'src')!r},SCIPLOT_PYTHON=sys.executable)\n"
    key = {"veusz_root": "SCIPLOT_VEUSZ_ROOT", "qtloops_input": "SCIPLOT_VEUSZ_ROOT", "runtime_root": "SCIPLOT_RUNTIME_REPO", "configuration_output": "MPLCONFIGDIR",
           "framework_loader": "DYLD_FRAMEWORK_PATH", "developer_toolchain": "DEVELOPER_DIR"}[mode]
    replacement = tmp_path / "watched/generated-wrapper-input"
    code += f"Path({str(replacement)!r}).mkdir(parents=True)\n"
    if mode == "qtloops_input":
        code += f"helpers=Path({str(replacement)!r})/'veusz/helpers';helpers.mkdir(parents=True);(helpers/'qtloops.so').symlink_to(WATCH)\n"
    code += f"env[{key!r}]={str(replacement)!r}\n"
    code += f"subprocess.run([{str(ROOT / 'skill/scripts/sciplot')!r},'--help'],env=env,check=True)\n"
    _, result = observed(tmp_path, code)
    assert result["status"] == "BLOCKED", result
    if mode == "qtloops_input":
        assert any(frame["event"] == "open" and frame.get("resolved_path") == str(tmp_path / "watched/input.txt")
                   for frame in result["frames"])


def test_wrapper_nonexecutable_python_cannot_open_shadow_fallback(tmp_path: Path) -> None:
    selected = tmp_path / "nonexecutable-python"
    selected.write_bytes(Path(sys.executable).read_bytes())
    selected.chmod(0o644)
    folder = tmp_path / "shadow-bin"
    folder.mkdir()
    sentinel, marker = tmp_path / "watched/input.txt", tmp_path / "fallback-native-read.txt"
    fallback = folder / "python3"
    fallback.write_text(f"#!/bin/sh\n/bin/cat '{sentinel}' > '{marker}'\nexec '{sys.executable}' \"$@\"\n")
    fallback.chmod(0o755)
    code = f"env=dict(os.environ,SCIPLOT_PYTHON={str(selected)!r},SCIPLOT_REPO={str(ROOT)!r},SCIPLOT_SOURCE_ROOT={str(ROOT / 'src')!r})\n"
    code += f"env['PATH']={str(folder)!r}+os.pathsep+env['PATH']\n"
    code += f"subprocess.run([{str(ROOT / 'skill/scripts/sciplot')!r},'--help'],env=env,check=True)\n"
    _, result = observed(tmp_path, code)
    assert marker.read_bytes() == sentinel.read_bytes()
    assert result["status"] == "BLOCKED"


def observed(tmp_path: Path, code: str, *, prefix: str = "") -> tuple[dict[str, Any], dict[str, Any]]:
    plugin = tmp_path / "bootstrap"
    write_bootstrap(plugin)
    if prefix:
        shim = plugin / "sitecustomize.py"
        shim.write_text(prefix + shim.read_text())
    output = tmp_path / "raw"
    output.mkdir()
    watch = tmp_path / "watched"
    watch.mkdir()
    sentinel = watch / "input.txt"
    sentinel.write_text("generated canary, not scientific data")
    environment = dict(os.environ)
    for key in (PARENT, CHILD, CONTINUATION, "PYTEST_CURRENT_TEST"):
        environment.pop(key, None)
    environment.update(PYTHONPATH=os.pathsep.join((str(plugin), str(ROOT / "src"), environment.get("PYTHONPATH", ""))),
                       SCIPLOT_PRIVATE_AUDIT_DIR=str(output), SCIPLOT_PRIVATE_AUDIT_ROOTS=json.dumps([str(watch)]))
    environment[RUN] = uuid4().hex
    program = "from pathlib import Path\nimport os,sys,subprocess,json\n" + code.replace("WATCH", repr(str(sentinel)))
    return execute_observed(tmp_path, [sys.executable, "-c", program], environment, output, [str(watch)])


def test_real_parent_child_access_and_genuine_finish_complete(tmp_path: Path) -> None:
    proof, result = observed(tmp_path, "subprocess.run([sys.executable,'-c','from pathlib import Path;Path('+repr(WATCH)+').read_bytes()'],check=True)\n")
    assert result["status"] == "COMPLETE", result["issues"]
    assert result["genuine_finish_count"] == result["epoch_count"] == 3
    assert len([frame for frame in result["frames"] if frame["event"] == "open"]) == 1
    assert any(frame["event"] == "child_exit" and frame["returncode"] == 0 for frame in result["frames"])
    unbound = review_capture({**proof, "root_execution_directory": None, "root_actual_exit": 0})
    assert unbound["status"] == "BLOCKED" and unbound["root_actual_exit"] is None
    assert any("external wait witness is absent" in issue for issue in unbound["issues"])


@pytest.mark.parametrize("mode", ["normal", "failed"])
def test_real_exec_handoff_and_failed_exec_continuation(tmp_path: Path, mode: str) -> None:
    code = ("os.execvpe(sys.executable,[sys.executable,'-c','from pathlib import Path;Path('+repr(WATCH)+').read_bytes()'],dict(os.environ))\n"
            if mode == "normal" else "try: os.execvpe('/nonexistent/sciplot-exec',[sys.executable],dict(os.environ))\nexcept OSError: Path(WATCH).read_bytes()\n")
    _, result = observed(tmp_path, code)
    assert result["status"] == "COMPLETE", result["issues"]
    assert result["exec_seal_count"] == (1 if mode == "normal" else 0)
    assert result["genuine_finish_count"] == 2
    primary = next(frame["pid"] for frame in result["frames"] if frame["event"] == "open")
    assert any(frame["event"] == "child_exit" and frame["child_pid"] == primary and frame["returncode"] == 0
               for frame in result["frames"])
    assert any(frame["event"] == ("exec_seal" if mode == "normal" else "exec_failed") for frame in result["frames"])


@pytest.mark.parametrize("mode", ["no_site", "isolated", "shadow", "removed_path"])
def test_unobserved_successful_child_remains_blocked(tmp_path: Path, mode: str) -> None:
    if mode in {"no_site", "isolated"}:
        code = f"subprocess.run([sys.executable,{('-S' if mode == 'no_site' else '-I')!r},'-c','pass'],check=True)\n"
    else:
        shadow = tmp_path / "shadow"
        shadow.mkdir()
        (shadow / "sitecustomize.py").write_text("# A shadow does not install the supported observer.\n")
        replacement = str(shadow) if mode == "shadow" else str(ROOT / "src")
        code = f"env=dict(os.environ,PYTHONPATH={replacement!r});subprocess.run([sys.executable,'-c','pass'],env=env,check=True)\n"
    _, result = observed(tmp_path, code)
    assert result["status"] == "BLOCKED"
    assert any("child startup missing" in issue for issue in result["issues"])
    assert any(frame["event"] == "child_exit" and frame["returncode"] == 0 for frame in result["frames"])


@pytest.mark.parametrize("mode", ["wrong_run", "missing_startup", "non_python"])
def test_exec_seal_alone_is_not_successor_proof(tmp_path: Path, mode: str) -> None:
    environment = "dict(os.environ)"
    arguments = "[sys.executable,'-c','pass']"
    target = "sys.executable"
    if mode == "wrong_run":
        environment = f"dict(os.environ,{RUN}='0'*32)"
    elif mode == "missing_startup":
        arguments = "[sys.executable,'-S','-c','pass']"
    else:
        target, arguments = "'/usr/bin/true'", "['/usr/bin/true']"
    _, result = observed(tmp_path, f"os.execvpe({target},{arguments},{environment})\n")
    assert result["status"] == "BLOCKED"
    assert any("exec successor" in issue or "run identity" in issue for issue in result["issues"])


@pytest.mark.parametrize("mode", ["os_exit", "sigkill", "sigterm", "fork"])
def test_abrupt_and_unsupported_processes_remain_blocked(tmp_path: Path, mode: str) -> None:
    if mode == "os_exit":
        code = "os._exit(7)\n"
    elif mode == "fork":
        code = "pid=os.fork()\nif pid==0: os._exit(0)\nos.waitpid(pid,0)\n"
    else:
        signal = "SIGKILL" if mode == "sigkill" else "SIGTERM"
        code = ("import signal\n"
                "child=subprocess.Popen([sys.executable,'-c','import time;print(1,flush=True);time.sleep(30)'],stdout=subprocess.PIPE)\n"
                "child.stdout.readline()\n"
                f"child.send_signal(signal.{signal});child.wait()\n")
    _, result = observed(tmp_path, code)
    assert result["status"] == "BLOCKED"
    assert any("terminal is absent" in issue or "signalled" in issue or "unsupported process" in issue for issue in result["issues"])


@pytest.mark.parametrize("mode", ["full_partial_write", "partial_then_zero", "loss", "sync_loss"])
def test_full_write_loop_and_real_loss_are_discriminated(tmp_path: Path, mode: str) -> None:
    setup = "from sciplot_core.verification.private_observer import current_observer\no=current_observer();write=o.writer\n"
    if mode == "full_partial_write":
        setup += "o.writer=lambda fd,value:write(fd,value[:3])\n"
    elif mode == "partial_then_zero":
        setup += "calls=[0]\ndef writer(fd,value):\n calls[0]+=1\n return write(fd,value[:3]) if calls[0]==1 else 0\no.writer=writer\n"
    elif mode == "sync_loss":
        setup += "def broken_sync(fd): raise OSError('generated sync failure')\no.sync=broken_sync\n"
    else:
        setup += "def broken_write(fd,value): raise OSError('generated write failure')\no.writer=broken_write\n"
    _, result = observed(tmp_path, setup + "Path(WATCH).read_bytes()\n")
    assert (result["status"] == "COMPLETE") is (mode == "full_partial_write")


def test_terminal_does_not_suppress_later_private_finalizer(tmp_path: Path) -> None:
    sentinel = tmp_path / "watched/input.txt"
    prefix = f"import atexit\nfrom pathlib import Path\natexit.register(lambda:Path({str(sentinel)!r}).read_bytes())\n"
    _, result = observed(tmp_path, "pass\n", prefix=prefix)
    assert result["status"] == "BLOCKED"
    assert any("late event" in issue for issue in result["issues"])
    assert any(frame["event"] == "open" for frame in result["frames"])


def test_child_cannot_replace_frozen_observed_roots(tmp_path: Path) -> None:
    code = ("env=dict(os.environ,SCIPLOT_PRIVATE_AUDIT_ROOTS=json.dumps(['/unrelated/generated/root']))\n"
            "subprocess.run([sys.executable,'-c','from pathlib import Path;Path('+repr(WATCH)+').read_bytes()'],env=env,check=True)\n")
    _, result = observed(tmp_path, code)
    assert result["status"] == "BLOCKED"
    assert any("root scope differs" in issue for issue in result["issues"])


def test_bypassed_python_spawn_port_cannot_hide_unobserved_child(tmp_path: Path) -> None:
    code = ("port=subprocess.Popen.__init__\n"
            "cells=dict(zip(port.__code__.co_freevars,port.__closure__))\n"
            "subprocess.Popen.__init__=cells['original_init'].cell_contents\n"
            "env=dict(os.environ);env.pop('SCIPLOT_PRIVATE_AUDIT_DIR');env.pop('SCIPLOT_PRIVATE_AUDIT_ROOTS')\n"
            "subprocess.run([sys.executable,'-S','-c','pass'],env=env,check=True)\n")
    _, result = observed(tmp_path, code)
    assert result["status"] == "BLOCKED"
    assert any(frame["event"] == "unsupported_spawn" and frame["mechanism"] == "subprocess.Popen"
               for frame in result["frames"])


@pytest.mark.parametrize("mode", ["terminal_sync_and_marker_loss", "late_event_and_write_loss", "pending_reopen_failure",
                                 "remove_sync_and_recreate_failure"])
def test_independent_incomplete_state_survives_combined_channel_failures(tmp_path: Path, mode: str) -> None:
    code = "from sciplot_core.verification.private_observer import current_observer\no=current_observer()\n"
    if mode == "terminal_sync_and_marker_loss":
        code += ("write=o.writer\n"
                 "def broken_sync(fd):raise OSError('generated terminal sync failure')\n"
                 "def writer(fd,value):\n"
                 " if b'sensor_failure' in bytes(value):raise OSError('generated marker loss')\n"
                 " return write(fd,value)\no.sync=broken_sync;o.writer=writer\n")
    elif mode == "remove_sync_and_recreate_failure":
        code += ("def broken_directory_sync():raise OSError('generated directory sync failure')\n"
                 "def broken_pending():raise OSError('generated recreate failure')\n"
                 "o._sync_directory=broken_directory_sync;o._mark_pending=broken_pending\n")
    else:
        code += "o.finish()\n"
        if mode == "pending_reopen_failure":
            code += "def broken_pending():raise OSError('generated reopen failure')\no._mark_pending=broken_pending\n"
        code += "def broken_write(fd,value):raise OSError('generated late event loss')\no.writer=broken_write\nPath(WATCH).read_bytes()\n"
    _, result = observed(tmp_path, code)
    assert result["status"] == "BLOCKED", result
    if mode not in {"pending_reopen_failure", "remove_sync_and_recreate_failure"}:
        assert result["raw_terminal_frame_count"] > result["genuine_finish_count"]
        assert any("synchronization is incomplete" in issue for issue in result["issues"])
    else:
        assert result["actual_returncode"] == 79


@pytest.mark.parametrize("mode", ["mutable_owner", "explicit_environment"])
def test_uname_boundary_uses_frozen_caller_and_invocation_inputs(tmp_path: Path, mode: str) -> None:
    code = "import platform\n"
    if mode == "mutable_owner":
        code += ("def replacement():return subprocess.check_output(['uname','-p'],stderr=subprocess.DEVNULL,text=True,encoding='utf8')\n"
                 "platform._Processor.from_subprocess=staticmethod(replacement)\n")
    else:
        code += ("original=subprocess.check_output\n"
                 "def replacement(args,**kwargs):return original(args,env=dict(os.environ),**kwargs)\n"
                 "subprocess.check_output=replacement\n")
    _, result = observed(tmp_path, code + "platform._Processor.from_subprocess()\n")
    assert result["status"] == "BLOCKED"
    assert result["bounded_auxiliary"] == []


def test_truncation_and_false_terminal_counter_cannot_be_declared_complete(tmp_path: Path) -> None:
    proof, result = observed(tmp_path, "Path(WATCH).read_bytes()\n")
    assert result["capture_complete"]
    path = next(Path(proof["directory"]).glob("*.jsonl"))
    original = path.read_bytes()
    path.write_bytes(original[:-1])
    proof["stream_sha256"][path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    assert review_capture(proof)["status"] == "BLOCKED"
    frames = [json.loads(line) for line in original.splitlines()]
    frames[-1]["recorded_events"] += 1
    content = dict(frames[-1])
    content.pop("sha256")
    frames[-1]["sha256"] = frame_digest(content)
    path.write_text("".join(json.dumps(frame) + "\n" for frame in frames))
    proof["stream_sha256"][path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    assert any("terminal counter" in issue for issue in review_capture(proof)["issues"])


def test_no_environment_or_request_values_are_persisted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "generated-sensitive-value-not-for-logs"
    monkeypatch.setenv("SCIPLOT_GENERATED_SECRET", secret)
    proof, result = observed(tmp_path, "assert os.environ['SCIPLOT_GENERATED_SECRET']\n")
    assert result["status"] == "COMPLETE"
    assert all(secret not in path.read_text() for path in Path(proof["directory"]).glob("*.jsonl"))


@pytest.mark.parametrize("mode", ["owned", "wrong_callsite", "wrong_arguments", "wrong_binary", "unknown_exit"])
def test_only_closed_stdlib_kernel_query_has_nonpython_input_boundary(tmp_path: Path, mode: str) -> None:
    code = "import platform\n"
    if mode == "wrong_callsite":
        code += "subprocess.run(['uname','-p'],check=True)\n"
    elif mode == "wrong_arguments":
        code += "original=subprocess.check_output\ndef wrong(args,**kwargs):return original(['uname','-a'],**kwargs)\nsubprocess.check_output=wrong\nplatform._Processor.from_subprocess()\n"
    elif mode == "wrong_binary":
        executable = tmp_path / "bin/uname"
        executable.parent.mkdir()
        executable.write_text("#!/bin/sh\nprintf 'generated kernel query replacement\\n'\n")
        executable.chmod(0o755)
        code += f"os.environ['PATH']={str(executable.parent)!r}+os.pathsep+os.environ['PATH']\nplatform._Processor.from_subprocess()\n"
    elif mode == "unknown_exit":
        code += ("import posix\ndef no_wait(args,**kwargs):\n"
                 " child=subprocess.Popen(args,stdout=subprocess.PIPE,**kwargs)\n"
                 " output=child.stdout.read()\n pid,status=posix.waitpid(child.pid,0)\n assert pid==child.pid\n"
                 " child.returncode=os.waitstatus_to_exitcode(status)\n child.stdout.close()\n return output\n"
                 "subprocess.check_output=no_wait\nplatform._Processor.from_subprocess()\n")
    else:
        code += "platform._Processor.from_subprocess()\n"
    _, result = observed(tmp_path, code)
    assert (result["status"] == "COMPLETE") is (mode == "owned"), result["issues"]
    if mode == "owned":
        assert len(result["bounded_auxiliary"]) == 1
        assert result["bounded_auxiliary"][0]["terminal_counters"] == "not_observed_non_python_kernel_query"
    if mode == "unknown_exit":
        assert result["root_actual_exit"] == 0, result["issues"]
        assert len(result["bounded_auxiliary"]) == 1
        child_pid = result["bounded_auxiliary"][0]["child_pid"]
        spawn = next(row for row in result["frames"] if row["event"] == "child_spawn" and row.get("child_pid") == child_pid)
        assert not any(row["event"] == "child_exit" and row.get("child_pid") == child_pid for row in result["frames"])
        assert f"child signalled or exit ledger invalid:{spawn['epoch']}:{spawn['child_token']}" in result["issues"]
