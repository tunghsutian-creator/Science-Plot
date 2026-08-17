"""Focused changed-owner mapping for shared axis and presentation policy."""

from __future__ import annotations

from sciplot_core.verification.owner_model import ChangedOwner


GENERIC_AXIS_OWNERS = (
    ChangedOwner(
        owner_id="generic_axis_policy",
        exact_paths=frozenset(
            {
                "src/sciplot_core/source_inspection/intent_recognition.py",
                "src/sciplot_core/studio_core/request_overrides.py",
                "src/sciplot_core/studio_render/axis_contract.py",
                "src/sciplot_core/studio_render/axis_limits.py",
                "src/sciplot_core/studio_render/metric_columns.py",
                "src/sciplot_core/studio_render/readability_defaults.py",
            }
        ),
        owned_test_paths=frozenset(
            {
                "tests/test_generic_axis_policy.py",
                "tests/test_registered_single_curve_figure_plan.py",
                "tests/test_semantic_validation.py",
                "tests/test_source_recognition_contract.py",
                "tests/test_studio_request_overrides.py",
            }
        ),
        pytest_targets=(
            "tests/test_generic_axis_policy.py",
            "tests/test_registered_single_curve_figure_plan.py",
            "tests/test_semantic_validation.py",
            "tests/test_source_recognition_contract.py",
            "tests/test_studio_request_overrides.py",
        ),
        release_gates=("full_pytest",),
    ),
)


__all__ = ["GENERIC_AXIS_OWNERS"]
