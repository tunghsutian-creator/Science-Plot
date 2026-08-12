"""Focused changed-owner mapping for the shared numeric axis policy."""

from __future__ import annotations

from sciplot_core.verification.owner_model import ChangedOwner


GENERIC_AXIS_OWNERS = (
    ChangedOwner(
        owner_id="generic_axis_policy",
        exact_paths=frozenset(
            {
                "src/sciplot_core/studio_render/axis_contract.py",
                "src/sciplot_core/studio_render/axis_limits.py",
            }
        ),
        owned_test_paths=frozenset({"tests/test_generic_axis_policy.py"}),
        pytest_targets=(
            "tests/test_generic_axis_policy.py::test_generic_linear_axis_padding_uses_the_observed_span",
            "tests/test_generic_axis_policy.py::test_reverse_linear_axis_only_reverses_bounds_and_major_ticks",
        ),
        release_gates=("full_pytest",),
    ),
)


__all__ = ["GENERIC_AXIS_OWNERS"]
