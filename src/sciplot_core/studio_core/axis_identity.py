"""Normalize terminal axis identity and derive the effective exact-current axis plan."""

from __future__ import annotations

import re
from copy import deepcopy
from pathlib import Path
from typing import Any
from sciplot_core.foundation.file_hashing import (
    existing_file_sha256,
)
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.materials_rules import (
    format_unit_label,
)

from sciplot_core.studio_core.registry_state import (
    _veusz_spec_path,
)


def _semantic_payload_with_exact_current_axes(
    semantic: dict[str, Any],
    *,
    qa: dict[str, Any],
    document_path: Path,
) -> dict[str, Any]:
    """Promote exact-current axis settings from the Veusz QA audit."""

    publication = (
        qa.get("publication") if isinstance(qa.get("publication"), dict) else {}
    )
    audit_set = (
        publication.get("veusz_document_audit")
        if isinstance(publication.get("veusz_document_audit"), dict)
        else {}
    )
    documents = (
        audit_set.get("documents")
        if isinstance(audit_set.get("documents"), list)
        else []
    )
    resolved = document_path.expanduser().resolve()
    document_audit = next(
        (
            item
            for item in documents
            if isinstance(item, dict)
            and Path(str(item.get("path") or "")).expanduser().resolve() == resolved
        ),
        None,
    )
    if not isinstance(document_audit, dict):
        return semantic
    axis_records = (
        document_audit.get("axes")
        if isinstance(document_audit.get("axes"), list)
        else []
    )
    axes = {
        str(item.get("name") or ""): item
        for item in axis_records
        if isinstance(item, dict)
        and str(item.get("name") or "") in {"x", "y"}
        and not bool(item.get("hidden"))
    }
    if set(axes) != {"x", "y"}:
        return semantic
    updated = deepcopy(semantic)
    registered = (
        updated.get("registered_axis_plan")
        if isinstance(updated.get("registered_axis_plan"), dict)
        else {}
    )
    effective = _effective_axis_plan(registered, axes=axes)
    updated["axis_plan"] = effective
    updated["effective_axis_plan"] = deepcopy(effective)
    updated["unit_plan"] = {
        axis: str(payload.get("canonical_unit") or "")
        for axis, payload in effective.items()
        if isinstance(payload, dict)
    }
    updated["axis_plan_role"] = "effective_terminal_render_axis"
    updated["axis_authority"] = {
        "kind": "sciplot_axis_authority",
        "version": 1,
        "status": "exact_current",
        "source": "veusz_exact_current_document_audit",
        "document": str(resolved),
        "document_sha256": str(
            document_audit.get("sha256") or existing_file_sha256(resolved) or ""
        ),
        "spec": str(_veusz_spec_path(resolved)),
    }
    return updated


def _effective_axis_plan(
    registered_axis_plan: dict[str, Any],
    *,
    axes: dict[str, Any],
) -> dict[str, Any]:
    effective: dict[str, Any] = {}
    for axis_name in ("x", "y"):
        terminal = axes.get(axis_name) if isinstance(axes.get(axis_name), dict) else {}
        registered = (
            deepcopy(registered_axis_plan.get(axis_name))
            if isinstance(registered_axis_plan.get(axis_name), dict)
            else {}
        )
        label = str(
            terminal.get("label")
            or registered.get("display_label")
            or registered.get("canonical_label")
            or axis_name
        ).strip()
        canonical_label, canonical_unit = _terminal_axis_identity(
            label,
            registered=registered,
            fallback=axis_name,
        )
        payload = {
            **registered,
            "canonical_label": canonical_label,
            "canonical_unit": canonical_unit,
            "display_label": label,
            "scale": str(terminal.get("scale") or registered.get("scale") or "linear"),
            "reverse": _terminal_axis_reverse(
                terminal,
                fallback=bool(registered.get("reverse")),
            ),
            "authority": "terminal_render_contract",
        }
        for source_key, target_key in (
            ("min", "minimum"),
            ("max", "maximum"),
            ("ticks", "ticks"),
        ):
            if source_key in terminal:
                payload[target_key] = json_safe(terminal[source_key])
        effective[axis_name] = payload
    return effective


def _terminal_axis_identity(
    label: str,
    *,
    registered: dict[str, Any],
    fallback: str,
) -> tuple[str, str]:
    from sciplot_core.plot_data import _split_label_unit

    visible_name, visible_unit = _split_label_unit(label, fallback=fallback)
    registered_name = str(
        registered.get("display_label") or registered.get("canonical_label") or ""
    ).strip()
    registered_visible_name, _registered_visible_unit = _split_label_unit(
        registered_name,
        fallback=fallback,
    )
    canonical_label = str(
        registered.get("canonical_label") or visible_name or fallback
    ).strip()
    if _axis_identity_token(visible_name) != _axis_identity_token(
        registered_visible_name
    ):
        canonical_label = visible_name or canonical_label
    registered_unit = str(registered.get("canonical_unit") or "").strip()
    canonical_unit = _canonical_terminal_axis_unit(
        visible_unit,
        registered=registered_unit,
    )
    return canonical_label, canonical_unit


def _axis_identity_token(value: object) -> str:
    return re.sub(r"[^a-z0-9%]+", "", str(value or "").casefold())


def _canonical_terminal_axis_unit(
    visible_unit: object,
    *,
    registered: str,
) -> str:
    unit = str(visible_unit or "").strip()
    if format_unit_label(unit) == format_unit_label(registered):
        return registered
    normalized = (
        unit.replace("$", "")
        .replace("{", "")
        .replace("}", "")
        .replace("\\", "")
        .replace("−", "-")
        .replace("·", ".")
    )
    aliases = {
        "°": "degree",
        "°c": "C",
        "cm^-1": "cm^-1",
        "nm^-1": "nm^-1",
        "å^-1": "A^-1",
        "counts": "count",
    }
    normalized = aliases.get(normalized.casefold(), normalized)
    if not normalized:
        return registered
    if _axis_identity_token(normalized) == _axis_identity_token(registered):
        return registered
    return normalized


def _terminal_axis_reverse(
    terminal: dict[str, Any],
    *,
    fallback: bool,
) -> bool:
    minimum = terminal.get("min")
    maximum = terminal.get("max")
    if isinstance(minimum, int | float) and isinstance(maximum, int | float):
        return float(minimum) > float(maximum)
    return fallback
