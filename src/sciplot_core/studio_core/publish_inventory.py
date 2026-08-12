"""Validate and collect the exact-current Studio figure-set export inventory."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sciplot_core.data_mapping import resolve_data_mapping_request
from sciplot_core.figure_plan import (
    FigurePlanResolutionError,
    ResolvedFigurePlan,
    resolve_current_figure_plan,
    resolved_figure_plan_from_payload,
)
from sciplot_core.figure_plan.constants import REQUIRED_FIGURE_PLAN_RULE_IDS
from sciplot_core.foundation.file_hashing import existing_file_sha256
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.presentation_identity import (
    SelectedPresentationIdentity,
    require_selected_template,
    resolve_selected_presentation_identity,
)
from sciplot_core.studio_figure_set_contract import (
    is_full_figure_set_export_scope as _is_full_figure_set_export_scope,
)

from sciplot_core.studio_core.export_execution import export_studio_document
from sciplot_core.studio_core.export_verification import (
    _verify_exact_current_export_binding,
)
from sciplot_core.studio_core.figure_requests import (
    _rheology_frequency_figure_queue,
)
from sciplot_core.studio_core.figure_set_state import (
    _read_studio_figure_set,
    _studio_figure_set_export_scope,
)
from sciplot_core.studio_core.json_files import _read_json
from sciplot_core.studio_core.presentation_evidence import (
    validate_prepared_studio_presentation,
    validate_veusz_spec_presentation,
)
from sciplot_core.studio_core.registry_state import (
    _registered_generated_hash,
    _studio_document_state,
    _veusz_spec_path,
)
from sciplot_core.studio_core.request_paths import (
    _next_studio_run_dir,
    _resolve_request_input,
)
from sciplot_core.studio_core.rule_readiness import (
    StudioRulePublicationReadiness,
    resolve_studio_rule_publication_readiness,
)


@dataclass(frozen=True)
class StudioExportInventory:
    """Validated documents, exports, request state, and destination for one run."""

    project_dir: Path
    request_path: Path
    document_path: Path
    request: dict[str, Any]
    presentation_identity: SelectedPresentationIdentity
    resolved_figure_plan: ResolvedFigurePlan | None
    rule_readiness: StudioRulePublicationReadiness
    figure_set_export_scope: dict[str, Any] | None
    exports: list[dict[str, Any]]
    veusz_documents: list[Path]
    veusz_document_hashes: dict[str, str]
    effective_request: dict[str, Any]
    data_mapping_application: dict[str, Any] | None
    document_state: dict[str, Any]
    export_document_sha256: str
    output_dir: Path

    @property
    def pending_rule_review(self) -> bool:
        return self.rule_readiness.pending_rule_review

    @property
    def publication_rule_blocked(self) -> bool:
        return self.rule_readiness.publication_blocked


def prepare_studio_export_inventory(
    *,
    project_dir: Path,
    request_path: Path,
    document_path: Path,
    exports: list[dict[str, Any]],
    export_document_sha256: str,
) -> StudioExportInventory:
    """Validate project authority and export every registered secondary figure."""

    project_dir, request_path, document_path = _canonical_project_paths(
        project_dir=project_dir,
        request_path=request_path,
        document_path=document_path,
    )
    _verify_exact_current_export_binding(
        document_path=document_path,
        export_document_sha256=export_document_sha256,
        exports=exports,
    )
    request = _read_json(request_path)
    rule_readiness = resolve_studio_rule_publication_readiness(request)
    request_rule_id = rule_readiness.rule_id or ""
    current_rule = rule_readiness.current_rule
    presentation_identity = resolve_selected_presentation_identity(
        request,
        current_rule=current_rule,
    )
    require_selected_template(
        request.get("template"),
        expected=presentation_identity,
        source="canonical plot request",
    )
    primary_spec = _veusz_spec_path(document_path)
    if primary_spec.is_file():
        validate_veusz_spec_presentation(
            _read_json(primary_spec),
            expected=presentation_identity,
            source="primary Studio Veusz spec",
        )
    persisted_plan = request.get("resolved_figure_plan")
    if request_rule_id in REQUIRED_FIGURE_PLAN_RULE_IDS and persisted_plan is None:
        raise RuntimeError(
            "prepared_resolved_figure_plan_required: Reprepare this Studio "
            "project before publishing a rule that requires a figure plan."
        )
    try:
        resolved_figure_plan = (
            resolve_current_figure_plan(
                persisted=persisted_plan,
                rule_id=request_rule_id,
                template=presentation_identity.template,
                study_model=(
                    request.get("study_model")
                    if isinstance(request.get("study_model"), dict)
                    else {}
                ),
                input_path=_resolve_request_input(
                    request,
                    base_dir=request_path.parent,
                ),
                request=request,
            )
            if request_rule_id or persisted_plan is not None
            else None
        )
    except FigurePlanResolutionError as exc:
        raise RuntimeError(f"{exc.reason_code}: {exc}") from exc
    validate_prepared_studio_presentation(
        project_dir=project_dir,
        document_path=document_path,
        identity=presentation_identity,
        figure_plan=resolved_figure_plan,
    )
    scope = _validated_figure_set_scope(project_dir, request=request)
    figure_documents = _collect_figure_documents(
        project_dir=project_dir,
        document_path=document_path,
        exports=exports,
        export_document_sha256=export_document_sha256,
        figure_set_export_scope=scope,
    )
    all_exports = [item for figure in figure_documents for item in figure["exports"]]
    veusz_documents = [Path(str(item["document"])) for item in figure_documents]
    document_hashes = {
        str(Path(str(item["document"])).expanduser().resolve()): str(
            item["document_sha256"]
        )
        for item in figure_documents
    }
    effective_request, mapping_application = resolve_data_mapping_request(
        request,
        base_dir=request_path.parent,
    )
    document_state = _studio_document_state(
        document_path,
        generated_hash=_registered_generated_hash(project_dir),
    )
    if document_state.get("current_hash") != export_document_sha256:
        raise RuntimeError(
            "The Veusz document changed before the project run could bind "
            "its exact-current document state."
        )
    output_dir = _next_studio_run_dir(project_dir)
    return StudioExportInventory(
        project_dir=project_dir,
        request_path=request_path,
        document_path=document_path,
        request=request,
        presentation_identity=presentation_identity,
        resolved_figure_plan=resolved_figure_plan,
        rule_readiness=rule_readiness,
        figure_set_export_scope=scope,
        exports=all_exports,
        veusz_documents=veusz_documents,
        veusz_document_hashes=document_hashes,
        effective_request=effective_request,
        data_mapping_application=mapping_application,
        document_state=document_state,
        export_document_sha256=export_document_sha256,
        output_dir=output_dir,
    )


def _canonical_project_paths(
    *,
    project_dir: Path,
    request_path: Path,
    document_path: Path,
) -> tuple[Path, Path, Path]:
    resolved_project = project_dir.expanduser().resolve()
    resolved_request = request_path.expanduser().resolve()
    resolved_document = document_path.expanduser().resolve()
    if resolved_request != (resolved_project / "plot_request.json").resolve():
        raise RuntimeError(
            "A project delivery receipt can use only the canonical "
            "project/plot_request.json. A foreign or relocated request cannot "
            "publish into this project."
        )
    if resolved_document != (resolved_project / "studio" / "document.vsz").resolve():
        raise RuntimeError(
            "A project delivery receipt can be published only from the "
            "canonical project/studio/document.vsz. Registered secondary "
            "figures are exported automatically into the same project receipt."
        )
    return resolved_project, resolved_request, resolved_document


def _validated_figure_set_scope(
    project_dir: Path,
    *,
    request: dict[str, Any],
) -> dict[str, Any] | None:
    try:
        request_plan = resolved_figure_plan_from_payload(
            request.get("resolved_figure_plan")
        )
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            "invalid_resolved_figure_plan: Studio cannot establish an export "
            "scope from the persisted FigurePlan."
        ) from exc
    selected_supported_plan = (
        request_plan
        if request_plan is not None
        and request_plan.rule_id in REQUIRED_FIGURE_PLAN_RULE_IDS
        else None
    )
    scope = _studio_figure_set_export_scope(project_dir, request=request)
    scope_expected = bool(
        selected_supported_plan is not None
        or _read_studio_figure_set(project_dir) is not None
        or _rheology_frequency_figure_queue(request)
    )
    if selected_supported_plan is not None and not _is_full_figure_set_export_scope(
        scope
    ):
        raise RuntimeError(
            "A selected required FigurePlan needs a matching task-aware v2 "
            "Studio figure-set registry before export. No project delivery "
            "receipt was published."
        )
    if scope_expected and not _is_full_figure_set_export_scope(scope):
        raise RuntimeError(
            "SciPlot could not establish the complete all-figures figure-set "
            "export scope. No project delivery receipt was published."
        )
    return scope


def _collect_figure_documents(
    *,
    project_dir: Path,
    document_path: Path,
    exports: list[dict[str, Any]],
    export_document_sha256: str,
    figure_set_export_scope: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    primary_id = (
        str(figure_set_export_scope.get("primary_figure_id") or "primary")
        if isinstance(figure_set_export_scope, dict)
        else "primary"
    )
    documents = [
        {
            "figure_id": primary_id,
            "document": str(document_path),
            "document_sha256": export_document_sha256,
            "exports": [
                {
                    **json_safe(item),
                    "figure_id": primary_id,
                    "document": str(document_path),
                    "document_sha256": export_document_sha256,
                }
                for item in exports
            ],
        }
    ]
    if not isinstance(figure_set_export_scope, dict):
        return documents
    registry = _read_studio_figure_set(project_dir)
    if registry is None:
        raise RuntimeError(
            "The complete figure-set registry disappeared before export."
        )
    by_id = {
        str(item.get("figure_id") or ""): item
        for item in registry.get("figures", [])
        if isinstance(item, dict)
    }
    requested_formats = list(
        dict.fromkeys(str(item.get("format") or "") for item in exports)
    )
    for figure_id in figure_set_export_scope["supported_figure_ids"]:
        if figure_id == primary_id:
            continue
        documents.append(
            _export_secondary_figure(
                project_dir=project_dir,
                figure_id=str(figure_id),
                registry_entry=by_id.get(str(figure_id)),
                requested_formats=requested_formats,
            )
        )
    return documents


def _export_secondary_figure(
    *,
    project_dir: Path,
    figure_id: str,
    registry_entry: dict[str, Any] | None,
    requested_formats: list[str],
) -> dict[str, Any]:
    if not isinstance(registry_entry, dict) or registry_entry.get("status") != "ready":
        raise RuntimeError(
            f"Registered figure is not ready for complete delivery: {figure_id}"
        )
    document = Path(str(registry_entry.get("document") or "")).expanduser().resolve()
    document_hash = existing_file_sha256(document)
    if not document_hash:
        raise RuntimeError(
            "A registered secondary VSZ is missing before the complete "
            f"figure set can be exported: {document}"
        )
    payload = export_studio_document(
        document,
        formats=requested_formats,
        output_dir=project_dir / "studio" / "exports" / "figure_set",
    )
    secondary_exports = [
        {
            **json_safe(item),
            "figure_id": figure_id,
            "document": str(document),
            "document_sha256": document_hash,
        }
        for item in payload["exports"]
    ]
    _verify_exact_current_export_binding(
        document_path=document,
        export_document_sha256=document_hash,
        exports=secondary_exports,
    )
    return {
        "figure_id": figure_id,
        "document": str(document),
        "document_sha256": document_hash,
        "exports": secondary_exports,
    }
