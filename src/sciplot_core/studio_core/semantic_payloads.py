"""Bind exported semantics to mapping lineage and exact-current axes."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any
from sciplot_core.foundation.file_hashing import (
    existing_file_sha256,
)
from sciplot_core.materials_rules import (
    semantic_payload_from_rule,
)
from sciplot_core.presentation_identity import (
    SelectedPresentationIdentity,
    resolve_selected_presentation_identity,
)

from sciplot_core.studio_core.json_files import (
    _read_json,
)

from sciplot_core.studio_core.axis_identity import (
    _effective_axis_plan,
)

from sciplot_core.studio_core.registry_state import (
    _veusz_spec_path,
)
from sciplot_core.studio_core.rule_readiness import (
    StudioRulePublicationReadiness,
    resolve_studio_rule_publication_readiness,
)


_CURRENT_RULE_AUTHORITY_FIELDS = (
    "rule_id",
    "semantic_family",
    "confidence",
    "needs_ai_intervention",
    "production_status",
    "rule_readiness",
    "missing_requirements",
    "template",
)


def _verified_mapping_ledger_extension(
    current: object,
    verified_base: object,
) -> dict[str, Any] | None:
    if not isinstance(verified_base, dict):
        return deepcopy(current) if isinstance(current, dict) else None
    if not isinstance(current, dict):
        return deepcopy(verified_base)
    base_steps = (
        verified_base.get("steps")
        if isinstance(verified_base.get("steps"), list)
        else []
    )
    current_steps = (
        current.get("steps") if isinstance(current.get("steps"), list) else []
    )
    if current_steps[: len(base_steps)] != base_steps:
        raise ValueError(
            "Studio transform lineage no longer extends the verified "
            "DataMappingProposal ledger."
        )
    return deepcopy(current)


def _studio_export_semantic_payload(
    *,
    request: dict[str, Any],
    intake_manifest: dict[str, Any],
    document_path: Path,
    rule_readiness: StudioRulePublicationReadiness | None = None,
    presentation_identity: SelectedPresentationIdentity | None = None,
) -> dict[str, Any]:
    recognition = (
        intake_manifest.get("recognition")
        if isinstance(intake_manifest.get("recognition"), dict)
        else {}
    )
    readiness = (
        rule_readiness
        if rule_readiness is not None
        else resolve_studio_rule_publication_readiness(request)
    )
    rule_id = readiness.rule_id
    rule = readiness.current_rule
    selected_presentation = (
        presentation_identity
        if presentation_identity is not None
        else resolve_selected_presentation_identity(
            request,
            current_rule=rule,
        )
    )
    recognition_rule_id = (
        recognition.get("rule_id")
        if isinstance(recognition.get("rule_id"), str)
        else None
    )
    matching_recognition = (
        recognition
        if (
            rule_id is not None
            and recognition_rule_id is not None
            and recognition_rule_id.strip() == rule_id
        )
        else {}
    )
    recognition_reason = (
        matching_recognition.get("reason")
        if isinstance(matching_recognition.get("reason"), str)
        and str(matching_recognition["reason"]).strip()
        else None
    )
    rule_payload = (
        semantic_payload_from_rule(
            rule,
            confidence=100.0,
            reason=(
                recognition_reason
                or "Resolved from the persisted request rule for Studio export."
            ),
        )
        if rule is not None
        else {}
    )
    experiment = (
        intake_manifest.get("experiment")
        if isinstance(intake_manifest.get("experiment"), dict)
        else {}
    )
    semantic = {
        **rule_payload,
        **matching_recognition,
        "semantic_family": (
            rule_payload.get("semantic_family")
            or experiment.get("id")
            or rule_id
            or "unknown"
        ),
        "rule_id": rule_id,
        "reason": (
            recognition_reason
            or rule_payload.get("reason")
            or "Exported from the canonical SciPlot Veusz document."
        ),
        "route": "studio",
    }
    if rule is not None:
        for field in _CURRENT_RULE_AUTHORITY_FIELDS:
            semantic[field] = deepcopy(rule_payload[field])
        if "fixture_status" in semantic:
            semantic["fixture_status"] = rule.fixture_status
    if readiness.pending_rule_review:
        semantic["pending_rule_review"] = True
    else:
        semantic.pop("pending_rule_review", None)
    semantic["studio_rule_publication_readiness"] = readiness.to_payload()
    semantic["publication_rule_ready"] = not readiness.publication_blocked
    semantic["presentation_identity"] = selected_presentation.to_payload()
    return _semantic_payload_with_terminal_axes(
        semantic,
        document_path=document_path,
    )


def _semantic_payload_with_terminal_axes(
    semantic: dict[str, Any],
    *,
    document_path: Path,
) -> dict[str, Any]:
    """Make the generated terminal render contract the exported axis truth."""

    updated = deepcopy(semantic)
    registered_axis_plan = (
        deepcopy(updated.get("registered_axis_plan"))
        if isinstance(updated.get("registered_axis_plan"), dict)
        else deepcopy(updated.get("axis_plan"))
        if isinstance(updated.get("axis_plan"), dict)
        else {}
    )
    registered_unit_plan = (
        deepcopy(updated.get("registered_unit_plan"))
        if isinstance(updated.get("registered_unit_plan"), dict)
        else deepcopy(updated.get("unit_plan"))
        if isinstance(updated.get("unit_plan"), dict)
        else {}
    )
    updated["registered_axis_plan"] = registered_axis_plan
    updated["registered_unit_plan"] = registered_unit_plan
    updated["expected_axis_plan"] = deepcopy(registered_axis_plan)
    updated["axis_plan"] = deepcopy(registered_axis_plan)
    updated["unit_plan"] = deepcopy(registered_unit_plan)
    for field in ("effective_axis_plan", "axis_plan_role", "axis_authority"):
        updated.pop(field, None)

    spec_path = _veusz_spec_path(document_path)
    spec = _read_json(spec_path) if spec_path.is_file() else {}
    axes = spec.get("axes") if isinstance(spec.get("axes"), dict) else {}
    document_sha256 = existing_file_sha256(document_path)
    terminal_axes_complete = document_sha256 is not None and all(
        isinstance(axes.get(axis_name), dict) and bool(axes[axis_name])
        for axis_name in ("x", "y")
    )
    effective_axis_plan = (
        _effective_axis_plan(
            registered_axis_plan,
            axes=axes,
        )
        if terminal_axes_complete
        else {}
    )
    if effective_axis_plan:
        updated["axis_plan"] = effective_axis_plan
        updated["unit_plan"] = {
            axis: str(payload.get("canonical_unit") or "")
            for axis, payload in effective_axis_plan.items()
            if isinstance(payload, dict)
        }
        updated["effective_axis_plan"] = deepcopy(effective_axis_plan)
        updated["axis_plan_role"] = "effective_terminal_render_axis"
        updated["axis_authority"] = {
            "kind": "sciplot_axis_authority",
            "version": 1,
            "status": "generated_terminal_contract",
            "source": "veusz_spec_terminal_render_contract",
            "document": str(document_path),
            "document_sha256": document_sha256,
            "spec": str(spec_path),
        }
    return updated
