from __future__ import annotations

import pytest

from sciplot_core.publication import build_publication_intent
from sciplot_core.publication_layouts import build_composite_layout


@pytest.mark.parametrize(
    "removed_key",
    ["composition_modules", "composition_legend_policy"],
)
def test_removed_composition_request_keys_fail_with_native_veusz_migration(
    removed_key: str,
) -> None:
    with pytest.raises(ValueError, match="native Veusz"):
        build_publication_intent({}, request={removed_key: []})


def test_existing_composition_plan_is_not_carried_into_current_intent() -> None:
    intent = build_publication_intent(
        {},
        existing={"composition_plan": {"state": "planned_not_compiled"}},
    )

    assert "composition_plan" not in intent


def test_publication_layout_is_metadata_not_a_future_frontend_plan() -> None:
    layout = build_composite_layout("single_180")

    assert layout["renderer_contract"]["metadata_only"] is True
    assert "future_widget_tree" not in layout["renderer_contract"]
