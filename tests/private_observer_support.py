"""Generated process controls, using the existing genuine execution witness."""
from __future__ import annotations

import json
import os
from pathlib import Path
import time
from typing import Any

from sciplot_core.verification.durable_runner import run_status, start_run
from sciplot_core.verification.evidence_identity import DOMAINS
from sciplot_core.verification.private_capture import capture_proof, review_capture


def execute_observed(root: Path, command: list[str], environment: dict[str, str],
                     output: Path, roots: list[str], *, nodes: set[str] | None = None,
                     timeout: float = 60) -> tuple[dict[str, Any], dict[str, Any]]:
    inputs = {}
    for domain in DOMAINS:
        path = root / f"generated-identity-{domain}"
        path.write_text("process observation self-test; no scientific closure claim")
        inputs[domain] = {"paths": [str(path)]}
    directory = root / ".tmp_verify/process-witness"
    spec = {"repo_root": str(root), "command": command,
            "scope": {"kind": "pytest" if nodes is not None else "process",
                      "closure_policy": "generated process-observer contract; not scientific input acceptance"},
            "selected_tests": sorted(nodes) if nodes is not None else ["synthetic:process-observation"],
            "inputs": inputs, "environment": environment,
            "corpus": {"mode": "synthetic", "complete": True, "policy": "generated observer self-test"}}
    start = start_run(directory=directory, spec=spec)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state_path = directory / "state.json"
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
    proof = capture_proof(output, primary_pid=state["child_pid"], root_pid=start["supervisor_pid"],
                          expected_roots=roots, durable_directory=directory)
    result = review_capture(proof, expected_nodeids=nodes)
    completion = json.loads((directory / "completion.json").read_bytes()) if (directory / "completion.json").is_file() else {}
    result.update(actual_returncode=completion.get("exit_code"), actual_supervisor_returncode=supervisor_exit,
                  execution=execution, stdout=(directory / "command.log").read_text(), stderr="")
    return proof, result
