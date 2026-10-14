"""Fail-closed local verification receipts; never scientific document authority.

Hashes detect drift, not malicious forgery. Receipts are local developer evidence,
not signed attestations, and are never executed while checking reuse.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any

from sciplot_core.verification.evidence_identity import digest, identity_valid

ARTIFACT_NAMES = frozenset({"request.json", "command.log", "finish.json", "completion.json"})

def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    """Replace one local state file only after its bytes are durable."""
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, sort_keys=True, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def make_receipt(*, before: dict[str, Any], after: dict[str, Any],
                 exit_code: int | None, session_finish: dict[str, Any] | None,
                 wall_seconds: float, artifacts: dict[str, str],
                 provenance: dict[str, Any] | None = None) -> dict[str, Any]:
    """Seal completion; only exact completed selection can produce PASS."""
    reason = "completed"
    status = "PASS"
    if not identity_valid(before) or not identity_valid(after):
        status, reason = "BLOCKED", "invalid_identity"
    elif before != after:
        status, reason = "BLOCKED", "input_drift"
    elif not isinstance(session_finish, dict) or session_finish.get("complete") is not True:
        status, reason = "BLOCKED", "session_finish_missing"
    elif type(exit_code) is not int or session_finish.get("exit_code") != exit_code:
        status, reason = "BLOCKED", "exit_mismatch"
    elif exit_code == 5 and not session_finish.get("selected_tests"):
        status, reason = "NO_TESTS", "empty_selection"
    elif exit_code < 0 or (before["scope"]["kind"] == "pytest" and exit_code in {2, 3, 4}):
        status, reason = "BLOCKED", "execution_interrupted_or_unavailable"
    elif exit_code != 0:
        status, reason = "FAIL", "command_failed"
    elif session_finish.get("selected_tests") != before["selected_tests"]:
        status, reason = "BLOCKED", "selection_mismatch"
    elif before["scope"]["kind"] == "pytest" and not before["selected_tests"]:
        status, reason = "NO_TESTS", "empty_selection"
    elif before["scope"]["kind"] == "pytest" and session_finish.get("executed_tests") != before["selected_tests"]:
        status, reason = "BLOCKED", "execution_incomplete"
    elif set(session_finish) != ({"complete", "exit_code", "selected_tests", "executed_tests"}
                                if before["scope"]["kind"] == "pytest"
                                else {"complete", "exit_code", "selected_tests"}):
        status, reason = "BLOCKED", "invalid_session_finish"
    if type(wall_seconds) not in (int, float) or not math.isfinite(wall_seconds) or wall_seconds < 0:
        raise ValueError("wall_seconds must be a finite monotonic duration")
    if not isinstance(artifacts, dict) or set(artifacts) != ARTIFACT_NAMES or any(
        not isinstance(name, str) or not _sha(value) for name, value in artifacts.items()
    ):
        raise ValueError("immutable execution artifact hashes are required")
    payload = {
        "kind": "sciplot_verification_receipt", "version": 1,
        "status": status, "reason": reason, "reused": False,
        "before": before, "after": after, "exit_code": exit_code,
        "session_finish": session_finish, "wall_seconds": wall_seconds,
        "artifacts": artifacts, "provenance": provenance or {},
    }
    return {**payload, "sha256": digest(payload)}


def _sha(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def check_reuse(receipt: object, current: dict[str, Any], *,
                artifacts: dict[str, str]) -> dict[str, Any]:
    """Compare fresh identities/artifact hashes; never follow receipt paths.

The caller hashes the known local immutable artifacts independently. A receipt
cannot choose a command to run or a path to read during this operation.
"""
    blocked = {"status": "BLOCKED", "reused": False, "reason": "invalid_receipt"}
    try:
        if not isinstance(receipt, dict):
            return blocked
        if receipt.get("sha256") != digest({key: value for key, value in receipt.items() if key != "sha256"}):
            return blocked
        expected = make_receipt(**{key: receipt[key] for key in (
            "before", "after", "exit_code", "session_finish", "wall_seconds", "artifacts", "provenance",
        )})
        if receipt != expected or not identity_valid(current):
            return blocked
        if receipt["status"] != "PASS":
            return {**blocked, "reason": "receipt_not_passed"}
        if receipt["before"] != current:
            return {**blocked, "reason": "identity_mismatch"}
        if artifacts != receipt["artifacts"]:
            return {**blocked, "reason": "artifact_drift"}
        return {"status": "PASS", "reused": True, "reason": "exact_evidence_reused",
                "receipt_sha256": receipt["sha256"], "scope": current["scope"],
                "selected_tests": current["selected_tests"],
                "original_wall_seconds": receipt["wall_seconds"]}
    except (KeyError, TypeError, ValueError, OverflowError, RecursionError):
        return blocked


def load_receipt(path: Path) -> object:
    """Read bounded JSON only; malformed local evidence becomes unavailable."""
    try:
        if path.is_symlink() or path.stat().st_size > 32 * 1024 * 1024:
            return None
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object,
                          parse_float=_finite_float, parse_constant=_finite_float)
    except (OSError, ValueError, UnicodeError, RecursionError):
        return None


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate evidence key")
        result[key] = value
    return result


def _finite_float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("nonfinite evidence number")
    return result
