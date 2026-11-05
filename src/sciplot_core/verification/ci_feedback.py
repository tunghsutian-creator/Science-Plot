"""Bounded CI feedback layers; unknown changes retain complete public gates."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any

from sciplot_core.verification.changed import build_changed_verification_plan
from sciplot_core.verification.task_control_owners import TASK_TIMING_PATH, TASK_TIMING_FEEDBACK_TARGETS

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


# Reviewed design prose with no native/runtime reader; README/skill/contracts are not certified.
_NARRATIVE_PATHS = frozenset({"docs/DESIGN_PROJECT_LIFECYCLE.md", "docs/DESIGN_PROJECT_CORE_MIGRATION.md"})

def native_preflight_plan(paths: list[str], root: Path) -> dict[str, Any]:
    """Only mapped narrative leaves can skip repeated diagnostics for now.

    Owner disjointness alone does not prove transitive native independence.
    Unknowns and executable/shared/runtime changes retain early regression checks.
    """
    plan = build_changed_verification_plan(paths, repo_root=root)
    owners = plan["owners"]
    overlaps = sorted({node for owner in owners for target in owner["pytest_targets"]
                       for node in NATIVE_EXPECTED if node == target or node.startswith(target + "::")})
    narrative = bool(paths) and set(paths) <= _NARRATIVE_PATHS
    skip = (narrative and not plan["unowned_paths"] and bool(owners)
            and all(owner["owner_id"] == "documentation_contract" for owner in owners) and not overlaps)
    return {"native_preflight": not skip, "reason": "mapped_narrative_leaf" if skip else
            "unknown_owner" if plan["unowned_paths"] else "native_consumer" if overlaps else "conservative_risk",
            "changed_paths": paths, "owners": [row["owner_id"] for row in owners],
            "unowned_paths": plan["unowned_paths"], "native_consumers": overlaps,
            "targets": sorted({target for owner in owners for target in owner["pytest_targets"]}) if skip else [],
            "claim": "diagnostic_selection_only_not_acceptance"}


# Shared source-wide contracts and the actual public process/API guard remain
# cheap gates even when a reviewed leaf does not need native/scientific bodies.
_AFFECTED_GUARDS = (
    "tests/test_architecture_boundaries.py::test_non_probe_source_has_no_exact_duplicate_function_implementations",
    "tests/test_architecture_boundaries.py::test_scoped_type_gate_has_one_strict_owned_scope_and_ci_entrypoint",
    "tests/test_public_stage.py",
)


def ci_feedback_plan(paths: list[str], root: Path, *, event: str = "push") -> dict[str, Any]:
    """Narrow only reviewed prose or the one shared metadata-only contract."""
    from sciplot_core.verification.type_gate_owners import ARCHITECTURE_CORE_TARGETS

    result = native_preflight_plan(paths, root)
    reason = result["reason"]
    eligible = reason == "mapped_narrative_leaf"
    if set(paths) == {TASK_TIMING_PATH} and not result["unowned_paths"]:
        from sciplot_core.verification.task_timing_feedback import task_timing_feedback_eligible

        eligible = task_timing_feedback_eligible(root)
        reason = "metadata_only_task_timing" if eligible else "task_timing_contract_not_proven"
    if event not in {"push", "pull_request"}:
        eligible, reason = False, "manual_or_unknown_event"
    targets: list[str] = []
    if eligible:
        if reason == "mapped_narrative_leaf":
            targets = result["targets"]
        else:
            targets = list(TASK_TIMING_FEEDBACK_TARGETS)
        targets = sorted(set((*targets, *ARCHITECTURE_CORE_TARGETS, *_AFFECTED_GUARDS)))
    result.update(layer="affected" if eligible else "full", native_preflight=not eligible,
                  reason=reason, targets=targets, claim="limited_public_development_and_merge_feedback" if eligible else
                  "complete_public_gates_required", full_public_profiles="NOT_EXECUTED" if eligible else "REQUIRED",
                  real_private_inputs="NOT_EXECUTED", access_capture="NOT_EXECUTED", reusable_origin=False)
    return result


def run_affected(root: Path, base: str, *, event: str) -> dict[str, Any]:
    """Replan at execution; drift after earlier skip decisions must fail."""
    from sciplot_core.verification.public_stage import run_public_stage

    plan = ci_feedback_plan(changed_paths(root, base), root, event=event)
    if plan["layer"] != "affected":
        raise ValueError("Affected eligibility changed; complete gates were not executed.")
    result = run_public_stage(root, root / ".tmp_verify/ci_public_affected", "public-affected", targets=plan["targets"])
    result.update(feedback_plan=plan, full_public_profiles="NOT_EXECUTED", real_private_inputs="NOT_EXECUTED",
                  access_capture="NOT_EXECUTED", native_preflight="NOT_EXECUTED", doctor="NOT_EXECUTED",
                  lifecycle_smoke="NOT_EXECUTED", reusable_origin=False)
    from sciplot_core.verification.evidence import atomic_json

    atomic_json(root / ".tmp_verify/ci_public_affected/feedback-result.json", result)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with Path(summary).open("a") as stream:
            stream.write("## Limited affected public feedback\n\n"
                         "Limited selected public assertions; configured static and runtime/build "
                         "distribution checks retain their separate steps. "
                         "Full public profiles, native preflight, Doctor, lifecycle smoke, "
                         "real private inputs and access capture: NOT_EXECUTED. "
                         "No canonical v2 origin is produced. Release gates remain separate.\n")
    return result


def changed_paths(root: Path, base: str) -> list[str]:
    if any(os.environ.get(key) for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR", "GIT_CONFIG_COUNT")):
        raise ValueError("Inherited Git namespace is not a proven CI base.")
    if not re.fullmatch(r"[0-9a-f]{40}", base) or base == "0" * 40:
        raise ValueError("A real event base commit is required.")
    def git(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False, timeout=30)
    if git("cat-file", "-e", base + "^{commit}").returncode:
        if git("fetch", "--no-tags", "--depth=1", "origin", base).returncode:
            raise ValueError("Event base is unavailable; retain early diagnostics.")
    diff = git("diff", "--name-only", "--no-renames", "-z", base, "HEAD", "--")
    if diff.returncode:
        raise ValueError("Cannot resolve event change scope.")
    return sorted({path for path in diff.stdout.split("\0") if path})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="")
    parser.add_argument("--run-affected", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    try:
        event = os.environ.get("GITHUB_EVENT_NAME", "")
        result = (run_affected(root, args.base, event=event) if args.run_affected else
                  ci_feedback_plan(changed_paths(root, args.base), root, event=event))
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        if args.run_affected:
            print(json.dumps({"status": "BLOCKED", "reason": "affected_execution_unavailable", "detail": str(error),
                              "full_public_profiles": "NOT_EXECUTED", "real_private_inputs": "NOT_EXECUTED",
                              "access_capture": "NOT_EXECUTED", "reusable_origin": False}))
            return 4
        result = {"native_preflight": True, "layer": "full", "reason": "unavailable_scope", "detail": str(error)}
    environment = os.environ
    print(json.dumps(result, sort_keys=True))
    output = environment.get("GITHUB_OUTPUT")
    if output and not args.run_affected:
        with Path(output).open("a") as stream:
            stream.write(f"preflight={str(result['native_preflight']).lower()}\nlayer={result['layer']}\n")
    return (0 if result["status"] == "PASS" else 4) if args.run_affected else 0


if __name__ == "__main__":
    raise SystemExit(main())
