"""Materialize exact source-bound tables for mechanical FigureTasks."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import pandas as pd

from sciplot_core.figure_plan import CartesianMetricBinding, ResolvedFigurePlan
from sciplot_core.figure_plan.task import FigureTask
from sciplot_core.mechanical_figure_contract import (
    MechanicalFigureTaskContract,
    mechanical_figure_contract,
    mechanical_selection_policy,
)
from sciplot_core.mechanical_render_options import (
    mechanical_summary_render_options,
    mechanical_task_explicit_option_keys,
)
from sciplot_core.preparation_source_attestation import PreparationSourceAttestation
from sciplot_core.semantic_sources.mechanical_facts import (
    MechanicalSourceFacts,
    load_mechanical_source_facts,
)
from sciplot_core.source_tables import canonicalize_token, load_curve_table
from sciplot_core.terminal_source_binding import MaterializedTerminalSourceBinding


_PLAN_MISMATCH = "mechanical_figure_plan_mismatch"
_SOURCE_MISMATCH = "mechanical_terminal_source_binding_mismatch"
MechanicalTaskKind = Literal["curve", "summary"]


@dataclass(frozen=True, slots=True)
class MechanicalSummaryGroup:
    """One ordered sample's unchanged raw observations for one metric."""

    sample: str
    replicates: tuple[str, ...]
    values: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class MechanicalTaskSource:
    """One task-owned terminal table and its typed source authority."""

    task: FigureTask
    source: Path
    render_options: dict[str, Any]
    binding: MaterializedTerminalSourceBinding
    task_kind: MechanicalTaskKind
    metric: str
    unit: str
    groups: tuple[MechanicalSummaryGroup, ...] = ()
    explicit_render_option_keys: tuple[str, ...] = ()


def build_mechanical_task_sources(
    prepared_source: Path,
    *,
    raw_source: Path,
    source_attestation: PreparationSourceAttestation,
    figure_plan: ResolvedFigurePlan,
    output_dir: Path,
    request: dict[str, Any],
    options: dict[str, Any],
) -> list[MechanicalTaskSource]:
    """Validate one source snapshot, then materialize every selected task table."""

    prepared = prepared_source.expanduser().resolve()
    raw = raw_source.expanduser().resolve()
    facts = load_mechanical_source_facts(
        raw,
        rule_id=figure_plan.rule_id,
        series_order=request.get("series_order"),
    )
    curve_mode = require_mechanical_execution_plan(
        figure_plan,
        facts=facts,
        prepared_source=prepared,
        source_attestation=source_attestation,
    )
    expected_curve = tuple(facts.curve_series_for_mode(curve_mode))
    _validate_prepared_curve(prepared, expected_curve)

    target = output_dir.expanduser().resolve()
    target.mkdir(parents=True, exist_ok=False)
    raw_sources = tuple(Path(item.path) for item in source_attestation.selected_sources)
    contract = mechanical_figure_contract(figure_plan.rule_id)
    records: list[MechanicalTaskSource] = []
    for task, task_contract in zip(
        figure_plan.tasks,
        contract.tasks,
        strict=True,
    ):
        if task_contract.is_summary:
            groups = _summary_groups(
                facts,
                metric=task_contract.y_metric,
            )
            terminal_source = target / f"{task.artifact_stem}.csv"
            _write_summary_table(
                terminal_source,
                groups=groups,
                task_contract=task_contract,
            )
            point_counts = {group.sample: len(group.values) for group in groups}
            task_options = mechanical_summary_render_options(
                task_contract,
                options=options,
            )
            kind: MechanicalTaskKind = "summary"
        else:
            groups = ()
            terminal_source = target / f"{task.artifact_stem}.csv"
            _write_curve_terminal_table(
                terminal_source,
                series=expected_curve,
                task_contract=task_contract,
            )
            point_counts = {
                series.sample: len(series.points) for series in expected_curve
            }
            task_options = {
                **options,
                "legend_position": options.get("legend_position", "auto"),
                "x_label_override": task_contract.x_label,
                "y_label_override": task_contract.y_label,
                "x_metric": task_contract.x_metric,
                "y_metric": task_contract.y_metric,
            }
            kind = "curve"
        binding = MaterializedTerminalSourceBinding.create(
            task_key=task.figure_id,
            rule_id=figure_plan.rule_id,
            template=task.template,
            x_metric=task_contract.x_metric,
            y_metric=task_contract.y_metric,
            raw_sources=raw_sources,
            prepared_source=prepared,
            terminal_source=terminal_source,
            sample_order=task.sample_order,
            point_counts=point_counts,
        )
        records.append(
            MechanicalTaskSource(
                task=task,
                source=terminal_source,
                render_options=task_options,
                binding=binding,
                task_kind=kind,
                metric=task_contract.y_metric,
                unit=task_contract.y_unit,
                groups=groups,
                explicit_render_option_keys=mechanical_task_explicit_option_keys(
                    request,
                    render_options=task_options,
                    summary=kind == "summary",
                ),
            )
        )
    return records


def require_mechanical_execution_plan(
    plan: ResolvedFigurePlan,
    *,
    facts: MechanicalSourceFacts,
    prepared_source: Path,
    source_attestation: PreparationSourceAttestation,
) -> str:
    """Reject forged, stale, reordered, or scientifically divergent plans."""

    contract = mechanical_figure_contract(plan.rule_id)
    curve_mode = next(
        (
            mode
            for mode in ("representative", "individual")
            if plan.selection_policy == mechanical_selection_policy(mode)
        ),
        None,
    )
    if (
        curve_mode is None
        or plan.primary_figure_id != contract.primary_task.figure_id
        or plan.source_sha256 != facts.source_sha256
        or len(plan.tasks) != len(contract.tasks)
        or facts.rule_id != plan.rule_id
    ):
        _fail(_PLAN_MISMATCH, "plan identity, source, or task count diverged")
    source_attestation.verify_current(
        source_root=Path(facts.source_root),
        prepared_source=prepared_source,
    )
    attested_paths = tuple(
        Path(item.path).resolve() for item in source_attestation.selected_sources
    )
    fact_paths = tuple(path.resolve() for path in facts.selected_sources)
    if (
        source_attestation.rule_id != plan.rule_id
        or source_attestation.source_tree_sha256_after != facts.source_sha256
        or attested_paths != fact_paths
    ):
        _fail(_SOURCE_MISMATCH, "semantic preparation and source facts diverged")

    summary_order = tuple(facts.sample_order)
    summary_counts = tuple(facts.replicate_counts)
    metric_units = dict(facts.metric_units)
    curve_order = facts.curve_sample_order(curve_mode)
    curve_counts = (
        summary_counts
        if curve_mode == "representative"
        else tuple((sample, 1) for sample in curve_order)
    )
    if (
        facts.x_label != contract.primary_task.source_x_label
        or facts.y_label != contract.primary_task.source_y_label
        or facts.x_unit != contract.primary_task.x_unit
        or facts.y_unit != contract.primary_task.y_unit
    ):
        _fail(_SOURCE_MISMATCH, "mechanical curve labels or units diverged")
    for order, (task, expected) in enumerate(
        zip(plan.tasks, contract.tasks, strict=True),
        start=1,
    ):
        binding = task.metric_binding
        expected_order = curve_order if order == 1 else summary_order
        expected_counts = curve_counts if order == 1 else summary_counts
        exact = (
            task.order == order
            and task.figure_id == expected.figure_id
            and task.title == expected.title
            and isinstance(binding, CartesianMetricBinding)
            and binding.x_metric == expected.x_metric
            and binding.y_metric == expected.y_metric
            and task.template == expected.template
            and task.artifact_stem == expected.artifact_stem
            and task.document_stem == expected.document_stem
            and task.sample_order == expected_order
            and task.replicate_counts == expected_counts
            and not task.conditions
            and not task.condition_labels
        )
        if not exact:
            _fail(_PLAN_MISMATCH, f"task {order} conflicts with canonical contract")
        if expected.is_summary and metric_units.get(expected.y_metric) != (
            expected.y_unit
        ):
            _fail(_SOURCE_MISMATCH, f"unit for {expected.y_metric} diverged")
    return curve_mode


def _validate_prepared_curve(
    prepared_source: Path,
    expected: tuple[Any, ...],
) -> None:
    actual = load_curve_table(prepared_source)
    if len(actual) != len(expected):
        _fail(_SOURCE_MISMATCH, "prepared curve series coverage diverged")
    for observed, source in zip(actual, expected, strict=True):
        points = tuple(
            (float(x), float(y))
            for x, y in observed.data.itertuples(index=False, name=None)
        )
        identities_match = (
            observed.sample == source.sample
            and canonicalize_token(observed.x_label)
            == canonicalize_token(source.x_label)
            and canonicalize_token(observed.y_label)
            == canonicalize_token(source.y_label)
            and observed.x_unit == source.x_unit
            and observed.y_unit == source.y_unit
            and len(points) == len(source.points)
        )
        if not identities_match or any(
            not math.isclose(x, sx, rel_tol=1e-12, abs_tol=1e-12)
            or not math.isclose(y, sy, rel_tol=1e-12, abs_tol=1e-12)
            for (x, y), (sx, sy) in zip(points, source.points, strict=True)
        ):
            _fail(_SOURCE_MISMATCH, f"prepared curve for {source.sample!r} diverged")


def _summary_groups(
    facts: MechanicalSourceFacts,
    *,
    metric: str,
) -> tuple[MechanicalSummaryGroup, ...]:
    rows = facts.summary_records()
    groups: list[MechanicalSummaryGroup] = []
    for sample, expected_count in facts.replicate_counts:
        selected = [row for row in rows if row.get("sample") == sample]
        replicates = tuple(str(row.get("replicate") or "") for row in selected)
        try:
            values = tuple(float(row[metric]) for row in selected)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                f"{_SOURCE_MISMATCH}: raw metric {metric!r} is incomplete."
            ) from exc
        if (
            len(values) != expected_count
            or not all(replicates)
            or len(set(replicates)) != len(replicates)
            or not all(math.isfinite(value) for value in values)
        ):
            _fail(_SOURCE_MISMATCH, f"raw observations for {sample!r} diverged")
        groups.append(
            MechanicalSummaryGroup(
                sample=sample,
                replicates=replicates,
                values=values,
            )
        )
    if sum(len(group.values) for group in groups) != len(rows):
        _fail(_SOURCE_MISMATCH, "summary rows contain unknown sample identities")
    return tuple(groups)


def _write_summary_table(
    path: Path,
    *,
    groups: tuple[MechanicalSummaryGroup, ...],
    task_contract: MechanicalFigureTaskContract,
) -> None:
    rows: list[list[Any]] = [
        [task_contract.y_label for _group in groups],
        [task_contract.y_unit for _group in groups],
        [group.sample for group in groups],
    ]
    for index in range(max(len(group.values) for group in groups)):
        rows.append(
            [
                group.values[index] if index < len(group.values) else ""
                for group in groups
            ]
        )
    pd.DataFrame(rows).to_csv(path, header=False, index=False)


def _write_curve_terminal_table(
    path: Path,
    *,
    series: tuple[Any, ...],
    task_contract: MechanicalFigureTaskContract,
) -> None:
    rows: list[list[Any]] = [[], [], []]
    for item in series:
        rows[0].extend([task_contract.x_metric, task_contract.y_metric])
        rows[1].extend([task_contract.x_unit, task_contract.y_unit])
        rows[2].extend([item.sample, item.sample])
    for index in range(max(len(item.points) for item in series)):
        row: list[Any] = []
        for item in series:
            row.extend(item.points[index] if index < len(item.points) else ("", ""))
        rows.append(row)
    pd.DataFrame(rows).to_csv(path, header=False, index=False)


def _fail(reason_code: str, detail: str) -> None:
    raise ValueError(f"{reason_code}: {detail}.")


__all__ = [
    "MechanicalSummaryGroup",
    "MechanicalTaskSource",
    "build_mechanical_task_sources",
    "require_mechanical_execution_plan",
]
