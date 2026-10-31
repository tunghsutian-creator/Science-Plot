"""Generated producer/receipt controls; no private data or native rendering."""
from __future__ import annotations

from copy import deepcopy
import json
import os
import errno
import inspect
from pathlib import Path
import sys
from uuid import uuid4

import pytest

from sciplot_core.verification import private_corpus_audit as audit
from sciplot_core.verification.private_access import _fd_path, access_events, file_parent_open, open_facts
from sciplot_core.verification.private_observer import CHILD, CONTINUATION, PARENT, RUN, write_bootstrap
from private_observer_support import execute_observed

NODE = "tests/test_generated.py::test_source"
FILE = "tests/fixtures/real_world/generated/input.csv"
DEPENDENCIES = [(FILE, "file")]
# Producer values deliberately differ from the host's os masks.
CONSTANTS = {"platform": "generated-foreign", "O_RDONLY": 0, "O_ACCMODE": 3,
             "O_DIRECTORY": 16, "O_NOFOLLOW": 64, "O_CLOEXEC": 256}


def _capture(tmp_path: Path) -> tuple[dict, list[tuple[Path, Path]]]:
    root = tmp_path / "real_world"
    path = root / "generated"
    path.mkdir(parents=True)
    frame = {"epoch": "a" * 32, "sequence": 1, "sha256": "b" * 64,
             "event": "open", "path": str(path), "resolved_path": str(path),
             "nodeid": NODE + " (call)", "open_mode": None, "open_flags": 16 | 64 | 256}
    start = {"event": "process_start", "epoch": frame["epoch"], "open_constants": CONSTANTS}
    return {"frames": [start, frame], "diagnostic_observations": []}, [(root, Path("tests/fixtures/real_world"))]


@pytest.mark.parametrize("mutation", [
    "none", "without_cloexec", "ordinary_open", "listdir", "scandir", "child", "sibling",
    "higher_ancestor", "alias", "write", "create", "truncate", "append", "missing_nofollow",
    "missing_directory", "text_mode", "missing_constants", "missing_facts", "boolean_flags",
    "overlapping_constants", "unknown_constant", "directory_dependency",
])
def test_only_exact_declared_file_parent_directory_request_is_derived(tmp_path: Path, mutation: str) -> None:
    capture, aliases = _capture(tmp_path)
    event = access_events(capture, aliases)[0][0]
    dependencies = DEPENDENCIES
    if mutation == "without_cloexec":
        event["open"]["flags"] &= ~256
    elif mutation == "ordinary_open":
        event["open"]["flags"] = 0
    elif mutation in {"listdir", "scandir"}:
        event["event"] = "os." + mutation
    elif mutation in {"child", "sibling", "higher_ancestor"}:
        event["path"] = {"child": FILE, "sibling": FILE.replace("input.csv", "other.csv"),
                         "higher_ancestor": "tests/fixtures/real_world"}[mutation]
    elif mutation == "alias":
        event["open"]["raw"]["path"] += "-alias"
    elif mutation in {"write", "create", "truncate", "append"}:
        event["open"]["flags"] |= {"write": 1, "create": 512, "truncate": 1024, "append": 2048}[mutation]
    elif mutation in {"missing_nofollow", "missing_directory"}:
        event["open"]["flags"] &= ~({"missing_nofollow": 64, "missing_directory": 16}[mutation])
    elif mutation == "text_mode":
        event["open"]["mode"] = "r"
    elif mutation == "missing_constants":
        event["open"]["constants"] = None
    elif mutation == "missing_facts":
        event.pop("open")
    elif mutation == "boolean_flags":
        event["open"]["flags"] = True
    elif mutation == "overlapping_constants":
        event["open"]["constants"] = {**CONSTANTS, "O_NOFOLLOW": 16}
    elif mutation == "unknown_constant":
        event["open"]["constants"] = {**CONSTANTS, "O_DIRECTORY": None}
    elif mutation == "directory_dependency":
        dependencies = [(FILE, "directory")]
    assert file_parent_open(event, dependencies) is (mutation in {"none", "without_cloexec"})


def test_old_unknown_open_stays_unknown_and_projection_keeps_original_facts(tmp_path: Path) -> None:
    capture, aliases = _capture(tmp_path)
    original = deepcopy(capture)
    event = access_events(capture, aliases)[0][0]
    assert event["open"]["constants"] == CONSTANTS
    assert event["open"]["raw"]["sha256"] == "b" * 64
    assert capture == original
    for key in ("open_mode", "open_flags"):
        capture["frames"][1].pop(key)
    old_event = access_events(capture, aliases)[0][0]
    assert "open" not in old_event
    assert not file_parent_open(old_event, DEPENDENCIES)
    assert open_facts(("generated", None, 80)) == {"open_mode": None, "open_flags": 80}
    assert open_facts(("generated", None, True)) == {}
    assert open_facts(("generated",)) == {}


@pytest.mark.parametrize("mutation", ["none", "flags", "constants", "raw_origin", "role_boolean", "drop_facts"])
def test_normalized_role_cannot_replace_the_original_raw_open_facts(
    tmp_path: Path, mutation: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture, aliases = _capture(tmp_path)
    capture["capture_complete"] = True
    capture["issues"] = []
    proof = {"expected_root_scope": {"generated": "bound"}}
    events, collection = access_events(capture, aliases)
    event = events[0]
    if mutation == "flags":
        event["open"]["flags"] = 0
    elif mutation == "constants":
        event["open"]["constants"] = {**CONSTANTS, "O_NOFOLLOW": 128}
    elif mutation == "raw_origin":
        event["open"]["raw"]["sequence"] = 999
    elif mutation == "role_boolean":
        event["directory_handle"] = True
    elif mutation == "drop_facts":
        event.pop("open")
    monkeypatch.setattr(audit, "review_capture", lambda proof, *, expected_nodeids: capture)
    from sciplot_core.verification import private_process_boundaries as boundaries
    monkeypatch.setattr(boundaries, "root_scope", lambda roots: proof["expected_root_scope"])
    monkeypatch.setattr(audit, "local_reference_root", lambda *, repo_root: tmp_path)
    receipt = {"capture_proof": proof, "events": events, "collection_events": collection}
    if mutation == "none":
        audit._validate_supported_streams(receipt, repo_root=tmp_path, nodeids={NODE},
                                          fixture_roots={Path("tests/fixtures/real_world"): "real_world"})
    else:
        with pytest.raises(ValueError, match="differ from original raw streams"):
            audit._validate_supported_streams(receipt, repo_root=tmp_path, nodeids={NODE},
                                              fixture_roots={Path("tests/fixtures/real_world"): "real_world"})
    # The fake capture is a unit seam only. Raw topology/wait/source closure is
    # exercised by the existing actual generated private-corpus receipt controls.
    assert json.loads(json.dumps(capture))["frames"][1]["open_flags"] == 336


@pytest.mark.parametrize("kind", ["dup_directory", "reused_file", "invalid", "deleted_file", "pipe_read", "pipe_write", "named_fifo"])
def test_kernel_descriptor_path_is_fresh_and_nonfilesystem_is_not_a_file(tmp_path: Path, kind: str) -> None:
    source = tmp_path / "input.csv"
    source.write_bytes(b"generated source")
    descriptors = []
    try:
        if kind == "dup_directory":
            original = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
            descriptor = os.dup(original)
            descriptors.extend([original, descriptor])
            access = _fd_path(descriptor)
            assert access.path == tmp_path and access.issue is None
        elif kind == "reused_file":
            original = os.open(source, os.O_RDONLY)
            descriptor = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
            descriptors.extend([original, descriptor])
            access = _fd_path(descriptor)
            assert access.path == tmp_path and access.issue is None
            os.dup2(original, descriptor)
            access = _fd_path(descriptor)
            assert access.path == source and access.issue is None
        elif kind == "invalid":
            descriptor = os.open(source, os.O_RDONLY)
            os.close(descriptor)
            access = _fd_path(descriptor)
            assert access.path is None and access.issue == "invalid_descriptor"
        elif kind == "deleted_file":
            descriptor = os.open(source, os.O_RDONLY)
            descriptors.append(descriptor)
            source.unlink()
            access = _fd_path(descriptor)
            assert access.path is None and access.issue == "unknown_descriptor"
        elif kind in {"pipe_read", "pipe_write"}:
            read, write = os.pipe()
            descriptors.extend([read, write])
            access = _fd_path(read if kind == "pipe_read" else write)
            assert access.path is None and access.issue == "nonfilesystem_pipe"
        elif kind == "named_fifo":
            source.unlink()
            os.mkfifo(source)
            descriptor = os.open(source, os.O_RDONLY | os.O_NONBLOCK)
            descriptors.append(descriptor)
            access = _fd_path(descriptor)
            assert access.path == source and access.issue is None
    finally:
        for descriptor in descriptors:
            os.close(descriptor)


def test_open_port_keeps_signature_protocol_once_and_original_errno(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from sciplot_core.verification import private_access as port
    original = os.open
    calls = []
    conversions = []

    def forwarded(path, flags, mode=0o777, *, dir_fd=None):
        calls.append((path, flags, mode, dir_fd))
        return original(path, flags, mode, dir_fd=dir_fd)

    class Source:
        def __fspath__(self):
            conversions.append("path")
            return "input.csv"

    class Flags:
        def __index__(self):
            conversions.append("flags")
            return os.O_RDONLY

    source = tmp_path / "input.csv"
    source.write_bytes(b"generated source")
    parent = original(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        monkeypatch.setattr(os, "open", forwarded)
        monkeypatch.setattr(port, "_port_installed", False)
        port.install_open_port()
        assert inspect.signature(os.open) == inspect.signature(forwarded)
        descriptor = os.open(Source(), Flags(), 0o640, dir_fd=parent)
        try:
            assert os.read(descriptor, 100) == b"generated source"
        finally:
            os.close(descriptor)
        assert conversions == ["path", "flags"]
        assert calls == [("input.csv", os.O_RDONLY, 0o640, parent)]
        with pytest.raises(OSError) as missing:
            os.open("missing.csv", os.O_RDONLY, dir_fd=parent)
        assert missing.value.errno == errno.ENOENT
        with pytest.raises(OSError) as invalid:
            os.open("input.csv", os.O_RDONLY, dir_fd=-99999)
        assert invalid.value.errno == errno.EBADF
        with pytest.raises(TypeError):
            os.open("input.csv", os.O_RDONLY, 0o777, parent)
    finally:
        os.close(parent)


def _observed(tmp_path: Path, code: str) -> dict:
    plugin, output = tmp_path / "bootstrap", tmp_path / "raw"
    write_bootstrap(plugin)
    output.mkdir()
    watch = tmp_path / "watched"
    watch.mkdir()
    (watch / "input.csv").write_bytes(b"generated original source")
    environment = dict(os.environ)
    for key in (PARENT, CHILD, CONTINUATION, "PYTEST_CURRENT_TEST"):
        environment.pop(key, None)
    root = Path(__file__).resolve().parents[1]
    environment.update(PYTHONPATH=os.pathsep.join((str(plugin), str(root / "src"), environment.get("PYTHONPATH", ""))),
                       SCIPLOT_PRIVATE_AUDIT_DIR=str(output), SCIPLOT_PRIVATE_AUDIT_ROOTS=json.dumps([str(watch)]))
    environment[RUN] = uuid4().hex
    program = ("import os,sys,json,errno,posix\nfrom pathlib import Path\n"
               "from sciplot_core.verification.private_observer import current_observer\n"
               f"watch=Path({str(watch)!r})\nbase=Path({str(tmp_path)!r})\n"
               "current_observer().nodeid='synthetic:setup'\n" + code)
    _proof, result = execute_observed(tmp_path, [sys.executable, "-c", program], environment, output, [str(watch)])
    assert result["actual_returncode"] == 0, result["stdout"]
    return result


@pytest.mark.parametrize("attempt", [
    "dirfd_child", "int_file", "listdir_fd", "scandir_fd", "dup_directory", "reused_file",
    "named_fifo", "deleted_file", "cwd_sentinel", "nested_fspath", "nested_index",
    "saved_posix_fspath", "saved_posix_index", "normal_public", "normal_cwd", "pipe", "invalid_fd",
    "str_subclass", "bytes_subclass", "normal_pathlike", "normal_index",
    "listdir_cwd_sentinel", "scandir_cwd_sentinel",
])
def test_actual_public_guard_keeps_descriptor_and_nested_protocol_requests_exact(tmp_path: Path, attempt: str) -> None:
    operations = {
        "dirfd_child": "os.close(os.open('input.csv',os.O_RDONLY,dir_fd=privatefd))",
        "int_file": "open(filefd,'rb',closefd=False).close()",
        "listdir_fd": "os.listdir(privatefd)",
        "scandir_fd": "os.scandir(privatefd).close()",
        "dup_directory": "os.close(os.open('input.csv',os.O_RDONLY,dir_fd=duplicate))",
        "reused_file": "open(reused,'rb',closefd=False).close()",
        "named_fifo": "open(fifofd,'rb',closefd=False).close()",
        "deleted_file": "open(deletedfd,'rb',closefd=False).close()",
        "cwd_sentinel": "os.close(os.open('input.csv',os.O_RDONLY,dir_fd=(-2 if sys.platform=='darwin' else -100)))",
        "nested_fspath": "os.close(os.open(PathCallback(),os.O_RDONLY,dir_fd=publicfd))",
        "nested_index": "os.close(os.open('public.csv',FlagCallback(),dir_fd=publicfd))",
        "saved_posix_fspath": "os.close(os.open(SavedPathCallback(),os.O_RDONLY,dir_fd=publicfd))",
        "saved_posix_index": "os.close(os.open('public.csv',SavedFlagCallback(),dir_fd=publicfd))",
        "normal_public": "os.close(os.open('public.csv',os.O_RDONLY,dir_fd=publicfd))",
        "normal_cwd": "os.close(os.open('public/public.csv',os.O_RDONLY))",
        "pipe": "os.fdopen(os.dup(read),'rb').close();os.fdopen(os.dup(write),'wb').close()",
        "invalid_fd": "open(invalid,'rb',closefd=False).close()",
        "str_subclass": "os.close(os.open(HostileStr('public.csv'),os.O_RDONLY,dir_fd=publicfd))",
        "bytes_subclass": "os.close(os.open(HostileBytes(b'public.csv'),os.O_RDONLY,dir_fd=publicfd))",
        "normal_pathlike": "os.close(os.open(PlainPath(),os.O_RDONLY,dir_fd=publicfd))",
        "normal_index": "os.close(os.open('public.csv',PlainFlags(),dir_fd=publicfd))",
        "listdir_cwd_sentinel": "os.listdir(-1)",
        "scandir_cwd_sentinel": "os.scandir(-1).close()",
    }
    setup = ("public=base/'public';public.mkdir();(public/'public.csv').write_bytes(b'generated public')\n"
             "privatefd=os.open(watch,os.O_RDONLY|os.O_DIRECTORY);publicfd=os.open(public,os.O_RDONLY|os.O_DIRECTORY)\n"
             "filefd=os.open(watch/'input.csv',os.O_RDONLY);duplicate=os.dup(privatefd)\n"
             "reused=os.open(public/'public.csv',os.O_RDONLY);os.dup2(filefd,reused)\n"
             "os.mkfifo(watch/'fifo');fifofd=os.open(watch/'fifo',os.O_RDONLY|os.O_NONBLOCK)\n"
             "(watch/'deleted').write_bytes(b'generated deleted');deletedfd=os.open(watch/'deleted',os.O_RDONLY);(watch/'deleted').unlink()\n"
             "read,write=os.pipe()\n"
             "class PathCallback:\n def __fspath__(self):\n  open('input.csv','rb').close()\n  return 'public.csv'\n"
             "class FlagCallback:\n def __index__(self):\n  open('input.csv','rb').close()\n  return os.O_RDONLY\n"
             "class SavedPathCallback:\n def __fspath__(self):\n  os.close(posix.open('input.csv',os.O_RDONLY))\n  return 'public.csv'\n"
             "class SavedFlagCallback:\n def __index__(self):\n  os.close(posix.open('input.csv',os.O_RDONLY))\n  return os.O_RDONLY\n"
             "class HostileStr(str):\n def __eq__(self,other):\n  open('input.csv','rb').close()\n  return super().__eq__(other)\n def __str__(self): raise AssertionError('str callback')\n"
             "class HostileBytes(bytes):\n def decode(self,*args): raise AssertionError('decode callback')\n def __bytes__(self): raise AssertionError('bytes callback')\n"
             "class PlainPath:\n def __fspath__(self): return HostileStr('public.csv')\n"
             "class PlainFlags:\n def __index__(self): return os.O_RDONLY\n"
             "from sciplot_core.verification.public_input_guard import install,ENVIRONMENT_KEY\n"
             "os.environ[ENVIRONMENT_KEY]=json.dumps([str(watch)]);install()\n"
             "invalid=os.open(public/'public.csv',os.O_RDONLY);os.close(invalid)\n"
             f"current_observer().nodeid={NODE!r}\n"
             + ("os.chdir(watch)\n" if attempt in {"cwd_sentinel", "nested_fspath", "nested_index", "saved_posix_fspath", "saved_posix_index", "listdir_cwd_sentinel", "scandir_cwd_sentinel"} else "os.chdir(base)\n"))
    success = attempt in {"normal_public", "normal_cwd", "pipe", "str_subclass", "bytes_subclass", "normal_pathlike", "normal_index"}
    program = setup + "try:\n " + operations[attempt] + "\n"
    if attempt == "invalid_fd":
        program += "except OSError as exc:\n assert exc.errno==errno.EBADF\nelse: raise AssertionError('invalid FD succeeded')\n"
    elif success:
        program += "except PermissionError: raise AssertionError('valid public request was denied')\n"
    else:
        program += "except PermissionError: pass\nelse: raise AssertionError('private or unresolved request was allowed')\n"
    result = _observed(tmp_path, program)
    unknown = attempt in {"deleted_file", "saved_posix_fspath", "saved_posix_index"}
    assert result["capture_complete"] is (not unknown), result["issues"]
    frames = [frame for frame in result["frames"] if frame["nodeid"] == NODE]
    if attempt == "pipe":
        assert sum(frame["event"] == "nonfilesystem_descriptor" for frame in frames) == 2
        assert not any(frame["event"] == "open" for frame in frames)
    if attempt in {"dirfd_child", "dup_directory", "int_file", "reused_file", "cwd_sentinel", "nested_fspath", "nested_index"}:
        assert any(frame["event"] == "open" and frame["resolved_path"] == str(tmp_path / "watched/input.csv") for frame in frames)


@pytest.mark.parametrize("state", ["valid", "changed", "missing", "alias"])
def test_actual_source_verifier_still_checks_original_bytes_through_directory_fd(tmp_path: Path, state: str) -> None:
    import hashlib
    expected = hashlib.sha256(b"generated original source").hexdigest()
    code = ("from sciplot_core.project_store.commands import verify_sources\n"
            "from sciplot_core.project_store.errors import ProjectConflict\n"
            "from sciplot_core.project_store.io import StoreIO\n"
            "class EmptyMetadata(StoreIO):\n def read(self,name):\n  assert name=='local_sources.json'\n  return super().read(name)\n"
            "metadata_root=base/'metadata';metadata_root.mkdir()\n"
            "metadata=EmptyMetadata(metadata_root,{})\n"
            "source=watch/'input.csv'\n")
    if state == "changed":
        code += "source.write_bytes(b'changed generated source')\n"
    elif state == "missing":
        code += "source.unlink()\n"
    elif state == "alias":
        code += "(watch/'alias').symlink_to(watch,target_is_directory=True);source=watch/'alias/input.csv'\n"
    code += (f"current_observer().nodeid={NODE!r}\n"
             f"sources={{'generated':{{{expected!r}:{{'locator':str(source),'sha256':{expected!r}}}}}}}\n"
             "with metadata.locked() as owned:\n"
             " try: verify_sources(owned,sources)\n")
    code += (" except ProjectConflict: raise AssertionError('valid original rejected')\n" if state == "valid" else
             " except ProjectConflict: pass\n else: raise AssertionError('source guard bypassed')\n")
    result = _observed(tmp_path, code)
    assert result["capture_complete"], result["issues"]
    if state == "valid":
        events = [row for row in access_events(result, [(tmp_path / "watched", Path("tests/fixtures/real_world/generated"))])[0]
                  if row["nodeid"] == NODE]
        assert any(file_parent_open(row, DEPENDENCIES) for row in events)
        assert any(row["path"] == FILE and row["event"] == "open" for row in events)


def test_actual_temporaryfile_write_seek_read_close_keeps_original_requests(tmp_path: Path) -> None:
    result = _observed(tmp_path,
        "import tempfile,stat\n"
        "from sciplot_core.verification.public_input_guard import install,ENVIRONMENT_KEY\n"
        "from sciplot_core.verification.private_access import _fd_path\n"
        "os.environ[ENVIRONMENT_KEY]=json.dumps([str(watch)]);install()\n"
        f"current_observer().nodeid={NODE!r}\n"
        "with tempfile.TemporaryFile(dir=base) as stderr:\n"
        " info=os.fstat(stderr.fileno())\n"
        " assert stat.S_ISREG(info.st_mode) and info.st_nlink==0\n"
        " stderr.write(b'generated stderr');stderr.seek(0);assert stderr.read()==b'generated stderr'\n"
        " print(json.dumps({'temporaryfile_regular':True,'nlink':info.st_nlink,'name_is_fd':isinstance(stderr.name,int),'descriptor_path_issue':_fd_path(stderr.fileno()).issue}))\n")
    assert result["capture_complete"], result["issues"]
    facts = json.loads(result["stdout"].splitlines()[-1])
    assert facts == {"temporaryfile_regular": True, "nlink": 0, "name_is_fd": True,
                     "descriptor_path_issue": "unknown_descriptor"}
    # CPython audits the named creation before its opener unlinks it; these
    # buffered operations add no open(int) request. Unknown preopened deleted
    # regular files remain refused by the separate actual FD-open controls.
    assert not any(frame["event"] == "sensor_failure" and frame["nodeid"] == NODE for frame in result["frames"])


def test_actual_socketpair_keeps_ipc_distinct_from_filesystem_access(tmp_path: Path) -> None:
    result = _observed(tmp_path,
        "import socket\n"
        "from sciplot_core.verification.public_input_guard import install,ENVIRONMENT_KEY\n"
        "from sciplot_core.verification.private_access import _fd_path\n"
        "os.environ[ENVIRONMENT_KEY]=json.dumps([str(watch)]);install()\n"
        f"current_observer().nodeid={NODE!r}\n"
        "left,right=socket.socketpair()\n"
        "try:\n"
        " access=_fd_path(left.fileno())\n"
        " assert access.path is None and access.issue=='nonfilesystem_socket'\n"
        " left.sendall(b'generated IPC')\n"
        " with os.fdopen(os.dup(right.fileno()),'rb') as incoming:\n"
        "  assert incoming.read(13)==b'generated IPC'\n"
        "finally:\n"
        " left.close();right.close()\n")
    assert result["capture_complete"], result["issues"]
    frames = [frame for frame in result["frames"] if frame["nodeid"] == NODE]
    assert sum(frame["event"] == "nonfilesystem_descriptor"
               and frame["descriptor_kind"] == "socket" for frame in frames) == 1
    assert not any(frame["event"] in {"open", "sensor_failure"} for frame in frames)


def test_each_integer_fd_consumer_resolves_once_and_keeps_both_live_identity_checks(tmp_path: Path) -> None:
    result = _observed(tmp_path,
        "from sciplot_core.verification.public_input_guard import install,ENVIRONMENT_KEY\n"
        "source=watch/'input.csv';descriptor=os.open(source,os.O_RDONLY)\n"
        "os.environ[ENVIRONMENT_KEY]=json.dumps([str(watch)]);install()\n"
        "actual_resolve=Path.resolve;actual_fstat=os.fstat;counts={'resolve':0,'fstat':0}\n"
        "def resolve(path,strict=False):\n"
        " if path==source: counts['resolve']+=1\n"
        " return actual_resolve(path,strict=strict)\n"
        "def fstat(fd):\n"
        " if fd==descriptor: counts['fstat']+=1\n"
        " return actual_fstat(fd)\n"
        "Path.resolve=resolve;os.fstat=fstat\n"
        f"current_observer().nodeid={NODE!r}\n"
        "try:\n"
        " try: open(descriptor,'rb',closefd=False).close()\n"
        " except PermissionError: pass\n"
        " else: raise AssertionError('private FD was allowed')\n"
        "finally:\n"
        " Path.resolve=actual_resolve;os.fstat=actual_fstat;os.close(descriptor)\n"
        "print(json.dumps(counts))\n")
    assert result["capture_complete"], result["issues"]
    # Each audit consumer still performs the complete live-FD proof. Neither
    # resolves its own same-request canonical fact again or caches for the other.
    assert json.loads(result["stdout"].splitlines()[-1]) == {"resolve": 2, "fstat": 4}


def test_public_directory_fd_still_resolves_the_final_private_child_alias(tmp_path: Path) -> None:
    result = _observed(tmp_path,
        "from sciplot_core.verification.public_input_guard import install,ENVIRONMENT_KEY\n"
        "public=base/'public';public.mkdir();alias=public/'alias.csv';alias.symlink_to(watch/'input.csv')\n"
        "directory=os.open(public,os.O_RDONLY|os.O_DIRECTORY)\n"
        "os.environ[ENVIRONMENT_KEY]=json.dumps([str(watch)]);install()\n"
        "actual=Path.resolve;counts={'child_resolve':0}\n"
        "def resolve(path,strict=False):\n"
        " if path==alias: counts['child_resolve']+=1\n"
        " return actual(path,strict=strict)\n"
        "Path.resolve=resolve\n"
        f"current_observer().nodeid={NODE!r}\n"
        "try:\n"
        " try: os.close(os.open('alias.csv',os.O_RDONLY,dir_fd=directory))\n"
        " except PermissionError: pass\n"
        " else: raise AssertionError('public base granted private child alias')\n"
        "finally:\n"
        " Path.resolve=actual;os.close(directory)\n"
        "print(json.dumps(counts))\n")
    assert result["capture_complete"], result["issues"]
    assert json.loads(result["stdout"].splitlines()[-1]) == {"child_resolve": 2}
    assert any(frame["event"] == "open" and frame.get("path") == str(tmp_path / "public/alias.csv")
               and frame["resolved_path"] == str(tmp_path / "watched/input.csv") for frame in result["frames"])


@pytest.mark.parametrize("change", ["rename", "dup_rename", "reuse"])
def test_next_integer_fd_request_rechecks_namespace_and_reuse(tmp_path: Path, change: str) -> None:
    setup = ("from sciplot_core.verification.public_input_guard import install,ENVIRONMENT_KEY\n"
             "public=base/'public.csv';public.write_bytes(b'generated public')\n"
             "descriptor=os.open(public,os.O_RDONLY);private=os.open(watch/'input.csv',os.O_RDONLY)\n")
    if change == "dup_rename":
        setup += "original=descriptor;descriptor=os.dup(original);os.close(original)\n"
    setup += ("os.environ[ENVIRONMENT_KEY]=json.dumps([str(watch)]);install()\n"
              f"current_observer().nodeid={NODE!r}\n"
              "with open(descriptor,'rb',closefd=False) as first: assert first.read()==b'generated public'\n")
    setup += "os.dup2(private,descriptor)\n" if change == "reuse" else "public.rename(watch/'moved.csv')\n"
    result = _observed(tmp_path, setup +
        "try:\n"
        " try: open(descriptor,'rb',closefd=False).close()\n"
        " except PermissionError: pass\n"
        " else: raise AssertionError('earlier public FD fact escaped into the next request')\n"
        "finally:\n"
        " os.close(descriptor);os.close(private)\n")
    assert result["capture_complete"], result["issues"]
    expected = "input.csv" if change == "reuse" else "moved.csv"
    assert any(frame["event"] == "open" and frame.get("resolved_path") == str(tmp_path / "watched" / expected)
               and frame["nodeid"] == NODE for frame in result["frames"])


@pytest.mark.parametrize("change", ["path_alias", "fd_reuse"])
def test_canonical_fact_is_not_issued_after_same_request_identity_drift(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str) -> None:
    source, other = tmp_path / "source", tmp_path / "other"
    source.write_bytes(b"generated source")
    other.write_bytes(b"other generated source")
    descriptor, replacement = os.open(source, os.O_RDONLY), os.open(other, os.O_RDONLY)
    original = Path.resolve
    mutated = False

    def resolve(path, strict=False):
        nonlocal mutated
        value = original(path, strict=strict)
        if path == source and not mutated:
            mutated = True
            if change == "path_alias":
                source.rename(tmp_path / "moved")
                source.symlink_to(other)
            else:
                os.dup2(replacement, descriptor)
        return value

    try:
        monkeypatch.setattr(Path, "resolve", resolve)
        access = _fd_path(descriptor)
        assert mutated
        assert access.path is None and access.issue == "unknown_descriptor"
        assert access._canonical_path is None
    finally:
        os.close(descriptor)
        os.close(replacement)


def test_caller_payload_cannot_supply_a_canonical_fact(tmp_path: Path) -> None:
    from sciplot_core.verification.private_access import ResolvedAccess, access_path
    supplied = {"path": str(tmp_path / "private"), "canonical_path": str(tmp_path / "public")}
    parsed = access_path("open", (supplied, "r", os.O_RDONLY))
    assert parsed.path is None and parsed._canonical_path is None
    parsed = access_path("open", (ResolvedAccess(tmp_path / "private", _canonical_path=tmp_path / "public"), "r", os.O_RDONLY))
    assert parsed.path is None and parsed._canonical_path is None
