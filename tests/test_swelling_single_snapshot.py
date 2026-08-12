from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import pytest

from sciplot_core._paths import resolve_fixture_path
from sciplot_core.materials_rules import get_rule
from sciplot_core.semantic import prepare_semantic_source
from sciplot_core.semantic_sources import prepare_curve_families, swelling_transform
from sciplot_core.semantic_sources.scientific_source import resolve_scientific_source
from sciplot_core.semantic_sources.scientific_transform import (
    ResolvedScientificTransform,
)
from sciplot_core.studio_core.figure_task_evidence import (
    generic_figure_queue_from_plan,
)
from sciplot_core.workflow import auto_split


def _prepared_curve_rows(
    source: Path,
    *,
    series_count: int,
) -> tuple[list[str], list[str], list[str], tuple[tuple[tuple[float, float], ...], ...]]:
    with source.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    headers = rows[0]
    units = rows[1]
    samples = rows[2]
    points: list[tuple[tuple[float, float], ...]] = []
    for series_index in range(series_count):
        x_index = series_index * 2
        series_points: list[tuple[float, float]] = []
        for row in rows[3:]:
            x_value = row[x_index].strip()
            y_value = row[x_index + 1].strip()
            assert bool(x_value) == bool(y_value)
            if x_value:
                series_points.append((float(x_value), float(y_value)))
        points.append(tuple(series_points))
    return headers, units, samples, tuple(points)


def test_swelling_prepare_and_terminals_reuse_one_resolved_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rule = get_rule("swelling_curve")
    source = resolve_fixture_path(str(rule.fixture_path or ""))
    resolver_calls: list[tuple[Path, object]] = []
    real_resolver = swelling_transform.resolve_swelling_scientific_transform

    def counted_resolver(
        selected: Path,
        *,
        series_order: object = None,
    ) -> ResolvedScientificTransform:
        resolver_calls.append((selected, series_order))
        return real_resolver(selected, series_order=series_order)

    monkeypatch.setattr(
        swelling_transform,
        "resolve_swelling_scientific_transform",
        counted_resolver,
    )
    resolved = resolve_scientific_source(
        source,
        rule_id=rule.rule_id,
        request={},
        template=rule.template,
    )

    assert resolved is not None
    transform = resolved.require_domain(ResolvedScientificTransform)
    plan = resolved.figure_plan
    assert plan is not None
    task = plan.tasks[0]
    sample_order = tuple(series.sample for series in transform.series)
    assert resolver_calls == [(source, None)]
    assert task.sample_order == sample_order

    monkeypatch.setattr(
        prepare_curve_families,
        "resolve_single_curve_transform",
        lambda *_args, **_kwargs: pytest.fail(
            "swelling preparation reread an already-resolved source"
        ),
    )
    prepared = prepare_semantic_source(
        source,
        output_dir=tmp_path / "prepared",
        semantic={"rule_id": rule.rule_id, "semantic_family": rule.semantic_family},
        resolved_scientific_source=resolved,
    )

    assert resolver_calls == [(source, None)]
    step = prepared["transform_steps"][0]
    contract = transform.contract.to_payload()
    assert step["parameters"]["scientific_transform"] == contract
    assert step["parameters"]["series_order"] == list(sample_order)
    headers, units, samples, points = _prepared_curve_rows(
        Path(str(prepared["processed_source"])),
        series_count=len(transform.series),
    )
    assert headers == [
        value
        for series in transform.series
        for value in (series.x_label, series.y_label)
    ]
    assert units == [
        value
        for series in transform.series
        for value in (series.x_unit, series.y_unit)
    ]
    assert samples == [sample for sample in sample_order for _axis in range(2)]
    assert points == tuple(series.points for series in transform.series)

    queue = generic_figure_queue_from_plan(
        plan,
        render_adapter=rule.render_adapter,
    )
    assert [item["id"] for item in queue] == [task.figure_id]
    assert queue[0]["resolved_figure_task"] == task.to_payload()
    bundle_calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        auto_split,
        "render_selected_single_task_bundle",
        lambda input_path, **kwargs: bundle_calls.append(
            {"input_path": input_path, **kwargs}
        )
        or {"kind": "swelling_single_task_result"},
    )
    monkeypatch.setattr(
        auto_split,
        "render_to_dir",
        lambda *_args, **_kwargs: pytest.fail(
            "planned swelling fell back to an unplanned renderer path"
        ),
    )
    render_result = auto_split._render_with_auto_split(
        Path(str(prepared["processed_source"])),
        template=rule.template,
        output_dir=tmp_path / "rendered",
        options={},
        export_formats=["pdf"],
        request={
            "rule_id": rule.rule_id,
            "resolved_figure_plan": plan.to_payload(),
        },
        _terminal_source_prepared=True,
        _resolved_scientific_source=resolved,
        _resolved_figure_plan=plan,
    )
    assert render_result == {"kind": "swelling_single_task_result"}
    assert len(bundle_calls) == 1
    assert bundle_calls[0]["input_path"] == Path(str(prepared["processed_source"]))
    assert bundle_calls[0]["plan"] is plan
    assert bundle_calls[0]["task"] is task
    assert bundle_calls[0]["terminal_source_prepared"] is True

    fallback_calls: list[tuple[Path, str, object]] = []

    def fallback_transform(
        selected: Path,
        *,
        rule: Any,
        series_order: object = None,
    ) -> ResolvedScientificTransform:
        fallback_calls.append((selected, rule.rule_id, series_order))
        return transform

    monkeypatch.setattr(
        prepare_curve_families,
        "resolve_single_curve_transform",
        fallback_transform,
    )
    requested_order = list(reversed(sample_order))
    fallback_prepared = prepare_semantic_source(
        source,
        output_dir=tmp_path / "fallback",
        semantic={"rule_id": rule.rule_id, "semantic_family": rule.semantic_family},
        series_order=requested_order,
    )
    assert fallback_calls == [(source, rule.rule_id, requested_order)]
    assert fallback_prepared["transform_steps"][0]["parameters"][
        "scientific_transform"
    ] == contract
    assert resolver_calls == [(source, None)]
