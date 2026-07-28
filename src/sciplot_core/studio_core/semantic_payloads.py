"""Bind exported semantics to mapping lineage and exact-current axes."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any
from sciplot_core.foundation.file_hashing import (
    existing_file_sha256,
)
from sciplot_core.materials_rules import (
    get_rule,
    semantic_payload_from_rule,
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
) -> dict[str, Any]:
    recognition = (
        intake_manifest.get("recognition")
        if isinstance(intake_manifest.get("recognition"), dict)
        else {}
    )
    rule_id = str(recognition.get("rule_id") or request.get("rule_id") or "").strip()
    rule = get_rule(rule_id) if rule_id else None
    rule_payload = (
        semantic_payload_from_rule(
            rule,
            confidence=100.0,
            reason=(
                recognition.get("reason")
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
        **recognition,
        "semantic_family": (
            recognition.get("semantic_family")
            or rule_payload.get("semantic_family")
            or experiment.get("id")
            or rule_id
            or "unknown"
        ),
        "rule_id": recognition.get("rule_id") or rule_id or None,
        "reason": (
            recognition.get("reason")
            or rule_payload.get("reason")
            or "Exported from the canonical SciPlot Veusz document."
        ),
        "route": "studio",
    }
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
