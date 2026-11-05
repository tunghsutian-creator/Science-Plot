"""Closed JSON proof for prior official public behavior; no execution authority."""
from __future__ import annotations

from datetime import datetime
import hashlib
import io
import json
import re
from typing import Any
import zipfile

from sciplot_core.verification.ci_public_environment import BINDING_FIELDS, COMMANDS, PROTOCOL, REPOSITORY, digest

MAX_ARCHIVE = 1024 * 1024
MAX_JSON = 512 * 1024
CLAIM = "prior_official_public_software_behavior_only"
FIELDS = {"kind", "version", "claim", "fresh_execution", "created_at", "binding", "origin", "focused", "comprehensive"}


def policy_compatible(branch: Any, rulesets: Any) -> bool:
    # This is the one supported policy, not a default for unknown/admin-denied reads.
    if not isinstance(branch, dict) or branch.get("name") != "main" or branch.get("protected") is not False:
        return False
    protection = branch.get("protection")
    if not isinstance(protection, dict) or protection.get("enabled") is not False:
        return False
    checks = protection.get("required_status_checks")
    return (isinstance(checks, dict) and checks.get("enforcement_level") == "off"
            and checks.get("contexts") == [] and checks.get("checks") == []
            and isinstance(rulesets, list) and rulesets == [])


def focused_summary(log: str, selected: int, allowed_skips: int) -> dict[str, int]:
    summaries = [line for line in log.splitlines() if re.search(r"\d+ passed.* in \d", line)]
    if not summaries:
        raise ValueError("focused_aggregate_missing")
    line = summaries[-1]
    if re.search(r"\d+ (?:failed|error)", line):
        raise ValueError("focused_failed")
    passed = re.search(r"(\d+) passed", line)
    skips = re.search(r"(\d+) skipped", line)
    count = int(passed[1]) if passed else 0
    skipped = int(skips[1]) if skips else 0
    if count + skipped != selected or skipped != allowed_skips:
        raise ValueError("focused_scope_or_skip_drift")
    return {"passed": count, "skipped": skipped, "selected": selected}


def unpack_artifact(data: bytes, expected_digest: str) -> dict[str, Any]:
    if len(data) > MAX_ARCHIVE or expected_digest != "sha256:" + hashlib.sha256(data).hexdigest():
        raise ValueError("artifact_size_or_digest")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries = archive.infolist()
        if (len(entries) != 1 or entries[0].filename != "public-result.json" or entries[0].file_size > MAX_JSON
                or entries[0].compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
                or entries[0].flag_bits & 1 or (entries[0].external_attr >> 16) & 0o170000 == 0o120000):
            raise ValueError("artifact_membership")
        raw = archive.read(entries[0])
    if len(raw) > MAX_JSON:
        raise ValueError("artifact_json_size")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("artifact_schema")
    return value


def origin_eligible(proof: Any, binding: dict[str, Any], run: Any,
                    jobs: Any, artifact: Any, now: datetime) -> str | None:
    """Return a bounded explicit refusal; no unknown value becomes compatible."""
    # Validate untrusted wire shapes once, before using internal values.
    if (not isinstance(proof, dict) or not isinstance(run, dict)
            or not isinstance(jobs, dict) or not isinstance(artifact, dict)):
        return "wire_schema"
    for key in ("repository", "head_repository"):
        if not isinstance(run.get(key), dict):
            return "official_repository_schema"
    if not isinstance(artifact.get("workflow_run"), dict):
        return "artifact_origin_schema"
    if not isinstance(jobs.get("jobs"), list) or any(not isinstance(row, dict) for row in jobs["jobs"]):
        return "official_jobs_schema"
    for job in jobs["jobs"]:
        if not isinstance(job.get("steps"), list) or any(not isinstance(row, dict) for row in job["steps"]):
            return "official_steps_schema"
    if (set(proof) != FIELDS or proof.get("kind") != "sciplot_public_ci_result"
            or type(proof.get("version")) is not int or proof["version"] != 1):
        return "proof_schema"
    if proof.get("claim") != CLAIM or proof.get("fresh_execution") is not True:
        return "not_fresh_origin"
    if set(binding) != BINDING_FIELDS:
        return "incomplete_current_binding"
    if not isinstance(proof.get("binding"), dict):
        return "proof_binding_schema"
    try:
        observed_binding = digest(proof["binding"])
    except (ValueError, TypeError):
        return "proof_binding_not_canonical_json"
    if binding["protocol"] != PROTOCOL or binding["commands"] != COMMANDS or observed_binding != digest(binding):
        return "binding_mismatch"
    origin = proof.get("origin")
    if not isinstance(origin, dict) or set(origin) != {"repository", "sha", "run_id", "attempt", "workflow"}:
        return "origin_schema"
    if (type(origin["run_id"]) is not int or origin["run_id"] <= 0 or type(origin["attempt"]) is not int
            or origin["attempt"] <= 0 or not isinstance(origin["sha"], str) or not re.fullmatch(r"[0-9a-f]{40}", origin["sha"])):
        return "origin_identity_schema"
    if (origin["repository"] != REPOSITORY or run.get("repository", {}).get("full_name") != REPOSITORY
            or run.get("head_repository", {}).get("full_name") != REPOSITORY
            or run.get("head_repository", {}).get("fork") is not False):
        return "repository_or_fork"
    if (type(run.get("id")) is not int or type(run.get("run_attempt")) is not int
            or run["id"] != origin["run_id"] or run["run_attempt"] != origin["attempt"]
            or run.get("head_sha") != origin["sha"] or origin["sha"] != binding["head"]
            or origin["workflow"] != ".github/workflows/minimal-repository.yml" or run.get("path") != origin["workflow"]
            or run.get("event") != "push" or run.get("status") != "completed" or run.get("conclusion") != "success"):
        return "official_origin_not_success"
    try:
        created = datetime.fromisoformat(proof["created_at"])
        expires = datetime.fromisoformat(artifact["expires_at"])
        if not 0 <= (now - created).total_seconds() <= 7 * 86400 or expires <= now:
            return "expired_origin"
    except (KeyError, TypeError, ValueError):
        return "invalid_origin_time"
    if (artifact.get("expired") is not False or artifact.get("name") != f"public-result-{origin['run_id']}-{origin['attempt']}"
            or artifact.get("workflow_run", {}).get("id") != origin["run_id"]
            or artifact.get("workflow_run", {}).get("head_sha") != origin["sha"]):
        return "artifact_origin_mismatch"
    candidates = [job for job in jobs.get("jobs", []) if job.get("name") == "runtime-integrity"]
    if len(candidates) != 1 or candidates[0].get("status") != "completed" or candidates[0].get("conclusion") != "success":
        return "official_job_not_success"
    steps = candidates[0].get("steps", [])
    for name in ("Run reviewed public focused behavior", "Run reviewed public comprehensive behavior"):
        actual = [step for step in steps if step.get("name") == name]
        if len(actual) != 1 or actual[0].get("conclusion") != "success" or actual[0].get("status") != "completed":
            return "origin_profile_not_executed"
    focused, comprehensive = proof.get("focused"), proof.get("comprehensive")
    if not isinstance(focused, dict) or not isinstance(comprehensive, dict):
        return "profile_schema"
    if (set(comprehensive) != {"status", "actual_exit_code", "selected_sha256", "original_result_sha256"}
            or type(comprehensive["actual_exit_code"]) is not int
            or not isinstance(comprehensive["original_result_sha256"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", comprehensive["original_result_sha256"])):
        return "comprehensive_schema"
    if set(focused) != {"selected", "skipped", "passed"} or any(type(value) is not int or value < 0 for value in focused.values()):
        return "focused_schema"
    if (focused.get("selected") != binding["focused_count"] or focused.get("skipped") != binding["focused_skips"]
            or focused["passed"] + focused["skipped"] != focused.get("selected")
            or comprehensive.get("status") != "PASS" or comprehensive.get("actual_exit_code") != 0
            or comprehensive.get("selected_sha256") != binding["comprehensive_nodes_sha256"]):
        return "profile_result_mismatch"
    return None
