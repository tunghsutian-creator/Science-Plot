"""Resolve request provenance and non-visual context for series encoding."""

from __future__ import annotations

import re
from typing import Any

from sciplot_core.studio_render.template_resolution import _explicit_render_options, _request_template
from sciplot_core.studio_render.value_parsing import _string_list
from sciplot_core.studio_render.models import StudioPreparationBlocked


def series_styles_by_identity(styles: list[Any], *, identities: set[str], structured: bool) -> dict[str, dict[str, Any]]:
    """Current styles consume frozen IDs; historical styles retain label rules."""
    result = {}
    for style in styles:
        if not isinstance(style, dict):
            if structured:
                raise StudioPreparationBlocked("unbound_series_style", "Current series styles require a source-bound style object.")
            continue
        key = style.get("series_id") if structured else (
            style.get("label") or style.get("sample") or style.get("name") or style.get("series_id"))
        if not isinstance(key, str):
            if structured:
                raise StudioPreparationBlocked("unbound_series_style", "Current structured series styles require their saved source ID.")
            continue
        if structured and (key not in identities or key in result):
            raise StudioPreparationBlocked("invalid_bound_series_style", "Each current style must name one retained source ID exactly once.")
        result[key] = style
    return result


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

    raw_options = request.get("render_options")
    request_options = raw_options if isinstance(raw_options, dict) else {}
    explicit_payload = request.get("explicit_render_option_keys")
    if isinstance(explicit_payload, list | tuple | set):
        if option_name in _explicit_render_options(request):
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
    raw_model = request.get("study_model")
    study_model = raw_model if isinstance(raw_model, dict) else {}
    sample_order = _string_list(study_model.get("sample_order"))
    if order != sample_order:
        return False
    raw_queue = study_model.get("figure_queue")
    figure_queue = raw_queue if isinstance(raw_queue, list) else []
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
    categorical = request.get("categorical_binding")
    if isinstance(categorical, dict) and "legend_columns" in categorical:
        from sciplot_core.mapping_contract.categorical import validate_categorical_context

        validate_categorical_context(request)
        merged["_ordinary_categorical_legend_columns"] = categorical["legend_columns"]
    return merged


__all__ = [
    "effective_render_options",
    "is_inferred_source_group_order",
    "replicate_group_style_indexes",
    "request_option_authority",
]
