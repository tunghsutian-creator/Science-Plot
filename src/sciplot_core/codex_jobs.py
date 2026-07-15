from __future__ import annotations

import json
import shutil
import subprocess
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sciplot_core._paths import REPO_ROOT
from sciplot_core._utils import json_safe
from sciplot_core.operation_modes import assisted_cleanup_mode_payload

HANDOFF_FILENAME = "sciplot_codex_handoff.json"
STATUS_FILENAME = "status.json"
STDOUT_FILENAME = "stdout.jsonl"
STDERR_FILENAME = "stderr.log"
FINAL_MESSAGE_FILENAME = "final_message.txt"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def codex_available(codex_binary: str = "codex") -> bool:
    return shutil.which(codex_binary) is not None


def _job_root(project_dir: Path) -> Path:
    return project_dir / "codex_jobs"


def _new_job_dir(project_dir: Path) -> Path:
    job_id = f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    path = _job_root(project_dir) / job_id
    path.mkdir(parents=True, exist_ok=False)
    return path


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(json_safe(payload), indent=2, ensure_ascii=False), encoding="utf-8")


def _default_required_checks(plot_request: Path | None, run_output: Path | None) -> list[str]:
    checks = [
        "python -m compileall -q src/sciplot_core src/sciplot_recipes",
        "skill/scripts/sciplot doctor --json",
    ]
    if plot_request is not None:
        checks.append(f"skill/scripts/sciplot run {plot_request}")
    if run_output is not None:
        checks.append(f"skill/scripts/sciplot qa {run_output}")
    return checks


def _allowed_paths() -> list[str]:
    return [
        "src/sciplot_core/materials_rules.py",
        "src/sciplot_core/semantic.py",
        "src/sciplot_core/workflow.py",
        "src/sciplot_core/one_step.py",
        "src/sciplot_core/policy.py",
        "src/sciplot_core/delivery.py",
        "src/sciplot_core/intake.py",
        "src/sciplot_recipes/",
        "tests/",
        "examples/",
        "AGENTS.md",
        "README.md",
        "skill/SKILL.md",
    ]


def build_codex_handoff(
    *,
    project_dir: str | Path,
    plot_request: str | Path | None = None,
    run_output: str | Path | None = None,
    intervention_request: str | Path | None = None,
    failure: str | None = None,
    user_goal: str | None = None,
) -> dict[str, Any]:
    request_path = Path(plot_request).expanduser().resolve() if plot_request else None
    output_path = Path(run_output).expanduser().resolve() if run_output else None
    intervention_path = Path(intervention_request).expanduser().resolve() if intervention_request else None
    return {
        "kind": "sciplot_codex_handoff",
        "version": 1,
        "created_at": _now(),
        "operation_mode": assisted_cleanup_mode_payload(reason="rule_or_data_repair", provider="codex"),
        "assistant_provider": "codex",
        "assistant_role": "codex_controlled_assisted_plotting_and_repair",
        "control_policy": {
            "frontend_default": "independent",
            "activation": "user_requests_codex_or_pipeline_blocks",
            "user_switch_required": False,
        },
        "base_pipeline_policy": "normal_mode_must_not_require_codex",
        "project_dir": str(Path(project_dir).expanduser().resolve()),
        "plot_request": str(request_path) if request_path else None,
        "run_output": str(output_path) if output_path else None,
        "intervention_request": str(intervention_path) if intervention_path else None,
        "failure": failure,
        "allowed_paths": _allowed_paths(),
        "required_checks": _default_required_checks(request_path, output_path),
        "review_policy": {
            "default": "structured_qa_summary",
            "image_review_required": False,
            "image_review_triggers": ["qa_failure", "low_confidence_semantics", "explicit_user_request"],
        },
        "user_goal": user_goal
        or (
            "Repair the SciPlot semantic/recipe or cleanup gap, add focused tests or fixtures, "
            "rerun the request, and verify QA."
        ),
    }


def _status_payload(
    *,
    job_dir: Path,
    status: str,
    handoff: dict[str, Any],
    command: list[str] | None = None,
    returncode: int | None = None,
    error: str | None = None,
    final_message: str | None = None,
    created_at: str | None = None,
    started_at: str | None = None,
    completed_at: str | None = None,
    touched_files: list[str] | None = None,
    verification_results: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "kind": "sciplot_codex_job",
        "job_id": job_dir.name,
        "job_dir": str(job_dir),
        "status": status,
        "created_at": created_at or handoff.get("created_at") or _now(),
        "started_at": started_at,
        "completed_at": completed_at,
        "returncode": returncode,
        "command": command or [],
        "operation_mode": handoff.get("operation_mode"),
        "assistant_provider": handoff.get("assistant_provider"),
        "handoff_path": str(job_dir / HANDOFF_FILENAME),
        "stdout_log": str(job_dir / STDOUT_FILENAME),
        "stderr_log": str(job_dir / STDERR_FILENAME),
        "final_message": final_message,
        "error": error,
        "touched_files": touched_files or [],
        "verification_results": verification_results or [],
        "handoff": handoff,
    }


def _collect_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list | tuple | set):
        collected: list[str] = []
        for item in value:
            collected.extend(_collect_strings(item))
        return collected
    return []


def _extract_jsonl_metadata(stdout_text: str) -> tuple[list[str], list[dict[str, Any]]]:
    touched: set[str] = set()
    verifications: list[dict[str, Any]] = []
    file_keys = ("touched_files", "changed_files", "modified_files", "files")
    verification_keys = ("verification_results", "checks", "required_checks", "test_results")
    command_keys = ("command", "cmd", "check")
    for line in stdout_text.splitlines():
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        candidates = [payload]
        for nested_key in ("data", "event", "item", "msg", "result"):
            nested = payload.get(nested_key)
            if isinstance(nested, dict):
                candidates.append(nested)
        for item in candidates:
            for key in file_keys:
                for value in _collect_strings(item.get(key)):
                    if value:
                        touched.add(value)
            for key in verification_keys:
                value = item.get(key)
                if isinstance(value, list):
                    for check in value:
                        if isinstance(check, dict):
                            verifications.append(dict(check))
                        elif isinstance(check, str):
                            verifications.append({"command": check})
                elif isinstance(value, dict):
                    verifications.append(dict(value))
                elif isinstance(value, str):
                    verifications.append({"command": value})
            if any(key in item for key in command_keys) and any(
                key in item for key in ("status", "returncode", "exit_code", "output")
            ):
                verifications.append(
                    {
                        key: item[key]
                        for key in ("command", "cmd", "check", "status", "returncode", "exit_code", "output")
                        if key in item
                    }
                )
    return sorted(touched), verifications


def _read_last_message(stdout_text: str) -> str:
    last = ""
    for line in stdout_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        last = stripped
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        for key in ("content", "message", "text"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                last = value.strip()
        if isinstance(payload.get("msg"), dict):
            content = payload["msg"].get("content")
            if isinstance(content, str) and content.strip():
                last = content.strip()
    return last


def _prompt_for_handoff(handoff_path: Path) -> str:
    return (
        "You are working on the SciPlot repository as the optional assistant repair provider. "
        f"Read {handoff_path}, follow AGENTS.md, do not edit src/sciplot_core/_vendor, "
        "patch only the public SciPlot wrapper/recipe/test layer needed for this handoff, "
        "then run the required checks and report exact results."
    )


def _run_codex_job(job_dir: Path, handoff: dict[str, Any], command: list[str]) -> None:
    status_path = job_dir / STATUS_FILENAME
    started_at = _now()
    _write_json(
        status_path,
        _status_payload(job_dir=job_dir, status="running", handoff=handoff, command=command, started_at=started_at),
    )
    try:
        process = subprocess.Popen(
            command,
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        stdout_text, stderr_text = process.communicate()
        (job_dir / STDOUT_FILENAME).write_text(stdout_text or "", encoding="utf-8")
        (job_dir / STDERR_FILENAME).write_text(stderr_text or "", encoding="utf-8")
        final_message = _read_last_message(stdout_text or "")
        touched_files, verification_results = _extract_jsonl_metadata(stdout_text or "")
        (job_dir / FINAL_MESSAGE_FILENAME).write_text(final_message, encoding="utf-8")
        status = "succeeded" if process.returncode == 0 else "failed"
        _write_json(
            status_path,
            _status_payload(
                job_dir=job_dir,
                status=status,
                handoff=handoff,
                command=command,
                returncode=process.returncode,
                final_message=final_message,
                started_at=started_at,
                completed_at=_now(),
                touched_files=touched_files,
                verification_results=verification_results,
            ),
        )
    except Exception as exc:
        (job_dir / STDERR_FILENAME).write_text(str(exc), encoding="utf-8")
        _write_json(
            status_path,
            _status_payload(
                job_dir=job_dir,
                status="failed",
                handoff=handoff,
                command=command,
                error=str(exc),
                started_at=started_at,
                completed_at=_now(),
            ),
        )


def start_codex_job(
    *,
    project_dir: str | Path,
    plot_request: str | Path | None = None,
    run_output: str | Path | None = None,
    intervention_request: str | Path | None = None,
    failure: str | None = None,
    user_goal: str | None = None,
    run_async: bool = True,
    codex_binary: str = "codex",
) -> dict[str, Any]:
    project_path = Path(project_dir).expanduser().resolve()
    project_path.mkdir(parents=True, exist_ok=True)
    job_dir = _new_job_dir(project_path)
    handoff = build_codex_handoff(
        project_dir=project_path,
        plot_request=plot_request,
        run_output=run_output,
        intervention_request=intervention_request,
        failure=failure,
        user_goal=user_goal,
    )
    handoff_path = job_dir / HANDOFF_FILENAME
    _write_json(handoff_path, handoff)
    if not codex_available(codex_binary):
        status = _status_payload(
            job_dir=job_dir,
            status="disabled",
            handoff=handoff,
            error=f"`{codex_binary}` was not found on PATH.",
        )
        _write_json(job_dir / STATUS_FILENAME, status)
        return status

    command = [
        codex_binary,
        "exec",
        "-C",
        str(REPO_ROOT),
        "--sandbox",
        "workspace-write",
        "--ask-for-approval",
        "never",
        "--json",
        _prompt_for_handoff(handoff_path),
    ]
    initial_status = _status_payload(job_dir=job_dir, status="queued", handoff=handoff, command=command)
    _write_json(job_dir / STATUS_FILENAME, initial_status)
    if run_async:
        thread = threading.Thread(target=_run_codex_job, args=(job_dir, handoff, command), daemon=True)
        thread.start()
        return initial_status
    _run_codex_job(job_dir, handoff, command)
    return load_codex_job(job_dir)


def load_codex_job(job_dir: str | Path) -> dict[str, Any]:
    path = Path(job_dir).expanduser().resolve() / STATUS_FILENAME
    return json.loads(path.read_text(encoding="utf-8"))


def list_codex_jobs(project_dir: str | Path) -> list[dict[str, Any]]:
    root = _job_root(Path(project_dir).expanduser().resolve())
    if not root.exists():
        return []
    jobs = []
    for status_path in sorted(root.glob(f"*/{STATUS_FILENAME}"), reverse=True):
        try:
            jobs.append(json.loads(status_path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return jobs


__all__ = [
    "HANDOFF_FILENAME",
    "build_codex_handoff",
    "codex_available",
    "list_codex_jobs",
    "load_codex_job",
    "start_codex_job",
]
