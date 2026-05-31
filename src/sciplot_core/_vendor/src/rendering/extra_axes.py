from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import replace
from typing import Any, TypedDict, cast

from src.rendering.advanced_plot_axes import mark_extra_axis, mark_primary_axis
from src.rendering.models import QAReport, RenderedPlot, RenderOptions
from src.text_normalization import _clean_text, normalize_unit

_VALID_X_POSITIONS = frozenset({"top", "bottom"})
_VALID_Y_POSITIONS = frozenset({"left", "right"})
_VALID_BINDING_MODES = frozenset({"conversion", "series_assignment"})


class ExtraAxisPayloadDict(TypedDict):
    enabled: bool
    position: str
    binding_mode: str
    series_ids: tuple[str, ...]
    title: str | None
    display_unit: str | None
    data_value: float
    display_value: float


def _clean_optional_text(value: object) -> str | None:
    if value is None:
        return None
    cleaned = _clean_text(str(value))
    return cleaned or None


def _coerce_positive_float(value: object, *, field_name: str) -> float:
    try:
        number = float(cast(Any, value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"`{field_name}` must be a positive number.") from exc
    if not number > 0:
        raise ValueError(f"`{field_name}` must be a positive number.")
    return number


def normalize_series_selection_ids(values: Iterable[object]) -> tuple[str, ...]:
    resolved: list[str] = []
    seen_counts: dict[str, int] = {}
    for raw in values:
        cleaned = _clean_text(str(raw))
        if not cleaned:
            continue
        occurrence = seen_counts.get(cleaned, 0) + 1
        seen_counts[cleaned] = occurrence
        resolved.append(cleaned if occurrence == 1 else f"{cleaned} ({occurrence})")
    return tuple(resolved)


def _series_ids_from_value(value: object, *, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes, bytearray, Mapping)):
        raise ValueError(f"`{field_name}` must be a list of series labels.")
    if not isinstance(value, Iterable):
        raise ValueError(f"`{field_name}` must be a list of series labels.")
    return normalize_series_selection_ids(value)


def extra_axis_binding_mode(value: Mapping[str, Any] | None) -> str:
    if value is None:
        return "conversion"
    resolved = _clean_text(str(value.get("binding_mode", "conversion"))) or "conversion"
    return resolved.lower()


def extra_axis_series_ids(value: Mapping[str, Any] | None) -> tuple[str, ...]:
    if value is None:
        return ()
    raw = value.get("series_ids")
    if not isinstance(raw, tuple):
        return ()
    return tuple(str(item) for item in raw)


def normalize_extra_axis_payload(
    value: object,
    *,
    axis_name: str,
) -> ExtraAxisPayloadDict | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError(f"`extra_{axis_name}_axis` must be a mapping.")

    position_raw = str(value.get("position", "top" if axis_name == "x" else "right")).strip().lower()
    valid_positions = _VALID_X_POSITIONS if axis_name == "x" else _VALID_Y_POSITIONS
    if position_raw not in valid_positions:
        joined = ", ".join(sorted(valid_positions))
        raise ValueError(f"`extra_{axis_name}_axis.position` must be one of: {joined}.")

    binding_mode = extra_axis_binding_mode(cast(Mapping[str, Any], value))
    if binding_mode not in _VALID_BINDING_MODES:
        joined = ", ".join(sorted(_VALID_BINDING_MODES))
        raise ValueError(f"`extra_{axis_name}_axis.binding_mode` must be one of: {joined}.")
    if axis_name == "x" and binding_mode != "conversion":
        raise ValueError("`extra_x_axis.binding_mode` only supports `conversion`.")
    series_ids = _series_ids_from_value(
        value.get("series_ids"),
        field_name=f"extra_{axis_name}_axis.series_ids",
    )

    return ExtraAxisPayloadDict(
        enabled=bool(value.get("enabled", False)),
        position=position_raw,
        binding_mode=binding_mode,
        series_ids=series_ids,
        title=_clean_optional_text(value.get("title")),
        display_unit=_clean_optional_text(value.get("display_unit")),
        data_value=_coerce_positive_float(
            value.get("data_value", 1.0),
            field_name=f"extra_{axis_name}_axis.data_value",
        ),
        display_value=_coerce_positive_float(
            value.get("display_value", 1.0),
            field_name=f"extra_{axis_name}_axis.display_value",
        ),
    )


def extra_axis_label(payload: Mapping[str, Any]) -> str:
    title = payload.get("title")
    display_unit = normalize_unit(payload.get("display_unit") or "")
    if title and display_unit:
        return f"{title} ({display_unit})"
    if title:
        return title
    return display_unit


def _append_autofix(report: QAReport | None, *, autofix_id: str) -> QAReport | None:
    if report is None:
        return None
    if autofix_id in report.autofixes_applied:
        return report
    return replace(
        report,
        autofixes_applied=report.autofixes_applied + (autofix_id,),
    )


def apply_extra_axes(rendered: RenderedPlot, *, options: RenderOptions) -> RenderedPlot:
    ax = rendered.figure.axes[0] if rendered.figure.axes else None
    if ax is None:
        return rendered
    mark_primary_axis(ax)

    applied = False
    for axis_name, payload in (
        ("x", normalize_extra_axis_payload(options.extra_x_axis, axis_name="x")),
        ("y", normalize_extra_axis_payload(options.extra_y_axis, axis_name="y")),
    ):
        if (
            payload is None
            or not payload["enabled"]
            or payload["binding_mode"] != "conversion"
        ):
            continue
        scale = payload["display_value"] / payload["data_value"]
        if axis_name == "x":
            secondary = ax.secondary_xaxis(
                payload["position"],
                functions=(
                    lambda value, scale=scale: value * scale,
                    lambda value, scale=scale: value / scale,
                ),
            )
            secondary.set_xscale(ax.get_xscale())
            if ax.xaxis_inverted():
                secondary.invert_xaxis()
            mark_extra_axis(secondary, axis_name="x")
            label = extra_axis_label(payload)
            if label:
                secondary.set_xlabel(label)
        else:
            secondary = ax.secondary_yaxis(
                payload["position"],
                functions=(
                    lambda value, scale=scale: value * scale,
                    lambda value, scale=scale: value / scale,
                ),
            )
            secondary.set_yscale(ax.get_yscale())
            if ax.yaxis_inverted():
                secondary.invert_yaxis()
            mark_extra_axis(secondary, axis_name="y")
            label = extra_axis_label(payload)
            if label:
                secondary.set_ylabel(label)
        applied = True

    if not applied:
        return rendered
    return replace(rendered, qa_report=_append_autofix(rendered.qa_report, autofix_id="extra_axis_overlay"))


__all__ = [
    "apply_extra_axes",
    "extra_axis_binding_mode",
    "extra_axis_label",
    "extra_axis_series_ids",
    "normalize_series_selection_ids",
    "normalize_extra_axis_payload",
]
