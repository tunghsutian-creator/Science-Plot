"""Mac process input exclusion facts; callers own node scope and actual waits.

This leaf does not activate an observer, grant an auxiliary classification or
claim a child's sensor completed. It never opens protected data for reading.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import sys
from typing import Any, Mapping, Sequence

from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.verification.evidence_runtime import runtime_loader_environment
from sciplot_core.verification.public_input_guard import forbidden_roots
from sciplot_core.verification.process_private_launch import bound_source_invocation, hold_stdio, launch_facts, launch_prefix, socket_scope_facts, validate_stdio
from sciplot_core.verification.process_private_launch import ExcludedInvocation as ExcludedInvocation
from sciplot_core.verification.process_private_launch import original_stdio_facts as original_stdio_facts

SANDBOX = Path("/usr/bin/sandbox-exec")
ENV = Path("/usr/bin/env")
SYSTEM = Path("/System/Library/CoreServices/SystemVersion.plist")
KIND = "sciplot_private_input_excluded_invocation"


def _digest(value: object) -> str:
    return canonical_json_sha256(value, allow_nan=False)


def _metadata(path: Path) -> dict[str, int] | None:
    try:
        value = path.lstat()
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(value.st_mode):
        raise ValueError(f"Private exclusion rejects a symlink: {path}")
    return {name: getattr(value, name) for name in
            ("st_dev", "st_ino", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")}


def _members(roots: Sequence[str]) -> dict[str, dict[str, int] | None]:
    result: dict[str, dict[str, int] | None] = {}
    def visit(path: Path) -> None:
        row = _metadata(path)
        result[str(path)] = row
        if row is None:
            return
        if stat.S_ISDIR(row["st_mode"]):
            with os.scandir(path) as entries:
                children = sorted(entry.name for entry in entries)
            for name in children:
                visit(path / name)
        elif not stat.S_ISREG(row["st_mode"]) or row["st_nlink"] != 1:
            raise ValueError(f"Private exclusion requires single-link regular files: {path}")
    for root in roots:
        visit(Path(root))
    return result


def _ancestors(paths: Sequence[str]) -> dict[str, dict[str, int] | None]:
    result = {}
    for name in paths:
        for path in Path(name).parents:
            row = _metadata(path)
            if row is not None and not stat.S_ISDIR(row["st_mode"]):
                raise ValueError("Private exclusion requires ordinary directory ancestors.")
            result[str(path)] = None if row is None else {key: row[key] for key in ("st_dev", "st_ino", "st_mode")}
    return result


def _tool(path: Path) -> dict[str, Any]:
    actual = path.resolve(strict=True)
    before = _metadata(actual)
    if before is None or not stat.S_ISREG(before["st_mode"]):
        raise ValueError("Private exclusion capability/source is not an actual regular file.")
    hashed = hashlib.sha256(actual.read_bytes()).hexdigest()
    if _metadata(actual) != before:
        raise ValueError("Private exclusion capability changed during hashing.")
    return {"path": str(actual), "sha256": hashed, "metadata": before}


def _identity() -> dict[str, Any]:
    if sys.platform != "darwin":
        raise ValueError("Private process exclusion requires the actual Mac capability.")
    uname = os.uname()
    return {"sandbox": _tool(SANDBOX), "env": _tool(ENV), "system": _tool(SYSTEM),
            "interpreter": _tool(Path(sys.executable)),
            "os": {"release": uname.release, "version": uname.version, "machine": uname.machine},
            "sources": [_tool(Path(__file__)), _tool(Path(__file__).with_name("public_input_guard.py")),
                        _tool(Path(__file__).with_name("evidence_runtime.py")),
                        _tool(Path(__file__).with_name("process_private_launch.py"))]}


@dataclass(frozen=True)
class ExclusionSnapshot:
    payload_json: str

    def to_dict(self) -> dict[str, Any]:
        return dict(json.loads(self.payload_json))


def _profile(names: Sequence[str], writes: Sequence[str], ancestors: Mapping[str, Any], scope: Mapping[str, Any] | None) -> str:
    profile = "(version 1)\n(allow default)\n"
    profile += "(deny file* " + " ".join("(subpath " + json.dumps(name) + ")" for name in names) + ")\n"
    if writes:
        profile += "(deny file-write* " + " ".join("(subpath " + json.dumps(name) + ")" for name in writes) + ")\n"
    profile += "(deny file-write* " + " ".join("(literal " + json.dumps(name) + ")" for name in sorted(ancestors)) + ")\n(deny network-outbound)\n"
    if scope is not None:
        literals = ["(literal " + json.dumps(name) + ")" for name in scope["sockets"]]
        profile += "".join("(allow network-outbound " + literal + ")\n" for literal in literals)
        return profile + "(deny file-write* file-link (require-all (vnode-type SOCKET) " + " ".join("(require-not " + literal + ")" for literal in literals) + "))\n"
    return profile + "(deny file-write* file-link (vnode-type SOCKET))\n"


def prepare_private_exclusion(repo_root: Path, environment: Mapping[str, str], *, stage_root: Path | None = None,
                              audit_directory: Path | None = None, evidence_paths: Sequence[Path] = (),
                              socket_scope: Mapping[str, Any] | None = None) -> ExclusionSnapshot:
    """Freeze actual membership/stat facts, without reading protected bytes."""
    scope = socket_scope_facts(socket_scope)
    parameters = {"repo_root": str(repo_root.absolute()), "reference_data": environment.get("SCIPLOT_REFERENCE_DATA"),
                  "stage_root": str(stage_root.absolute()) if stage_root is not None else None,
                  "audit_directory": str(audit_directory.absolute()) if audit_directory is not None else None,
                  "evidence_paths": sorted(str(path.absolute()) for path in evidence_paths), "socket_scope": scope}
    roots = forbidden_roots(repo_root.absolute(), dict(environment))
    if stage_root is not None:
        roots.extend(forbidden_roots(stage_root.absolute(), {}))
    names = sorted({str(path.absolute()) for path in roots})
    writes = sorted({*(str(path.absolute()) for path in evidence_paths),
                     *([str(audit_directory.absolute())] if audit_directory is not None else [])})
    ancestor_paths = [*names, *writes, *(scope["sockets"] if scope is not None else [])]
    ancestors = _ancestors(ancestor_paths)
    evidence_anchors = {}
    for name in writes:
        row = _metadata(Path(name))
        if row is not None and stat.S_ISDIR(row["st_mode"]):
            evidence_anchors[name] = {key: row[key] for key in ("st_dev", "st_ino", "st_mode")}
    members = _members(names)
    payload = {"version": 1, "parameters": parameters, "roots": names, "members": members,
               "ancestors": ancestors, "write_protected_paths": writes, "evidence_anchors": evidence_anchors,
               "profile": _profile(names, writes, ancestors, scope), "identity": _identity(), "socket_scope": scope}
    if _members(names) != members or _ancestors(ancestor_paths) != ancestors:
        raise ValueError("Private exclusion namespace changed during preparation.")
    return ExclusionSnapshot(json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False))


def validate_private_exclusion(snapshot: ExclusionSnapshot | Mapping[str, Any]) -> None:
    """Recompute a serialized snapshot; a caller must bind its trusted parameters."""
    value = snapshot.to_dict() if isinstance(snapshot, ExclusionSnapshot) else dict(snapshot)
    if set(value) != {"version", "parameters", "roots", "members", "ancestors", "write_protected_paths", "evidence_anchors", "profile", "identity", "socket_scope"}:
        raise ValueError("Unknown private exclusion snapshot shape.")
    parameters = value.get("parameters")
    if isinstance(parameters, dict) and set(parameters) == {"components"}:
        components = parameters["components"]
        if not isinstance(components, list) or len(components) != 2:
            raise ValueError("Invalid exclusion composition.")
        if value != compose_private_exclusion(*components).to_dict():
            raise ValueError("Private exclusion composition drift.")
        return
    if not isinstance(parameters, dict) or set(parameters) != {"repo_root", "reference_data", "stage_root", "audit_directory", "evidence_paths", "socket_scope"}:
        raise ValueError("Unknown private exclusion parameters.")
    try:
        reference = parameters["reference_data"]
        environment = {} if reference is None else {"SCIPLOT_REFERENCE_DATA": reference}
        expected = prepare_private_exclusion(Path(parameters["repo_root"]), environment,
            stage_root=Path(parameters["stage_root"]) if parameters["stage_root"] is not None else None,
            audit_directory=Path(parameters["audit_directory"]) if parameters["audit_directory"] is not None else None,
            evidence_paths=tuple(Path(path) for path in parameters["evidence_paths"]), socket_scope=parameters["socket_scope"])
    except (OSError, TypeError, KeyError) as error:
        raise ValueError("Invalid or unavailable private exclusion facts.") from error
    if value != expected.to_dict():
        raise ValueError("Private exclusion membership, resource, ancestor or capability drift.")


def compose_private_exclusion(primary: ExclusionSnapshot | Mapping[str, Any], secondary: ExclusionSnapshot | Mapping[str, Any]) -> ExclusionSnapshot:
    parts = [item.to_dict() if isinstance(item, ExclusionSnapshot) else dict(item) for item in (primary, secondary)]
    for item in parts:
        validate_private_exclusion(item)
    result = dict(parts[0])
    if result["identity"] != parts[1]["identity"]:
        raise ValueError("Exclusion component capabilities differ.")
    for key in ("members", "ancestors", "evidence_anchors"):
        combined = dict(result[key])
        for path, value in parts[1][key].items():
            if path in combined and combined[path] != value:
                raise ValueError("Exclusion component facts conflict.")
            combined[path] = value
        result[key] = combined
    for key in ("roots", "write_protected_paths"):
        result[key] = sorted(set(result[key]) | set(parts[1][key]))
    result["parameters"] = {"components": parts}
    result["socket_scope"] = result["socket_scope"] if result["socket_scope"] == parts[1]["socket_scope"] else None
    result["profile"] = _profile(result["roots"], result["write_protected_paths"], result["ancestors"], result["socket_scope"])
    return ExclusionSnapshot(json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False))


def source_private_exclusion(argv: Sequence[str], environment: Mapping[str, str], *, stdio: tuple[Any, Any, Any],
                             cwd: Path | None = None, drop_environment: Sequence[str] = ()) -> tuple[ExclusionSnapshot, tuple[str, ...]] | None:
    current = bound_source_invocation(argv, environment, stdio, cwd, drop_environment)
    return None if current is None else (ExclusionSnapshot(current._snapshot_json), current._drop_environment)


def invocation_snapshot(invocation: ExcludedInvocation) -> ExclusionSnapshot:
    return ExclusionSnapshot(invocation._snapshot_json)


def _inode_set(rows: Mapping[str, Any]) -> set[tuple[int, int]]:
    return {(row["st_dev"], row["st_ino"]) for row in rows.values() if row is not None}


def _evidence_inodes(paths: Sequence[str]) -> set[tuple[int, int]]:
    result: set[tuple[int, int]] = set()
    for name in paths:
        path = Path(name)
        row = _metadata(path)
        if row is None:
            continue
        result.add((row["st_dev"], row["st_ino"]))
        if not stat.S_ISDIR(row["st_mode"]) and (not stat.S_ISREG(row["st_mode"]) or row["st_nlink"] != 1):
            raise ValueError("Private exclusion requires ordinary single-link evidence.")
        if stat.S_ISDIR(row["st_mode"]):
            for parent, directories, files in os.walk(path, followlinks=False):
                for part in [*directories, *files]:
                    current = _metadata(Path(parent) / part)
                    if current is not None:
                        if not stat.S_ISDIR(current["st_mode"]) and (not stat.S_ISREG(current["st_mode"]) or current["st_nlink"] != 1):
                            raise ValueError("Private exclusion requires ordinary single-link evidence.")
                        result.add((current["st_dev"], current["st_ino"]))
    return result






def actual_launch_facts(snapshot: ExclusionSnapshot, argv: tuple[str, ...], environment: Mapping[str, str], *,
                        stdio: tuple[int, int, int], cwd: Path | None = None, close_fds: bool = True,
                        pass_fds: Sequence[int] = (), preexec_fn: Any = None, shell: bool = False,
                        executable: str | None = None, drop_environment: Sequence[str] = ()) -> dict[str, Any]:
    """Derive facts independently from the final immutable original_init call."""
    return launch_facts(snapshot.to_dict(), argv, environment, stdio=stdio, cwd=cwd, close_fds=close_fds,
        pass_fds=pass_fds, preexec_fn=preexec_fn, shell=shell, executable=executable, drop_environment=drop_environment)


def _target(command: str, cwd: Path, environment: Mapping[str, str]) -> Path:
    if os.sep in command:
        return (cwd / command).resolve(strict=True)
    search = os.pathsep.join(str((cwd / part).absolute()) for part in environment.get("PATH", os.defpath).split(os.pathsep))
    found = shutil.which(command, path=search)
    if found is None:
        raise ValueError("Private exclusion cannot resolve the original executable.")
    return Path(found).resolve(strict=True)


def wrap_private_exclusion(snapshot: ExclusionSnapshot, argv: Sequence[str], *, environment: Mapping[str, str],
                           cwd: Path | None = None, stdin: Any = None, stdout: Any = None, stderr: Any = None,
                           close_fds: bool = True, pass_fds: Sequence[int] = (), preexec_fn: Any = None,
                           shell: bool = False, executable: str | None = None,
                           drop_environment: Sequence[str] = ()) -> ExcludedInvocation:
    """Hold duplicated endpoints through Popen; no sensor/lifecycle waiver here."""
    if (shell is not False or executable is not None or close_fds is not True or pass_fds or preexec_fn is not None
            or isinstance(argv, (str, bytes)) or not argv
            or any(not isinstance(arg, str) or "\0" in arg for arg in argv) or not argv[0] or "=" in argv[0]):
        raise ValueError("Unsupported or unsafe private exclusion invocation.")
    if any(not isinstance(key, str) or not key or "=" in key or "\0" in key for key in drop_environment):
        raise ValueError("Invalid post-boundary environment projection.")
    validate_private_exclusion(snapshot)
    source = bound_source_invocation(argv, environment, (stdin, stdout, stderr), cwd, drop_environment)
    composition = None
    target_argv = tuple(argv)
    if source is not None:
        inherited = ExclusionSnapshot(source._snapshot_json)
        snapshot = compose_private_exclusion(snapshot, inherited)
        target_argv = source._target_argv
        composition = {"source_snapshot": inherited.to_dict(), "source_drop_environment": list(source._drop_environment),
                       "target_argv_sha256": _digest(list(target_argv))}
    payload = snapshot.to_dict()
    current = Path.cwd() if cwd is None else cwd.absolute()
    _ancestors([str(current / "scope-child")])
    target = _target(argv[0], current, environment)
    if any(current.is_relative_to(Path(root)) or target.is_relative_to(Path(root)) for root in payload["roots"]):
        raise ValueError("Private exclusion refuses a protected cwd or executable before reading it.")
    original_target = _tool(target)
    forbidden = _inode_set(payload["members"]) | _evidence_inodes(payload["write_protected_paths"])
    duplicates: list[int] = []
    try:
        stdio = [hold_stdio(value, index, forbidden, duplicates) for index, value in enumerate((stdin, stdout, stderr))]
        dropped = sorted(set(drop_environment) | (set(source._drop_environment) if source is not None else set()))
        actual = (*launch_prefix(payload, runtime_loader_environment(environment), dropped), *target_argv)
        original = {"argv_sha256": _digest(list(argv)), "environment_sha256": _digest(dict(environment)),
                    "cwd": str(current), "executable": original_target, "stdio": [row[1] for row in stdio]}
        endpoints = (stdio[0][0], stdio[1][0], stdio[2][0])
        effective = actual_launch_facts(snapshot, actual, environment, stdio=endpoints, cwd=current, drop_environment=dropped)
        proof = {"kind": KIND, "version": 1, "snapshot": payload, "snapshot_sha256": _digest(payload),
                 "profile_sha256": hashlib.sha256(payload["profile"].encode()).hexdigest(),
                 "original": original, "actual": effective, "drop_environment": dropped,
                 "evidence_inodes": sorted([list(pair) for pair in forbidden]), "composition": composition}
        return ExcludedInvocation(actual, dict(environment), endpoints, proof, duplicates,
            _target_argv=target_argv, _snapshot_json=snapshot.payload_json, _drop_environment=tuple(dropped))
    except BaseException:
        for descriptor in duplicates:
            os.close(descriptor)
        raise


def validate_excluded_proof(proof: Mapping[str, Any], *, expected_snapshot: ExclusionSnapshot | Mapping[str, Any],
                            original_argv_sha256: str, original_environment_sha256: str,
                            original_executable_sha256: str, original_cwd: str,
                            original_stdio: Sequence[Mapping[str, Any]], actual_launch: Mapping[str, Any],
                            drop_environment: Sequence[str] = (), caller_launch: Mapping[str, Any] | None = None) -> None:
    """Validate closed facts against trusted parent launch-frame bindings."""
    validate_private_exclusion(expected_snapshot)
    value = dict(proof)
    expected_keys = {"kind", "version", "snapshot", "snapshot_sha256", "profile_sha256", "original", "actual", "drop_environment", "evidence_inodes", "composition"}
    payload = expected_snapshot.to_dict() if isinstance(expected_snapshot, ExclusionSnapshot) else dict(expected_snapshot)
    composition = value.get("composition")
    target_hash = original_argv_sha256
    dropped = set(drop_environment)
    if composition is not None:
        if not isinstance(composition, dict) or set(composition) != {"source_snapshot", "source_drop_environment", "target_argv_sha256"} or caller_launch is None:
            raise ValueError("Missing independent source-owned caller launch.")
        if (not isinstance(composition["source_snapshot"], dict) or set(caller_launch) != set(actual_launch)
                or not isinstance(caller_launch.get("loader_environment"), dict)):
            raise ValueError("Incomplete source-owned caller launch facts.")
        source_payload = composition["source_snapshot"]
        source_drop = composition["source_drop_environment"]
        if not isinstance(source_drop, list) or any(not isinstance(key, str) for key in source_drop) or source_drop != sorted(set(source_drop)):
            raise ValueError("Invalid source-owned environment projection.")
        dropped.update(source_drop)
        payload = compose_private_exclusion(payload, source_payload).to_dict()
        target_hash = composition["target_argv_sha256"]
        if (caller_launch["argv_sha256"] != original_argv_sha256 or caller_launch["suffix_sha256"] != target_hash
                or caller_launch["launch_environment_sha256"] != original_environment_sha256
                or caller_launch["prefix_sha256"] != _digest(list(launch_prefix(source_payload, caller_launch["loader_environment"], composition["source_drop_environment"])))
                or caller_launch["stdio"] != actual_launch["stdio"] or caller_launch["cwd"] != original_cwd or caller_launch["flags"] != actual_launch["flags"]):
            raise ValueError("Source-owned caller and composed target differ.")
    elif caller_launch is not None:
        raise ValueError("Unexpected source-owned caller launch.")
    if (set(value) != expected_keys or value.get("kind") != KIND or value.get("version") != 1
            or value.get("snapshot") != payload or value.get("snapshot_sha256") != _digest(payload)
            or value.get("profile_sha256") != hashlib.sha256(payload["profile"].encode()).hexdigest()
            or value.get("drop_environment") != sorted(dropped)):
        raise ValueError("Unknown, stale or mismatched private exclusion proof.")
    original, actual = value["original"], value["actual"]
    if (not isinstance(original, dict) or set(original) != {"argv_sha256", "environment_sha256", "cwd", "executable", "stdio"}
            or not isinstance(actual, dict) or set(actual) != {"argv_sha256", "prefix_sha256", "suffix_sha256", "launch_environment_sha256",
                "target_environment_sha256", "loader_environment", "stdio", "cwd", "flags"} or actual != dict(actual_launch)
            or original["argv_sha256"] != original_argv_sha256 or original["environment_sha256"] != original_environment_sha256
            or actual["launch_environment_sha256"] != original_environment_sha256 or actual["suffix_sha256"] != target_hash
            or actual["cwd"] != original_cwd or original["stdio"] != list(original_stdio)
            or actual["flags"] != {"close_fds": True, "pass_fds": [], "preexec_fn": None, "shell": False, "executable": None}
            or original["cwd"] != original_cwd or not isinstance(original["executable"], dict)
            or set(original["executable"]) != {"path", "sha256", "metadata"}
            or original["executable"]["sha256"] != original_executable_sha256):
        raise ValueError("Private exclusion original/actual launch bindings differ.")
    loader = actual["loader_environment"]
    if (not isinstance(loader, dict) or set(loader) - {"DYLD_FRAMEWORK_PATH"}
            or any(not isinstance(key, str) or not isinstance(item, str) for key, item in loader.items())
            or set(loader) & dropped
            or actual["prefix_sha256"] != _digest(list(launch_prefix(payload, loader, sorted(dropped))))):
        raise ValueError("Actual launch does not carry the exact exclusion prefix.")
    rows, old = actual["stdio"], original["stdio"]
    if not isinstance(rows, list) or not isinstance(old, list) or len(rows) != 3 or len(old) != 3:
        raise ValueError("Incomplete private exclusion stdio binding.")
    inode_rows = value["evidence_inodes"]
    if (not isinstance(inode_rows, list) or any(not isinstance(pair, list) or len(pair) != 2
            or any(type(number) is not int or number < 0 for number in pair) for pair in inode_rows)
            or inode_rows != sorted([list(pair) for pair in {tuple(pair) for pair in inode_rows}])):
        raise ValueError("Malformed private exclusion evidence inode facts.")
    excluded = _inode_set(payload["members"]) | {tuple(pair) for pair in inode_rows} | _evidence_inodes(payload["write_protected_paths"])
    validate_stdio(rows, old, excluded)
