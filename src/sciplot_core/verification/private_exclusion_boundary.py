"""Source-bound pytest phases and finite private-namespace process proofs."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import inspect
import json
import os
from pathlib import Path
import stat
from typing import Any, Iterator

from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.verification.input_scope import load_manifest
from sciplot_core.verification.private_process_boundaries import executable_hash, owned_caller, owner_identity, root_scope, watch_roots
from sciplot_core.verification.private_audit_runtime import active_socket_scope, saved_socket_scope
from sciplot_core.verification.process_private_exclusion import (
    KIND, ExclusionSnapshot, actual_launch_facts, invocation_snapshot, original_stdio_facts,
    prepare_private_exclusion, source_private_exclusion, validate_excluded_proof, wrap_private_exclusion,
)

REPO = Path(__file__).resolve().parents[3]
MANIFEST = Path(__file__).with_name("input_scope_manifest.json")
_PHASES = {"setup", "call", "teardown"}
_GIT_LISTING = ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"]


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _scope(nodes: list[str]) -> dict[str, Any] | None:
    manifest = load_manifest(MANIFEST)
    public = set(manifest["scopes"]["public"])
    union = public | set(manifest["scopes"]["private"])
    if not nodes or len(nodes) != len(set(nodes)) or not set(nodes).issubset(union):
        return None
    return {"manifest_sha256": _hash(MANIFEST), "collection_sha256": canonical_json_sha256(sorted(nodes)),
            "public": public, "nodes": set(nodes)}


def bind_collection(observer: Any, nodes: list[str]) -> None:
    # A second in-process collection cannot inherit the first primary's grant.
    scope = None if hasattr(observer, "_exclusion_collection") else _scope(nodes)
    try:
        durable = Path(observer.wrapper_environment["SCIPLOT_VERIFY_FINISH"]).parent
        state = json.loads((durable / "state.json").read_bytes())
        request = json.loads((durable / "request.json").read_bytes())
        if state.get("child_pid") != os.getpid() or request.get("scope", {}).get("kind") != "pytest":
            scope = None
    except (OSError, KeyError, TypeError, ValueError):
        scope = None
    roots = []
    if scope is not None:
        for path in observer.directory.glob("*.jsonl"):
            with path.open() as stream:
                first = json.loads(stream.readline())
            if (first.get("event") == "process_start" and first.get("parent_epoch") is None
                    and first.get("continuation") is None and first.get("run_id") == observer.run
                    and first.get("activation") == owner_identity("suite_evidence.py", "_audit_environment")):
                roots.append(first["sha256"])
    observer._exclusion_collection = {**scope, "suite_root_sha256": roots[0]} if scope is not None and len(roots) == 1 else None


def begin_phase(observer: Any, item: Any, phase: str) -> None:
    observer.nodeid = item.nodeid
    observer._exclusion_phase = None
    scope = getattr(observer, "_exclusion_collection", None)
    if phase not in _PHASES or scope is None or item.nodeid not in scope["public"]:
        return
    source = REPO / item.nodeid.split("::", 1)[0]
    if Path(item.path).resolve() != source.resolve() or not source.is_relative_to(REPO / "tests"):
        return
    frame = observer.record({"event": "pytest_phase_enter", "test_nodeid": item.nodeid, "phase": phase,
                             "manifest_sha256": scope["manifest_sha256"],
                             "collection_sha256": scope["collection_sha256"], "test_source_sha256": _hash(source),
                             "suite_root_sha256": scope["suite_root_sha256"],
                             "phase_owner": owner_identity("private_exclusion_boundary.py", "begin_phase")}, sync=True)
    if frame is not None:
        observer._exclusion_phase = frame


def end_phase(observer: Any, item: Any, phase: str) -> None:
    active = getattr(observer, "_exclusion_phase", None)
    try:
        if active is not None:
            observer.record({"event": "pytest_phase_exit", "test_nodeid": item.nodeid, "phase": phase,
                             "phase_enter_sha256": active["sha256"]}, sync=True)
    finally:
        observer._exclusion_phase = None
        observer.nodeid = None


def _evidence(environment: dict[str, str]) -> tuple[Path, ...]:
    finish = environment.get("SCIPLOT_VERIFY_FINISH")
    if not finish:
        return ()
    directory = Path(finish).absolute().parent
    return tuple(directory / name for name in ("request.json", "state.json", "completion.json", "receipt.json", "launch.json", "finish.json"))


def _root_listing(observer: Any, bound: inspect.BoundArguments) -> dict[str, str] | None:
    command = bound.arguments.get("args")
    if (observer.nodeid is not None or not isinstance(command, (list, tuple)) or list(command) != _GIT_LISTING
            or Path(bound.arguments.get("cwd") or Path.cwd()).resolve() != REPO
            or bound.arguments.get("stdin") is not None or bound.arguments.get("stdout") != -1
            or bound.arguments.get("stderr") != -1 or bound.arguments.get("text") is not True):
        return None
    return owned_caller("evidence_scope.py", "_repository_inputs")


@contextmanager
def excluded_launch(observer: Any, bound: inspect.BoundArguments, audit_keys: tuple[str, ...]) -> Iterator[tuple[dict[str, Any], ExclusionSnapshot, tuple[str, ...]] | None]:
    active = getattr(observer, "_exclusion_phase", None)
    command = bound.arguments.get("args")
    baseline = observer.wrapper_environment
    root_listing = _root_listing(observer, bound)
    if ((active is None and root_listing is None) or not isinstance(command, (list, tuple)) or not command
            or not all(isinstance(value, str) for value in command)
            or observer.root_scope != root_scope(watch_roots(REPO, baseline))):
        yield None
        return
    environment = bound.arguments["env"]
    dropped = audit_keys if (environment.get("SCIPLOT_PRIVATE_AUDIT_DIR") == str(observer.directory)
                            and environment.get("SCIPLOT_PRIVATE_AUDIT_RUN") == observer.run) else ()
    # Reject unsupported invocation semantics before enumerating any raw roots.
    if (bound.arguments.get("shell", False) is not False or bound.arguments.get("executable") is not None
            or bound.arguments.get("close_fds", True) is not True or bound.arguments.get("pass_fds", ())
            or bound.arguments.get("preexec_fn") is not None):
        yield None
        return
    try:
        original = {"original_argv_sha256": canonical_json_sha256(list(command)),
                    "original_environment_sha256": canonical_json_sha256(environment),
                    "original_executable_sha256": executable_hash(command[0], cwd=bound.arguments.get("cwd"), environment=environment),
                    "original_cwd": str(Path(bound.arguments.get("cwd") or Path.cwd()).absolute()),
                    "original_stdio": original_stdio_facts(bound.arguments.get("stdin"), bound.arguments.get("stdout"), bound.arguments.get("stderr"))}
        snapshot = prepare_private_exclusion(REPO, baseline, audit_directory=observer.directory,
            evidence_paths=_evidence(dict(os.environ) if root_listing is not None else baseline),
            socket_scope=active_socket_scope(observer))
        source = source_private_exclusion(command, environment,
            stdio=(bound.arguments.get("stdin"), bound.arguments.get("stdout"), bound.arguments.get("stderr")),
            cwd=Path(bound.arguments["cwd"]) if bound.arguments.get("cwd") is not None else None,
            drop_environment=dropped)
        caller_launch = None
        if source is not None:
            stdin, stdout, stderr = (bound.arguments.get(key) for key in ("stdin", "stdout", "stderr"))
            if not isinstance(stdin, int) or not isinstance(stdout, int) or not isinstance(stderr, int):
                raise ValueError("Source invocation must still hold its actual endpoints.")
            caller_launch = actual_launch_facts(source[0], tuple(command), environment, stdio=(stdin, stdout, stderr),
                cwd=Path(bound.arguments["cwd"]) if bound.arguments.get("cwd") is not None else None,
                close_fds=bound.arguments.get("close_fds", True), pass_fds=bound.arguments.get("pass_fds", ()),
                preexec_fn=bound.arguments.get("preexec_fn"), shell=bound.arguments.get("shell", False),
                executable=bound.arguments.get("executable"), drop_environment=source[1])
        invocation = wrap_private_exclusion(snapshot, command, environment=environment,
            cwd=Path(bound.arguments["cwd"]) if bound.arguments.get("cwd") is not None else None,
            stdin=bound.arguments.get("stdin"), stdout=bound.arguments.get("stdout"), stderr=bound.arguments.get("stderr"),
            drop_environment=dropped)
    except (OSError, ValueError):
        yield None
        return
    with invocation:
        bound.arguments.update(args=invocation.argv, env=invocation.environment,
                               stdin=invocation.stdio[0], stdout=invocation.stdio[1], stderr=invocation.stdio[2])
        yield ({"kind": KIND, "version": 1, "phase_enter_sha256": active["sha256"] if active else None,
                "root_listing_owner": root_listing,
                "process_proof": invocation.proof, "drop_environment": list(dropped),
                "caller_launch": caller_launch, **original}, invocation_snapshot(invocation),
               tuple(sorted(set(dropped) | set(source[1] if source else ()))))


def final_launch(bound: inspect.BoundArguments, signature: inspect.Signature, snapshot: ExclusionSnapshot,
                 boundary: dict[str, Any], dropped: tuple[str, ...]) -> tuple[tuple[Any, ...], dict[str, Any], str | None, dict[str, Any]]:
    actual = signature.bind(*bound.args, **bound.kwargs)
    actual.arguments["args"] = tuple(actual.arguments["args"])
    actual.arguments["env"] = dict(actual.arguments["env"])
    launch = actual_launch_facts(snapshot, actual.arguments["args"], actual.arguments["env"],
        stdio=(actual.arguments["stdin"], actual.arguments["stdout"], actual.arguments["stderr"]),
        cwd=Path(actual.arguments["cwd"]) if actual.arguments.get("cwd") is not None else None,
        close_fds=actual.arguments.get("close_fds", True), pass_fds=actual.arguments.get("pass_fds", ()),
        preexec_fn=actual.arguments.get("preexec_fn"), shell=actual.arguments.get("shell", False),
        executable=actual.arguments.get("executable"), drop_environment=dropped)
    fields = {"excluded_" + name: boundary[name] for name in (
        "original_argv_sha256", "original_environment_sha256", "original_executable_sha256", "original_cwd", "original_stdio")}
    fields.update(excluded_actual_launch=launch, excluded_caller_launch=boundary["caller_launch"])
    target = executable_hash(actual.arguments["args"][0], environment=actual.arguments["env"])
    return actual.args, actual.kwargs, target, fields


def excluded_bound(value: Any, attempt: dict[str, Any], records: list[dict[str, Any]], *,
                   primary: int, expected_nodeids: set[str] | None, directory: Path,
                   durable: dict[str, Any] | None, suite_start: dict[str, Any], audit_keys: tuple[str, ...],
                   root_pid: int, caller: dict[str, Any] | None) -> bool:
    if not isinstance(value, dict) or value.get("kind") != KIND:
        return False
    expected_keys = {"kind", "version", "phase_enter_sha256", "process_proof", "drop_environment",
                     "original_argv_sha256", "original_environment_sha256", "original_executable_sha256", "original_cwd",
                     "original_stdio"}
    expected_keys.add("caller_launch")
    expected_keys.add("root_listing_owner")
    root_listing = value.get("root_listing_owner") is not None
    if set(value) != expected_keys or value["version"] != 1 or expected_nodeids is None or durable is None:
        return False
    try:
        if root_listing:
            if (attempt["pid"] != root_pid or caller is None or value["phase_enter_sha256"] is not None
                    or value["root_listing_owner"] != owner_identity("evidence_scope.py", "_repository_inputs")
                    or value["original_argv_sha256"] != canonical_json_sha256(_GIT_LISTING)
                    or value["original_cwd"] != str(REPO)):
                return False
        elif attempt["pid"] != primary:
            return False
        scope = _scope(sorted(expected_nodeids))
        enters = [row for row in records if row["event"] == "pytest_phase_enter" and row["sha256"] == value["phase_enter_sha256"]]
        if not root_listing and (scope is None or len(enters) != 1):
            return False
        entered = enters[0] if enters else {}
        exits = [row for row in records if row["event"] == "pytest_phase_exit" and row.get("phase_enter_sha256") == entered.get("sha256")]
        node = entered.get("test_nodeid", next(iter(expected_nodeids)))
        source = REPO / node.split("::", 1)[0]
        if not root_listing and (scope is None or node not in scope["public"] or entered.get("phase") not in _PHASES or entered["pid"] != primary
                or entered.get("phase_owner") != owner_identity("private_exclusion_boundary.py", "begin_phase")
                or suite_start.get("activation") != owner_identity("suite_evidence.py", "_audit_environment")
                or entered.get("suite_root_sha256") != suite_start["sha256"]
                or entered.get("manifest_sha256") != scope["manifest_sha256"]
                or entered.get("collection_sha256") != scope["collection_sha256"]
                or entered.get("test_source_sha256") != _hash(source)
                or durable["records"].get(canonical_json_sha256(str(source)), {}).get("sha256") != _hash(source)
                or len(exits) != 1 or exits[0].get("test_nodeid") != node or exits[0].get("phase") != entered["phase"]
                or not entered["sequence"] < attempt["sequence"] < exits[0]["sequence"]):
            return False
        if (suite_start.get("activation") != owner_identity("suite_evidence.py", "_audit_environment")
                or value["original_argv_sha256"] != attempt.get("excluded_original_argv_sha256")
                or value["original_environment_sha256"] != attempt.get("excluded_original_environment_sha256")
                or value["original_executable_sha256"] != attempt.get("excluded_original_executable_sha256")
                or value["original_cwd"] != attempt.get("excluded_original_cwd")
                or value["original_stdio"] != attempt.get("excluded_original_stdio")
                or value["caller_launch"] != attempt.get("excluded_caller_launch")):
            return False
        expected_drop = list(audit_keys) if attempt.get("same_observer_routing") else []
        if value["drop_environment"] != expected_drop:
            return False
        environment = dict(os.environ)
        context = caller if root_listing else durable
        if context is None:
            return False
        evidence = tuple(Path(context["directory"]) / name for name in
                         ("request.json", "state.json", "completion.json", "receipt.json", "launch.json", "finish.json"))
        expected_snapshot = prepare_private_exclusion(REPO, environment, audit_directory=directory,
            evidence_paths=evidence, socket_scope=None if root_listing else saved_socket_scope(records, attempt))
        if attempt.get("expected_executable_sha256") != expected_snapshot.to_dict()["identity"]["sandbox"]["sha256"]:
            return False
        validate_excluded_proof(value["process_proof"], expected_snapshot=expected_snapshot,
            **{name: value[name] for name in ("original_argv_sha256", "original_environment_sha256",
                                              "original_executable_sha256", "original_cwd", "original_stdio")},
            actual_launch=attempt["excluded_actual_launch"],
            caller_launch=attempt["excluded_caller_launch"],
            drop_environment=value["drop_environment"])
        return True
    except (OSError, KeyError, TypeError, ValueError):
        return False


def metadata_diagnostic(frame: dict[str, Any], snapshots: list[dict[str, Any]]) -> bool:
    if frame["event"] not in {"os.scandir", "os.listdir"}:
        return False
    owner = frame.get("diagnostic_owner")
    if owner not in [owner_identity("process_private_exclusion.py", name) for name in ("_members", "_evidence_inodes")]:
        return False
    path = frame.get("resolved_path")
    return any((row := snapshot["members"].get(path)) is not None and stat.S_ISDIR(row["st_mode"]) for snapshot in snapshots)
