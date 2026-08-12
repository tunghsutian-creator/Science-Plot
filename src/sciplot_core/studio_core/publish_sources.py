"""Archive source evidence and compute rule-backed metrics for a Studio run."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sciplot_core.figure_plan import (
    ResolvedFigurePlan,
    source_trees_match_sha256,
)
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.materials_rules import compute_analysis_metrics
from sciplot_core.presentation_identity import SelectedPresentationIdentity

from sciplot_core.studio_core.json_files import _read_json
from sciplot_core.studio_core.rule_readiness import (
    StudioRulePublicationReadiness,
)
from sciplot_core.studio_core.request_overrides import (
    _write_studio_data_snapshots,
)
from sciplot_core.studio_core.request_paths import (
    _archive_studio_input,
    _resolve_request_input,
)
from sciplot_core.studio_core.semantic_payloads import (
    _studio_export_semantic_payload,
    _verified_mapping_ledger_extension,
)
from sciplot_core.studio_core.source_snapshots import (
    _studio_metric_source,
    _studio_snapshot_sources,
)


@dataclass(frozen=True)
class StudioRunSources:
    """Archived input, snapshots, semantic metadata, and analysis metrics."""

    input_path: Path | None
    raw_archive: dict[str, Any]
    existing_transform_ledger: dict[str, Any] | None
    snapshot_sources: list[Path]
    snapshot_source: Path | None
    processed_source: Path | None
    semantic: dict[str, Any]
    metric_source: Path | None
    analysis_metrics: list[dict[str, Any]]


def prepare_studio_run_sources(
    *,
    request: dict[str, Any],
    rule_readiness: StudioRulePublicationReadiness,
    presentation_identity: SelectedPresentationIdentity,
    effective_request: dict[str, Any],
    data_mapping_application: dict[str, Any] | None,
    request_path: Path,
    project_dir: Path,
    document_path: Path,
    output_dir: Path,
) -> StudioRunSources:
    """Snapshot request/input lineage and derive metrics without mutating source."""

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "request_snapshot.json").write_text(
        json.dumps(json_safe(request), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    input_path = _resolve_request_input(request, base_dir=request_path.parent)
    raw_archive = (
        _archive_studio_input(input_path, output_dir) if input_path is not None else {}
    )
    existing_ledger = _verified_mapping_ledger_extension(
        request.get("transform_ledger"),
        (
            effective_request.get("transform_ledger")
            if data_mapping_application is not None
            else None
        ),
    )
    snapshot_sources = _studio_snapshot_sources(
        input_path,
        project_dir=project_dir,
        transform_ledger=existing_ledger,
    )
    snapshot_source = snapshot_sources[0] if snapshot_sources else None
    processed_source = (
        _write_studio_data_snapshots(snapshot_sources, output_dir)
        if snapshot_sources
        else None
    )
    intake_manifest_path = project_dir / "intake_manifest.json"
    intake_manifest = (
        _read_json(intake_manifest_path) if intake_manifest_path.exists() else {}
    )
    semantic = _studio_export_semantic_payload(
        request=request,
        intake_manifest=intake_manifest,
        document_path=document_path,
        rule_readiness=rule_readiness,
        presentation_identity=presentation_identity,
    )
    metric_source = _studio_metric_source(snapshot_source or input_path)
    analysis_metrics = (
        compute_analysis_metrics(
            source_path=metric_source,
            processed_source=metric_source,
            semantic=semantic,
            output_dir=output_dir,
        )
        if metric_source is not None and semantic.get("rule_id")
        else []
    )
    return StudioRunSources(
        input_path=input_path,
        raw_archive=raw_archive,
        existing_transform_ledger=existing_ledger,
        snapshot_sources=snapshot_sources,
        snapshot_source=snapshot_source,
        processed_source=processed_source,
        semantic=semantic,
        metric_source=metric_source,
        analysis_metrics=analysis_metrics,
    )


def verify_studio_run_source_binding(
    plan: ResolvedFigurePlan | None,
    sources: StudioRunSources,
) -> None:
    """Require live and archived sources to match the prepare-time plan."""

    if plan is None:
        return
    expected = plan.source_sha256
    if expected is None:
        raise RuntimeError(
            "Resolved figure plan has no prepare-time source fingerprint; "
            "reprepare the Studio project before publishing."
        )
    archive_value = sources.raw_archive.get("path")
    archive_path = (
        Path(archive_value).expanduser()
        if isinstance(archive_value, str) and archive_value.strip()
        else None
    )
    sources_match = source_trees_match_sha256(
        expected,
        sources.input_path,
        archive_path,
    )
    if not sources_match:
        raise RuntimeError(
            "Studio source changed after its resolved figure plan was prepared; "
            "reprepare before publishing."
        )


__all__ = [
    "StudioRunSources",
    "prepare_studio_run_sources",
    "verify_studio_run_source_binding",
]
