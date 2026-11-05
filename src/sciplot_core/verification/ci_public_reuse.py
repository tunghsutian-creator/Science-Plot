"""Opt-in reference to one official fresh public CI result; otherwise run fresh."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any
import urllib.error
import urllib.parse
import urllib.request
import zipfile

from sciplot_core.foundation.iso_timestamps import utc_now_iso
from sciplot_core.verification.ci_public_environment import (
    COMMANDS, REPOSITORY, UnsupportedEnvironment, application_environment, collect_environment, digest,
)
from sciplot_core.verification.ci_public_proof import (
    CLAIM, MAX_ARCHIVE, origin_eligible, policy_compatible, unpack_artifact,
)
from sciplot_core.verification.input_scope import load_manifest
from sciplot_core.verification.public_stage import BINDING_CHECKS, PLATFORM_SKIPS, review_stage_reports

DIRECTORY = ".tmp_verify/ci-public-reference"
WORKFLOW = ".github/workflows/minimal-repository.yml"


class RemoteUnavailable(ValueError):
    """Expected unavailable/invalid remote evidence; never an execution PASS."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: urllib.request.Request, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None


def api(path: str, *, archive: bool = False) -> Any:
    token = os.environ.get("GH_TOKEN")
    if not token or not (path == "/repos/" + REPOSITORY or path.startswith("/repos/" + REPOSITORY + "/")):
        raise RemoteUnavailable("missing_read_token_or_unsupported_api")
    request = urllib.request.Request("https://api.github.com" + path,
        headers={"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})
    try:
        if archive:
            try:
                with urllib.request.build_opener(NoRedirect).open(request, timeout=20):
                    pass
            except urllib.error.HTTPError as response:
                if response.code != 302:
                    raise
                location = response.headers.get("Location", "")
                try:
                    parsed = urllib.parse.urlsplit(location)
                    port = parsed.port
                except ValueError as error:
                    raise RemoteUnavailable("artifact_redirect_schema") from error
                if (parsed.scheme != "https" or port not in {None, 443} or parsed.username or parsed.password or parsed.fragment
                        or not parsed.hostname or not parsed.hostname.endswith((".blob.core.windows.net", ".actions.githubusercontent.com"))):
                    raise RemoteUnavailable("unsupported_artifact_redirect") from response
                # Never forward the API Authorization header to artifact storage.
                with urllib.request.urlopen(location, timeout=20) as stream:
                    data = stream.read(MAX_ARCHIVE + 1)
                if len(data) > MAX_ARCHIVE:
                    raise RemoteUnavailable("artifact_size") from response
                return data
            raise RemoteUnavailable("artifact_redirect_missing")
        with urllib.request.urlopen(request, timeout=20) as stream:
            raw = stream.read(2 * 1024 * 1024 + 1)
        if len(raw) > 2 * 1024 * 1024:
            raise RemoteUnavailable("api_response_size")
        value = json.loads(raw)
        if not isinstance(value, (dict, list)):
            raise RemoteUnavailable("api_response_schema")
        return value
    except urllib.error.HTTPError as error:
        raise RemoteUnavailable("HTTP_" + str(error.code)) from error
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        raise RemoteUnavailable(type(error).__name__) from error


def output(**values: str) -> None:
    print(json.dumps(values, sort_keys=True))
    target = os.environ.get("GITHUB_OUTPUT")
    if target:
        with Path(target).open("a") as stream:
            for key, value in values.items():
                stream.write(f"{key}={value}\n")


def binding(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    facts, costs = collect_environment(root)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, text=True, capture_output=True, check=True).stdout.strip()
    if head != os.environ.get("GITHUB_SHA"):
        raise UnsupportedEnvironment("current_checkout_sha_mismatch")
    manifest = load_manifest()
    focused = sorted(set(manifest["scopes"]["public"]) & set(manifest["tiers"]["focused"]))
    comprehensive = sorted(set(manifest["scopes"]["public"]) & set(manifest["tiers"]["comprehensive"]))
    facts.update(head=head, focused_count=len(focused), focused_skips=len(set(focused) & set(PLATFORM_SKIPS)),
                 focused_nodes_sha256=digest(focused), comprehensive_nodes_sha256=digest(comprehensive))
    return facts, costs


def fresh_policy() -> None:
    prefix = "/repos/" + REPOSITORY
    if not policy_compatible(api(prefix + "/branches/main"), api(prefix + "/rulesets?includes_parents=true")):
        raise RemoteUnavailable("required_policy_incompatible_or_unknown")


def prepare(root: Path) -> None:
    if os.environ.get("SCIPLOT_PUBLIC_REUSE") != "true":
        output(reuse="false", origin="false", reason="FRESH:disabled")
        return
    if os.environ.get("GITHUB_EVENT_NAME") != "push" or os.environ.get("GITHUB_REPOSITORY") != REPOSITORY:
        output(reuse="false", origin="false", reason="FRESH:unsupported_event_or_repository")
        return
    directory = root / DIRECTORY
    if (root / ".tmp_verify").is_symlink() or directory.is_symlink():
        raise ValueError("CI evidence roots cannot follow aliases.")
    directory.mkdir(parents=True, exist_ok=False)
    try:
        repository = api("/repos/" + REPOSITORY)
        if not isinstance(repository, dict) or repository.get("full_name") != REPOSITORY or repository.get("fork") is not False:
            raise RemoteUnavailable("repository_or_fork")
        fresh_policy()
        controlled = application_environment(root)
        for name in ("HOME", "TMPDIR", "PYTHONPYCACHEPREFIX"):
            path = Path(controlled[name])
            if path.is_symlink():
                raise UnsupportedEnvironment("owned_root_alias")
            if path.exists() and any(path.iterdir()):
                raise UnsupportedEnvironment("owned_initial_state_not_empty")
            path.mkdir(parents=True, exist_ok=True)
        current, costs = binding(root)
        print(json.dumps({"collector_costs": costs}, sort_keys=True))
        (directory / "current.json").write_text(json.dumps({"binding": current, "costs": costs}, sort_keys=True))
    except (RemoteUnavailable, UnsupportedEnvironment, ImportError, OSError, subprocess.SubprocessError) as error:
        output(reuse="false", origin="false", reason="FRESH:" + str(error).splitlines()[0][:160])
        return
    if os.environ.get("GITHUB_REF") != "refs/heads/main":
        output(reuse="false", origin="true", reason="FRESH:origin_push_only")
        return
    # Candidate discovery is bounded; no retries or waiting for another run.
    try:
        runs = api(f"/repos/{REPOSITORY}/actions/workflows/minimal-repository.yml/runs?event=push&head_sha={current['head']}&status=success&per_page=5")
        if not isinstance(runs, dict) or not isinstance(runs.get("workflow_runs"), list):
            raise RemoteUnavailable("run_list_schema")
        refusal = "origin_absent"
        for run in runs["workflow_runs"]:
            if not isinstance(run, dict) or type(run.get("id")) is not int or type(run.get("run_attempt")) is not int:
                raise RemoteUnavailable("run_identity_schema")
            if str(run["id"]) == os.environ["GITHUB_RUN_ID"]:
                continue
            artifacts = api(f"/repos/{REPOSITORY}/actions/runs/{run['id']}/artifacts?per_page=30")
            if not isinstance(artifacts, dict) or not isinstance(artifacts.get("artifacts"), list):
                raise RemoteUnavailable("artifact_list_schema")
            for artifact in artifacts["artifacts"]:
                if not isinstance(artifact, dict):
                    raise RemoteUnavailable("artifact_schema")
                if artifact.get("name") != f"public-result-{run['id']}-{run['run_attempt']}":
                    continue
                if type(artifact.get("id")) is not int:
                    raise RemoteUnavailable("artifact_id")
                data = api(f"/repos/{REPOSITORY}/actions/artifacts/{artifact['id']}/zip", archive=True)
                try:
                    proof = unpack_artifact(data, artifact.get("digest", ""))
                except (ValueError, zipfile.BadZipFile, UnicodeDecodeError) as error:
                    raise RemoteUnavailable("artifact_invalid:" + str(error)) from error
                jobs = api(f"/repos/{REPOSITORY}/actions/runs/{run['id']}/attempts/{run['run_attempt']}/jobs?per_page=30")
                refusal = origin_eligible(proof, current, run, jobs, artifact, datetime.now(timezone.utc)) or ""
                if not refusal:
                    fresh_policy()
                    (directory / "reference.json").write_text(json.dumps({"origin": proof["origin"], "claim": CLAIM}))
                    output(reuse="true", origin="false", reason=f"REFERENCED:official_run_{run['id']}_attempt_{run['run_attempt']}")
                    summary = os.environ.get("GITHUB_STEP_SUMMARY")
                    if summary:
                        with Path(summary).open("a") as stream:
                            stream.write(f"Public software behavior references [original run {run['id']}](https://github.com/{REPOSITORY}/actions/runs/{run['id']}). "
                                         "This run did not execute the two public profiles; current native/runtime/Doctor/smoke gates remain required.\n")
                    return
        output(reuse="false", origin="true", reason="FRESH:" + refusal)
    except RemoteUnavailable as error:
        output(reuse="false", origin="true", reason="FRESH:" + str(error).splitlines()[0][:160])


def run_profile(root: Path, profile: str) -> int:
    directory = root / DIRECTORY
    if (root / ".tmp_verify").is_symlink() or directory.is_symlink():
        raise ValueError("CI evidence roots cannot follow aliases.")
    controlled = (directory / "current.json").is_file()
    environment = application_environment(root) if controlled else dict(os.environ)
    command = [sys.executable, "-m", "sciplot_core.verification.public_stage", "--profile", "public-" + profile,
               "--out", ".tmp_verify/ci_public_" + profile]
    directory.mkdir(parents=True, exist_ok=True)
    log = directory / f"{profile}.log"
    with log.open("x") as stream:
        # Same owned command.log stream previously used by comprehensive in Actions.
        # It is progress only; the original stage exit/finish/reports own completion.
        progress = subprocess.Popen(["tail", "-n", "+1", "--follow=name", "--retry",
                                     str(root / f".tmp_verify/ci_public_{profile}/command.log")],
                                    env=environment, stderr=subprocess.DEVNULL)
        try:
            child = subprocess.Popen(command, cwd=root, env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            assert child.stdout is not None
            for line in child.stdout:
                print(line, end="", flush=True)
                stream.write(line)
            code = child.wait()
        finally:
            if progress.poll() is None:
                progress.terminate()
            progress.wait()
    (directory / f"{profile}.exit.json").write_text(json.dumps({"actual_exit_code": code, "controlled": controlled, "command": COMMANDS[0 if profile == "focused" else 1]}))
    return code



def _stage_evidence(root: Path, profile: str, before: dict[str, Any]) -> tuple[dict[str, Any], str]:
    stage = root / f".tmp_verify/ci_public_{profile}"
    result_path = stage / "result.json"
    raw = result_path.read_bytes()
    result = json.loads(raw)
    reports = json.loads((stage / "reports.json").read_bytes())
    checks = result["binding_checks"]
    if (not isinstance(checks, dict) or set(checks) != set(BINDING_CHECKS)
            or any(checks[key] is not True for key in BINDING_CHECKS)):
        raise ValueError(f"Fresh {profile} original evidence has incomplete or non-boolean binding checks.")
    if (result["status"] != "PASS" or result["actual_exit_code"] != 0 or result["origin_head"] != before["head"]
            or result["profile"] != "public-" + profile
            or review_stage_reports(result["finish"], reports, platform="linux")
            or digest(sorted(result["finish"]["selected_tests"])) != before[profile + "_nodes_sha256"]):
        raise ValueError(f"Fresh {profile} original evidence is inconsistent.")
    return result, hashlib.sha256(raw).hexdigest()


def publish(root: Path) -> None:
    directory = root / DIRECTORY
    if (directory / "reference.json").exists():
        before = json.loads((directory / "current.json").read_bytes())["binding"]
        try:
            after, costs = binding(root)
            fresh_policy()
        except (RemoteUnavailable, UnsupportedEnvironment, ImportError, OSError, subprocess.SubprocessError) as error:
            raise RuntimeError("Referenced public result lost final current facts/policy; cannot claim execution.") from error
        if before != after:
            raise RuntimeError("Referenced public result binding drifted after profiles were skipped.")
        print(json.dumps({"reference_final_collector_costs": costs}, sort_keys=True))
        output(artifact="false", reason="REFERENCE:final_binding_and_policy_revalidated_no_new_origin")
        return
    if not (directory / "current.json").is_file():
        output(artifact="false", reason="NO_ORIGIN:unbound")
        return
    before = json.loads((directory / "current.json").read_bytes())["binding"]
    try:
        after, costs = binding(root)
        print(json.dumps({"collector_costs_after": costs}, sort_keys=True))
    except (UnsupportedEnvironment, ImportError, OSError, subprocess.SubprocessError) as error:
        output(artifact="false", reason="NO_ORIGIN:" + str(error).splitlines()[0][:160])
        return
    if before != after:
        output(artifact="false", reason="NO_ORIGIN:input_drift")
        return
    for profile in ("focused", "comprehensive"):
        record = json.loads((directory / f"{profile}.exit.json").read_bytes())
        if (record["actual_exit_code"] != 0 or record["controlled"] is not True
                or record["command"] != COMMANDS[0 if profile == "focused" else 1]):
            raise ValueError("Fresh profile original exit/control evidence is inconsistent.")
    focused_result, focused_sha256 = _stage_evidence(root, "focused", before)
    marker = focused_result["finish"]
    focused = {"passed": len(marker["executed_tests"]),
               "skipped": len(marker["selected_tests"]) - len(marker["executed_tests"]),
               "selected": len(marker["selected_tests"]), "selected_sha256": before["focused_nodes_sha256"],
               "original_result_sha256": focused_sha256}
    if focused["selected"] != before["focused_count"] or focused["skipped"] != before["focused_skips"]:
        raise ValueError("Fresh focused profile counts differ from the bound scope.")
    _result, comprehensive_sha256 = _stage_evidence(root, "comprehensive", before)
    proof = {"kind": "sciplot_public_ci_result", "version": 2, "claim": CLAIM, "fresh_execution": True,
             "created_at": utc_now_iso(), "binding": before,
             "origin": {"repository": REPOSITORY, "sha": before["head"], "run_id": int(os.environ["GITHUB_RUN_ID"]),
                        "attempt": int(os.environ["GITHUB_RUN_ATTEMPT"]), "workflow": WORKFLOW}, "focused": focused,
             "comprehensive": {"status": "PASS", "actual_exit_code": 0,
                               "selected_sha256": before["comprehensive_nodes_sha256"],
                               "original_result_sha256": comprehensive_sha256}}
    (directory / "public-result.json").write_text(json.dumps(proof, sort_keys=True))
    (directory / "after-costs.json").write_text(json.dumps(costs, sort_keys=True))
    output(artifact="true", reason="ORIGIN:await_official_job_completion_not_yet_eligible")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "focused", "comprehensive", "publish"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    if args.action == "prepare":
        prepare(root)
    elif args.action == "publish":
        publish(root)
    else:
        return run_profile(root, args.action)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
