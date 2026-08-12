"""Build QA, publication, package, and lifecycle evidence for a workflow run."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sciplot_core.delivery import build_delivery_package
from sciplot_core.figure_plan import ResolvedFigurePlan, resolved_figure_plan_from_payload
from sciplot_core.foundation.iso_timestamps import utc_now_iso
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.one_step import build_one_step_project
from sciplot_core.operation_modes import normal_mode_payload
from sciplot_core.policy import layout_policy_payload
from sciplot_core.publication import (
    build_transform_ledger,
    link_intent_to_transform_ledger,
    write_publication_artifacts,
)
from sciplot_core.publish_state import build_publish_state
from sciplot_core.qa import run_qa
from sciplot_core.study_model import (
    attach_run_artifacts_to_study_model,
    build_output_package_contract,
)

from sciplot_core.workflow.project_state import (
    _update_intake_project_after_run,
    _write_one_step_status,
    _write_revision_brief,
)
from sciplot_core.workflow.reports import (
    _layout_quality_from_result,
    _write_review_html,
)
from sciplot_core.workflow.request_io import (
    _bind_result_data_snapshots,
    _extend_runtime_transform_steps,
    _figures_from_result,
)
from sciplot_core.workflow.request_rendering import RequestRenderResult


def publish_request_result(
    *,
    request_path: Path,
    source_request: dict[str, Any],
    request: dict[str, Any],
    mapping_application: dict[str, Any] | None,
    cleanup_application: dict[str, Any] | None,
    semantic: dict[str, Any],
    input_path: Path,
    raw_archive: dict[str, Any],
    study_model: dict[str, Any],
    publication_intent: dict[str, Any],
    publication_profile: dict[str, Any],
    transform_steps: list[dict[str, Any]],
    layout_policy: Any,
    output_dir: Path,
    rendered: RequestRenderResult,
) -> dict[str, Any]:
    """Attach lineage and quality evidence, then persist a complete manifest."""

    result = _bind_result_data_snapshots(
        rendered.result,
        plotted_source=rendered.plotted_data_source,
        mapping_application=mapping_application,
        request=request,
    )
    resolved_figure_plan = resolved_figure_plan_from_payload(
        request.get("resolved_figure_plan")
    )
    if resolved_figure_plan != rendered.selected_figure_plan:
        raise ValueError(
            "workflow_result_figure_plan_mismatch: the rendered result belongs "
            "to a different selected FigurePlan."
        )
    completed_figure_plan = rendered.completed_figure_plan
    _extend_runtime_transform_steps(transform_steps, result.get("transform_steps"))
    transform_ledger = build_transform_ledger(
        study_model,
        request=request,
        input_path=input_path,
        steps=transform_steps,
        existing=(
            request.get("transform_ledger")
            if isinstance(request.get("transform_ledger"), dict)
            else None
        ),
    )
    publication_intent = link_intent_to_transform_ledger(
        publication_intent,
        transform_ledger,
    )
    study_model["publication_intent_ref"] = "publication_intent.json"
    publication_artifacts = write_publication_artifacts(
        output_dir,
        publication_intent=publication_intent,
        transform_ledger=transform_ledger,
        publication_profile=publication_profile,
    )
    qa = run_qa(
        output_dir,
        publication_profile=publication_profile,
        strict_publication=bool(request.get("publication_strict")),
        veusz_documents=[
            Path(value)
            for value in result.get("veusz_documents", [])
            if isinstance(value, str)
        ],
    )
    publication_qa = (
        qa.get("publication") if isinstance(qa.get("publication"), dict) else {}
    )
    publication_artifacts = write_publication_artifacts(
        output_dir,
        publication_intent=publication_intent,
        transform_ledger=transform_ledger,
        publication_profile=publication_profile,
        publication_qa=publication_qa,
    )
    figures = _figures_from_result(result)
    analysis_metrics = (
        result.get("analysis_metrics")
        if isinstance(result.get("analysis_metrics"), list)
        else []
    )
    study_model = attach_run_artifacts_to_study_model(
        study_model,
        output_dir=output_dir,
        figures=figures,
        analysis_metrics=analysis_metrics,
        qa=qa,
        resolved_figure_plan=(
            completed_figure_plan.to_payload()
            if completed_figure_plan is not None
            else None
        ),
    )
    manifest = _build_request_manifest(
        request_path=request_path,
        source_request=source_request,
        request=request,
        mapping_application=mapping_application,
        cleanup_application=cleanup_application,
        semantic=semantic,
        input_path=input_path,
        raw_archive=raw_archive,
        output_dir=output_dir,
        rendered=rendered,
        result=result,
        study_model=study_model,
        publication_intent=publication_intent,
        transform_ledger=transform_ledger,
        publication_profile=publication_profile,
        publication_qa=publication_qa,
        publication_artifacts=publication_artifacts,
        qa=qa,
        figures=figures,
        layout_policy=layout_policy,
    )
    _finalize_request_manifest(
        manifest,
        request_path=request_path,
        request=request,
        input_path=input_path,
        raw_archive=raw_archive,
        study_model=study_model,
        semantic=semantic,
        layout_policy=layout_policy,
        output_dir=output_dir,
        qa=qa,
        completed_figure_plan=completed_figure_plan,
    )
    return manifest


def _build_request_manifest(
    *,
    request_path: Path,
    source_request: dict[str, Any],
    request: dict[str, Any],
    mapping_application: dict[str, Any] | None,
    cleanup_application: dict[str, Any] | None,
    semantic: dict[str, Any],
    input_path: Path,
    raw_archive: dict[str, Any],
    output_dir: Path,
    rendered: RequestRenderResult,
    result: dict[str, Any],
    study_model: dict[str, Any],
    publication_intent: dict[str, Any],
    transform_ledger: dict[str, Any],
    publication_profile: dict[str, Any],
    publication_qa: dict[str, Any],
    publication_artifacts: dict[str, Any],
    qa: dict[str, Any],
    figures: list[str],
    layout_policy: Any,
) -> dict[str, Any]:
    manifest = {
        "kind": "sciplot_run",
        "created_at": utc_now_iso(),
        "request_path": str(request_path),
        "request": json_safe(request),
        "source_request": json_safe(source_request),
        "data_mapping_application": (
            json_safe(mapping_application) if mapping_application is not None else None
        ),
        "cleanup_application": (
            json_safe(cleanup_application) if cleanup_application is not None else None
        ),
        "route": rendered.route,
        "semantic": json_safe(semantic),
        "final_recipe": rendered.final_recipe,
        "input": str(input_path),
        "raw_archive": json_safe(raw_archive),
        "output": str(output_dir),
        "figures": figures,
        "result": json_safe(result),
        "study_model": json_safe(study_model),
        "publication_intent": json_safe(publication_intent),
        "transform_ledger": json_safe(transform_ledger),
        "journal_profile": json_safe(publication_profile),
        "publication_qa": json_safe(publication_qa),
        "publication_artifacts": json_safe(publication_artifacts),
        "qa": qa,
        "render_engine": result.get("render_engine") or "veusz",
        "qa_target": result.get("qa_target") or "veusz_export",
        "veusz_documents": result.get("veusz_documents", []),
        "veusz_specs": result.get("veusz_specs", []),
        "layout_policy": layout_policy_payload(layout_policy),
        "operation_mode": normal_mode_payload(route=rendered.route),
    }
    if isinstance(result.get("resolved_figure_plan"), dict):
        manifest["resolved_figure_plan"] = json_safe(result["resolved_figure_plan"])
    return manifest


def _finalize_request_manifest(
    manifest: dict[str, Any],
    *,
    request_path: Path,
    request: dict[str, Any],
    input_path: Path,
    raw_archive: dict[str, Any],
    study_model: dict[str, Any],
    semantic: dict[str, Any],
    layout_policy: Any,
    output_dir: Path,
    qa: dict[str, Any],
    completed_figure_plan: ResolvedFigurePlan | None,
) -> None:
    manifest["layout_quality"] = _layout_quality_from_result(manifest["result"])
    manifest["revision_brief"] = _write_revision_brief(output_dir, manifest=manifest)
    _write_review_html(output_dir, manifest=manifest)
    _write_manifest(output_dir, manifest)
    manifest["package_contract"] = build_output_package_contract(
        output_dir,
        manifest=manifest,
    )
    manifest["delivery_package"] = build_delivery_package(
        output_dir,
        manifest=manifest,
    )
    manifest["one_step"] = build_one_step_project(
        input_path=input_path,
        request_path=request_path,
        request=request,
        semantic=semantic,
        raw_archive=raw_archive,
        study_model=study_model,
        layout_policy=layout_policy,
        layout_quality=manifest["layout_quality"],
        qa=qa,
        delivery_package=manifest["delivery_package"],
        resolved_figure_plan=completed_figure_plan,
    )
    manifest.update(
        build_publish_state(
            qa=qa,
            package_contract=manifest["package_contract"],
            delivery_package=manifest["delivery_package"],
            prerequisite_state=manifest["one_step"]["state"],
            resolved_figure_plan=manifest.get("resolved_figure_plan"),
        )
    )
    _write_one_step_status(output_dir, manifest["one_step"])
    _write_manifest(output_dir, manifest)
    _update_intake_project_after_run(request_path, manifest)


def _write_manifest(output_dir: Path, manifest: dict[str, Any]) -> None:
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
