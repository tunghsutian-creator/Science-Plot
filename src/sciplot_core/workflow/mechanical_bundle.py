"""Render one exact source-bound mechanical FigurePlan transactionally."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

from sciplot_core.figure_plan import (
    ResolvedFigurePlan,
    finalize_figure_plan_result,
    outcomes_for_artifact_map,
    request_for_figure_task,
    resolved_figure_plan_from_payload,
)
from sciplot_core.mechanical_figure_contract import (
    MECHANICAL_FIGURE_CONTRACTS,
    MECHANICAL_RULE_IDS,
)
from sciplot_core.mechanical_task_sources import (
    MechanicalTaskSource,
    build_mechanical_task_sources,
)
from sciplot_core.policy import DEFAULT_EXPORT_FORMATS_POLICY, normalize_export_formats
from sciplot_core.preparation_source_attestation import PreparationSourceAttestation
from sciplot_core.render import render_to_dir
from sciplot_core.workflow.bundle_exports import _rename_metric_exports
from sciplot_core.workflow.mechanical_execution_evidence import (
    build_mechanical_execution_evidence,
)
from sciplot_core.workflow.mechanical_summary_sources import (
    _mechanical_summary_sources,
)
from sciplot_core.workflow.mechanical_terminal_validation import (
    validate_mechanical_render_payload,
)
from sciplot_core.workflow.task_artifacts import (
    install_task_worker_tree,
    task_qa_reports,
)


_MECHANICAL_FIGURE_CONTRACTS = MECHANICAL_FIGURE_CONTRACTS


def _render_veusz_mechanical_bundle(
    input_path: Path,
    *,
    source_input: Path | None = None,
    source_attestation: PreparationSourceAttestation | None = None,
    output_dir: Path,
    options: dict[str, Any],
    export_formats: object,
    request: dict[str, Any],
    _source_builder: Callable[..., list[MechanicalTaskSource]] = (
        build_mechanical_task_sources
    ),
    _renderer: Callable[..., dict[str, Any]] = render_to_dir,
    _payload_validator: Callable[..., None] = validate_mechanical_render_payload,
    _evidence_builder: Callable[..., dict[str, Any]] = (
        build_mechanical_execution_evidence
    ),
    _resolved_figure_plan: ResolvedFigurePlan | None = None,
) -> dict[str, Any] | None:
    """Render every selected curve/summary task, then install the whole set."""

    rule_id = str(request.get("rule_id") or "").strip()
    if rule_id not in MECHANICAL_RULE_IDS:
        return None
    plan = _resolved_figure_plan
    if plan is None and request.get("resolved_figure_plan") is not None:
        plan = resolved_figure_plan_from_payload(request["resolved_figure_plan"])
    if plan is None:
        raise ValueError(
            "mechanical_figure_plan_required: mechanical Workflow execution "
            "requires one exact resolved FigurePlan."
        )
    if plan.rule_id != rule_id:
        raise ValueError(
            "mechanical_figure_plan_mismatch: selected FigurePlan belongs to "
            "another rule."
        )
    if source_input is None or source_attestation is None:
        raise ValueError(
            "mechanical_preparation_attestation_missing: mechanical Workflow "
            "requires its raw source and typed prepare-time attestation."
        )
    requested_formats = normalize_export_formats(export_formats)
    if not {"pdf", "tiff_300"}.issubset(requested_formats):
        raise ValueError(
            "mechanical_export_contract_mismatch: every selected task requires "
            "PDF and 300-dpi TIFF exports."
        )

    output = output_dir.expanduser().resolve()
    transaction = output / f".sciplot-mechanical-stage-{uuid4().hex}"
    staged_figures = transaction / "figures"
    render_root = transaction / "render"
    source_root = (
        output / "processed" / "veusz_metric_sources" / f"mechanical_{plan.plan_id}"
    )
    source_backup = transaction / "previous_metric_sources"
    transaction.mkdir(parents=True, exist_ok=False)
    staged_figures.mkdir()
    render_root.mkdir()
    source_root.parent.mkdir(parents=True, exist_ok=True)
    source_replaced = False
    installed = False
    if source_root.exists() or source_root.is_symlink():
        source_root.replace(source_backup)
        source_replaced = True

    try:
        records = _source_builder(
            input_path,
            raw_source=source_input,
            source_attestation=source_attestation,
            figure_plan=plan,
            output_dir=source_root,
            request=request,
            options=options,
        )
        if tuple(record.task for record in records) != plan.tasks:
            raise ValueError(
                "mechanical_task_source_unavailable: task-source materialization "
                "did not preserve the exact selected sequence."
            )
        combined: dict[str, list[Any]] = {
            "outputs": [],
            "exports": [],
            "qa_reports": [],
            "veusz_documents": [],
            "veusz_specs": [],
            "terminal_render_requests": [],
            "transform_steps": [],
        }
        staged_artifacts = {task.figure_id: [] for task in plan.tasks}
        final_artifacts = {task.figure_id: [] for task in plan.tasks}
        staged_specs: dict[str, Path] = {}
        figures_dir = output / "figures"
        for record in records:
            payload = _render_task(
                record,
                request=request,
                render_root=render_root,
                export_formats=requested_formats,
                renderer=_renderer,
            )
            metric_dir = render_root / record.task.artifact_stem
            _payload_validator(
                payload,
                record=record,
                metric_dir=metric_dir,
                export_formats=requested_formats,
            )
            staged_outputs, staged_exports = _rename_metric_exports(
                payload,
                metric_id=record.task.artifact_stem,
                figures_dir=staged_figures,
            )
            staged_documents, staged_spec_paths = install_task_worker_tree(
                payload,
                task=record.task,
                figures_dir=staged_figures,
            )
            if len(staged_documents) != 1 or len(staged_spec_paths) != 1:
                raise ValueError(
                    "mechanical_terminal_evidence_mismatch: every task requires "
                    "one editable VSZ and one terminal specification."
                )
            staged_specs[record.task.figure_id] = Path(staged_spec_paths[0])
            outputs = _rebase_paths(
                staged_outputs,
                source_root=staged_figures,
                target_root=figures_dir,
            )
            documents = _rebase_paths(
                staged_documents,
                source_root=staged_figures,
                target_root=figures_dir,
            )
            specs = _rebase_paths(
                staged_spec_paths,
                source_root=staged_figures,
                target_root=figures_dir,
            )
            exports = [
                {
                    **item,
                    "source": output_path,
                    "path": output_path,
                    "figure_id": record.task.figure_id,
                }
                for item, output_path in zip(staged_exports, outputs, strict=True)
            ]
            combined["outputs"].extend(outputs)
            combined["exports"].extend(exports)
            combined["veusz_documents"].extend(documents)
            combined["veusz_specs"].extend(specs)
            combined["qa_reports"].extend(
                task_qa_reports(
                    payload,
                    outputs=outputs,
                    documents=documents,
                )
            )
            combined["terminal_render_requests"].extend(
                item
                for item in payload.get("terminal_render_requests", [])
                if isinstance(item, dict)
            )
            combined["transform_steps"].extend(
                item
                for item in payload.get("transform_steps", [])
                if isinstance(item, dict)
            )
            staged_artifacts[record.task.figure_id].extend(
                [*staged_outputs, *staged_documents, *staged_spec_paths]
            )
            final_artifacts[record.task.figure_id].extend(
                [*outputs, *documents, *specs]
            )

        evidence = _evidence_builder(
            plan=plan,
            records=records,
            specs_by_figure_id=staged_specs,
        )
        result = _result_payload(
            input_path=input_path,
            plan=plan,
            records=records,
            export_formats=requested_formats,
            combined=combined,
            evidence=evidence,
            staged_artifacts=staged_artifacts,
            final_artifacts=final_artifacts,
        )
        completed = finalize_figure_plan_result(plan, result)
        if completed is None or not completed.complete:
            raise ValueError(
                "mechanical_task_artifacts_incomplete: every selected mechanical "
                "task requires one VSZ, PDF, and 300-dpi TIFF."
            )
        _install_staged_figures(
            staged_figures,
            figures_dir=figures_dir,
            transaction_dir=transaction,
        )
        installed = True
        return result
    finally:
        if not installed:
            if source_root.exists() or source_root.is_symlink():
                shutil.rmtree(source_root, ignore_errors=True)
            if source_replaced and source_backup.exists():
                source_backup.replace(source_root)
        shutil.rmtree(transaction, ignore_errors=True)


def _render_task(
    record: MechanicalTaskSource,
    *,
    request: dict[str, Any],
    render_root: Path,
    export_formats: tuple[str, ...],
    renderer: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    task_request = request_for_figure_task(request, record.task)
    return renderer(
        record.source,
        template=record.task.template,
        output_dir=render_root / record.task.artifact_stem,
        options=record.render_options,
        export_formats=export_formats,
        request_context={
            **task_request,
            "explicit_render_option_keys": list(record.explicit_render_option_keys),
        },
        _terminal_source_binding=record.binding,
    )


def _result_payload(
    *,
    input_path: Path,
    plan: Any,
    records: list[MechanicalTaskSource],
    export_formats: tuple[str, ...],
    combined: dict[str, list[Any]],
    evidence: dict[str, Any],
    staged_artifacts: dict[str, list[str]],
    final_artifacts: dict[str, list[str]],
) -> dict[str, Any]:
    staged_outcomes = outcomes_for_artifact_map(
        plan,
        staged_artifacts,
        missing_reason_code="mechanical_task_artifacts_incomplete",
    )
    return {
        "kind": "sciplot_render_result",
        "template": "mechanical_figure_set",
        "input": str(input_path),
        "sheet": None,
        "render_engine": "veusz",
        "qa_target": "veusz_export",
        "export_formats": list(export_formats or DEFAULT_EXPORT_FORMATS_POLICY),
        **combined,
        "multi_metric_bundle": {
            "kind": "mechanical_curve_and_descriptive_summary_figure_set",
            "metric_ids": [record.metric for record in records],
            "templates": [record.task.template for record in records],
            "figure_ids": list(plan.selected_figure_ids),
            "document_policy": "independent_single_page_vsz",
        },
        "figure_outcomes": [
            {
                **outcome.to_payload(),
                "artifacts": list(final_artifacts[outcome.figure_id]),
            }
            for outcome in staged_outcomes
        ],
        "mechanical_execution_evidence": evidence,
    }


def _rebase_paths(
    values: list[str],
    *,
    source_root: Path,
    target_root: Path,
) -> list[str]:
    rebased: list[str] = []
    for value in values:
        path = Path(value).expanduser().resolve()
        try:
            relative = path.relative_to(source_root.resolve())
        except ValueError as exc:
            raise ValueError(
                "mechanical_transaction_scope_mismatch: staged artifact escaped "
                "the mechanical transaction."
            ) from exc
        rebased.append(str(target_root / relative))
    return rebased


def _install_staged_figures(
    staged_figures: Path,
    *,
    figures_dir: Path,
    transaction_dir: Path,
) -> None:
    previous = transaction_dir / "previous_figures"
    try:
        if figures_dir.exists() or figures_dir.is_symlink():
            figures_dir.replace(previous)
        staged_figures.replace(figures_dir)
    except BaseException:
        if previous.exists() and not figures_dir.exists():
            previous.replace(figures_dir)
        raise


__all__ = [
    "_MECHANICAL_FIGURE_CONTRACTS",
    "_mechanical_summary_sources",
    "_render_veusz_mechanical_bundle",
]
