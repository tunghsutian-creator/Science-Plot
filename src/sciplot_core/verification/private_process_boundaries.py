"""Finite process input and source-owner identities for private observation."""
from __future__ import annotations

import hashlib
import ctypes
import inspect
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import sysconfig
from types import CodeType
from typing import Any, Mapping

_PLATFORM_SOURCE = Path(sysconfig.get_path("stdlib")) / "platform.py"
ZERO = "0" * 64


def frame_digest(value: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def source_hashes() -> dict[str, str]:
    names = ["private_observer.py", "private_observer_pytest.py", "private_capture.py", "private_process_boundaries.py",
             "suite_evidence.py", "evidence_scope.py", "durable_runner.py", "evidence_identity.py", "private_corpus.py", "private_corpus_audit.py",
             "native_probe_boundary.py", "evidence_runtime.py", "evidence_environment.py",
             "process_private_exclusion.py", "process_private_launch.py", "private_exclusion_boundary.py", "private_audit_runtime.py", "private_socket_ports.py",
             "private_native_exit_port.py", "native_exit_boundary.py",
             "../plot_protocol/socket_client.py", "../plot_protocol/paths.py", "../plot_protocol/server.py",
             "input_scope.py", "input_scope_manifest.json"]
    public = Path(__file__).parent / "public_guard_bootstrap/sitecustomize.py"
    if public.is_file():
        names.append("public_guard_bootstrap/sitecustomize.py")
    result = {name: hashlib.sha256((Path(__file__).parent / name).read_bytes()).hexdigest() for name in names}
    result["repository:skill/scripts/sciplot"] = hashlib.sha256((Path(__file__).parents[3] / "skill/scripts/sciplot").read_bytes()).hexdigest()
    return result


def runtime_loader_environment(environment: Mapping[str, str]) -> dict[str, str]:
    """The existing reviewed loader override; never restore unknown loaders."""
    if any(environment.get(key) for key in environment
           if key.startswith(("DYLD_", "LD_")) and key != "DYLD_FRAMEWORK_PATH"):
        raise ValueError("native loader overrides have no reviewed closure policy")
    return {"DYLD_FRAMEWORK_PATH": environment["DYLD_FRAMEWORK_PATH"]} if "DYLD_FRAMEWORK_PATH" in environment else {}


def forbidden_roots(root: Path, environment: dict[str, str] | None = None) -> list[Path]:
    values = os.environ if environment is None else environment
    raw = Path(values.get("SCIPLOT_REFERENCE_DATA", str(root / ".local/reference_data"))).expanduser()
    if not raw.is_absolute():
        raw = root / raw
    paths = [root / "tests/fixtures" / name for name in
             ("real_world", "polymer_corpus", "archived_output_raw_data", "rendering_profiles")]
    paths.extend(raw / name for name in ("real_world", "polymer_corpus", "archived_sources"))
    # Keep lexical aliases too: a forbidden symlink must not escape the guard.
    return list(dict.fromkeys([*paths, *(path.resolve() for path in paths)]))


def _linux_core_hashes(addresses: list[int], mappings: str) -> list[str]:
    """Hash the actual executable mapping owning the finite CPython C APIs."""
    if len(addresses) != 3 or any(type(address) is not int or address <= 0 for address in addresses):
        raise ValueError("Three actual CPython API addresses are required.")
    owners = []
    for address in addresses:
        matches = []
        for line in mappings.splitlines():
            fields = line.split(maxsplit=5)
            if len(fields) < 5:
                raise ValueError("Actual CPython mapping fields are malformed.")
            start, end = (int(value, 16) for value in fields[0].split("-"))
            if start <= address < end:
                matches.append(fields)
        if len(matches) != 1:
            raise ValueError("CPython API address has no unique actual mapping.")
        fields = matches[0]
        if (len(fields) != 6 or "x" not in fields[1] or not fields[5].startswith("/")
                or fields[5].endswith(" (deleted)")):
            raise ValueError("CPython API mapping is not an executable backed file.")
        major, minor = (int(value, 16) for value in fields[3].split(":"))
        owners.append((Path(fields[5]).resolve(strict=True), major, minor, int(fields[4])))
    if len(addresses) != 3 or len(set(owners)) != 1:
        raise ValueError("Finite CPython APIs do not share one actual core mapping.")
    path, major, minor, inode = owners[0]
    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        if (not stat.S_ISREG(before.st_mode) or os.major(before.st_dev) != major
                or os.minor(before.st_dev) != minor or before.st_ino != inode):
            raise ValueError("CPython mapped device/inode differs from its actual open file.")
        content = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            content.update(chunk)
        after, current = os.fstat(stream.fileno()), path.stat()
    stable = ("st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns", "st_ctime_ns")
    if any(getattr(before, key) != getattr(after, key) or getattr(before, key) != getattr(current, key)
           for key in stable):
        raise ValueError("CPython mapped core changed while hashing actual bytes.")
    return [content.hexdigest()]


def runtime_identity() -> dict[str, Any]:
    """Bind the loaded CPython core and the finite observation stdlib owners."""
    core_hashes: list[str | None] = []
    if sys.platform == "darwin":
        cores: set[Path] = set()
        loader = ctypes.CDLL(None)
        count, name = loader._dyld_image_count, loader._dyld_get_image_name
        count.restype, name.restype = ctypes.c_uint32, ctypes.c_char_p
        name.argtypes = [ctypes.c_uint32]
        for index in range(count()):
            value = name(index)
            if isinstance(value, bytes):
                path = Path(os.fsdecode(value))
                if path.name == "Python" and "Python.framework" in str(path):
                    cores.add(path.resolve(strict=True))
        if not cores and not sysconfig.get_config_var("Py_ENABLE_SHARED"):
            cores.add(Path(sys.executable).resolve(strict=True))
        core_hashes.extend(executable_hash(path) for path in cores)
    elif sys.platform.startswith("linux"):
        addresses = [ctypes.cast(getattr(ctypes.pythonapi, name), ctypes.c_void_p).value
                     for name in ("Py_GetVersion", "PyObject_Call", "PyErr_Occurred")]
        if any(address is None for address in addresses):
            raise ValueError("Actual CPython API addresses are unavailable.")
        core_hashes.extend(_linux_core_hashes([int(address) for address in addresses if address is not None],
                                              Path("/proc/self/maps").read_text()))
    elif not sysconfig.get_config_var("Py_ENABLE_SHARED"):
        core_hashes.append(executable_hash(Path(sys.executable).resolve(strict=True)))
    if not core_hashes:
        raise ValueError("Actual loaded CPython core is unavailable for observation binding.")
    stdlib = Path(sysconfig.get_path("stdlib"))
    sources = {name: executable_hash(stdlib / name) for name in ("os.py", "subprocess.py", "threading.py", "platform.py")}
    if any(value is None for value in [*core_hashes, *sources.values()]):
        raise ValueError("Python observation runtime bytes are unreadable.")
    return {"python_version": sys.version, "implementation": sys.implementation.name,
            "cache_tag": sys.implementation.cache_tag,
            "loaded_core_sha256": sorted(str(value) for value in core_hashes),
            "stdlib_sources_sha256": sources}


def root_scope(roots: list[str]) -> dict[str, list[str]]:
    if not roots or not all(isinstance(name, str) and Path(name).is_absolute() for name in roots):
        raise ValueError("Audit roots must be nonempty absolute paths.")
    return {"lexical": sorted({os.path.abspath(name) for name in roots}),
            "canonical": sorted({str(Path(name).resolve()) for name in roots})}


def watch_roots(repo: Path, environment: dict[str, str]) -> list[str]:
    raw = Path(environment.get("SCIPLOT_REFERENCE_DATA", str(repo / ".local/reference_data"))).expanduser()
    raw = raw if raw.is_absolute() else repo / raw
    return [str((repo / "tests/fixtures").absolute()), str(raw.absolute())]


def _platform_code() -> CodeType:
    module = compile(_PLATFORM_SOURCE.read_bytes(), str(_PLATFORM_SOURCE), "exec",
                     dont_inherit=True, optimize=sys.flags.optimize)
    owner = next(c for c in module.co_consts if isinstance(c, CodeType) and c.co_name == "_Processor")
    return next(c for c in owner.co_consts if isinstance(c, CodeType) and c.co_name == "from_subprocess")


def _code_hash(code: CodeType) -> str:
    # Relocated official Python pycs retain their original installation filename.
    # Marshal encodes shared/interned object references differently between a
    # loaded pyc and fresh compile; freeze the complete code fields directly.
    def constant(value: Any) -> str:
        if isinstance(value, CodeType):
            return "code:" + _code_hash(value)
        if isinstance(value, tuple):
            return "tuple:" + repr(tuple(constant(item) for item in value))
        if isinstance(value, frozenset):
            return "frozenset:" + repr(sorted(constant(item) for item in value))
        return type(value).__name__ + ":" + repr(value)

    fields = (code.co_code.hex(), tuple(constant(value) for value in code.co_consts), code.co_names, code.co_varnames,
              code.co_freevars, code.co_cellvars, code.co_argcount, code.co_posonlyargcount,
              code.co_kwonlyargcount, code.co_flags, code.co_stacksize, code.co_nlocals,
              code.co_firstlineno, code.co_linetable.hex(), code.co_exceptiontable.hex(), code.co_qualname)
    return hashlib.sha256(repr(fields).encode()).hexdigest()

def executable_hash(file: str | bytes | os.PathLike[Any], *, cwd: str | None = None,
                    environment: dict[str, str] | None = None) -> str | None:
    name = os.fsdecode(file)
    if os.path.dirname(name):
        path = Path(name)
        path = path if path.is_absolute() else Path(cwd or os.getcwd()) / path
    else:
        found = shutil.which(name, path=(environment or os.environ).get("PATH"))
        if found is None:
            return None
        path = Path(found)
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def uname_boundary() -> dict[str, str]:
    return {"kind": "stdlib_platform_uname_p", "platform_source_sha256": str(executable_hash(_PLATFORM_SOURCE)),
            "caller_bytecode_sha256": _code_hash(_platform_code()),
            "executable_sha256": str(executable_hash("/usr/bin/uname"))}


def uname_call(bound: inspect.BoundArguments, target_hash: str | None) -> dict[str, str] | None:
    if (bound.arguments.get("args") != ["uname", "-p"]
            or any(bound.arguments.get(key) for key in ("shell", "executable", "cwd", "preexec_fn", "pass_fds",
                                                       "env", "start_new_session", "process_group"))
            or bound.arguments.get("stdin") is not None or bound.arguments.get("stdout") != -1
            or bound.arguments.get("stderr") != -3 or bound.arguments.get("text") is not True
            or bound.arguments.get("encoding") != "utf8"
            or bound.arguments.get("errors") is not None
            or target_hash != uname_boundary().get("executable_sha256")):
        return None
    expected = _code_hash(_platform_code())
    frame = inspect.currentframe()
    try:
        while frame is not None:
            if (Path(frame.f_code.co_filename).name == "platform.py"
                    and frame.f_code.co_name == "from_subprocess" and _code_hash(frame.f_code) == expected):
                return uname_boundary()
            frame = frame.f_back
    finally:
        del frame
    return None


def wrapper_boundary() -> dict[str, str]:
    return {"kind": "owned_sciplot_python_exec",
            "wrapper_sha256": str(executable_hash(Path(__file__).parents[3] / "skill/scripts/sciplot")),
            "shell_sha256": str(executable_hash("/bin/bash")),
            "env_executable_sha256": str(executable_hash("/usr/bin/env")),
            "expected_python_sha256": str(executable_hash(sys.executable))}


_WRAPPER_HELPERS = {"bash": "/bin/bash", "dirname": "/usr/bin/dirname", "uname": "/usr/bin/uname",
                    "otool": "/usr/bin/otool", "awk": "/usr/bin/awk", "realpath": "/bin/realpath", "mkdir": "/bin/mkdir"}


def wrapper_inputs(environment: dict[str, str]) -> dict[str, Any]:
    root = Path(__file__).parents[3]
    runtime = Path(environment.get("SCIPLOT_RUNTIME_REPO", str(root))).resolve()
    veusz = Path(environment.get("SCIPLOT_VEUSZ_ROOT", str(runtime / "third_party/veusz"))).resolve()
    output = Path(environment.get("MPLCONFIGDIR", str(Path(environment.get("TMPDIR", "/tmp")) / "sciplot-mpl")))
    if not output.is_absolute():
        raise ValueError("Relative wrapper configuration output has no fixed input boundary.")
    return {"runtime_root_sha256": hashlib.sha256(str(runtime).encode()).hexdigest(),
            "veusz_root_sha256": hashlib.sha256(str(veusz).encode()).hexdigest(),
            "configuration_output_sha256": hashlib.sha256(str(output.resolve()).encode()).hexdigest(),
            "helpers_sha256": {name: executable_hash(path) for name, path in _WRAPPER_HELPERS.items()},
            "qtloops_sha256": {hashlib.sha256(str(path.resolve()).encode()).hexdigest(): executable_hash(path)
                               for path in sorted((veusz / "veusz/helpers").glob("qtloops*.so")) if path.is_file()}}


def _wrapper_path_bound(environment: dict[str, str]) -> bool:
    for name, expected in _WRAPPER_HELPERS.items():
        actual = shutil.which(name, path=environment.get("PATH", os.defpath))
        if Path(expected).is_file():
            if actual is None or Path(actual).resolve() != Path(expected).resolve():
                return False
        elif actual is not None:
            return False
    return True


def wrapper_call(bound: inspect.BoundArguments, environment: dict[str, str],
                 baseline: dict[str, str]) -> dict[str, str] | None:
    root = Path(__file__).parents[3]
    command = bound.arguments.get("args")
    cwd = bound.arguments.get("cwd")
    if (not isinstance(command, (list, tuple)) or not command
            or any(bound.arguments.get(key) for key in ("shell", "executable", "preexec_fn"))
            or (cwd is not None and (Path(cwd).absolute() != root or Path(cwd).resolve() != root))
            or not isinstance(command[0], (str, bytes, os.PathLike))
            or Path(os.fsdecode(command[0])).resolve() != root / "skill/scripts/sciplot"
            or any(environment.get(key) for key in ("BASH_ENV", "ENV", "SHELLOPTS", "BASHOPTS", "PS4", "IFS", "CDPATH",
                                                      "GLOBIGNORE", "DEVELOPER_DIR", "SDKROOT", "TOOLCHAINS"))
            or any(key.startswith("BASH_") for key in environment)
            or any(environment.get(key) for key in environment if key.startswith(("DYLD_", "LD_")) and key != "DYLD_FRAMEWORK_PATH")
            or any(environment.get(key) for key in ("PYTHONHOME", "PYTHONUSERBASE"))
            or environment.get("DYLD_FRAMEWORK_PATH", "") != baseline.get("DYLD_FRAMEWORK_PATH", "")
            or any(environment.get(key, "") != baseline.get(key, "") for key in ("LANG", "LC_ALL", "LC_COLLATE"))
            or not _wrapper_path_bound(environment)):
        return None
    selected = environment.get("SCIPLOT_PYTHON", str(Path(environment.get("SCIPLOT_RUNTIME_REPO", str(root))) / ".venv/bin/python"))
    selected_path = selected if os.path.dirname(selected) else shutil.which(selected, path=environment.get("PATH", os.defpath))
    if (Path(environment.get("SCIPLOT_REPO", str(root))).resolve() != root
            or Path(environment.get("SCIPLOT_SOURCE_ROOT", str(root / "src"))).resolve() != root / "src"
            or executable_hash(selected, environment=environment) != executable_hash(sys.executable)
            or selected_path is None or not os.access(selected_path, os.X_OK)
            or Path(selected_path).resolve() != Path(sys.executable).resolve()
            or executable_hash("bash", environment=environment) != executable_hash("/bin/bash")
            or wrapper_inputs(environment) != wrapper_inputs(baseline)):
        return None
    return wrapper_boundary()


_OWNERS = {"evidence_runtime.py": {"native_dependencies", "qt_import_bindings"}, "suite_evidence.py": {"_audit_environment"}, "durable_runner.py": {"start_run"},
           "private_audit_runtime.py": {"start_node", "reserve_socket_fixture"}, "socket_client.py": {"ensure_server"},
           "server.py": {"serve"}, "private_native_exit_port.py": {"_Port.discover"},
           "evidence_scope.py": {"_repository_inputs"},
           "private_exclusion_boundary.py": {"begin_phase"},
           "process_private_exclusion.py": {"_members", "_ancestors", "_metadata", "_evidence_inodes"},
           "evidence_identity.py": {"_stable_file", "_members"},
           "private_corpus.py": {"_readable_nonempty_file", "_listed_source_issues", "_case_dependencies"},
           "private_corpus_audit.py": {"test_sources_sha256"}}


def owner_identity(filename: str, function: str) -> dict[str, str]:
    if function not in _OWNERS.get(filename, set()):
        return {}
    path = (Path(__file__).parents[1] / "plot_protocol" / filename
            if filename in {"socket_client.py", "server.py"} else Path(__file__).with_name(filename))
    source = path.read_bytes()
    module = compile(source, str(path), "exec", dont_inherit=True, optimize=sys.flags.optimize)
    code = module
    for part in function.split("."):
        code = next(c for c in code.co_consts if isinstance(c, CodeType) and c.co_name == part)
    if code.co_qualname != function:
        raise ValueError("Source owner qualified name differs.")
    return {"owner": filename, "function": function, "source_sha256": hashlib.sha256(source).hexdigest(),
            "bytecode_sha256": _code_hash(code)}


def owned_caller(filename: str, function: str) -> dict[str, str] | None:
    frame = inspect.currentframe()
    path = (Path(__file__).parents[1] / "plot_protocol" / filename
            if filename in {"socket_client.py", "server.py"} else Path(__file__).with_name(filename))
    try:
        while frame is not None:
            if frame.f_code.co_qualname == function and Path(frame.f_code.co_filename).resolve() == path.resolve():
                identity = owner_identity(filename, function)
                if _code_hash(frame.f_code) == identity.get("bytecode_sha256"):
                    return identity
            frame = frame.f_back
    finally:
        del frame
    return None


def live_native_request(observer: Any, request: dict[str, Any], recorded: dict[str, Any] | None,
                        *, primary: int, node: str) -> bool:
    """Admit a just-written internal source fact, never a queued declaration.

    A queue has no live frame and retains complete historical admission. An
    alleged live frame must come from the actual discover call and its successful
    synchronous writer. Full capture still validates every source/chain/exit.
    """
    if recorded is None:
        return False
    try:
        caller = owned_caller('private_native_exit_port.py', '_Port.discover')
        valid = (caller is not None and caller == request['actor']['owner']
            and recorded['event'] == 'native_registration_request'
            and recorded['request'] is request
            and recorded['epoch'] == request['epoch'] == observer.epoch
            and recorded['pid'] == primary == os.getpid()
            and recorded['test_nodeid'] == node
            and type(recorded['sequence']) is int and recorded['sequence'] >= 0
            and recorded['sha256'] == frame_digest({key: value for key, value in recorded.items() if key != 'sha256'}))
    except (AttributeError, KeyError, OSError, TypeError, ValueError):
        valid = False
    if not valid:
        raise ValueError('Native live request has no actual current source record.')
    return True



def diagnostic_owner() -> dict[str, str] | None:
    calls = [(filename, function) for filename in ("evidence_identity.py", "private_corpus.py", "process_private_exclusion.py")
             for function in _OWNERS[filename]]
    calls.extend((("evidence_runtime.py", "qt_import_bindings"), ("private_corpus_audit.py", "test_sources_sha256")))
    return next((value for filename, function in calls
                 if (value := owned_caller(filename, function)) is not None), None)
