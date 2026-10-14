"""Generated process controls, using the existing genuine execution witness."""
from __future__ import annotations

from contextlib import nullcontext
import json
import os
from pathlib import Path
import time
from typing import Any

from sciplot_core.verification.durable_runner import prepare_run, run_status, start_run
from sciplot_core.verification.evidence_identity import DOMAINS
from sciplot_core.verification.private_capture import capture_proof, review_capture
from sciplot_core.verification.public_control_boundary import generated_control


def execute_observed(root: Path, command: list[str], environment: dict[str, str],
                     output: Path, roots: list[str], *, nodes: set[str] | None = None,
                     timeout: float = 60, keep_public_guard: bool = False) -> tuple[dict[str, Any], dict[str, Any]]:
    inputs = {}
    for domain in DOMAINS:
        path = root / f"generated-identity-{domain}"
        path.write_text("process observation self-test; no scientific closure claim")
        inputs[domain] = {"paths": [str(path)]}
    implementation = Path(__file__).parents[1] / "src/sciplot_core/verification/durable_runner.py"
    inputs["implementation"]["paths"].append(str(implementation))
    directory = root / ".tmp_verify/process-witness"
    spec = {"repo_root": str(root), "command": command,
            "scope": {"kind": "pytest" if nodes is not None else "process",
                      "closure_policy": "generated process-observer contract; not scientific input acceptance"},
            "selected_tests": sorted(nodes) if nodes is not None else ["synthetic:process-observation"],
            "inputs": inputs, "environment": environment,
            "corpus": {"mode": "synthetic", "complete": True, "policy": "generated observer self-test"}}
    # Only missing-startup controls need the private-absent exception. Ordinary
    # receipt controls keep their full guard declaration and owned bootstrap.
    with (nullcontext(environment) if keep_public_guard else generated_control(
            environment, command, root, durable=True, directory=directory)) as prepared_environment:
        directory, original_environment, request_hash = prepare_run(
            directory=directory, spec={**spec, "environment": prepared_environment})
    settings = {key: value for key, value in original_environment.items()
                if key.startswith("SCIPLOT_PRIVATE_AUDIT_") or key == "SCIPLOT_VERIFY_FINISH"}
    outer_environment = {key: value for key, value in original_environment.items() if key not in settings}
    code = ("import os,sys;from pathlib import Path;"
            f"os.environ.update({settings!r});"
            "from sciplot_core.verification.private_observer import install;install();"
            "from sciplot_core.verification.durable_runner import supervise;"
            f"sys.exit(supervise(Path({str(directory)!r}),{request_hash!r}))")
    witness = root / ".tmp_verify/root-execution-witness"
    witness_spec = {**spec, "command": [command[0], "-c", code], "environment": outer_environment,
                    "scope": {"kind": "process", "closure_policy": "actual OS wait for generated observer root"},
                    "selected_tests": ["synthetic:observer-root-actual-exit"]}
    launch_environment = {**outer_environment, **{key: value for key, value in environment.items()
                          if key.startswith("SCIPLOT_PUBLIC_")}}
    # Context exit verifies Git through subprocess; wait before that can reap
    # the discarded supervisor handle via subprocess._cleanup.
    with (nullcontext(launch_environment) if keep_public_guard else generated_control(
            launch_environment, witness_spec["command"], root, durable=True,
            directory=witness)) as child_environment:
        start = start_run(directory=witness, spec={**witness_spec, "environment": child_environment})
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state_path = witness / "state.json"
            state = json.loads(state_path.read_bytes()) if state_path.is_file() else {}
            if state.get("phase") in {"completed", "blocked"}:
                break
            time.sleep(0.02)
        else:
            raise AssertionError("generated observer witness did not complete")
        # This test is the actual OS parent of the supervisor, not a declared exit.
        _, status = os.waitpid(start["supervisor_pid"], 0)
        supervisor_exit = os.waitstatus_to_exitcode(status)
    execution = run_status(directory)
    if "child_pid" not in state:
        raise AssertionError((state, (directory / "supervisor.log").read_text()))
    inner_state = json.loads((directory / "state.json").read_bytes())
    proof = capture_proof(output, primary_pid=inner_state["child_pid"], root_pid=state["child_pid"],
                          expected_roots=roots, durable_directory=directory, root_execution_directory=witness)
    result = review_capture(proof, expected_nodeids=nodes)
    completion = json.loads((directory / "completion.json").read_bytes()) if (directory / "completion.json").is_file() else {}
    result.update(actual_returncode=completion.get("exit_code"), actual_supervisor_returncode=supervisor_exit,
                  execution=execution, stdout=(directory / "command.log").read_text(), stderr="")
    return proof, result


def launch_generated_suite(command: list[str], environment: dict[str, str], cwd: Path,
                           *, timeout: float = 60) -> tuple[int, int, bytes, Path]:
    """Actually wait for the source-owned suite caller through the existing runner."""
    inputs = {}
    for domain in DOMAINS:
        path = cwd / f"outer-suite-{domain}"
        path.write_text("generated suite caller witness; not scientific acceptance")
        inputs[domain] = {"paths": [str(path)]}
    implementation = Path(__file__).parents[1] / "src/sciplot_core/verification/durable_runner.py"
    inputs["implementation"]["paths"].append(str(implementation))
    witness = cwd / ".tmp_verify/suite-root-witness"
    # Keep the genuine wait inside the grant, before exit-time Git verification.
    with generated_control(environment, command, cwd, durable=True, directory=witness) as child_environment:
        start = start_run(directory=witness, spec={
            "repo_root": str(cwd), "command": command, "environment": child_environment,
            "scope": {"kind": "process", "closure_policy": "actual OS wait for generated suite caller"},
            "selected_tests": ["synthetic:suite-root-actual-exit"], "inputs": inputs,
            "corpus": {"mode": "synthetic", "complete": True, "policy": "generated caller control"}})
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state_path = witness / "state.json"
            state = json.loads(state_path.read_bytes()) if state_path.is_file() else {}
            if state.get("phase") in {"completed", "blocked"}:
                break
            time.sleep(.02)
        else:
            raise AssertionError("actual suite caller witness did not complete")
        os.waitpid(start["supervisor_pid"], 0)
    if run_status(witness)["status"] not in {"PASS", "FAIL"}:
        raise AssertionError((state, (witness / "supervisor.log").read_text()))
    completion = json.loads((witness / "completion.json").read_bytes())
    return state["child_pid"], completion["exit_code"], (witness / "command.log").read_bytes(), witness
