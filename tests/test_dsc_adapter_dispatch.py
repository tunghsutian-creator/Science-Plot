from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from sciplot_core.figure_plan import resolution as figure_plan_resolution
from sciplot_core.materials_rules import get_rule
from sciplot_core.semantic_sources import scientific_source


def test_dsc_catalog_uses_the_shared_single_curve_spine() -> None:
    rule = get_rule("dsc_curve")

    assert rule.scientific_source_adapter == "registered_paired_curve"
    assert rule.figure_plan_adapter == "registered_single_curve"
    assert rule.render_adapter == "generic"


def test_dsc_plan_dispatches_through_the_shared_scientific_source_adapter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "arbitrary-dsc.csv"
    expected_plan = object()
    calls: list[dict[str, object]] = []

    def resolve_shared_source(
        input_path: Path,
        *,
        rule_id: str,
        request: dict[str, object],
        template: str,
        study_model: dict[str, object],
    ) -> SimpleNamespace:
        calls.append(
            {
                "input_path": input_path,
                "rule_id": rule_id,
                "request": request,
                "template": template,
                "study_model": study_model,
            }
        )
        return SimpleNamespace(figure_plan=expected_plan)

    monkeypatch.setattr(
        scientific_source,
        "resolve_scientific_source",
        resolve_shared_source,
    )

    result = figure_plan_resolution.resolve_figure_plan(
        rule_id="dsc_curve",
        template="curve",
        study_model={"figure_queue": []},
        input_path=source,
        request={"series_order": ["sample-b", "sample-a"]},
    )

    assert result is expected_plan
    assert calls == [
        {
            "input_path": source,
            "rule_id": "dsc_curve",
            "request": {"series_order": ["sample-b", "sample-a"]},
            "template": "curve",
            "study_model": {"figure_queue": []},
        }
    ]
