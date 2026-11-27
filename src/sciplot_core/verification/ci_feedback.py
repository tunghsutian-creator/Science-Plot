"""Bounded CI feedback layers; unknown changes retain complete public gates."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

from sciplot_core.verification.changed import build_changed_verification_plan
from sciplot_core.verification.reviewed_feedback import DOCUMENTATION_SOURCE_TARGETS
from sciplot_core.verification.scope_feedback import scope_delta_is_reviewed

NATIVE_PREFIX = (
    "tests/test_annotation_operations_native.py::test_native_semantic_batch_preview_commit_export_cold_resume_and_remove",
    "tests/test_annotation_operations_native.py::test_native_display_window_preserves_measurements_through_export",
    "tests/test_annotation_operations_native.py::test_initial_crop_can_be_reviewed_and_exported_without_regeneration",
    "tests/test_attached_edit_checkpoints_native.py::test_default_attached_native_common_style_save_undo_restart_replay",
    "tests/test_attached_semantic_native.py::test_attached_public_native_cold_lifecycle[managed]",
    "tests/test_attached_semantic_native.py::test_attached_public_native_cold_lifecycle[legacy]",
    "tests/test_attached_semantic_native.py::test_attached_public_native_cold_lifecycle[legacy_pending]",
)
NATIVE_EXPECTED = frozenset(NATIVE_PREFIX) | {
    "tests/test_mechanical_rendering_profile_native.py::test_wide_category_native_labels_fit_and_clipped_rotation_cannot_commit",
    "tests/test_private_observer.py::test_archived_metadata_reads_keep_actual_root_and_node_boundaries",
    "tests/test_private_observer.py::test_suite_parent_collector_and_supervisor_share_actual_scope[False]",
    "tests/test_private_observer.py::test_suite_parent_collector_and_supervisor_share_actual_scope[True]",
    "tests/test_render_worker_rejection.py::test_real_public_radar_size_conflict_retains_clear_reason_and_no_artifacts",
}


def ci_feedback_plan(paths: list[str], root: Path, *, event: str = "push", ref: str = "", base: str = "") -> dict[str, Any]:
    """Select bounded reviewed owner tests; never infer coverage for unknown paths."""
    plan = build_changed_verification_plan(paths, repo_root=root, feedback_base=base,
                                           scope_validator=scope_delta_is_reviewed)
    reviewed = plan["public_feedback"]
    result = {"changed_paths": plan["changed_paths"], "unowned_paths": plan["unowned_paths"],
              "owners": [row["owner_id"] for row in plan["owners"]]}
    reason, targets, native_targets = reviewed["reason"], reviewed["targets"], reviewed["native_targets"]
    full_ref = ref in {"refs/heads/integration", "refs/heads/release"} or ref.startswith(
        ("refs/tags/", "refs/heads/integration/", "refs/heads/release/")
    )
    if event not in {"push", "pull_request"} or full_ref:
        targets, native_targets, reason = [], [], "integration_release_or_manual"
    affected = bool(targets)
    result.update(layer="affected" if affected else "full", reason=reason,
                  targets=targets, native_targets=native_targets, source_only=affected and reviewed["source_only"],
                  claim="limited_public_development_and_merge_feedback" if affected else "complete_public_gates_required",
                  full_public_profiles="NOT_EXECUTED" if affected else "REQUIRED",
                  real_private_inputs="NOT_EXECUTED", access_capture="NOT_EXECUTED", reusable_origin=False)
    return result


def run_affected(root: Path, base: str, *, event: str, ref: str = "") -> dict[str, Any]:
    """Replan at execution; drift after earlier skip decisions must fail."""
    from sciplot_core.verification.public_stage import run_public_profiles, run_public_stage

    plan = ci_feedback_plan(changed_paths(root, base), root, event=event, ref=ref, base=base)
    if plan["layer"] != "affected" or plan["source_only"]:
        raise ValueError("Affected eligibility changed; complete gates were not executed.")
    directory = root / ".tmp_verify/ci_public_affected"
    from sciplot_core.verification.ci_public_profiles import report_profile

    if plan["native_targets"]:
        results = run_public_profiles(root, directory, [
            ("public-affected", plan["targets"]), ("public-affected-native", plan["native_targets"])])
        result = results[0]
        for profile, report in zip(("public-affected", "public-affected-native"), results, strict=False):
            report_profile(directory / profile, report)
        if len(results) == 2:
            result.update(status=results[-1]["status"], targeted_native=results[-1])
    else:
        result = run_public_stage(root, directory, "public-affected", targets=plan["targets"])
        report_profile(directory, result)
    result.update(feedback_plan=plan, full_public_profiles="NOT_EXECUTED", real_private_inputs="NOT_EXECUTED",
                  access_capture="NOT_EXECUTED", native_preflight="NOT_EXECUTED", doctor="NOT_EXECUTED",
                  lifecycle_smoke="NOT_EXECUTED", reusable_origin=False)
    from sciplot_core.verification.evidence import atomic_json

    atomic_json(directory / "feedback-result.json", result)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with Path(summary).open("a") as stream:
            stream.write("## Limited affected public feedback\n\n"
                         "Selected public owner assertions; any targeted native checks are reported separately. "
                         "Full public profiles, historical native preflight, Doctor, lifecycle smoke, "
                         "real private inputs and access capture: NOT_EXECUTED. Release gates remain separate.\n")
    return result


def run_source_only(root: Path, base: str, *, event: str, ref: str) -> int:
    plan = ci_feedback_plan(changed_paths(root, base), root, event=event, ref=ref, base=base)
    if not plan["source_only"]:
        raise ValueError("Source-only eligibility changed; runtime tests were not executed.")
    code = subprocess.call([sys.executable, "-m", "pytest", "-q", *DOCUMENTATION_SOURCE_TARGETS], cwd=root)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with Path(summary).open("a") as stream:
            stream.write("## Source-only documentation feedback\n\n"
                         "Selected prose and tracked-path tests only. Qt, native helpers, wheel, public stages, "
                         "Doctor, smoke and private science: NOT_EXECUTED.\n")
    return code


def _require_git_namespace() -> None:
    if any(os.environ.get(key) for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR", "GIT_CONFIG_COUNT")):
        raise ValueError("Inherited Git namespace is not a proven CI base.")


def candidate_base(root: Path, event: str, ref: str, supplied: str) -> str:
    """Compare a branch to main, not to the last possibly unverified push."""
    _require_git_namespace()
    if event != "push" or not ref.startswith("refs/heads/") or ref == "refs/heads/main":
        return supplied
    subprocess.run(["git", "fetch", "--no-tags", "--depth=1", "origin", "refs/heads/main"],
                   cwd=root, capture_output=True, check=True, timeout=30)
    return subprocess.check_output(["git", "rev-parse", "FETCH_HEAD"], cwd=root, text=True, timeout=30).strip()


def changed_paths(root: Path, base: str) -> list[str]:
    _require_git_namespace()
    if not re.fullmatch(r"[0-9a-f]{40}", base) or base == "0" * 40:
        raise ValueError("A real event base commit is required.")
    def git(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False, timeout=30)
    if git("cat-file", "-e", base + "^{commit}").returncode:
        if git("fetch", "--no-tags", "--depth=1", "origin", base).returncode:
            raise ValueError("Event base is unavailable; retain complete gates.")
    diff = git("diff", "--name-only", "--no-renames", "-z", base, "HEAD", "--")
    if diff.returncode:
        raise ValueError("Cannot resolve event change scope.")
    return sorted({path for path in diff.stdout.split("\0") if path})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="")
    parser.add_argument("--run-affected", action="store_true")
    parser.add_argument("--run-source-only", action="store_true")
    parser.add_argument("--candidate-base", action="store_true")
    parser.add_argument("--lint", choices=("affected", "full"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    resolved_base = args.base
    try:
        event = os.environ.get("GITHUB_EVENT_NAME", "")
        ref = os.environ.get("SCIPLOT_EVENT_REF", "")
        if args.candidate_base:
            resolved_base = candidate_base(root, event, ref, args.base)
        if args.run_source_only:
            return run_source_only(root, resolved_base, event=event, ref=ref)
        if args.lint == "full":
            return subprocess.call([sys.executable, "-m", "ruff", "check", "src", "tests"], cwd=root)
        paths = changed_paths(root, resolved_base) if not args.run_affected else []
        if args.lint == "affected":
            plan = ci_feedback_plan(paths, root, event=event, ref=ref, base=resolved_base)
            if plan["layer"] != "affected":
                raise ValueError("Affected lint eligibility changed.")
            files = [path for path in paths if path.endswith(".py") and (root / path).is_file()]
            return subprocess.call([sys.executable, "-m", "ruff", "check", "--", *files], cwd=root) if files else 0
        result = (run_affected(root, resolved_base, event=event, ref=ref) if args.run_affected else
                  ci_feedback_plan(paths, root, event=event, ref=ref, base=resolved_base))
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        if args.run_affected or args.run_source_only or args.lint:
            print(json.dumps({"status": "BLOCKED",
                              "reason": "lint_scope_unavailable" if args.lint else "affected_execution_unavailable",
                              "detail": str(error),
                              "full_public_profiles": "NOT_EXECUTED", "real_private_inputs": "NOT_EXECUTED",
                              "access_capture": "NOT_EXECUTED", "reusable_origin": False}))
            return 4
        result = {"layer": "full", "reason": "unavailable_scope", "detail": str(error), "source_only": False}
    environment = os.environ
    if not args.run_affected:
        print(json.dumps(result, sort_keys=True))
    output = environment.get("GITHUB_OUTPUT")
    if output and not args.run_affected:
        with Path(output).open("a") as stream:
            stream.write(f"layer={result['layer']}\n")
            if args.candidate_base:
                stream.write(f"base={resolved_base if re.fullmatch(r'[0-9a-f]{40}', resolved_base) else ''}\n")
                stream.write(f"source_only={str(result['source_only']).lower()}\n")
    return (0 if result["status"] == "PASS" else 4) if args.run_affected else 0


if __name__ == "__main__":
    raise SystemExit(main())
