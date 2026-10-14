"""Finite process input and source-owner identities for private observation."""
from __future__ import annotations

import hashlib
import ctypes
import inspect
import os
from pathlib import Path
import shutil
import sys
import sysconfig
from types import CodeType
from typing import Any

_PLATFORM_SOURCE = Path(sysconfig.get_path("stdlib")) / "platform.py"


def runtime_identity() -> dict[str, Any]:
    """Bind the loaded CPython core and the finite observation stdlib owners."""
    cores: set[Path] = set()
    if sys.platform == "darwin":
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
    elif sys.platform.startswith("linux"):
        for line in Path("/proc/self/maps").read_text().splitlines():
            value = line.split(maxsplit=5)[-1]
            if value.startswith("/") and Path(value).name.startswith("libpython"):
                cores.add(Path(value).resolve(strict=True))
    if not cores and not sysconfig.get_config_var("Py_ENABLE_SHARED"):
        cores.add(Path(sys.executable).resolve(strict=True))
    if not cores:
        raise ValueError("Actual loaded CPython core is unavailable for observation binding.")
    stdlib = Path(sysconfig.get_path("stdlib"))
    core_hashes = [executable_hash(path) for path in cores]
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


def wrapper_call(bound: inspect.BoundArguments, environment: dict[str, str]) -> dict[str, str] | None:
    root = Path(__file__).parents[3]
    command = bound.arguments.get("args")
    cwd = bound.arguments.get("cwd")
    if (not isinstance(command, (list, tuple)) or not command
            or any(bound.arguments.get(key) for key in ("shell", "executable", "preexec_fn"))
            or (cwd is not None and (Path(cwd).absolute() != root or Path(cwd).resolve() != root))
            or not isinstance(command[0], (str, bytes, os.PathLike))
            or Path(os.fsdecode(command[0])).resolve() != root / "skill/scripts/sciplot"
            or any(environment.get(key) for key in ("BASH_ENV", "ENV", "SHELLOPTS", "BASHOPTS", "PS4"))
            or any(key.startswith("BASH_FUNC_") for key in environment)):
        return None
    selected = environment.get("SCIPLOT_PYTHON", str(Path(environment.get("SCIPLOT_RUNTIME_REPO", str(root))) / ".venv/bin/python"))
    if (Path(environment.get("SCIPLOT_REPO", str(root))).resolve() != root
            or Path(environment.get("SCIPLOT_SOURCE_ROOT", str(root / "src"))).resolve() != root / "src"
            or executable_hash(selected, environment=environment) != executable_hash(sys.executable)
            or executable_hash("bash", environment=environment) != executable_hash("/bin/bash")):
        return None
    return wrapper_boundary()


_OWNERS = {"suite_evidence.py": {"_audit_environment"}, "durable_runner.py": {"start_run"},
           "evidence_identity.py": {"_stable_file", "_members"},
           "private_corpus.py": {"_readable_nonempty_file", "_listed_source_issues", "_case_dependencies"}}


def owner_identity(filename: str, function: str) -> dict[str, str]:
    if function not in _OWNERS.get(filename, set()):
        return {}
    path = Path(__file__).with_name(filename)
    source = path.read_bytes()
    module = compile(source, str(path), "exec", dont_inherit=True, optimize=sys.flags.optimize)
    code = next(c for c in module.co_consts if isinstance(c, CodeType) and c.co_name == function)
    return {"owner": filename, "function": function, "source_sha256": hashlib.sha256(source).hexdigest(),
            "bytecode_sha256": _code_hash(code)}


def owned_caller(filename: str, function: str) -> dict[str, str] | None:
    frame = inspect.currentframe()
    path = Path(__file__).with_name(filename)
    try:
        while frame is not None:
            if frame.f_code.co_name == function and Path(frame.f_code.co_filename).resolve() == path.resolve():
                identity = owner_identity(filename, function)
                if _code_hash(frame.f_code) == identity.get("bytecode_sha256"):
                    return identity
            frame = frame.f_back
    finally:
        del frame
    return None



def diagnostic_owner() -> dict[str, str] | None:
    return next((value for filename in ("evidence_identity.py", "private_corpus.py")
                 for function in _OWNERS[filename]
                 if (value := owned_caller(filename, function)) is not None), None)
