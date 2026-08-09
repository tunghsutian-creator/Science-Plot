from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

import sciplot_core.mechanical_task_sources as task_sources
from sciplot_core.figure_plan import (
    CartesianMetricBinding,
    FigureTask,
    ResolvedFigurePlan,
)
from sciplot_core.foundation.source_tree import source_tree_sha256
from sciplot_core.mechanical_figure_contract import (
    mechanical_figure_contract,
    mechanical_selection_policy,
)
from sciplot_core.mechanical_task_sources import (
    MechanicalSummaryGroup,
    MechanicalTaskSource,
    build_mechanical_task_sources,
)
from sciplot_core.preparation_source_attestation import PreparationSourceAttestation
from sciplot_core.semantic_sources.mechanical_fact_models import (
    MechanicalSourceFacts,
    MechanicalSummaryObservation,
)
from sciplot_core.semantic_sources.models import CurveSeriesPayload
from sciplot_core.terminal_source_binding import MaterializedTerminalSourceBinding
from sciplot_core.workflow.mechanical_bundle import _render_veusz_mechanical_bundle


def _series(sample: str, offset: float) -> CurveSeriesPayload:
    return CurveSeriesPayload(
        sample=sample,
        x_label="Tensile strain",
        x_unit="%",
        y_label="Tensile stress",
        y_unit="MPa",
        points=((0.0, 0.0), (1.0, 10.0 + offset), (2.0, 8.0 + offset)),
    )


def _facts(tmp_path: Path) -> tuple[MechanicalSourceFacts, Path]:
    raw = tmp_path / "raw.csv"
    raw.write_text("synthetic source authority\n", encoding="utf-8")
    raw_series = (_series("Sample__rep1", 0.0), _series("Sample__rep2", 2.0))
    representative = replace(raw_series[0], sample="Sample")
    rows = (
        MechanicalSummaryObservation(
            "Sample",
            "rep1",
            (
                ("strength_MPa", 10.0),
                ("elongation_at_break_percent", 2.0),
                ("modulus_MPa", 500.0),
                ("toughness_MJ_m3", 0.10),
            ),
            str(raw),
        ),
        MechanicalSummaryObservation(
            "Sample",
            "rep2",
            (
                ("strength_MPa", 12.0),
                ("elongation_at_break_percent", 2.1),
                ("modulus_MPa", 520.0),
                ("toughness_MJ_m3", 0.12),
            ),
            str(raw),
        ),
    )
    digest = source_tree_sha256(raw)
    assert digest is not None
    return (
        MechanicalSourceFacts(
            rule_id="tensile_curve",
            source_root=raw,
            source_sha256=digest,
            selected_sources=(raw,),
            raw_series=raw_series,
            individual_curve_series=raw_series,
            representative_curve_series=(representative,),
            summary_rows=rows,
            sample_order=("Sample",),
            replicate_counts=(("Sample", 2),),
            x_label="Tensile strain",
            x_unit="%",
            y_label="Tensile stress",
            y_unit="MPa",
            metric_units=(
                ("strength_MPa", "MPa"),
                ("elongation_at_break_percent", "%"),
                ("modulus_MPa", "MPa"),
                ("toughness_MJ_m3", "MJ/m3"),
            ),
            curve_source_kind="raw_specimen_curves",
            individual_curves_complete=True,
        ),
        raw,
    )


def _plan(facts: MechanicalSourceFacts, mode: str) -> ResolvedFigurePlan:
    contract = mechanical_figure_contract(facts.rule_id)
    curve_order = facts.curve_sample_order(mode)
    curve_counts = (
        facts.replicate_counts
        if mode == "representative"
        else tuple((sample, 1) for sample in curve_order)
    )
    tasks = tuple(
        FigureTask.with_metric_binding(
            figure_id=item.figure_id,
            order=index,
            title=item.title,
            metric_binding=CartesianMetricBinding(item.x_metric, item.y_metric),
            template=item.template,
            artifact_stem=item.artifact_stem,
            document_stem=item.document_stem,
            sample_order=curve_order if index == 1 else facts.sample_order,
            replicate_counts=curve_counts if index == 1 else facts.replicate_counts,
        )
        for index, item in enumerate(contract.tasks, start=1)
    )
    return ResolvedFigurePlan.planned(
        rule_id=facts.rule_id,
        selection_policy=mechanical_selection_policy(mode),
        primary_figure_id=tasks[0].figure_id,
        tasks=tasks,
        source_sha256=facts.source_sha256,
    )


def _write_prepared(path: Path, series: tuple[CurveSeriesPayload, ...]) -> None:
    rows: list[list[object]] = [[], [], []]
    for item in series:
        rows[0].extend([item.x_label, item.y_label])
        rows[1].extend([item.x_unit, item.y_unit])
        rows[2].extend([item.sample, item.sample])
    for point_index in range(max(len(item.points) for item in series)):
        row: list[object] = []
        for item in series:
            row.extend(item.points[point_index])
        rows.append(row)
    pd.DataFrame(rows).to_csv(path, header=False, index=False)


@pytest.mark.parametrize("mode", ["representative", "individual"])
def test_task_source_builder_consumes_pair_shaped_counts_and_units(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    facts, raw = _facts(tmp_path)
    plan = _plan(facts, mode)
    prepared = tmp_path / "prepared.csv"
    _write_prepared(prepared, facts.curve_series_for_mode(mode))
    attestation = PreparationSourceAttestation.capture(
        rule_id=facts.rule_id,
        source_root=raw,
        source_tree_sha256_before=facts.source_sha256,
        selected_sources=facts.selected_sources,
        prepared_source=prepared,
    )
    monkeypatch.setattr(
        task_sources,
        "load_mechanical_source_facts",
        lambda *_args, **_kwargs: facts,
    )
    records = build_mechanical_task_sources(
        prepared,
        raw_source=raw,
        source_attestation=attestation,
        figure_plan=plan,
        output_dir=tmp_path / "terminal_sources",
        request={},
        options={},
    )
    assert len(records) == 5
    assert tuple(record.task for record in records) == plan.tasks
    assert records[0].binding.sample_order == facts.curve_sample_order(mode)
    assert all(record.task.template == "box_strip" for record in records[1:])
    assert all(
        record.render_options["summary_statistic"] == "median_iqr"
        for record in records[1:]
    )
    assert records[-1].metric == "toughness_MJ_m3"
    assert records[-1].groups[0].values == (0.10, 0.12)


def _fake_source_builder(
    prepared: Path,
    *,
    raw_source: Path,
    source_attestation: PreparationSourceAttestation,
    figure_plan: ResolvedFigurePlan,
    output_dir: Path,
    request: dict[str, Any],
    options: dict[str, Any],
) -> list[MechanicalTaskSource]:
    del raw_source, request, options
    output_dir.mkdir(parents=True)
    raw_sources = tuple(Path(item.path) for item in source_attestation.selected_sources)
    records: list[MechanicalTaskSource] = []
    contract = mechanical_figure_contract(figure_plan.rule_id)
    for task, task_contract in zip(figure_plan.tasks, contract.tasks, strict=True):
        source = output_dir / f"{task.artifact_stem}.csv"
        source.write_text("x,y\n%,MPa\nSample,Sample\n0,0\n1,1\n", encoding="utf-8")
        binding = MaterializedTerminalSourceBinding.create(
            task_key=task.figure_id,
            rule_id=figure_plan.rule_id,
            template=task.template,
            x_metric=task_contract.x_metric,
            y_metric=task_contract.y_metric,
            raw_sources=raw_sources,
            prepared_source=prepared,
            terminal_source=source,
            sample_order=task.sample_order,
            point_counts={sample: 2 for sample in task.sample_order},
        )
        records.append(
            MechanicalTaskSource(
                task=task,
                source=source,
                render_options={
                    "x_metric": task_contract.x_metric,
                    "y_metric": task_contract.y_metric,
                },
                binding=binding,
                task_kind="summary" if task_contract.is_summary else "curve",
                metric=task_contract.y_metric,
                unit=task_contract.y_unit,
                groups=(MechanicalSummaryGroup("Sample", ("r1", "r2"), (1.0, 2.0)),)
                if task_contract.is_summary
                else (),
            )
        )
    return records


def _fake_renderer(
    _source: Path,
    *,
    output_dir: Path,
    export_formats: tuple[str, ...],
    _terminal_source_binding: MaterializedTerminalSourceBinding,
    **_kwargs: object,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True)
    exports: list[dict[str, Any]] = []
    outputs: list[str] = []
    for fmt in export_formats:
        path = output_dir / ("figure.pdf" if fmt == "pdf" else "figure_300dpi.tiff")
        path.write_bytes(fmt.encode())
        exports.append({"format": fmt, "path": str(path)})
        outputs.append(str(path))
    studio = output_dir / "_veusz" / "single" / "studio"
    studio.mkdir(parents=True)
    document = studio / "document.vsz"
    spec = studio / "spec.json"
    document.write_text("# fake editable document\n", encoding="utf-8")
    spec.write_text(
        json.dumps({"task": _terminal_source_binding.task_key}), encoding="utf-8"
    )
    return {
        "export_formats": list(export_formats),
        "exports": exports,
        "outputs": outputs,
        "qa_reports": [{"layout_summary": {}}],
        "veusz_documents": [str(document)],
        "veusz_specs": [str(spec)],
        "terminal_render_requests": [],
        "transform_steps": [],
    }


def _bundle_inputs(
    tmp_path: Path,
) -> tuple[Path, Path, PreparationSourceAttestation, ResolvedFigurePlan]:
    facts, raw = _facts(tmp_path)
    prepared = tmp_path / "prepared.csv"
    _write_prepared(prepared, facts.representative_curve_series)
    attestation = PreparationSourceAttestation.capture(
        rule_id=facts.rule_id,
        source_root=raw,
        source_tree_sha256_before=facts.source_sha256,
        selected_sources=facts.selected_sources,
        prepared_source=prepared,
    )
    return prepared, raw, attestation, _plan(facts, "representative")


def test_bundle_installs_all_five_tensile_tasks_and_completed_plan(
    tmp_path: Path,
) -> None:
    prepared, raw, attestation, plan = _bundle_inputs(tmp_path)
    result = _render_veusz_mechanical_bundle(
        prepared,
        source_input=raw,
        source_attestation=attestation,
        output_dir=tmp_path / "out",
        options={},
        export_formats=("pdf", "tiff_300"),
        request={"rule_id": plan.rule_id, "resolved_figure_plan": plan.to_payload()},
        _source_builder=_fake_source_builder,
        _renderer=_fake_renderer,
        _payload_validator=lambda *_args, **_kwargs: None,
        _evidence_builder=lambda **_kwargs: {"kind": "test_evidence"},
    )
    assert result is not None
    assert result["multi_metric_bundle"]["figure_ids"] == list(plan.selected_figure_ids)
    assert result["resolved_figure_plan"]["complete"] is True
    assert len(result["veusz_documents"]) == 5
    assert len(result["outputs"]) == 10
    assert all(Path(path).is_file() for path in result["outputs"])


def test_bundle_failure_rolls_back_figures_and_terminal_sources(tmp_path: Path) -> None:
    prepared, raw, attestation, plan = _bundle_inputs(tmp_path)
    output = tmp_path / "out"
    figures = output / "figures"
    figures.mkdir(parents=True)
    sentinel = figures / "sentinel.txt"
    sentinel.write_text("prior complete figures", encoding="utf-8")
    source_root = (
        output / "processed" / "veusz_metric_sources" / f"mechanical_{plan.plan_id}"
    )
    source_root.mkdir(parents=True)
    source_sentinel = source_root / "sentinel.txt"
    source_sentinel.write_text("prior complete sources", encoding="utf-8")
    calls = 0

    def failing_renderer(*args: object, **kwargs: object) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("second task failed")
        return _fake_renderer(*args, **kwargs)

    with pytest.raises(RuntimeError, match="second task failed"):
        _render_veusz_mechanical_bundle(
            prepared,
            source_input=raw,
            source_attestation=attestation,
            output_dir=output,
            options={},
            export_formats=("pdf", "tiff_300"),
            request={
                "rule_id": plan.rule_id,
                "resolved_figure_plan": plan.to_payload(),
            },
            _source_builder=_fake_source_builder,
            _renderer=failing_renderer,
            _payload_validator=lambda *_args, **_kwargs: None,
            _evidence_builder=lambda **_kwargs: {"kind": "test_evidence"},
        )
    assert sentinel.read_text(encoding="utf-8") == "prior complete figures"
    assert source_sentinel.read_text(encoding="utf-8") == "prior complete sources"
    assert not list(output.glob(".sciplot-mechanical-stage-*"))
