"""Resolve request provenance and non-visual context for series encoding."""

from __future__ import annotations

import re
from typing import Any

from sciplot_core.studio_render.template_resolution import _request_template
from sciplot_core.studio_render.value_parsing import _string_list


def replicate_group_style_indexes(labels: list[str]) -> dict[str, tuple[int, int]]:
    """Return stable condition and within-condition replicate indexes."""

    pattern = re.compile(
        r"^(?P<condition>.+?)\s+replicate\s+(?P<replicate>\S+)\s*$",
        flags=re.IGNORECASE,
    )
    conditions: list[str] = []
    replicates: dict[str, list[str]] = {}
    parsed: dict[str, tuple[str, str]] = {}
    for label in labels:
        match = pattern.fullmatch(label.strip())
        if match is None:
            continue
        condition = match.group("condition").strip()
        replicate = match.group("replicate").strip()
        if condition not in conditions:
            conditions.append(condition)
        if replicate not in replicates.setdefault(condition, []):
            replicates[condition].append(replicate)
        parsed[label] = (condition, replicate)
    return {
        label: (
            conditions.index(condition),
            replicates[condition].index(replicate),
        )
        for label, (condition, replicate) in parsed.items()
    }


def request_option_authority(
    request: dict[str, Any],
    option_name: str,
) -> tuple[str, bool]:
    """Return the option source and whether exact-current output must match it."""

    request_options = (
        request.get("render_options")
        if isinstance(request.get("render_options"), dict)
        else {}
    )
    explicit_payload = request.get("explicit_render_option_keys")
    if isinstance(explicit_payload, list | tuple | set):
        explicit_keys = {str(value) for value in explicit_payload}
        if option_name in explicit_keys:
            return "explicit_render_option", True
        return "inherited_render_option", False
    if option_name in request_options:
        return "direct_render_option", True
    return "resolved_default", False


def is_inferred_source_group_order(
    order: list[str],
    *,
    request: dict[str, Any],
) -> bool:
    """Recognize intake grouping labels that are not terminal curve labels."""

    if not order:
        return False
    study_model = (
        request.get("study_model")
        if isinstance(request.get("study_model"), dict)
        else {}
    )
    sample_order = _string_list(study_model.get("sample_order"))
    if order != sample_order:
        return False
    figure_queue = (
        study_model.get("figure_queue")
        if isinstance(study_model.get("figure_queue"), list)
        else []
    )
    confirmation_statuses = {
        str(evidence.get("confirmation_status") or "").strip().casefold()
        for figure in figure_queue
        if isinstance(figure, dict)
        for evidence in [figure.get("evidence_contract")]
        if isinstance(evidence, dict)
    }
    return not confirmation_statuses.intersection(
        {"confirmed", "approved", "user_confirmed"}
    )


def effective_render_options(request: dict[str, Any]) -> dict[str, Any]:
    """Merge template defaults with the request before domain resolution."""

    template_id = _request_template(request)
    merged: dict[str, Any] = {}
    try:
        from sciplot_core.contract import load_plot_contract

        contract = load_plot_contract()
        template = contract.templates.get(template_id)
        if template is not None:
            merged.update(template.default_options)
    except Exception:
        if template_id == "stacked_curve":
            merged.update(
                {"series_label_mode": "inline", "baseline": "none", "reverse_x": False}
            )

    if isinstance(request.get("render_options"), dict):
        merged.update(request["render_options"])
    return merged


__all__ = [
    "effective_render_options",
    "is_inferred_source_group_order",
    "replicate_group_style_indexes",
    "request_option_authority",
]
