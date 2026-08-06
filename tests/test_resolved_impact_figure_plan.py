from __future__ import annotations

from pathlib import Path
import re

import pytest
from openpyxl import Workbook

import sciplot_core.semantic_sources.impact_sources as impact_sources
from sciplot_core.figure_plan import (
    FigurePlanResolutionError,
    ResolvedFigurePlan,
    request_for_figure_task,
    resolve_current_figure_plan,
    resolve_figure_plan,
    stable_impact_figure_id,
)
from sciplot_core.semantic_sources.models import ImpactReplicatePayload


def _impact_payload(
    samples: tuple[str, ...] = ("E0", "E2"),
) -> ImpactReplicatePayload:
    return ImpactReplicatePayload(
        rows=(),
        samples=samples,
        replicate_counts=tuple(2 for _sample in samples),
        values=tuple((1.0, 2.0) for _sample in samples),
        unit="kJ/m2",
    )


def _resolve_impact_plan(
    *,
    tmp_path: Path,
    template: str,
    request: dict[str, object],
) -> ResolvedFigurePlan:
    source = tmp_path / "impact.xlsx"
    source.touch(exist_ok=True)
    plan = resolve_figure_plan(
        rule_id="impact_metric",
        template=template,
        study_model={},
        input_path=source,
        request=request,
    )
    assert plan is not None
    return plan


def test_impact_unicode_punctuation_ids_survive_source_reordering(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    labels = ("2 mm", "厚度 4 mm（缺口）", "常温，未缺口")
    payloads = {label: _impact_payload() for label in labels}
    available = [(label, payloads[label]) for label in labels]
    monkeypatch.setattr(
        impact_sources,
        "read_impact_condition_payloads",
        lambda _source: available,
    )

    first = _resolve_impact_plan(
        tmp_path=tmp_path,
        template="box_strip",
        request={},
    )
    available = [
        (labels[2], payloads[labels[2]]),
        (labels[0], payloads[labels[0]]),
        (labels[1], payloads[labels[1]]),
    ]
    reordered = _resolve_impact_plan(
        tmp_path=tmp_path,
        template="box_strip",
        request={},
    )

    first_ids = {task.conditions[0]: task.figure_id for task in first.tasks}
    reordered_ids = {task.conditions[0]: task.figure_id for task in reordered.tasks}
    assert first_ids == reordered_ids
    assert first_ids == {label: stable_impact_figure_id(label) for label in labels}
    assert len(set(first_ids.values())) == len(labels)
    assert all(
        re.fullmatch(r"[a-z0-9][a-z0-9_]*", figure_id)
        for figure_id in first_ids.values()
    )
    assert tuple(task.conditions[0] for task in first.tasks) == labels
    assert tuple(task.conditions[0] for task in reordered.tasks) == (
        labels[2],
        labels[0],
        labels[1],
    )


def test_impact_point_line_selection_is_frozen_into_task_projection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    available = [
        ("2 mm", _impact_payload()),
        ("厚度 4 mm（缺口）", _impact_payload()),
        ("常温，未缺口", _impact_payload(("E3", "E4"))),
    ]
    monkeypatch.setattr(
        impact_sources,
        "read_impact_condition_payloads",
        lambda _source: available,
    )
    requested_order = ("厚度 4 mm（缺口）", "2 mm")
    request = {
        "condition_order": list(requested_order),
        "condition_label_mapping": {
            requested_order[0]: "4 mm notched",
            requested_order[1]: "2 mm",
        },
    }

    plan = _resolve_impact_plan(
        tmp_path=tmp_path,
        template="point_line",
        request=request,
    )
    task = plan.tasks[0]
    persisted = ResolvedFigurePlan.from_payload(plan.to_payload())
    projected = request_for_figure_task(
        {
            "condition_order": ["常温，未缺口", "2 mm"],
            "condition_label_mapping": {"常温，未缺口": "later override"},
        },
        persisted.tasks[0],
    )

    assert plan.selection_policy == "explicit_condition_order"
    assert task.conditions == requested_order
    assert task.condition_labels == ("4 mm notched", "2 mm")
    assert persisted.tasks[0].conditions == requested_order
    assert projected["condition_order"] == list(requested_order)
    assert projected["condition_label_mapping"] == {
        requested_order[0]: "4 mm notched",
        requested_order[1]: "2 mm",
    }
    assert projected["study_model"]["figure_queue"][0]["id"] == (
        "impact_strength_by_sample"
    )


def test_resolve_current_rejects_added_or_reordered_impact_sheets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = [
        ("2 mm", _impact_payload()),
        ("4 mm", _impact_payload()),
    ]
    available = list(base)
    monkeypatch.setattr(
        impact_sources,
        "read_impact_condition_payloads",
        lambda _source: available,
    )
    persisted = _resolve_impact_plan(
        tmp_path=tmp_path,
        template="box_strip",
        request={},
    )
    source = tmp_path / "impact.xlsx"

    available = [*base, ("6 mm", _impact_payload())]
    with pytest.raises(FigurePlanResolutionError) as added:
        resolve_current_figure_plan(
            persisted=persisted.to_payload(),
            rule_id="impact_metric",
            template="box_strip",
            study_model={},
            input_path=source,
            request={},
        )
    assert added.value.reason_code == "stale_resolved_figure_plan"

    available = [base[1], base[0]]
    with pytest.raises(FigurePlanResolutionError) as reordered:
        resolve_current_figure_plan(
            persisted=persisted.to_payload(),
            rule_id="impact_metric",
            template="box_strip",
            study_model={},
            input_path=source,
            request={},
        )
    assert reordered.value.reason_code == "stale_resolved_figure_plan"


def test_resolve_current_rejects_changed_point_line_condition_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    available = [
        ("2 mm", _impact_payload()),
        ("4 mm", _impact_payload()),
        ("6 mm", _impact_payload()),
    ]
    monkeypatch.setattr(
        impact_sources,
        "read_impact_condition_payloads",
        lambda _source: available,
    )
    persisted = _resolve_impact_plan(
        tmp_path=tmp_path,
        template="point_line",
        request={"condition_order": ["2 mm", "4 mm"]},
    )

    with pytest.raises(FigurePlanResolutionError) as changed:
        resolve_current_figure_plan(
            persisted=persisted.to_payload(),
            rule_id="impact_metric",
            template="point_line",
            study_model={},
            input_path=tmp_path / "impact.xlsx",
            request={"condition_order": ["4 mm", "2 mm"]},
        )

    assert changed.value.reason_code == "stale_resolved_figure_plan"


def test_impact_legacy_stems_and_collision_mapping_are_stable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    available = [
        ("2 mm", _impact_payload()),
        ("4 mm", _impact_payload()),
    ]
    monkeypatch.setattr(
        impact_sources,
        "read_impact_condition_payloads",
        lambda _source: available,
    )
    legacy = _resolve_impact_plan(
        tmp_path=tmp_path,
        template="box_strip",
        request={},
    )
    by_condition = {task.conditions[0]: task for task in legacy.tasks}

    assert (
        by_condition["2 mm"].artifact_stem,
        by_condition["2 mm"].document_stem,
    ) == ("impact_2mm", "impact_2_mm")
    assert (
        by_condition["4 mm"].artifact_stem,
        by_condition["4 mm"].document_stem,
    ) == ("impact_4mm", "impact_4_mm")

    collision_labels = ("A B", "AB", "A-B", "A_B")
    available = [(condition, _impact_payload()) for condition in collision_labels]
    first = _resolve_impact_plan(
        tmp_path=tmp_path,
        template="box_strip",
        request={},
    )
    available = [
        (condition, _impact_payload()) for condition in reversed(collision_labels)
    ]
    reordered = _resolve_impact_plan(
        tmp_path=tmp_path,
        template="box_strip",
        request={},
    )
    first_stems = {
        task.conditions[0]: (task.artifact_stem, task.document_stem)
        for task in first.tasks
    }
    reordered_stems = {
        task.conditions[0]: (task.artifact_stem, task.document_stem)
        for task in reordered.tasks
    }

    assert first_stems == reordered_stems
    assert len({stems[0] for stems in first_stems.values()}) == len(collision_labels)
    assert len({stems[1] for stems in first_stems.values()}) == len(collision_labels)
    assert first_stems["A B"][0] != first_stems["AB"][0]
    assert first_stems["A B"][1] != first_stems["A-B"][1]


def test_xlsm_impact_workbook_resolves_all_sheets(
    tmp_path: Path,
) -> None:
    source = tmp_path / "impact.xlsm"
    workbook = Workbook()
    for index, condition in enumerate(("2 mm", "厚度 4 mm（缺口）")):
        sheet = workbook.active if index == 0 else workbook.create_sheet()
        sheet.title = condition
        for row in (
            ("Re", "Re"),
            ("kJ/m²", "kJ/m²"),
            ("E0", "E2"),
            (1.0, 2.0),
            (1.5, 2.5),
        ):
            sheet.append(row)
    workbook.save(source)

    parsed = impact_sources.read_impact_condition_payloads(source)
    plan = resolve_figure_plan(
        rule_id="impact_metric",
        template="box_strip",
        study_model={},
        input_path=source,
        request={},
    )

    assert [condition for condition, _payload in parsed] == [
        "2 mm",
        "厚度 4 mm（缺口）",
    ]
    assert plan is not None
    assert tuple(task.conditions[0] for task in plan.tasks) == (
        "2 mm",
        "厚度 4 mm（缺口）",
    )
