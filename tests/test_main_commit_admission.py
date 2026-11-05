"""Official source-check admission never claims a new environment execution."""

from __future__ import annotations

import copy
import io
import json
from pathlib import Path
import sys
import urllib.error

import pytest

from main_commit_admission_records import RECORDED_AFFECTED_JOB
from sciplot_core.verification import main_commit_admission as gate

SHA = "a" * 40


def context(**changes):
    return {
        "GITHUB_EVENT_NAME": "push",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_SHA": SHA,
        "GITHUB_REPOSITORY": gate.REPOSITORY,
        "GITHUB_WORKFLOW_SHA": SHA,
        "GITHUB_RUN_ID": "200",
        "GITHUB_WORKFLOW_REF": f"{gate.REPOSITORY}/{gate.WORKFLOW}@refs/heads/main",
        **changes,
    }


def future_origin():
    # Synthetic success in the original official API shape: it is NOT a claim
    # that any historical run executed the new checkout/admission steps.
    run = {
        "id": 100,
        "run_number": 10,
        "run_attempt": 1,
        "head_sha": SHA,
        "event": "push",
        "path": gate.WORKFLOW,
        "status": "completed",
        "conclusion": "success",
        "repository": {"full_name": gate.REPOSITORY, "fork": False},
        "head_repository": {"full_name": gate.REPOSITORY, "fork": False},
    }
    job = copy.deepcopy(RECORDED_AFFECTED_JOB)
    job.update(run_id=100, run_attempt=1, head_sha=SHA)
    # Literal complete workflow obligations, independent of the production list.
    names = [
        "Require a valid scheduling plan",
        "Run actions/checkout@v4",
        "Verify exact workflow checkout",
        "Check main commit admission",
        "Plan bounded public feedback",
        "Enforce minimal runtime distribution",
        "Compile SciPlot-owned Python",
        "Install matching system Python and Qt toolchain",
        "Install local runtime",
        "Verify Qt build and runtime identity",
        "Verify Chinese glyph fallback in the system Qt runtime",
        "Run lint gate",
        "Run shared source contracts",
        "Run scoped static type gate",
        "Build vendored Veusz helpers",
        "Verify vendored Veusz helpers",
        "Verify minimal wheel surface",
        "Check known native CI regressions before the public suites",
        "Run reviewed public focused behavior",
        "Run reviewed public comprehensive behavior",
        "Verify source-checkout wrapper bootstrap",
        "Run readiness check",
        "Run fixture-free lifecycle smoke",
    ]
    job["steps"] = [
        {"name": name, "number": number, "status": "completed", "conclusion": "success"}
        for number, name in enumerate(names, 1)
    ]
    job["steps"].append(
        {
            "name": "Run reviewed affected public feedback",
            "number": len(names) + 1,
            "status": "completed",
            "conclusion": "skipped",
        }
    )
    return {"total_count": 1, "workflow_runs": [run]}, {"total_count": 1, "jobs": [job]}


def reader(runs, jobs, final=None):
    calls = []

    def read(path):
        calls.append(path)
        if "/attempts/" in path:
            assert "/100/attempts/1/jobs?per_page=100" in path
            return copy.deepcopy(jobs)
        assert "?head_sha=" + SHA in path and "status=" not in path and "event=" not in path
        return copy.deepcopy(final if final is not None and len(calls) > 1 else runs)

    return read, calls


def test_complete_source_check_is_referenced_without_current_execution():
    runs, jobs = future_origin()
    read, calls = reader(runs, jobs)
    result = gate.admit(context(), read)
    assert (
        result["referenced"] is True and result["current_run_executed_tests"] is False
    )
    assert (
        result["claim"] == "source_commit_admission_only"
        and result["origin_attempt"] == 1
    )
    assert result["origin_url"].endswith("/actions/runs/100/attempts/1")
    assert len(calls) == 3


@pytest.mark.parametrize(
    "mutation",
    [
        "wrong_sha",
        "wrong_repo",
        "fork",
        "event",
        "workflow",
        "self",
        "failed",
        "in_progress",
        "cancelled",
        "partial",
        "wrong_attempt",
        "wrong_job_sha",
        "missing_job",
        "duplicate_job",
        "missing_step",
        "skipped_full_step",
        "duplicate_step",
        "unknown_step",
        "unknown_status",
        "bad_step_number",
        "unordered_steps",
        "missing_attempt",
        "run_bool",
        "incomplete_runs",
        "incomplete_jobs",
        "no_origin",
    ],
)
def test_ineligible_or_unknown_original_evidence_executes_fresh(mutation):
    runs, jobs = future_origin()
    run, job = runs["workflow_runs"][0], jobs["jobs"][0]
    if mutation == "wrong_sha":
        run["head_sha"] = "b" * 40
    elif mutation == "wrong_repo":
        run["repository"]["full_name"] = "other/repo"
    elif mutation == "fork":
        run["head_repository"]["fork"] = True
    elif mutation == "event":
        run["event"] = "pull_request"
    elif mutation == "workflow":
        run["path"] = "other.yml"
    elif mutation == "self":
        run["id"] = 200
    elif mutation in {"failed", "cancelled"}:
        run["conclusion"] = mutation
    elif mutation == "in_progress":
        run.update(status="in_progress", conclusion=None)
    elif mutation == "partial":
        job["conclusion"] = "failure"
    elif mutation == "wrong_attempt":
        job["run_attempt"] = 2
    elif mutation == "wrong_job_sha":
        job["head_sha"] = "b" * 40
    elif mutation == "missing_job":
        jobs.update(total_count=0, jobs=[])
    elif mutation == "duplicate_job":
        jobs["jobs"].append(copy.deepcopy(job))
        jobs["total_count"] = 2
    elif mutation == "missing_step":
        job["steps"].pop(2)
    elif mutation == "skipped_full_step":
        job["steps"][18]["conclusion"] = "skipped"
    elif mutation == "duplicate_step":
        job["steps"].append(copy.deepcopy(job["steps"][0]))
    elif mutation == "unknown_step":
        job["steps"].append(
            {
                "name": "new obligation",
                "number": 99,
                "status": "completed",
                "conclusion": "success",
            }
        )
    elif mutation == "unknown_status":
        job["steps"][0]["status"] = "unknown"
    elif mutation == "bad_step_number":
        job["steps"][0]["number"] = True
    elif mutation == "unordered_steps":
        job["steps"][0]["number"], job["steps"][1]["number"] = 2, 1
    elif mutation == "missing_attempt":
        del run["run_attempt"]
    elif mutation == "run_bool":
        run["id"] = True
    elif mutation == "incomplete_runs":
        runs["total_count"] = 101
    elif mutation == "incomplete_jobs":
        jobs["total_count"] = 2
    elif mutation == "no_origin":
        runs.update(total_count=0, workflow_runs=[])
    read, _calls = reader(runs, jobs)
    assert gate.admit(context(), read)["referenced"] is False


@pytest.mark.parametrize(
    "latest_state", ["failure", "in_progress", "reference_only", "changed_attempt"]
)
def test_latest_or_changed_push_never_falls_back_to_an_older_green(latest_state):
    runs, jobs = future_origin()
    latest = copy.deepcopy(runs)
    if latest_state == "changed_attempt":
        latest["workflow_runs"][0]["run_attempt"] = 2
    elif latest_state == "reference_only":
        jobs["jobs"][0]["steps"][18]["conclusion"] = "skipped"
    else:
        run = copy.deepcopy(runs["workflow_runs"][0])
        run.update(id=101, run_number=11)
        run.update(
            status="in_progress" if latest_state == "in_progress" else "completed",
            conclusion=latest_state,
        )
        latest["workflow_runs"].append(run)
        latest["total_count"] = 2
    read, calls = reader(
        latest if latest_state != "changed_attempt" else runs, jobs, final=latest
    )
    assert gate.admit(context(), read)["referenced"] is False
    assert len(calls) <= 3


@pytest.mark.parametrize("state", ["failure", "in_progress", "manual_failure", "old_attempt_changed", "old_retry_success"])
def test_all_visible_same_head_attempts_must_be_successful_and_stable(state):
    runs, jobs = future_origin()
    older = copy.deepcopy(runs["workflow_runs"][0])
    older.update(id=99, run_number=9, run_attempt=2)
    runs["workflow_runs"].append(older)
    runs["total_count"] = 2
    if state == "old_attempt_changed":
        final = copy.deepcopy(runs)
        final["workflow_runs"][1]["run_attempt"] = 3
    else:
        if state != "old_retry_success":
            older.update(status="in_progress" if state == "in_progress" else "completed", conclusion=None if state == "in_progress" else "failure")
        if state == "manual_failure":
            older["event"] = "workflow_dispatch"
            older["run_number"] = 11
        final = runs
    read, calls = reader(runs, jobs, final)
    assert gate.admit(context(), read)["referenced"] is (state == "old_retry_success")
    assert len(calls) == (3 if state in {"old_attempt_changed", "old_retry_success"} else 1)


def test_real_recorded_successful_affected_job_is_not_a_full_source_origin():
    runs, _jobs = future_origin()
    job = copy.deepcopy(RECORDED_AFFECTED_JOB)
    # Match only the envelope so the original skip statuses are the rejection.
    job.update(run_id=100, head_sha=SHA)
    read, _calls = reader(runs, {"total_count": 1, "jobs": [job]})
    assert (
        gate.admit(context(), read)["reason"]
        == "full_source_checks_not_executed_successfully"
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"GITHUB_EVENT_NAME": "workflow_dispatch"},
        {"GITHUB_EVENT_NAME": "pull_request"},
        {"GITHUB_REF": "refs/heads/candidate"},
        {"GITHUB_REPOSITORY": "other/repo"},
        {"GITHUB_WORKFLOW_SHA": "b" * 40},
        {"GITHUB_WORKFLOW_REF": "other"},
        {"GITHUB_RUN_ID": ""},
        {"GITHUB_SHA": "unknown"},
    ],
)
def test_non_main_or_unknown_context_never_queries_an_origin(changes):
    assert (
        gate.admit(
            context(**changes), lambda _p: pytest.fail("No lookup for this context")
        )["referenced"]
        is False
    )


@pytest.mark.parametrize(
    "failure", [b"bad JSON", b"[]", b"x" * 2_000_001, 403, 302, "network"],
    ids=("bad_json", "array_response", "oversized_response", "permission_denied", "redirect", "network_error"),
)
def test_http_boundary_falls_back_without_secrets_or_redirects(monkeypatch, failure):
    class Opener:
        def open(self, request, *, timeout):
            assert timeout == 20 and request.full_url.startswith(
                "https://api.github.com/repos/" + gate.REPOSITORY
            )
            if isinstance(failure, int):
                raise urllib.error.HTTPError(
                    request.full_url, failure, "secret-detail", {}, None
                )
            if failure == "network":
                raise urllib.error.URLError("secret-detail")
            return io.BytesIO(failure)

    monkeypatch.setenv("GH_TOKEN", "secret-token")
    monkeypatch.setattr(gate.urllib.request, "build_opener", lambda _handler: Opener())
    result = gate.admit(context())
    assert result["referenced"] is False and "secret" not in json.dumps(result)
    assert (
        gate.NoRedirect().redirect_request(
            None, None, 302, "redirect", {}, "https://other.invalid"
        )
        is None
    )


def test_checkout_identity_is_hard_and_push_workflow_is_source_bound(
    monkeypatch, tmp_path
):
    calls = []

    def git(command, **kwargs):
        calls.append(command)
        return SHA + "\n" if command[1] == "rev-parse" else ""

    monkeypatch.setattr(gate.subprocess, "check_output", git)
    gate.verify_checkout(context(), tmp_path)
    assert calls == [
        ["git", "rev-parse", "HEAD"],
        ["git", "status", "--porcelain", "--untracked-files=all"],
    ]
    with pytest.raises(gate.Unavailable):
        gate.verify_checkout(context(GITHUB_WORKFLOW_SHA="b" * 40), tmp_path)
    for event in ("pull_request", "workflow_dispatch"):
        gate.verify_checkout(
            context(GITHUB_EVENT_NAME=event, GITHUB_WORKFLOW_SHA="base-workflow"),
            tmp_path,
        )
    for name in ("GIT_CONFIG_COUNT", "GIT_TEMPLATE_DIR"):
        with monkeypatch.context() as scoped:
            scoped.setenv(name, "foreign")
            with pytest.raises(gate.Unavailable, match="foreign_Git_namespace"):
                gate.verify_checkout(context(), tmp_path)
    monkeypatch.setattr(
        gate.subprocess,
        "check_output",
        lambda command, **_kwargs: (
            SHA + "\n" if command[1] == "rev-parse" else " M tracked.py\n"
        ),
    )
    with pytest.raises(gate.Unavailable, match="checkout_does_not_match"):
        gate.verify_checkout(context(), tmp_path)
    monkeypatch.setattr(
        gate.subprocess, "check_output", lambda *_args, **_kwargs: "wrong"
    )
    with pytest.raises(gate.Unavailable, match="checkout_does_not_match"):
        gate.verify_checkout(context(), tmp_path)


def test_current_workflow_keeps_hard_identity_and_fresh_fallback():
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github/workflows/minimal-repository.yml").read_text()
    parts = workflow.split("      - name: ")
    identity = next(
        s for s in parts if s.startswith("Verify exact workflow checkout\n")
    )
    admission = next(s for s in parts if s.startswith("Check main commit admission\n"))
    assert (
        "if:" not in identity
        and "continue-on-error" not in identity
        and "--verify-checkout" in identity
    )
    assert (
        "continue-on-error: true" in admission
        and "GH_TOKEN: ${{ github.token }}" in admission
    )
    names = {s.splitlines()[0] for s in parts[1:]}
    assert set(gate.REQUIRED_STEPS) - {"Run actions/checkout@v4"} <= names
    for step in parts[1:]:
        if step.splitlines()[0] in names - {
            "Isolate future obsolete-run scheduling",
            "Require a valid scheduling plan",
            "Verify exact workflow checkout",
            "Check main commit admission",
        }:
            assert "steps.main-admission.outcome != 'success'" in step
            assert "steps.main-admission.outputs.referenced != 'true'" in step
    assert (
        workflow.index("Verify exact workflow checkout")
        < workflow.index("Check main commit admission")
        < workflow.index("Install matching")
    )


@pytest.mark.parametrize("referenced", [True, False])
def test_cli_records_reference_or_fresh_without_execution_claim(monkeypatch, tmp_path, referenced):
    result = {"referenced": referenced, "reason": "fixture", "origin_url": "https://github.com/origin", "current_run_executed_tests": False}
    monkeypatch.setattr(gate, "admit", lambda _environment: result)
    monkeypatch.setattr(sys, "argv", ["main_commit_admission"])
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "output"))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(tmp_path / "summary"))
    assert gate.main() == 0
    assert (tmp_path / "output").read_text() == f"referenced={str(referenced).lower()}\n"
    summary = (tmp_path / "summary").read_text()
    assert ("executed no build/tests or artifacts" in summary) is referenced
    assert ("FRESH source checks" in summary) is not referenced
