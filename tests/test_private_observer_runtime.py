"""Synthetic mapping/parser controls; real Linux startup remains a CI gate."""
from __future__ import annotations

import ctypes
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
import hashlib
import os
from pathlib import Path
import sys
import sysconfig
from types import FunctionType, SimpleNamespace

import pytest

from sciplot_core.verification import private_process_boundaries as boundary
from sciplot_core.verification import evidence_runtime, private_corpus_audit
from sciplot_core.verification.private_capture import _diagnostic_bound
from sciplot_core.verification.evidence_identity import digest
from sciplot_core.verification.private_observer import write_bootstrap
from sciplot_core.verification.public_input_guard import ENVIRONMENT_KEY, rebind_bootstrap
from private_observer_support import execute_observed

ROOT = Path(__file__).resolve().parents[1]
ADDRESSES = [0x1100, 0x1200, 0x1300]


def mapping(path: Path, *, start: int = 0x1000, end: int = 0x2000, permissions: str = "r-xp") -> str:
    value = path.stat()
    return f"{start:x}-{end:x} {permissions} 00000000 {os.major(value.st_dev):x}:{os.minor(value.st_dev):x} {value.st_ino} {path}\n"


@pytest.mark.parametrize("name", ["python3.12", "libpython3.12.so.1.0"])
def test_core_owner_follows_actual_api_mapping_not_binary_name(tmp_path: Path, name: str) -> None:
    core = tmp_path / name
    core.write_bytes(b"generated mapped-core bytes")
    assert boundary._linux_core_hashes(ADDRESSES, mapping(core)) == [hashlib.sha256(core.read_bytes()).hexdigest()]


@pytest.mark.parametrize("mode", ["unmapped", "anonymous", "nonexec", "deleted", "wrong_device", "malformed", "missing_api", "ambiguous", "different_owners"])
def test_unproved_core_mapping_blocks(tmp_path: Path, mode: str) -> None:
    core = tmp_path / "python3.12"
    core.write_bytes(b"generated core")
    maps, addresses = mapping(core), ADDRESSES
    if mode == "unmapped":
        addresses = [*ADDRESSES[:2], 0x3000]
    elif mode == "anonymous":
        maps = maps.rsplit(" ", 1)[0] + "\n"
    elif mode == "nonexec":
        maps = mapping(core, permissions="r--p")
    elif mode == "deleted":
        maps = maps.rstrip() + " (deleted)\n"
    elif mode == "wrong_device":
        fields = maps.split(maxsplit=5)
        fields[3] = "ffff:ffff"
        maps = " ".join(fields)
    elif mode == "malformed":
        maps = "not a proc mapping\n"
    elif mode == "missing_api":
        addresses = ADDRESSES[:2]
    elif mode == "ambiguous":
        maps += maps
    else:
        second = tmp_path / "second-core"
        second.write_bytes(b"different generated owner")
        maps = mapping(core, end=0x1200) + mapping(second, start=0x1200, end=0x2000)
    with pytest.raises(ValueError):
        boundary._linux_core_hashes(addresses, maps)


def test_core_path_replacement_cannot_impersonate_loaded_inode(tmp_path: Path) -> None:
    core = tmp_path / "python3.12"
    core.write_bytes(b"original generated owner")
    maps = mapping(core)
    core.rename(tmp_path / "still-loaded-original")
    core.write_bytes(b"different new file at same path")
    with pytest.raises(ValueError, match="device/inode"):
        boundary._linux_core_hashes(ADDRESSES, maps)


def test_unreadable_core_is_not_accepted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    core = tmp_path / "python3.12"
    core.write_bytes(b"generated owner")
    maps, original = mapping(core), Path.open
    def denied(path: Path, *args, **kwargs):
        if path == core:
            raise PermissionError("generated unavailable mapped owner")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", denied)
    with pytest.raises(PermissionError):
        boundary._linux_core_hashes(ADDRESSES, maps)


def test_core_owner_change_during_hash_is_blocked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    core = tmp_path / "python3.12"
    core.write_bytes(b"generated core")
    maps, original = mapping(core), Path.stat
    def replaced(path: Path, *args, **kwargs):
        value = original(path, *args, **kwargs)
        if path == core:
            names = ("st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns", "st_ctime_ns")
            return SimpleNamespace(**{name: getattr(value, name) + (name == "st_ino") for name in names})
        return value
    monkeypatch.setattr(Path, "stat", replaced)
    with pytest.raises(ValueError, match="changed while hashing"):
        boundary._linux_core_hashes(ADDRESSES, maps)


def test_static_core_mapping_is_bound_even_with_shared_build_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    core = tmp_path / "python3.12"
    core.write_bytes(b"generated executable core; not an actual Linux runtime claim")
    addresses = [ctypes.cast(getattr(ctypes.pythonapi, name), ctypes.c_void_p).value
                 for name in ("Py_GetVersion", "PyObject_Call", "PyErr_Occurred")]
    assert all(isinstance(address, int) for address in addresses)
    maps = mapping(core, start=min(addresses) - 1, end=max(addresses) + 1)
    original_read, original_config = Path.read_text, sysconfig.get_config_var
    def read(path: Path, *args, **kwargs):
        return maps if path == Path("/proc/self/maps") else original_read(path, *args, **kwargs)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(Path, "read_text", read)
    monkeypatch.setattr(sysconfig, "get_config_var", lambda name: 1 if name == "Py_ENABLE_SHARED" else original_config(name))
    assert boundary.runtime_identity()["loaded_core_sha256"] == [hashlib.sha256(core.read_bytes()).hexdigest()]


def test_failed_outer_root_reports_actual_exit_and_traceback(tmp_path: Path) -> None:
    plugin, output = tmp_path / "bootstrap", tmp_path / "raw"
    write_bootstrap(plugin)
    output.mkdir()
    environment = dict(os.environ, PYTHONPATH=os.pathsep.join((str(plugin), str(ROOT / "src"), os.environ.get("PYTHONPATH", ""))),
                       SCIPLOT_PRIVATE_AUDIT_DIR=str(output), SCIPLOT_PRIVATE_AUDIT_ROOTS="[]")
    if ENVIRONMENT_KEY in environment:
        environment = rebind_bootstrap(environment, plugin)
    with pytest.raises(AssertionError) as error:
        execute_observed(tmp_path, [sys.executable, "-c", "pass"], environment, output, [], keep_public_guard=True)
    actual = error.value.args[0]
    assert actual["actual_outer_completion"]["exit_code"] == 1
    assert "ValueError" in actual["actual_outer_command_log"]
    assert "Audit roots must be absolute paths." in actual["actual_outer_command_log"]
    assert actual["actual_outer_state"]["child_pid"] > 0


@pytest.mark.parametrize("producer", ["test_sources_sha256", "qt_import_bindings"])
def test_metadata_owner_requires_the_actual_compiled_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, producer: str) -> None:
    archived = tmp_path / "tests/fixtures/rendering_profiles/generated/capture-runner.py"
    archived.parent.mkdir(parents=True)
    archived.write_text("# generated archived producer, never an experiment\n")
    owners, opened = [], Path.open
    def observed(path: Path, *args, **kwargs):
        if path == archived:
            owners.append(boundary.diagnostic_owner())
        return opened(path, *args, **kwargs)
    module = private_corpus_audit if producer == "test_sources_sha256" else evidence_runtime
    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", observed)
        getattr(module, producer)(tmp_path if module is private_corpus_audit else [tmp_path / "tests"])
    expected = boundary.owner_identity(Path(module.__file__).name, producer)
    assert owners and all(owner == expected for owner in owners)
    assert boundary.source_hashes()[Path(module.__file__).name] == expected["source_sha256"]
    assert boundary.diagnostic_owner() is None
    foreign = {}
    exec(compile(f"def {producer}():\n return probe()\n", module.__file__, "exec"),
         {"probe": boundary.diagnostic_owner}, foreign)
    assert foreign[producer]() is None
    _owner_derivation_controls(tmp_path, monkeypatch, Path(module.__file__).name, producer)


def _owner_derivation_controls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, filename: str, function: str) -> None:
    """The same compiled-owner controls also exercise hits and expiry, not just misses."""
    directory = tmp_path / "generated-owner"
    directory.mkdir()
    source = directory / filename
    original = f"def {function}():\n return probe()\n"
    changed = original.replace("probe()", "other()")
    assert len(original) == len(changed)
    source.write_text(original)
    timestamp = source.stat().st_mtime_ns
    compiled = compile(original, str(source), "exec", dont_inherit=True, optimize=sys.flags.optimize)
    namespace = {"probe": lambda: boundary.owned_caller(filename, function)}
    exec(compiled, namespace)
    actual = namespace[function]
    forged = FunctionType(actual.__code__.replace(co_consts=(*actual.__code__.co_consts, "foreign")), namespace)
    calls = []
    def counted(*args, **kwargs):
        calls.append(None)
        return compile(*args, **kwargs)
    with monkeypatch.context() as control:
        control.setattr(boundary, "__file__", str(directory / "private_process_boundaries.py"))
        control.setattr(boundary, "compile", counted, raising=False)
        with boundary.owner_derivation_scope():
            expected = boundary.owner_identity(filename, function)
            assert actual() == expected
            assert forged() is None  # A hit still hashes the actual live frame.
            assert boundary.owned_caller(filename, function) is None
            assert boundary.owner_identity(filename, "unknown") == {}
            assert len(calls) == 1
            returned = boundary.owner_identity(filename, function)
            returned["bytecode_sha256"] = "caller mutation"
            assert boundary.owner_identity(filename, function) == expected
            inherited = copy_context()
            with boundary.owner_derivation_scope():
                assert boundary.owner_identity(filename, function) == expected
                assert boundary.owner_identity(filename, function) == expected
            assert len(calls) == 2
            assert boundary.owner_identity(filename, function) == expected
            with ThreadPoolExecutor(max_workers=1) as executor:
                assert executor.submit(copy_context().run, boundary.owner_identity, filename, function).result() == expected
            assert len(calls) == 3  # A foreign thread cannot borrow this scope.
            with monkeypatch.context() as options:
                options.setattr(sys, "flags", SimpleNamespace(optimize=1))
                boundary.owner_identity(filename, function)
            assert len(calls) == 4
            assert boundary.owner_identity(filename, function) == expected
            opened = Path.open
            def denied(path, *args, **kwargs):
                if path == source:
                    raise PermissionError("generated source denial on a hit")
                return opened(path, *args, **kwargs)
            with monkeypatch.context() as refusal:
                refusal.setattr(Path, "open", denied)
                with pytest.raises(PermissionError, match="source denial"):
                    boundary.owner_identity(filename, function)
            source.write_text(changed)
            os.utime(source, ns=(timestamp, timestamp))
            assert source.stat().st_mtime_ns == timestamp
            different = boundary.owner_identity(filename, function)
            assert different != expected and actual() is None
            source.write_text(original)
            os.utime(source, ns=(timestamp, timestamp))
            assert boundary.owner_identity(filename, function) == expected
        count = len(calls)
        assert inherited.run(boundary.owner_identity, filename, function) == expected
        assert len(calls) == count + 1  # A copied context expires with the operation.
        with pytest.raises(RuntimeError, match="original failure"):
            with boundary.owner_derivation_scope():
                boundary.owner_identity(filename, function)
                raise RuntimeError("original failure")
        count = len(calls)
        assert boundary.owner_identity(filename, function) == expected
        assert len(calls) == count + 1
        with pytest.raises(ValueError, match="Source owner changed"):
            with boundary.owner_derivation_scope():
                boundary.owner_identity(filename, function)
                source.write_text(changed)  # No subsequent lookup may conceal exit drift.
                os.utime(source, ns=(timestamp, timestamp))
        assert boundary.owner_identity(filename, function) == different
        source.write_text(original)
        def wrong_qualname(*args, **kwargs):
            module = compile(*args, **kwargs)
            return module.replace(co_consts=tuple(value.replace(co_qualname="foreign")
                if isinstance(value, type(module)) and value.co_name == function else value for value in module.co_consts))
        with pytest.raises(ValueError, match="qualified name"):
            with boundary.owner_derivation_scope():
                boundary.owner_identity(filename, function)
                with monkeypatch.context() as invalid:
                    invalid.setattr(boundary, "compile", wrong_qualname)
                    boundary.owner_identity(filename, function)


def test_native_dependency_discovery_does_not_inherit_metadata_read_permission(monkeypatch: pytest.MonkeyPatch) -> None:
    class StopBeforeNativeDiscovery(Exception):
        pass
    def probe(environment):
        assert boundary.diagnostic_owner() is None
        raise StopBeforeNativeDiscovery
    with monkeypatch.context() as patch:
        patch.setattr(sys, "platform", "darwin")
        patch.setattr(evidence_runtime, "runtime_loader_environment", probe)
        with pytest.raises(StopBeforeNativeDiscovery):
            evidence_runtime.native_dependencies([], executable=Path(sys.executable), environment={})


@pytest.mark.parametrize("failure", [None, "actor", "context", "missing_record", "changed_bytes", "source", "bytecode", "function", "empty_owner", "missing_owner"])
def test_metadata_diagnostic_keeps_actor_receipt_and_current_byte_guards(tmp_path: Path, failure: str | None) -> None:
    archived = tmp_path / "capture-runner.py"
    archived.write_bytes(b"generated original producer bytes")
    owner = boundary.owner_identity("private_corpus_audit.py", "test_sources_sha256")
    frame = {"event": "open", "pid": os.getpid(), "resolved_path": str(archived), "diagnostic_owner": owner}
    context = {"records": {digest(str(archived)): {"sha256": hashlib.sha256(archived.read_bytes()).hexdigest()}}}
    actors = {os.getpid()}
    if failure == "actor":
        actors.clear()
    elif failure == "context":
        context = None
    elif failure == "missing_record":
        context["records"].clear()
    elif failure == "changed_bytes":
        archived.write_bytes(b"replaced after the receipt")
    elif failure in {"source", "bytecode"}:
        owner[f"{failure}_sha256"] = "0" * 64
    elif failure == "function":
        owner["function"] = "implementation_sources_sha256"
    elif failure == "empty_owner":
        owner.clear()
    elif failure == "missing_owner":
        frame.pop("diagnostic_owner")
    assert _diagnostic_bound(frame, context, actors) is (failure is None)
