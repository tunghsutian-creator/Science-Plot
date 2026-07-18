from __future__ import annotations

from typing import Any

from sciplot_core._utils import json_safe

TERMINAL_RENDER_REQUEST_FIELDS = frozenset(
    {
        "template",
        "render_options",
        "x_metric",
        "y_metric",
        "series_order",
    }
)


def _clean_metric(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _terminal_metric_pair(
    request: dict[str, Any],
) -> tuple[str | None, str | None]:
    x_metric = _clean_metric(request.get("x_metric"))
    y_metric = _clean_metric(request.get("y_metric"))
    study_model = (
        request.get("study_model")
        if isinstance(request.get("study_model"), dict)
        else {}
    )
    figure_queue = (
        study_model.get("figure_queue")
        if isinstance(study_model.get("figure_queue"), list)
        else []
    )
    if (x_metric is None or y_metric is None) and figure_queue:
        first_figure = next(
            (item for item in figure_queue if isinstance(item, dict)),
            {},
        )
        x_metric = x_metric or _clean_metric(first_figure.get("x_metric"))
        y_metric = y_metric or _clean_metric(first_figure.get("y_metric"))
    rule_id = str(request.get("rule_id") or "").strip()
    if x_metric is None or y_metric is None:
        if rule_id == "rheology_frequency_sweep":
            x_metric = x_metric or "angular_frequency"
            y_metric = y_metric or "storage_modulus"
        elif rule_id == "rheology_temperature_sweep":
            x_metric = x_metric or "temperature"
            y_metric = y_metric or "storage_modulus"
    return x_metric, y_metric


def project_terminal_render_request(
    *,
    template: str,
    render_options: dict[str, Any],
    request_context: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build the minimal request applied to already-materialized tables."""

    request: dict[str, Any] = {
        "template": str(template).strip(),
        "render_options": json_safe(dict(render_options)),
    }
    if not request["template"]:
        raise ValueError("A terminal render request needs a template.")
    if not isinstance(request_context, dict):
        return request
    x_metric, y_metric = _terminal_metric_pair(request_context)
    if x_metric is not None:
        request["x_metric"] = x_metric
    if y_metric is not None:
        request["y_metric"] = y_metric
    series_order = request_context.get("series_order")
    if (
        isinstance(series_order, list)
        and all(isinstance(item, str) for item in series_order)
    ):
        request["series_order"] = list(series_order)
    return request


def authoritative_terminal_render_request(
    request: dict[str, Any],
) -> dict[str, Any]:
    """Rebuild one unsplit terminal request from user/request authority."""

    if "_terminal_source_prepared" in request:
        raise ValueError(
            "`_terminal_source_prepared` is reserved and cannot appear in a "
            "plot request."
        )
    template = request.get("template")
    if not isinstance(template, str) or not template.strip():
        raise ValueError(
            "Mapped source verification requires an explicit authoritative "
            "template; auto or recipe-only requests must first persist a "
            "reviewed terminal plan."
        )
    render_options = (
        dict(request["render_options"])
        if isinstance(request.get("render_options"), dict)
        else {}
    )
    return project_terminal_render_request(
        template=template,
        render_options=render_options,
        request_context=request,
    )


def normalize_terminal_render_request(
    value: object,
    *,
    label: str,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} is not an object.")
    unknown = set(value) - TERMINAL_RENDER_REQUEST_FIELDS
    if unknown:
        raise ValueError(
            f"{label} contains reserved fields: {sorted(unknown)}"
        )
    template = value.get("template")
    render_options = value.get("render_options")
    if (
        not isinstance(template, str)
        or not template.strip()
        or not isinstance(render_options, dict)
    ):
        raise ValueError(
            f"{label} needs a template and render_options object."
        )
    normalized = project_terminal_render_request(
        template=template,
        render_options=render_options,
        request_context=value,
    )
    if normalized != value:
        raise ValueError(f"{label} is not canonical.")
    return normalized


__all__ = [
    "TERMINAL_RENDER_REQUEST_FIELDS",
    "authoritative_terminal_render_request",
    "normalize_terminal_render_request",
    "project_terminal_render_request",
]
