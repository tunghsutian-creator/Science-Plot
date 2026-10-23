"""Strict closure of supported raw observer streams; assertions are not proof."""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Callable

from sciplot_core.verification.durable_runner import run_status
from sciplot_core.verification.evidence_identity import digest, identity_valid
from sciplot_core.verification.private_observer import AUDIT_KEYS, VERSION, ZERO, bootstrap_hashes, frame_digest, source_hashes
from sciplot_core.verification.private_exclusion_boundary import excluded_bound, metadata_diagnostic
from sciplot_core.verification.private_exclusion_boundary import _review_index, _scope
from sciplot_core.verification.private_audit_runtime import review_sockets
from sciplot_core.verification.private_native_exit_port import validated_exits

from sciplot_core.verification.private_process_boundaries import executable_hash, owner_identity, root_scope, runtime_identity, uname_boundary, wrapper_boundary, wrapper_inputs

from sciplot_core.verification.native_probe_boundary import native_probe_bound

_HEX = re.compile(r"[0-9a-f]{32}")


def observer_source_hashes() -> dict[str, str]:
    return source_hashes()


def _streams(directory: Path) -> dict[str, str]:
    result = {}
    for path in sorted(directory.glob("*.jsonl")):
        if path.is_symlink() or not path.is_file() or not _HEX.fullmatch(path.stem):
            raise ValueError("unsupported or aliased observer stream")
        result[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    if not result:
        raise ValueError("observer streams are absent")
    return result


def capture_proof(directory: Path, *, primary_pid: int, root_pid: int | None = None,
                  expected_roots: list[str], interpreter: Path | None = None,
                  durable_directory: Path | None = None, root_execution_directory: Path | None = None) -> dict[str, Any]:
    """Snapshot original streams. Completeness is calculated when read back."""
    import sys

    return {"version": VERSION, "directory": str(directory.resolve()), "primary_pid": primary_pid,
            "root_pid": root_pid or primary_pid, "interpreter_sha256": executable_hash(interpreter or sys.executable),
            "durable_directory": str(durable_directory.resolve()) if durable_directory else None,
            "root_execution_directory": str(root_execution_directory.resolve()) if root_execution_directory else None,
            "expected_root_scope": root_scope(expected_roots),
            "python_runtime": runtime_identity(),
            "wrapper_inputs": wrapper_inputs(dict(os.environ)),
            "stream_sha256": _streams(directory), "observer_sources_sha256": observer_source_hashes()}


def _read_epochs(directory: Path) -> dict[str, list[dict[str, Any]]]:
    epochs = {}
    for path in sorted(directory.glob("*.jsonl")):
        data = path.read_bytes()
        if not data.endswith(b"\n"):
            raise ValueError("observer stream is truncated")
        records = []
        head = ZERO
        for sequence, raw in enumerate(data.splitlines()):
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError("malformed observer frame")
            content = dict(value)
            observed = content.pop("sha256", None)
            if (observed != frame_digest(content) or value.get("sequence") != sequence
                    or type(value.get("sequence")) is not int or value.get("previous_sha256") != head
                    or value.get("version") != VERSION or value.get("epoch") != path.stem
                    or type(value.get("pid")) is not int or value["pid"] < 1
                    or type(value.get("parent_pid")) is not int or value["parent_pid"] < 1
                    or type(value.get("monotonic_ns")) is not int
                    or type(value.get("lost_events_before")) is not int or value["lost_events_before"] != 0):
                raise ValueError("observer sequence, hash, identity or loss is invalid")
            head = observed
            records.append(value)
        if not records or records[0].get("event") != "process_start":
            raise ValueError("observer startup is absent")
        first = records[0]
        if (sum(record.get("event") == "process_start" for record in records) != 1
                or not isinstance(first.get("run_id"), str) or not _HEX.fullmatch(first["run_id"])
                or any(record["pid"] != first["pid"] or record["run_id"] != first["run_id"] for record in records)
                or any(a["monotonic_ns"] > b["monotonic_ns"] for a, b in zip(records, records[1:], strict=False))):
            raise ValueError("observer epoch identity changes")
        epochs[path.stem] = records
    return epochs


def _durable_context(proof: dict[str, Any], *, root: bool = False) -> dict[str, Any] | None:
    name = proof.get("root_execution_directory" if root else "durable_directory")
    if name is None:
        return None
    directory = Path(name)
    if not directory.is_absolute() or directory.is_symlink() or run_status(directory)["status"] not in {"PASS", "FAIL"}:
        raise ValueError("bound durable execution has no validated completion")
    state = json.loads((directory / "state.json").read_bytes())
    receipt = json.loads((directory / "receipt.json").read_bytes())
    completion = json.loads((directory / "completion.json").read_bytes())
    request_bytes = (directory / "request.json").read_bytes()
    request = json.loads(request_bytes)
    if any(type(completion.get(key)) is not int or completion[key] <= 0
           or completion[key] != state.get(key) for key in ("child_pid", "supervisor_pid")):
        raise ValueError("original wait completion lacks sealed actual child/supervisor PID agreement")
    if (completion["child_pid"] != proof["root_pid" if root else "primary_pid"] or not identity_valid(receipt["before"])
            or not identity_valid(receipt["after"]) or receipt["before"]["sha256"] != receipt["after"]["sha256"]):
        raise ValueError("durable process or input identity differs")
    source = Path(__file__).with_name("durable_runner.py").resolve()
    if receipt["before"]["inputs"]["implementation"].get("files", {}).get(digest(str(source)), {}).get("sha256") != source_hashes()["durable_runner.py"]:
        raise ValueError("original execution witness does not bind its actual supervisor implementation")
    return {"state": state, "directory": str(directory), "exit_code": receipt["exit_code"], "command_sha256": frame_digest({"arguments": receipt["before"]["command"][1:]}),
            "command_executable_sha256": executable_hash(receipt["before"]["command"][0]),
            "request_sha256": hashlib.sha256(request_bytes).hexdigest(),
            "directory_sha256": frame_digest({"directory": str(directory.resolve())}),
            "native_records": receipt["before"]["inputs"].get("native", {}).get("files", {}),
            "records": {key: record for domain in receipt["before"]["inputs"].values()
                        for key, record in domain.get("files", {}).items()},
            "declared_paths": [Path(path).resolve() for domain in request["inputs"].values()
                               for path in domain.get("paths", [])]}


def _diagnostic_bound(frame: dict[str, Any], context: dict[str, Any] | None, actors: set[int],
                      identify: Callable[[str, str], dict[str, str]] | None = None) -> bool:
    owner = frame.get("diagnostic_owner")
    if context is None or frame["pid"] not in actors or not isinstance(owner, dict) or not owner:
        return False
    if owner != (owner_identity if identify is None else identify)(owner.get("owner", ""), owner.get("function", "")):
        return False
    path = Path(frame["resolved_path"])
    if frame["event"] == "open":
        record = context["records"].get(digest(str(path)))
        return bool(record and path.is_file() and record["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest())
    return bool(path.is_dir() and any(path == bound or path.is_relative_to(bound) or bound.is_relative_to(path)
                                     for bound in context["declared_paths"]))


def review_capture(proof: dict[str, Any], *, expected_nodeids: set[str] | None = None) -> dict[str, Any]:
    """A missing/abrupt process, successor, event or sensor remains BLOCKED."""
    issues: list[str] = []
    bounded_auxiliary: list[dict[str, Any]] = []
    excluded_snapshots: list[dict[str, Any]] = []
    native_exits: dict[str, dict[str, Any]] = {}
    diagnostics: list[dict[str, Any]] = []
    frames: list[dict[str, Any]] = []
    epochs: dict[str, list[dict[str, Any]]] = {}
    closed_finishes: set[str] = set()
    closed_execs: set[str] = set()
    root_exit: int | None = None
    try:
        if proof.get("version") != VERSION or proof.get("observer_sources_sha256") != observer_source_hashes():
            raise ValueError("observer version or source bytes differ")
        identities: dict[tuple[str, str], dict[str, str]] = {}
        def identify(filename: str, function: str) -> dict[str, str]:
            key = (filename, function)
            if key not in identities:
                value = owner_identity(filename, function)
                source = "../plot_protocol/" + filename if filename in {"socket_client.py", "server.py"} else filename
                if value and value.get("source_sha256") != proof["observer_sources_sha256"].get(source):
                    raise ValueError("source owner differs from the bound review snapshot")
                identities[key] = value
            return identities[key]
        directory = Path(proof["directory"])
        if not directory.is_absolute() or not directory.is_dir() or directory.is_symlink():
            raise ValueError("observer output directory is absent or aliased")
        if proof.get("stream_sha256") != _streams(directory):
            raise ValueError("observer stream bytes or membership changed")
        epochs = _read_epochs(directory)
        indexes = {epoch: _review_index(records) for epoch, records in epochs.items()}
        node_scope = _scope(sorted(expected_nodeids)) if expected_nodeids is not None else None
        frames = [frame for records in epochs.values() for frame in records]
        pending = {path.stem for path in directory.glob("*.pending")}
        if any(not _HEX.fullmatch(name) or name not in epochs for name in pending):
            issues.append("orphan or malformed incomplete observer state")
        if pending:
            issues.append("observer terminal synchronization is incomplete:" + ",".join(sorted(pending)))
        if len({records[0]["run_id"] for records in epochs.values()}) != 1:
            raise ValueError("observer run identity differs")
        primary = proof.get("primary_pid")
        if type(primary) is not int or not any(records[0]["pid"] == primary for records in epochs.values()):
            raise ValueError("actual primary process startup is absent")
        starts = [records[0] for records in epochs.values()]
        child_starts_by_token: dict[tuple[Any, Any], list[dict[str, Any]]] = {}
        for start in starts:
            if start.get("continuation") is None:
                child_starts_by_token.setdefault((start.get("parent_epoch"), start.get("child_token")), []).append(start)
        durable = _durable_context(proof)
        if durable is None:
            issues.append("original durable primary execution witness is absent")
        elif durable["exit_code"] not in {0, 1}:
            issues.append("primary process has a non-normal or sensor-fatal actual exit")
        if durable:
            actual_exits = [frame for frame in frames if frame["event"] == "child_exit"
                            and frame["pid"] == durable["state"]["supervisor_pid"]
                            and frame.get("child_pid") == primary]
            if len(actual_exits) != 1 or actual_exits[0].get("returncode") != durable["exit_code"]:
                issues.append("durable primary exit differs from actual supervisor wait ledger")
        roots = [s for s in starts if not s.get("parent_epoch") and s.get("continuation") is None]
        if len(roots) != 1 or roots[0]["pid"] != proof.get("root_pid"):
            raise ValueError("unregistered startup or expected root process missing")
        caller = _durable_context(proof, root=True)
        if caller is None:
            issues.append("original root/caller external wait witness is absent")
        else:
            root_exit = caller["exit_code"]
            if (caller["command_sha256"] != roots[0].get("command_sha256")
                    or caller["command_executable_sha256"] != roots[0].get("executable_sha256")):
                issues.append("original root/caller command differs from actual first startup")
            if root_exit != 0:
                issues.append("original root/caller actual external wait did not exit successfully")
        if any(s.get("observer_sources_sha256") != proof["observer_sources_sha256"]
               or s.get("executable_sha256") != proof.get("interpreter_sha256")
               or s.get("python_runtime") != proof.get("python_runtime") for s in starts):
            raise ValueError("observer module or actual interpreter startup identity differs")
        if proof.get("python_runtime") != runtime_identity():
            raise ValueError("bound actual Python core or stdlib source bytes changed")
        if (proof.get("wrapper_inputs") != wrapper_inputs(dict(os.environ))
                or any(start.get("wrapper_inputs") != proof["wrapper_inputs"] for start in starts)):
            raise ValueError("wrapper helper, native runtime input or output boundary changed")
        scope = proof.get("expected_root_scope")
        if (not isinstance(scope, dict) or set(scope) != {"lexical", "canonical"}
                or scope != root_scope(scope["lexical"]) or any(s.get("root_scope") != scope for s in starts)):
            raise ValueError("frozen observed root scope differs from expected input boundary")
        if any(s.get("no_site") is not False or s.get("isolated") is not False
               or (s.get("bootstrap_sha256") not in {value for name, value in bootstrap_hashes().items() if name.endswith("sitecustomize.py")}
                   and not (s is roots[0] and s.get("activation") == identify("suite_evidence.py", "_audit_environment"))) for s in starts):
            issues.append("supported observer was not installed by the bound startup bootstrap")
        source_exclusions = {epoch + ":" + a["child_token"] for epoch, idx in indexes.items()
            for a in idx["event"].get("spawn_attempt", []) if excluded_bound(a.get("input_boundary"), a, epochs[epoch],
                primary=primary, expected_nodeids=expected_nodeids, directory=directory, durable=durable,
                suite_start=roots[0], audit_keys=AUDIT_KEYS, root_pid=proof["root_pid"], caller=caller,
                review_index=idx, node_scope=node_scope, identify=identify)}
        native_actors: dict[str, dict[str, Any]] = {}
        native_exits = validated_exits(frames, primary=primary, source_exclusions=source_exclusions, actors=native_actors)
        successors: dict[str, list[dict[str, Any]]] = {}
        for start in starts:
            continuation = start.get("continuation")
            if continuation is not None:
                if not isinstance(continuation, dict):
                    raise ValueError("malformed exec continuation")
                successors.setdefault(continuation.get("epoch", ""), []).append(start)
        for epoch, records in epochs.items():
            indexed = indexes[epoch]
            last = records[-1]
            if any(record["event"] in {"unsupported_spawn", "unsupported_exec"} for record in records):
                issues.append(f"unsupported process boundary:{epoch}")
            terminals = [r for r in records if r["event"] == "process_finish"]
            if terminals:
                if (len(terminals) != 1 or terminals[0] != last or last.get("recorded_events") != len(records) - 1
                        or type(last.get("recorded_events")) is not int or last.get("lost_events") != 0
                        or type(last.get("lost_events")) is not int):
                    issues.append(f"invalid terminal counter or late event:{epoch}")
                elif epoch not in pending:
                    closed_finishes.add(epoch)
            elif last["event"] == "exec_seal":
                next_starts = successors.get(epoch, [])
                expected = {"epoch": epoch, "sha256": last["sha256"], "sequence": last["sequence"],
                            "successor_token": last.get("successor_token")}
                if (len(next_starts) != 1 or next_starts[0].get("continuation") != expected
                        or next_starts[0]["pid"] != last["pid"]
                        or next_starts[0].get("executable_sha256") != last.get("expected_executable_sha256")
                        or next_starts[0]["monotonic_ns"] <= last["monotonic_ns"]
                        or last.get("recorded_events") != len(records) - 1 or last.get("lost_events") != 0):
                    issues.append(f"exec successor or seal counter missing:{epoch}")
                elif epoch not in pending:
                    closed_execs.add(epoch)
            else:
                issues.append(f"genuine terminal is absent:{epoch}")
            for start in successors.get(epoch, []):
                if last["event"] != "exec_seal" or start["pid"] != records[0]["pid"]:
                    issues.append(f"exec continuation has no final matching seal:{epoch}")
            for index, record in enumerate(records):
                if record["event"] == "exec_seal" and index != len(records) - 1:
                    following = records[index + 1:]
                    if not any(r["event"] == "exec_failed" and r.get("successor_token") == record.get("successor_token") for r in following):
                        issues.append(f"exec seal is followed by unsealed activity:{epoch}")
            attempts = indexed["event"].get("spawn_attempt", [])
            if len({r.get("child_token") for r in attempts}) != len(attempts):
                issues.append(f"duplicate successful-spawn token:{epoch}")
            for record in records:
                if record["event"] in {"child_spawn", "spawn_failed", "child_exit"}:
                    parents = [a for a in indexed["token"].get(record.get("child_token"), []) if a["event"] == "spawn_attempt" and a["sequence"] < record["sequence"]]
                    if len(parents) != 1:
                        issues.append(f"child ledger has no unique preceding attempt:{epoch}")
            for attempt in attempts:
                token = attempt.get("child_token")
                outcomes = [r for r in indexed["token"].get(token, []) if r["event"] in {"child_spawn", "spawn_failed"}]
                if not isinstance(token, str) or not _HEX.fullmatch(token) or len(outcomes) != 1:
                    issues.append(f"spawn outcome missing or ambiguous:{epoch}")
                    continue
                outcome = outcomes[0]
                if outcome["event"] == "spawn_failed":
                    continue
                child_starts = child_starts_by_token.get((epoch, token), [])
                transferred = bool(durable and attempt.get("durable_transfer_owner") == identify("durable_runner.py", "start_run")
                    and attempt.get("request_sha256") == durable["request_sha256"]
                    and attempt.get("directory_sha256") == durable["directory_sha256"]
                    and outcome.get("child_pid") == durable["state"]["supervisor_pid"])
                native_probe = bool(durable and native_probe_bound(attempt.get("input_boundary"), durable["native_records"], attempt))
                excluded = epoch + ":" + str(token) in source_exclusions
                auxiliary = attempt.get("input_boundary") == uname_boundary() or native_probe or excluded
                if (attempt.get("input_boundary") is not None and not auxiliary
                        and attempt["input_boundary"] != wrapper_boundary()):
                    issues.append(f"unsupported process input boundary:{epoch}:{token}")
                if auxiliary:
                    if excluded:
                        excluded_snapshots.append(attempt["input_boundary"]["process_proof"]["snapshot"])
                    bounded_auxiliary.append({"parent_epoch": epoch, "child_pid": outcome["child_pid"],
                                              "input_boundary": attempt["input_boundary"],
                                              "terminal_counters": "UNKNOWN" if excluded else "not_observed_non_python_macho_inspector" if native_probe else "not_observed_non_python_kernel_query"})
                    if child_starts:
                        issues.append(f"native auxiliary boundary unexpectedly starts Python:{epoch}:{token}")
                elif len(child_starts) != 1 or child_starts[0]["pid"] != outcome.get("child_pid") or (child_starts[0]["parent_pid"] != records[0]["pid"] and not transferred):
                    issues.append(f"successful child startup missing or mismatched:{epoch}:{token}")
                elif child_starts[0].get("executable_sha256") != attempt.get("expected_executable_sha256"):
                    issues.append(f"child executable differs from successful launch:{epoch}:{token}")
                elif child_starts[0]["monotonic_ns"] <= attempt["monotonic_ns"]:
                    issues.append(f"child startup precedes successful launch attempt:{epoch}:{token}")
                exits = [r for r in indexed["token"].get(token, []) if r["event"] == "child_exit"]
                kernel_exit = native_exits.get(epoch + ":" + token)
                if not exits and kernel_exit is not None and kernel_exit["returncode"] == 0:
                    pass  # Genuine kernel status is a separate kind, never a parent wait.
                elif not exits or len(exits) > 1 or any(type(r.get("returncode")) is not int or (not excluded and (r["returncode"] < 0 or r["returncode"] in {78, 79})) or r.get("child_pid") != outcome.get("child_pid") for r in exits):
                    issues.append(f"child signalled or exit ledger invalid:{epoch}:{token}")
                elif kernel_exit is not None and exits[0]["returncode"] != kernel_exit["returncode"]:
                    issues.append(f"parent wait and genuine kernel status disagree:{epoch}:{token}")
                elif auxiliary and not excluded and exits[0]["returncode"] != 0:
                    issues.append(f"native auxiliary query did not complete successfully:{epoch}:{token}")
        for start in starts:
            if start.get("continuation") is not None:
                if start["continuation"].get("epoch") not in epochs:
                    issues.append(f"exec predecessor is absent:{start['epoch']}")
            elif start.get("parent_epoch"):
                parent = indexes.get(start["parent_epoch"], {}).get("token", {}).get(start.get("child_token"), [])
                if not any(r["event"] == "child_spawn" and r.get("child_token") == start.get("child_token") and r.get("child_pid") == start["pid"] for r in parent):
                    issues.append(f"child has no successful parent spawn:{start['epoch']}")
        if expected_nodeids is not None:
            observed = [r for r in frames if r["pid"] == primary]
            collections = [r for r in observed if r["event"] == "pytest_collection"]
            sessions = [r for r in observed if r["event"] == "pytest_session_finish"]
            reports = [r for r in observed if r["event"] == "pytest_report"]
            expected_phases = Counter({(node, phase): 1 for node in expected_nodeids for phase in ("setup", "call", "teardown")})
            actual = Counter((r.get("test_nodeid"), r.get("phase")) for r in reports)
            if (len(collections) != 1 or collections[0].get("nodeids") is None
                    or len(collections[0]["nodeids"]) != len(expected_nodeids)
                    or set(collections[0]["nodeids"]) != expected_nodeids or len(sessions) != 1
                    or sessions[0].get("exitstatus") not in {0, 1} or actual != expected_phases
                    or any(r.get("outcome") not in {"passed", "failed"} for r in reports)):
                issues.append("complete primary collection/report/session evidence is absent")
            if roots[0].get("activation") == identify("suite_evidence.py", "_audit_environment"):
                if node_scope is not None:
                    node_scope["suite_root_sha256"] = roots[0]["sha256"]
                issues.extend(review_sockets(frames, primary=primary, scope=node_scope,
                    records=durable["records"] if durable else {}, native_exits=native_exits,
                    source_exclusions=source_exclusions, native_actors=native_actors))
        actors = {proof["root_pid"]}
        if durable:
            actors.add(durable["state"]["supervisor_pid"])
        for records in epochs.values():
            collections = [r for r in records if r["event"] == "pytest_collection"]
            if (expected_nodeids is not None and len(collections) == 1
                    and set(collections[0]["nodeids"]) == expected_nodeids
                    and not any(r["event"] == "pytest_report" for r in records)):
                actors.add(records[0]["pid"])
        metadata_owners = [identify("process_private_exclusion.py", name) for name in ("_members", "_evidence_inodes")]
        members: dict[Any, list[dict[str, Any] | None]] = {}
        for snapshot in excluded_snapshots:
            for path, row in snapshot["members"].items():
                members.setdefault(path, []).append(row)
        diagnostics = [r for r in frames if r["event"] in {"open", "os.scandir", "os.listdir"}
                       and ((not r["nodeid"] and _diagnostic_bound(r, durable, actors, identify))
                            or (r["pid"] in {primary, proof["root_pid"]} and metadata_diagnostic(r, excluded_snapshots, owners=metadata_owners, members=members)))]
        fatal_pids = {frame["child_pid"] for frame in frames if frame["event"] == "child_exit"
                      and frame.get("returncode") in {78, 79}}
        fatal_pids.update(fact["identity"]["pid"] for fact in native_exits.values() if fact["returncode"] in {78, 79})
        if root_exit != 0:
            fatal_pids.add(proof["root_pid"])
        closed_finishes.difference_update(epoch for epoch, records in epochs.items() if records[0]["pid"] in fatal_pids)
        closed_execs.difference_update(epoch for epoch, records in epochs.items() if records[0]["pid"] in fatal_pids)
        if proof["observer_sources_sha256"] != observer_source_hashes():
            raise ValueError("observer source bytes changed during review")
    except (OSError, UnicodeError, ValueError, TypeError, KeyError) as exc:
        issues.append(str(exc))
    return {"status": "BLOCKED" if issues else "COMPLETE", "capture_complete": not issues,
            "issues": issues, "frames": frames, "epoch_count": len(epochs),
            "bounded_auxiliary": bounded_auxiliary,
            "kernel_exit_observations": list(native_exits.values()),
            "diagnostic_observations": diagnostics,
            "raw_terminal_frame_count": sum(record["event"] == "process_finish" for record in frames),
            "root_actual_exit": root_exit,
            "genuine_finish_count": len(closed_finishes), "exec_seal_count": len(closed_execs)}
