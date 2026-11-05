"""Admit a main source ref using its latest completed official full push check."""
from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any
import urllib.error
import urllib.request

REPOSITORY = "tunghsutian-creator/Science-Plot"
WORKFLOW = ".github/workflows/minimal-repository.yml"
REQUIRED_STEPS = (
    "Require a valid scheduling plan", "Run actions/checkout@v4", "Verify exact workflow checkout",
    "Check main commit admission", "Plan bounded public feedback", "Enforce minimal runtime distribution",
    "Compile SciPlot-owned Python", "Install matching system Python and Qt toolchain", "Install local runtime",
    "Verify Qt build and runtime identity", "Verify Chinese glyph fallback in the system Qt runtime",
    "Run lint gate", "Run shared source contracts", "Run scoped static type gate", "Build vendored Veusz helpers",
    "Verify vendored Veusz helpers", "Verify minimal wheel surface",
    "Check known native CI regressions before the public suites", "Run reviewed public focused behavior",
    "Run reviewed public comprehensive behavior", "Verify source-checkout wrapper bootstrap",
    "Run readiness check", "Run fixture-free lifecycle smoke",
)
PLATFORM_STEPS = {"Set up job", "Complete job", "Post Run actions/checkout@v4"}
AFFECTED_STEP = "Run reviewed affected public feedback"


class Unavailable(ValueError):
    """Expected missing or malformed official API evidence; execute fresh gates."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None


def api_get(path: str) -> dict[str, Any]:
    token = os.environ.get("GH_TOKEN")
    if not token:
        raise Unavailable("missing_read_token")
    request = urllib.request.Request("https://api.github.com" + path, headers={
        "Authorization": "Bearer " + token, "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=20) as response:
            raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise Unavailable("metadata_too_large")
        value = json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as error:
        raise Unavailable(f"HTTP_{error.code}") from error
    except (urllib.error.URLError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise Unavailable("unreadable_API_metadata") from error
    if not isinstance(value, dict):
        raise Unavailable("non_object_API_metadata")
    return value


def verify_checkout(environment: Mapping[str, str], root: Path) -> None:
    sha, ref = environment.get("GITHUB_SHA", ""), environment.get("GITHUB_REF", "")
    if not re.fullmatch("[0-9a-f]{40}", sha):
        raise Unavailable("unknown_event_source")
    # PR/manual workflow context can differ from the merge/event checkout.
    # Only push checks can serve as an origin and need this stricter identity.
    if environment.get("GITHUB_EVENT_NAME") == "push" and (
            environment.get("GITHUB_WORKFLOW_SHA") != sha or not ref
            or environment.get("GITHUB_WORKFLOW_REF") != f"{environment.get('GITHUB_REPOSITORY')}/{WORKFLOW}@{ref}"):
        raise Unavailable("workflow_source_identity_unknown")
    if any(os.environ.get(key) for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR", "GIT_CONFIG_COUNT", "GIT_TEMPLATE_DIR")):
        raise Unavailable("foreign_Git_namespace")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    if head != sha or subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=all"], cwd=root, text=True):
        raise Unavailable("checkout_does_not_match_workflow_commit")


def _page(value: dict[str, Any], key: str) -> list[dict[str, Any]]:
    rows, total = value.get(key), value.get("total_count")
    if (not isinstance(rows, list) or type(total) is not int or total != len(rows) or total > 100
            or any(not isinstance(row, dict) for row in rows)):
        raise Unavailable("incomplete_API_page")
    return rows


def _latest(value: dict[str, Any], current: int) -> dict[str, Any]:
    rows = _page(value, "workflow_runs")
    if any(type(row.get(key)) is not int or row[key] <= 0 for row in rows for key in ("id", "run_number", "run_attempt")):
        raise Unavailable("unknown_run_identity")
    if any(len({row[key] for row in rows}) != len(rows) for key in ("id", "run_number")):
        raise Unavailable("duplicate_run_identity")
    related = [row for row in rows if row["id"] != current]
    if not related:
        raise Unavailable("no_prior_push")
    return max(related, key=lambda row: row["run_number"])


def _successful(value: dict[str, Any]) -> bool:
    return value.get("status") == "completed" and value.get("conclusion") == "success"


def _origin(run: dict[str, Any], sha: str) -> bool:
    return (_successful(run) and run.get("head_sha") == sha and run.get("event") == "push" and run.get("path") == WORKFLOW
            and all(isinstance(run.get(key), dict) and run[key].get("full_name") == REPOSITORY
                    and run[key].get("fork") is False for key in ("repository", "head_repository")))


def admit(environment: Mapping[str, str], read: Callable[[str], dict[str, Any]] = api_get) -> dict[str, Any]:
    if environment.get("GITHUB_EVENT_NAME") != "push" or environment.get("GITHUB_REF") != "refs/heads/main":
        return {"referenced": False, "reason": "fresh_event_or_branch"}
    sha, current = environment.get("GITHUB_SHA", ""), environment.get("GITHUB_RUN_ID", "")
    if (not re.fullmatch("[0-9a-f]{40}", sha) or not re.fullmatch("[1-9][0-9]*", current)
            or environment.get("GITHUB_REPOSITORY") != REPOSITORY or environment.get("GITHUB_WORKFLOW_SHA") != sha
            or environment.get("GITHUB_WORKFLOW_REF") != f"{REPOSITORY}/{WORKFLOW}@refs/heads/main"):
        return {"referenced": False, "reason": "unknown_current_source"}
    path = f"/repos/{REPOSITORY}/actions/workflows/minimal-repository.yml/runs?event=push&head_sha={sha}&per_page=100"
    try:
        run = _latest(read(path), int(current))
        if not _origin(run, sha):
            raise Unavailable("latest_push_not_successful_or_matching")
        jobs = _page(read(f"/repos/{REPOSITORY}/actions/runs/{run['id']}/attempts/{run['run_attempt']}/jobs?per_page=100"), "jobs")
        runtime = [job for job in jobs if job.get("name") == "runtime-integrity"]
        if len(runtime) != 1 or not _successful(runtime[0]):
            raise Unavailable("missing_or_unsuccessful_runtime_job")
        job = runtime[0]
        if any(type(job.get(key)) is not int or job[key] != run[source] for key, source in (("run_id", "id"), ("run_attempt", "run_attempt"))) or job.get("head_sha") != sha:
            raise Unavailable("wrong_job_attempt_or_source")
        steps = job.get("steps")
        if (not isinstance(steps, list) or any(not isinstance(step, dict) or not isinstance(step.get("name"), str)
                or type(step.get("number")) is not int or step["number"] <= 0 for step in steps)
                or any(len({step[key] for step in steps}) != len(steps) for key in ("name", "number"))):
            raise Unavailable("unknown_or_duplicate_steps")
        by_name = {step["name"]: step for step in steps}
        if not all(name in by_name and _successful(by_name[name]) for name in REQUIRED_STEPS):
            raise Unavailable("full_source_checks_not_executed_successfully")
        if [by_name[name]["number"] for name in REQUIRED_STEPS] != sorted(by_name[name]["number"] for name in REQUIRED_STEPS):
            raise Unavailable("required_steps_out_of_order")
        if any(not _successful(step) if name in PLATFORM_STEPS else
               name != AFFECTED_STEP or step.get("status") != "completed" or step.get("conclusion") != "skipped"
               for name, step in by_name.items() if name not in REQUIRED_STEPS):
            raise Unavailable("unknown_or_nonfull_step")
        final = _latest(read(path), int(current))
        if not _origin(final, sha) or any(final[key] != run[key] for key in ("id", "run_attempt", "run_number")):
            raise Unavailable("latest_push_changed_during_admission")
    except Unavailable as error:
        return {"referenced": False, "reason": str(error)}
    return {"referenced": True, "reason": "completed_full_source_check", "origin_run_id": run["id"],
            "origin_attempt": run["run_attempt"], "origin_url": f"https://github.com/{REPOSITORY}/actions/runs/{run['id']}/attempts/{run['run_attempt']}",
            "claim": "source_commit_admission_only", "current_run_executed_tests": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-checkout", action="store_true")
    arguments = parser.parse_args()
    if arguments.verify_checkout:
        verify_checkout(os.environ, Path(__file__).resolve().parents[3])
        print("Actual checkout and workflow source match GITHUB_SHA.")
        return 0
    result = admit(os.environ)
    print(json.dumps(result, sort_keys=True))
    with Path(os.environ["GITHUB_OUTPUT"]).open("a") as stream:
        stream.write(f"referenced={str(result['referenced']).lower()}\n")
    with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a") as stream:
        stream.write((f"Source approval REFERENCE: {result['origin_url']}. Current run executed no build/tests or artifacts; "
                      "the original environment and execution belong to that run. Other required checks and release/private/scientific evidence remain separate.\n")
                     if result["referenced"] else f"FRESH source checks: {result['reason']}.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
