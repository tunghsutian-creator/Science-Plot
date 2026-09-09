"""Verification ownership for local tasks, native annotations and distribution."""

from sciplot_core.verification.owner_model import ChangedOwner
from sciplot_core.verification.type_gate_owners import ARCHITECTURE_CORE_TARGETS


TASK_CONTROL_OWNERS = (
    ChangedOwner(
        owner_id="local_task_control",
        path_prefixes=("src/sciplot_core/task_",),
        exact_paths=frozenset({
            ".github/workflows/minimal-repository.yml",
            "skill/references/experiment-group.json",
            "skill/references/figure-comparison.json",
            "src/sciplot_core/cli/parsers/tasks.py", "src/sciplot_core/cli/dispatch/tasks.py",
            "src/sciplot_core/studio_core/project_creation.py",
            "src/sciplot_core/studio_core/project_receipt.py",
            "src/sciplot_core/studio_core/project_capabilities.py",
        }),
        owned_test_paths=frozenset({"tests/test_task_review_gallery.py", "tests/test_task_control.py", "tests/test_task_control_native.py", "tests/test_task_recovery.py", "tests/test_task_preview_revision.py", "tests/test_task_revision_guards.py", "tests/test_task_discovery.py", "tests/test_task_groups.py", "tests/test_task_groups_native.py", "tests/test_task_comparisons.py", "tests/test_task_comparisons_native.py"}),
        pytest_targets=("tests/test_task_review_gallery.py", "tests/test_task_control.py", "tests/test_task_control_native.py", "tests/test_task_recovery.py", "tests/test_task_preview_revision.py", "tests/test_task_discovery.py",
                        "tests/test_task_revision_guards.py", "tests/test_task_groups.py", "tests/test_task_groups_native.py",
                        "tests/test_task_comparisons.py", "tests/test_task_comparisons_native.py",
                        "tests/test_project_create_cli.py", *ARCHITECTURE_CORE_TARGETS),
        mypy_required=True, handoff_gates=("doctor",),
        final_milestone_gates=("smoke",), release_gates=("full_pytest",),
    ),
    ChangedOwner(
        owner_id="native_annotations",
        path_prefixes=("src/sciplot_core/studio_core/annotation_",
                       "src/sciplot_core/studio_core/peak_"),
        exact_paths=frozenset({
            "src/sciplot_core/studio_core/document_edit_companion.py",
            "src/sciplot_core/studio_core/sample_style.py",
            "src/sciplot_core/studio_core/sample_style_presets.py",
            "src/sciplot_core/veusz_worker/annotations.py",
            "src/sciplot_core/veusz_worker/spec_audit/labels.py",
            "src/sciplot_core/veusz_worker/spec_audit/overlays.py",
        }),
        owned_test_paths=frozenset({"tests/test_annotation_operations.py", "tests/test_annotation_operations_native.py", "tests/test_annotation_validation.py", "tests/test_sample_style_presets.py", "tests/test_sample_style_presets_native.py"}),
        pytest_targets=("tests/test_annotation_operations.py", "tests/test_annotation_operations_native.py", "tests/test_annotation_validation.py",
                        "tests/test_sample_style_presets.py", "tests/test_sample_style_presets_native.py",
                        "tests/test_document_edit.py", "tests/test_document_edit_native.py",
                        *ARCHITECTURE_CORE_TARGETS),
        mypy_required=True, handoff_gates=("doctor",),
        final_milestone_gates=("smoke",), release_gates=("acceptance_rules", "full_pytest"),
    ),
    ChangedOwner(
        owner_id="mcp_control_adapter", path_prefixes=("src/sciplot_core/mcp_server/",),
        exact_paths=frozenset({"src/sciplot_core/studio_core/control_results.py"}),
        owned_test_paths=frozenset({"tests/test_mcp_server.py", "tests/test_mcp_stdio.py"}),
        pytest_targets=("tests/test_mcp_server.py", "tests/test_mcp_stdio.py", *ARCHITECTURE_CORE_TARGETS),
        mypy_required=True, handoff_gates=("doctor",),
        final_milestone_gates=("smoke",), release_gates=("full_pytest",),
    ),
    ChangedOwner(
        owner_id="macos_distribution", path_prefixes=("distribution/",),
        exact_paths=frozenset({"src/sciplot_core/veusz_runtime.py", "src/sciplot_core/studio_core/runtime.py"}),
        owned_test_paths=frozenset({"tests/test_macos_distribution.py", "tests/test_bundled_runtime.py"}),
        pytest_targets=("tests/test_macos_distribution.py", "tests/test_bundled_runtime.py",
                        *ARCHITECTURE_CORE_TARGETS),
        mypy_required=True, handoff_gates=("doctor",),
        final_milestone_gates=("smoke",), release_gates=("full_pytest",),
    ),
)
