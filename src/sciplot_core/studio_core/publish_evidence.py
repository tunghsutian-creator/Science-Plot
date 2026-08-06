"""Build publication lineage, QA evidence, and run-linked study metadata."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sciplot_core.publication import (
    build_publication_intent,
    build_transform_ledger,
    build_transform_step,
    get_publication_profile,
    link_intent_to_transform_ledger,
    write_publication_artifacts,
)
from sciplot_core.study_model import (
    attach_run_artifacts_to_study_model,
    normalize_study_model,
)

from sciplot_core.studio_core.axis_identity import (
    _semantic_payload_with_exact_current_axes,
)
from sciplot_core.studio_core.export_verification import (
    _verify_qa_artifact_hashes,
)
from sciplot_core.studio_core.publish_sources import StudioRunSources
from sciplot_core.studio_core.review_artifacts import (
    _run_studio_qa,
    _studio_layout_quality_from_spec,
    _studio_visual_presentation_transforms,
    _write_studio_analysis_report,
)


@dataclass(frozen=True)
class StudioPublicationEvidence:
    """Publication contracts and exact-current QA attached to a Studio run."""

    study_model: dict[str, Any]
    publication_intent: dict[str, Any]
    publication_profile: dict[str, Any]
    transform_ledger: dict[str, Any]
    publication_artifacts: dict[str, Any]
    qa: dict[str, Any]
    semantic: dict[str, Any]
    publication_qa: dict[str, Any]
    layout_quality: dict[str, Any]


def build_studio_publication_evidence(
    *,
    request: dict[str, Any],
    document_path: Path,
    output_dir: Path,
    figures: list[str],
    copied_exports: list[dict[str, Any]],
    veusz_documents: list[Path],
    figure_set_export_scope: dict[str, Any] | None,
    sources: StudioRunSources,
    resolved_figure_plan: dict[str, Any] | None = None,
) -> StudioPublicationEvidence:
    """Create lineage, reports, QA, and study-model run artifacts."""

    study_model = normalize_study_model(
        request.get("study_model")
        if isinstance(request.get("study_model"), dict)
        else {
            "kind": "sciplot_study_model",
            "version": 1,
            "samples": [],
            "figure_queue": [],
        }
    )
    publication_intent = build_publication_intent(
        study_model,
        request=request,
        existing=request.get("publication_intent")
        if isinstance(request.get("publication_intent"), dict)
        else None,
    )
    publication_profile = get_publication_profile(
        publication_intent["target_profile_id"]
    )
    transform_ledger = build_transform_ledger(
        study_model,
        request=request,
        input_path=sources.input_path or document_path,
        existing=sources.existing_transform_ledger,
    )
    _attach_visual_presentation_step(
        transform_ledger,
        document_path=document_path,
        sources=sources,
    )
    _preserve_incomplete_legacy_lineage(
        transform_ledger,
        existing_transform_ledger=sources.existing_transform_ledger,
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
    _write_studio_analysis_report(
        output_dir,
        request=request,
        document_path=document_path,
        figures=figures,
        analysis_metrics=sources.analysis_metrics,
        figure_set_export_scope=figure_set_export_scope,
    )
    qa = _run_studio_qa(
        output_dir,
        publication_profile=publication_profile,
        strict_publication=bool(request.get("publication_strict")),
        veusz_documents=veusz_documents,
    )
    if qa.get("status") == "passed":
        _verify_qa_artifact_hashes(
            qa,
            exports=copied_exports,
            covered_formats={"pdf", "tiff_300"},
        )
    semantic = _semantic_payload_with_exact_current_axes(
        sources.semantic,
        qa=qa,
        document_path=document_path,
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
    study_model = attach_run_artifacts_to_study_model(
        study_model,
        output_dir=output_dir,
        figures=figures,
        analysis_metrics=sources.analysis_metrics,
        qa=qa,
        resolved_figure_plan=resolved_figure_plan,
    )
    return StudioPublicationEvidence(
        study_model=study_model,
        publication_intent=publication_intent,
        publication_profile=publication_profile,
        transform_ledger=transform_ledger,
        publication_artifacts=publication_artifacts,
        qa=qa,
        semantic=semantic,
        publication_qa=publication_qa,
        layout_quality=_studio_layout_quality_from_spec(document_path),
    )


def _attach_visual_presentation_step(
    transform_ledger: dict[str, Any],
    *,
    document_path: Path,
    sources: StudioRunSources,
) -> None:
    transforms = _studio_visual_presentation_transforms(document_path)
    if not transforms:
        return
    presentation_input = (
        sources.metric_source
        or sources.snapshot_source
        or sources.input_path
        or document_path
    )
    presentation_step = build_transform_step(
        step_id="veusz_visual_presentation",
        operation="apply_recorded_visual_presentation_transforms",
        input_path=presentation_input,
        output_path=document_path,
        implementation_ref="sciplot_core.studio._apply_template_series_transforms",
        parameters={
            "transforms": transforms,
            "source_values_preserved_outside_visual_presentation": True,
        },
    )
    transform_ledger["steps"] = [
        step
        for step in transform_ledger.get("steps", [])
        if isinstance(step, dict) and step.get("id") != presentation_step["id"]
    ] + [presentation_step]


def _preserve_incomplete_legacy_lineage(
    transform_ledger: dict[str, Any],
    *,
    existing_transform_ledger: dict[str, Any] | None,
) -> None:
    if not (
        isinstance(existing_transform_ledger, dict)
        and existing_transform_ledger.get("status") == "pending_runtime"
        and not existing_transform_ledger.get("steps")
    ):
        return
    transform_ledger["status"] = "incomplete_lineage"
    transform_ledger["steps"] = []
    transform_ledger["limitations"] = [
        "The saved Veusz document predates persisted runtime transform steps; "
        "preprocessing lineage requires review."
    ]
