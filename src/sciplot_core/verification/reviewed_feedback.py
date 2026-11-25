"""The reviewed public subset of the shared changed verification plan."""
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sciplot_core.verification.frequency_feedback import (
    FREQUENCY_ENTRY_NATIVE, FREQUENCY_ENTRY_PATHS, FREQUENCY_FOCUSED, FREQUENCY_WORKFLOW_NATIVE, FREQUENCY_WORKFLOW_PATHS,
)
from sciplot_core.verification.ordinary_plotting_owners import (
    MANAGED_CURVE_PROJECT_FOCUSED, MANAGED_CURVE_PROJECT_NATIVE, MANAGED_CURVE_PROJECT_PATHS,
)
from sciplot_core.verification.source_contracts import CHEAP_SOURCE_TARGETS
from sciplot_core.verification.scope_feedback import SCOPE_PATHS, scope_delta_is_reviewed
from sciplot_core.verification.task_control_owners import TASK_TIMING_FEEDBACK_TARGETS
from sciplot_core.verification.task_timing_feedback import TASK_TIMING_PATH

# Only isolated design prose can skip the historical native diagnostic.
NARRATIVE_PATHS = frozenset({"docs/DESIGN_PROJECT_LIFECYCLE.md", "docs/DESIGN_PROJECT_CORE_MIGRATION.md"})
DOCUMENTATION_PATHS = NARRATIVE_PATHS | {"README.md", "skill/references/ordinary-create.md"}

# These checks read prose and tracked paths. The CLI/MCP example contracts
# remain in public behavior for changes to their actual executable surfaces.
DOCUMENTATION_SOURCE_TARGETS = tuple("tests/test_documentation_contract.py::" + name for name in (
    "test_user_plotting_guidance_keeps_deliveries_source_adjacent",
    "test_current_documents_do_not_restore_the_dated_architecture_snapshot",
    "test_tracked_guidance_does_not_keep_a_duplicate_agent_file",
    "test_roadmap_contains_closable_work_not_standing_invariants",
    "test_active_documents_declare_distinct_responsibilities",
    "test_task_guidance_preserves_real_choices_and_separate_human_acceptance",
    "test_skill_defers_the_exact_mypy_scope_to_pyproject",
    "test_skill_entrypoint_is_bounded_and_its_routes_are_readable",
    "test_self_use_edit_guidance_keeps_deferred_readiness_and_full_evidence",
    "test_saved_figure_ai_entry_chooses_compact_only_for_known_managed_plots",
)) + (
    "tests/test_repository_policy.py::test_curated_docs_are_allowed_by_repository_policy",
    "tests/test_repository_policy.py::test_local_only_documentation_stays_ignored",
)

# Exact reviewed paths, not broad owner prefixes: shared code, unlisted tests,
# deleted files and changes to the planner itself keep complete public gates.
_TABLE_PATHS = frozenset({
    "src/sciplot_core/source_tables/curve_tables.py",
    "src/sciplot_core/source_tables/heatmap_tables.py",
    "src/sciplot_core/source_tables/parsing.py",
    "tests/test_plot_data_exports.py",
    "tests/test_source_numeric_encodings.py",
})
_TABLE_CHECKS = (
    "tests/test_legacy_core_migration.py::test_curve_table_parser_preserves_labels_units_and_numeric_pairs",
    "tests/test_legacy_core_migration.py::test_replicate_and_heatmap_parsers_keep_their_distinct_models",
    "tests/test_plot_data_exports.py",
    "tests/test_source_numeric_encodings.py",
)
_INTAKE_PATHS = frozenset({
    "src/sciplot_core/intake/table_preview.py", "tests/test_intake_review_recovery.py",
    "tests/test_intake_session_adapter.py",
})
_INTAKE_CHECKS = ("tests/test_intake_review_recovery.py", "tests/test_intake_session_adapter.py")
_ASSEMBLY_NATIVE_PATH = "src/sciplot_core/panel_assembly/native.py"
_ASSEMBLY_EXPORT_PATHS = frozenset({
    "src/sciplot_core/panel_assembly/export.py", "tests/test_panel_assembly_export.py",
    _ASSEMBLY_NATIVE_PATH,
})
_ASSEMBLY_PREVIEW_PATHS = frozenset({
    "src/sciplot_core/panel_assembly/preview.py", "tests/test_panel_assembly_preview.py",
    _ASSEMBLY_NATIVE_PATH,
})
_ASSEMBLY_CHECKS = (
    "tests/test_panel_assembly_export.py", "tests/test_panel_assembly_preview.py",
    "tests/test_panel_assembly_sources.py",
)
_ASSEMBLY_NATIVE_EXPORT_CHECKS = (
    "tests/test_panel_assembly_export.py::test_native_legacy_mixed_export_preserves_state_science_and_portable_sources",
    "tests/test_panel_assembly_export.py::test_native_managed_reflows_canonical_document_without_source_artifacts",
)

_ASSEMBLY_NATIVE_PREVIEW_CHECKS = (
    "tests/test_panel_assembly_preview.py::test_legacy_preview_uses_current_native_not_adjacent_pdf_and_does_not_accept_export",
    "tests/test_panel_assembly_preview.py::test_managed_preview_compiles_current_semantics_without_native_save_or_qa_claim",
)


_RAW_ANALYSIS_PATHS = frozenset({"src/sciplot_core/task_semantic_raw_analysis.py", "tests/test_task_shortcuts.py"})
_RAW_ANALYSIS_CHECKS = ("tests/test_task_shortcuts.py", "tests/test_task_semantic_creation.py")
_RAW_ANALYSIS_NATIVE = (
    "tests/test_task_semantic_creation.py::test_native_single_table_ftir_raw_overlay_preserves_sample_membership_and_descending_display",
    "tests/test_legacy_saved_plot.py::test_legacy_open_and_redraw_read_exact_saved_vsz_without_writing_project",
)
_SCOPE_CHECKS = (
    "tests/test_private_corpus_preflight.py::test_checked_in_inventory_is_explicitly_preliminary",
    "tests/test_private_corpus_preflight.py::test_complete_inventory_requires_bound_full_access_evidence",
    "tests/test_public_stage.py",
)


# Shared source-wide contracts and the actual public process/API guard remain
# cheap gates even when a reviewed leaf does not need native/scientific bodies.
_AFFECTED_GUARDS = (
    "tests/test_architecture_boundaries.py::test_non_probe_source_has_no_exact_duplicate_function_implementations",
    "tests/test_architecture_boundaries.py::test_scoped_type_gate_has_one_strict_owned_scope_and_ci_entrypoint",
    "tests/test_public_stage.py",
)


ScopeValidator = Callable[[Path, str, set[str], list[str], list[str]], bool]


def reviewed_feedback(
    paths: list[str], root: Path, unowned: list[str], *, base: str,
    scope_validator: ScopeValidator = scope_delta_is_reviewed,
) -> dict[str, Any]:
    from sciplot_core.verification.type_gate_owners import ARCHITECTURE_CORE_TARGETS

    reason = "unknown_owner" if unowned else "conservative_risk"
    targets: list[str] = []
    native_targets: list[str] = []
    selected = set(paths)
    if TASK_TIMING_PATH in selected and selected <= {TASK_TIMING_PATH, "tests/test_task_timing_feedback.py"} and not unowned:
        from sciplot_core.verification.task_timing_feedback import task_timing_feedback_eligible

        if task_timing_feedback_eligible(root):
            targets = list(TASK_TIMING_FEEDBACK_TARGETS)
            reason = "metadata_only_task_timing"
        else:
            reason = "task_timing_contract_not_proven"
    feedback_groups = (
        (_TABLE_PATHS, _TABLE_CHECKS, ()),
        (_INTAKE_PATHS, _INTAKE_CHECKS, ()),
        (_ASSEMBLY_EXPORT_PATHS, _ASSEMBLY_CHECKS, _ASSEMBLY_NATIVE_EXPORT_CHECKS),
        (_ASSEMBLY_PREVIEW_PATHS, _ASSEMBLY_CHECKS, _ASSEMBLY_NATIVE_PREVIEW_CHECKS),
        (FREQUENCY_WORKFLOW_PATHS, FREQUENCY_FOCUSED, FREQUENCY_WORKFLOW_NATIVE),
        (FREQUENCY_ENTRY_PATHS, FREQUENCY_FOCUSED, FREQUENCY_ENTRY_NATIVE),
        (MANAGED_CURVE_PROJECT_PATHS, MANAGED_CURVE_PROJECT_FOCUSED, MANAGED_CURVE_PROJECT_NATIVE),
        (_RAW_ANALYSIS_PATHS, _RAW_ANALYSIS_CHECKS, _RAW_ANALYSIS_NATIVE),
        (SCOPE_PATHS, _SCOPE_CHECKS, ()),
        (DOCUMENTATION_PATHS, ("tests/test_documentation_contract.py", "tests/test_repository_policy.py"), ()),
    )
    # A reviewed leaf and its own exact generated regression form one change.
    # Do not widen eligibility to every test called as a downstream consumer.
    reviewed = frozenset().union(*(owner_paths for owner_paths, _, _ in feedback_groups))
    reviewed_change = (bool(selected) and selected <= reviewed and not unowned
                       and all((root / path).is_file() and not (root / path).is_symlink() for path in selected))
    if reviewed_change:
        for owner_paths, owner_checks, owner_native in feedback_groups:
            if selected & owner_paths:
                targets.extend(owner_checks)
                native_targets.extend(owner_native)
        if selected & (FREQUENCY_WORKFLOW_PATHS | FREQUENCY_ENTRY_PATHS | MANAGED_CURVE_PROJECT_PATHS
                       | _RAW_ANALYSIS_PATHS | DOCUMENTATION_PATHS | SCOPE_PATHS):
            targets.extend((*ARCHITECTURE_CORE_TARGETS, *_AFFECTED_GUARDS))
        reason = "reviewed_owner_native_feedback" if native_targets else "reviewed_owner_feedback"
    if selected & SCOPE_PATHS and reviewed_change and not scope_validator(root, base, selected, targets, native_targets):
        targets, native_targets, reason = [], [], "scope_delta_not_proven"
    if targets:
        targets.extend(CHEAP_SOURCE_TARGETS)
        if not reviewed_change:
            targets.extend((*ARCHITECTURE_CORE_TARGETS, *_AFFECTED_GUARDS))
    return {"reason": reason, "targets": sorted(set(targets)), "native_targets": sorted(set(native_targets)),
            "source_only": bool(targets) and bool(selected) and selected <= DOCUMENTATION_PATHS}
