from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from typing import TypedDict

from src import plot_style
from src.rendering.advanced_plot_axes import primary_axis, secondary_y_axis
from src.rendering.artist_tags import tag_interaction_artist
from src.rendering.axis_breaks import (
    axis_break_panel_axes,
    transform_axis_break_interval_segments,
    transform_axis_break_value,
    value_hidden_by_axis_break,
)
from src.rendering.models import QAReport, RenderedPlot, RenderOptions
from src.rendering.overlay_coordinates import (
    anchor_axis_for_band,
    anchor_axis_for_value,
    panel_contains_value,
    panel_overlap,
    secondary_y_conversion_scale,
)

_VALID_GUIDE_KINDS = frozenset({"line", "band"})
_VALID_GUIDE_AXIS_TARGETS = frozenset({"x", "y_primary", "y_secondary"})


class ReferenceGuidePayloadDict(TypedDict):
    id: str
    enabled: bool
    kind: str
    axis_target: str
    value: float | None
    start: float | None
    end: float | None
    label: str | None


@dataclass(frozen=True)
class ReferenceGuideOptions:
    id: str
    enabled: bool = True
    kind: str = "line"
    axis_target: str = "y_primary"
    value: float | None = None
    start: float | None = None
    end: float | None = None
    label: str | None = None


def _mapping(value: object) -> Mapping[str, object] | None:
    return value if isinstance(value, Mapping) else None


def _string(value: object, *, field_name: str, default: str) -> str:
    cleaned = str(value if value is not None else default).strip() or default
    if not cleaned:
        raise ValueError(f"`{field_name}` must not be blank.")
    return cleaned


def _normalized_kind(value: object, *, field_name: str) -> str:
    kind = _string(value, field_name=field_name, default="line").lower()
    if kind not in _VALID_GUIDE_KINDS:
        raise ValueError(f"`{field_name}` must be one of {', '.join(sorted(_VALID_GUIDE_KINDS))}.")
    return kind


def _normalized_axis_target(value: object, *, field_name: str) -> str:
    axis_target = _string(value, field_name=field_name, default="y_primary").lower()
    if axis_target not in _VALID_GUIDE_AXIS_TARGETS:
        raise ValueError(
            f"`{field_name}` must be one of {', '.join(sorted(_VALID_GUIDE_AXIS_TARGETS))}."
        )
    return axis_target


def _normalized_float(value: object, *, field_name: str, default: float | None) -> float:
    if value is None:
        if default is None:
            raise ValueError(f"`{field_name}` must be numeric.")
        numeric = default
    elif isinstance(value, int | float | str):
        numeric = float(value)
    else:
        raise ValueError(f"`{field_name}` must be numeric.")
    if not math.isfinite(numeric):
        raise ValueError(f"`{field_name}` must be a finite number.")
    return numeric


def _normalized_label(value: object) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _iter_guide_maps(value: object) -> tuple[Mapping[str, object], ...]:
    if value is None:
        return ()
    if not isinstance(value, Iterable) or isinstance(value, (str, bytes, bytearray, Mapping)):
        raise ValueError("`reference_guides` must be a list of mappings.")
    items: list[Mapping[str, object]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise ValueError("`reference_guides` items must be mappings.")
        items.append(item)
    return tuple(items)


def _legacy_guide_items(
    *,
    legacy_line: object,
    legacy_band: object,
) -> tuple[Mapping[str, object], ...]:
    items: list[Mapping[str, object]] = []
    line_map = _mapping(legacy_line)
    if line_map is not None:
        items.append(
            {
                "id": "reference-line-1",
                "enabled": line_map.get("enabled", False),
                "kind": "line",
                "axis_target": "x" if str(line_map.get("axis", "y")).strip().lower() == "x" else "y_primary",
                "value": line_map.get("value"),
                "label": line_map.get("label"),
            }
        )
    band_map = _mapping(legacy_band)
    if band_map is not None:
        items.append(
            {
                "id": "reference-band-1",
                "enabled": band_map.get("enabled", False),
                "kind": "band",
                "axis_target": "x" if str(band_map.get("axis", "y")).strip().lower() == "x" else "y_primary",
                "start": band_map.get("start"),
                "end": band_map.get("end"),
                "label": band_map.get("label"),
            }
        )
    return tuple(items)


def normalize_reference_guides_payload(
    value: object,
    *,
    legacy_line: object = None,
    legacy_band: object = None,
) -> tuple[ReferenceGuidePayloadDict, ...] | None:
    items = _iter_guide_maps(value)
    if not items:
        items = _legacy_guide_items(legacy_line=legacy_line, legacy_band=legacy_band)
    if not items:
        return None

    normalized: list[ReferenceGuidePayloadDict] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(items):
        kind = _normalized_kind(item.get("kind"), field_name=f"reference_guides[{index}].kind")
        guide_id = _string(
            item.get("id"),
            field_name=f"reference_guides[{index}].id",
            default=f"reference-guide-{index + 1}",
        )
        if guide_id in seen_ids:
            raise ValueError("`reference_guides` ids must be unique.")
        seen_ids.add(guide_id)
        axis_target = _normalized_axis_target(
            item.get("axis_target"),
            field_name=f"reference_guides[{index}].axis_target",
        )
        value_number: float | None = None
        start_number: float | None = None
        end_number: float | None = None
        if kind == "line":
            value_number = _normalized_float(
                item.get("value"),
                field_name=f"reference_guides[{index}].value",
                default=0.0,
            )
        else:
            start_number = _normalized_float(
                item.get("start"),
                field_name=f"reference_guides[{index}].start",
                default=0.0,
            )
            end_number = _normalized_float(
                item.get("end"),
                field_name=f"reference_guides[{index}].end",
                default=1.0,
            )
            if end_number < start_number:
                start_number, end_number = end_number, start_number
        normalized.append(
            {
                "id": guide_id,
                "enabled": bool(item.get("enabled", True)),
                "kind": kind,
                "axis_target": axis_target,
                "value": value_number,
                "start": start_number,
                "end": end_number,
                "label": _normalized_label(item.get("label")),
            }
        )
    return tuple(normalized)


def reference_guides_from_payload(
    value: object,
    *,
    legacy_line: object = None,
    legacy_band: object = None,
) -> tuple[ReferenceGuideOptions, ...]:
    payload = normalize_reference_guides_payload(value, legacy_line=legacy_line, legacy_band=legacy_band)
    if payload is None:
        return ()
    return tuple(
        ReferenceGuideOptions(
            id=item["id"],
            enabled=item["enabled"],
            kind=item["kind"],
            axis_target=item["axis_target"],
            value=item["value"],
            start=item["start"],
            end=item["end"],
            label=item["label"],
        )
        for item in payload
    )


def _validate_reference_scale(*, axis_label: str, value: float, scale: str, kind: str) -> None:
    if scale == "log" and value <= 0.0:
        raise ValueError(f"{kind} on a log {axis_label} axis requires a positive value.")


def _guide_scale(axis_target: str, *, options: RenderOptions) -> tuple[str, str]:
    if axis_target == "x":
        return options.xscale, "X"
    return options.yscale, "Y"


def _secondary_label_anchor(options: RenderOptions) -> tuple[float, str]:
    payload = options.extra_y_axis
    if not isinstance(payload, Mapping):
        return 0.98, "right"
    position = str(payload.get("position", "right")).strip().lower()
    if position == "left":
        return 0.02, "left"
    return 0.98, "right"


def _append_autofixes(report: QAReport | None, *, autofix_ids: tuple[str, ...]) -> QAReport | None:
    if report is None:
        return None
    applied = tuple(report.autofixes_applied)
    merged = applied + tuple(item for item in autofix_ids if item not in applied)
    return replace(report, autofixes_applied=merged)


def _band_label_center(segments: tuple[tuple[float, float], ...]) -> float | None:
    if not segments:
        return None
    return (segments[0][0] + segments[-1][1]) / 2.0


def _tag_reference_guide_artist(artist: object, guide: ReferenceGuideOptions) -> None:
    tag_interaction_artist(
        artist,
        payload_type="reference_guide",
        payload_id=guide.id,
        kind="reference_guide",
        label=guide.label,
        operations=("select", "quick_edit", "drag", "more"),
        part=guide.kind,
    )


def apply_reference_guides(rendered: RenderedPlot, *, options: RenderOptions) -> RenderedPlot:
    guides = tuple(
        guide
        for guide in reference_guides_from_payload(options.reference_guides)
        if guide.enabled
    )
    if not guides:
        return rendered

    primary = primary_axis(rendered)
    if primary is None:
        return rendered
    secondary = secondary_y_axis(rendered)
    x_panels = axis_break_panel_axes(rendered, axis_name="x")
    y_panels = axis_break_panel_axes(rendered, axis_name="y")
    stroke = plot_style.current_stroke()
    typography = plot_style.current_typography()
    palette = plot_style.get_categorical_palette(options.palette_preset, n_colors=max(1, len(guides)))
    applied_line = False
    applied_band = False

    for index, guide in enumerate(guides):
        base_axis = secondary if guide.axis_target == "y_secondary" else primary
        if base_axis is None:
            continue
        scale, axis_label = _guide_scale(guide.axis_target, options=options)
        color = palette[index % len(palette)] if palette else "#111827"
        secondary_conversion = guide.axis_target == "y_secondary" and not hasattr(base_axis, "axhline")
        conversion_scale = secondary_y_conversion_scale(options) if secondary_conversion else None
        label_x, label_ha = (
            _secondary_label_anchor(options)
            if guide.axis_target == "y_secondary"
            else (0.98, "right")
        )
        label_transform_axis = base_axis if hasattr(base_axis, "get_yaxis_transform") else primary
        if guide.axis_target == "x":
            if len(x_panels) > 1:
                target_axes = x_panels
            elif len(y_panels) > 1:
                target_axes = y_panels
            else:
                target_axes = (primary,)
        elif guide.axis_target == "y_primary":
            if len(y_panels) > 1:
                target_axes = y_panels
            elif len(x_panels) > 1:
                target_axes = x_panels
            else:
                target_axes = (primary,)
        else:
            target_axes = (base_axis,)

        if guide.kind == "band":
            assert guide.start is not None
            assert guide.end is not None
            _validate_reference_scale(
                axis_label=axis_label,
                value=guide.start,
                scale=scale,
                kind="Reference band",
            )
            _validate_reference_scale(
                axis_label=axis_label,
                value=guide.end,
                scale=scale,
                kind="Reference band",
            )
            if guide.axis_target == "x":
                if len(x_panels) > 1:
                    anchor_axis, anchor_overlap = anchor_axis_for_band(
                        target_axes,
                        axis_name="x",
                        start=guide.start,
                        end=guide.end,
                    )
                    drawn = False
                    for draw_axis in target_axes:
                        overlap = panel_overlap(
                            draw_axis,
                            axis_name="x",
                            start=guide.start,
                            end=guide.end,
                        )
                        if overlap is None:
                            continue
                        span = draw_axis.axvspan(
                            overlap[0],
                            overlap[1],
                            facecolor=color,
                            alpha=min(0.12, stroke.max_fill_alpha * 0.6),
                            linewidth=0.0,
                            zorder=0.6,
                        )
                        _tag_reference_guide_artist(span, guide)
                        drawn = True
                    if not drawn:
                        continue
                    if guide.label and anchor_axis is not None and anchor_overlap is not None:
                        label_x_value = _band_label_center((anchor_overlap,))
                        if label_x_value is None:
                            continue
                        anchor_axis.text(
                            label_x_value,
                            0.98,
                            guide.label,
                            transform=anchor_axis.get_xaxis_transform(),
                            ha="center",
                            va="top",
                            fontsize=typography.legend_font_size_pt,
                            color=color,
                            bbox={
                                "facecolor": "white",
                                "alpha": 0.7,
                                "linewidth": 0.0,
                                "boxstyle": "round,pad=0.18",
                            },
                            zorder=3.5,
                        )
                elif len(y_panels) > 1:
                    for draw_axis in target_axes:
                        span = draw_axis.axvspan(
                            guide.start,
                            guide.end,
                            facecolor=color,
                            alpha=min(0.12, stroke.max_fill_alpha * 0.6),
                            linewidth=0.0,
                            zorder=0.6,
                        )
                        _tag_reference_guide_artist(span, guide)
                    if guide.label:
                        primary.text(
                            (guide.start + guide.end) / 2.0,
                            0.98,
                            guide.label,
                            transform=primary.get_xaxis_transform(),
                            ha="center",
                            va="top",
                            fontsize=typography.legend_font_size_pt,
                            color=color,
                            bbox={
                                "facecolor": "white",
                                "alpha": 0.7,
                                "linewidth": 0.0,
                                "boxstyle": "round,pad=0.18",
                            },
                            zorder=3.5,
                        )
                else:
                    spans = transform_axis_break_interval_segments(
                        primary,
                        axis_name="x",
                        start=guide.start,
                        end=guide.end,
                    )
                    if not spans:
                        continue
                    for span_start, span_end in spans:
                        span = primary.axvspan(
                            span_start,
                            span_end,
                            facecolor=color,
                            alpha=min(0.12, stroke.max_fill_alpha * 0.6),
                            linewidth=0.0,
                            zorder=0.6,
                        )
                        _tag_reference_guide_artist(span, guide)
                    if guide.label:
                        label_x_value = _band_label_center(spans)
                        if label_x_value is None:
                            continue
                        primary.text(
                            label_x_value,
                            0.98,
                            guide.label,
                            transform=primary.get_xaxis_transform(),
                            ha="center",
                            va="top",
                            fontsize=typography.legend_font_size_pt,
                            color=color,
                            bbox={
                                "facecolor": "white",
                                "alpha": 0.7,
                                "linewidth": 0.0,
                                "boxstyle": "round,pad=0.18",
                            },
                            zorder=3.5,
                        )
            else:
                draw_start = guide.start if conversion_scale is None else guide.start / conversion_scale
                draw_end = guide.end if conversion_scale is None else guide.end / conversion_scale
                if len(y_panels) > 1 and guide.axis_target == "y_primary":
                    anchor_axis, anchor_overlap = anchor_axis_for_band(
                        target_axes,
                        axis_name="y",
                        start=draw_start,
                        end=draw_end,
                    )
                    drawn = False
                    for draw_axis in target_axes:
                        overlap = panel_overlap(
                            draw_axis,
                            axis_name="y",
                            start=draw_start,
                            end=draw_end,
                        )
                        if overlap is None:
                            continue
                        span = draw_axis.axhspan(
                            overlap[0],
                            overlap[1],
                            facecolor=color,
                            alpha=min(0.12, stroke.max_fill_alpha * 0.6),
                            linewidth=0.0,
                            zorder=0.6,
                        )
                        _tag_reference_guide_artist(span, guide)
                        drawn = True
                    if not drawn:
                        continue
                    if guide.label and anchor_axis is not None and anchor_overlap is not None:
                        label_y_value = _band_label_center((anchor_overlap,))
                        if label_y_value is None:
                            continue
                        anchor_axis.text(
                            label_x,
                            label_y_value,
                            guide.label,
                            transform=anchor_axis.get_yaxis_transform(),
                            ha=label_ha,
                            va="center",
                            fontsize=typography.legend_font_size_pt,
                            color=color,
                            bbox={
                                "facecolor": "white",
                                "alpha": 0.7,
                                "linewidth": 0.0,
                                "boxstyle": "round,pad=0.18",
                            },
                            zorder=3.5,
                        )
                elif len(x_panels) > 1 and guide.axis_target == "y_primary":
                    for draw_axis in target_axes:
                        span = draw_axis.axhspan(
                            draw_start,
                            draw_end,
                            facecolor=color,
                            alpha=min(0.12, stroke.max_fill_alpha * 0.6),
                            linewidth=0.0,
                            zorder=0.6,
                        )
                        _tag_reference_guide_artist(span, guide)
                    if guide.label:
                        primary.text(
                            label_x,
                            (draw_start + draw_end) / 2.0,
                            guide.label,
                            transform=primary.get_yaxis_transform(),
                            ha=label_ha,
                            va="center",
                            fontsize=typography.legend_font_size_pt,
                            color=color,
                            bbox={
                                "facecolor": "white",
                                "alpha": 0.7,
                                "linewidth": 0.0,
                                "boxstyle": "round,pad=0.18",
                            },
                            zorder=3.5,
                        )
                else:
                    draw_axis = primary if conversion_scale is not None else base_axis
                    spans = (
                        transform_axis_break_interval_segments(
                            draw_axis,
                            axis_name="y",
                            start=draw_start,
                            end=draw_end,
                        )
                        if conversion_scale is None and guide.axis_target == "y_primary"
                        else ((draw_start, draw_end),)
                    )
                    if not spans:
                        continue
                    for span_start, span_end in spans:
                        span = draw_axis.axhspan(
                            span_start,
                            span_end,
                            facecolor=color,
                            alpha=min(0.12, stroke.max_fill_alpha * 0.6),
                            linewidth=0.0,
                            zorder=0.6,
                        )
                        _tag_reference_guide_artist(span, guide)
                    if guide.label:
                        label_y_value = _band_label_center(spans)
                        if label_y_value is None:
                            continue
                        primary.text(
                            label_x,
                            label_y_value,
                            guide.label,
                            transform=label_transform_axis.get_yaxis_transform(),
                            ha=label_ha,
                            va="center",
                            fontsize=typography.legend_font_size_pt,
                            color=color,
                            bbox={
                                "facecolor": "white",
                                "alpha": 0.7,
                                "linewidth": 0.0,
                                "boxstyle": "round,pad=0.18",
                            },
                            zorder=3.5,
                        )
            applied_band = True
            continue

        assert guide.value is not None
        _validate_reference_scale(
            axis_label=axis_label,
            value=guide.value,
            scale=scale,
            kind="Reference line",
        )
        if guide.axis_target == "x":
            if len(x_panels) > 1:
                target_axes = tuple(
                    draw_axis
                    for draw_axis in target_axes
                    if panel_contains_value(draw_axis, axis_name="x", value=guide.value)
                )
                if not target_axes:
                    continue
                for draw_axis in target_axes:
                    line = draw_axis.axvline(
                        guide.value,
                        color=color,
                        linewidth=max(0.9, stroke.line_width_pt * 0.85),
                        alpha=min(0.92, stroke.line_alpha + 0.08),
                        linestyle="--",
                        label="_nolegend_",
                        zorder=3.6,
                    )
                    _tag_reference_guide_artist(line, guide)
                if guide.label:
                    anchor_axis = anchor_axis_for_value(target_axes, axis_name="x", value=guide.value)
                    if anchor_axis is None:
                        continue
                    anchor_axis.text(
                        guide.value,
                        0.98,
                        guide.label,
                        transform=anchor_axis.get_xaxis_transform(),
                        ha="center",
                        va="top",
                        fontsize=typography.legend_font_size_pt,
                        color=color,
                        bbox={
                            "facecolor": "white",
                            "alpha": 0.74,
                            "linewidth": 0.0,
                            "boxstyle": "round,pad=0.18",
                        },
                        zorder=3.8,
                    )
            elif len(y_panels) > 1:
                for draw_axis in target_axes:
                    line = draw_axis.axvline(
                        guide.value,
                        color=color,
                        linewidth=max(0.9, stroke.line_width_pt * 0.85),
                        alpha=min(0.92, stroke.line_alpha + 0.08),
                        linestyle="--",
                        label="_nolegend_",
                        zorder=3.6,
                    )
                    _tag_reference_guide_artist(line, guide)
                if guide.label:
                    primary.text(
                        guide.value,
                        0.98,
                        guide.label,
                        transform=primary.get_xaxis_transform(),
                        ha="center",
                        va="top",
                        fontsize=typography.legend_font_size_pt,
                        color=color,
                        bbox={
                            "facecolor": "white",
                            "alpha": 0.74,
                            "linewidth": 0.0,
                            "boxstyle": "round,pad=0.18",
                        },
                        zorder=3.8,
                    )
            else:
                if value_hidden_by_axis_break(primary, axis_name="x", value=guide.value):
                    continue
                draw_value = transform_axis_break_value(primary, axis_name="x", value=guide.value)
                if draw_value is None:
                    continue
                line = primary.axvline(
                    draw_value,
                    color=color,
                    linewidth=max(0.9, stroke.line_width_pt * 0.85),
                    alpha=min(0.92, stroke.line_alpha + 0.08),
                    linestyle="--",
                    label="_nolegend_",
                    zorder=3.6,
                )
                _tag_reference_guide_artist(line, guide)
                if guide.label:
                    primary.text(
                        draw_value,
                        0.98,
                        guide.label,
                        transform=primary.get_xaxis_transform(),
                        ha="center",
                        va="top",
                        fontsize=typography.legend_font_size_pt,
                        color=color,
                        bbox={
                            "facecolor": "white",
                            "alpha": 0.74,
                            "linewidth": 0.0,
                            "boxstyle": "round,pad=0.18",
                        },
                        zorder=3.8,
                    )
        else:
            draw_value = guide.value if conversion_scale is None else guide.value / conversion_scale
            if len(y_panels) > 1 and guide.axis_target == "y_primary":
                target_axes = tuple(
                    draw_axis
                    for draw_axis in target_axes
                    if panel_contains_value(draw_axis, axis_name="y", value=draw_value)
                )
                if not target_axes:
                    continue
                for draw_axis in target_axes:
                    line = draw_axis.axhline(
                        draw_value,
                        color=color,
                        linewidth=max(0.9, stroke.line_width_pt * 0.85),
                        alpha=min(0.92, stroke.line_alpha + 0.08),
                        linestyle="--",
                        label="_nolegend_",
                        zorder=3.6,
                    )
                    _tag_reference_guide_artist(line, guide)
                if guide.label:
                    anchor_axis = anchor_axis_for_value(target_axes, axis_name="y", value=draw_value)
                    if anchor_axis is None:
                        continue
                    anchor_axis.text(
                        label_x,
                        draw_value,
                        guide.label,
                        transform=anchor_axis.get_yaxis_transform(),
                        ha=label_ha,
                        va="center",
                        fontsize=typography.legend_font_size_pt,
                        color=color,
                        bbox={
                            "facecolor": "white",
                            "alpha": 0.74,
                            "linewidth": 0.0,
                            "boxstyle": "round,pad=0.18",
                        },
                        zorder=3.8,
                    )
            elif len(x_panels) > 1 and guide.axis_target == "y_primary":
                for draw_axis in target_axes:
                    line = draw_axis.axhline(
                        draw_value,
                        color=color,
                        linewidth=max(0.9, stroke.line_width_pt * 0.85),
                        alpha=min(0.92, stroke.line_alpha + 0.08),
                        linestyle="--",
                        label="_nolegend_",
                        zorder=3.6,
                    )
                    _tag_reference_guide_artist(line, guide)
                if guide.label:
                    primary.text(
                        label_x,
                        draw_value,
                        guide.label,
                        transform=primary.get_yaxis_transform(),
                        ha=label_ha,
                        va="center",
                        fontsize=typography.legend_font_size_pt,
                        color=color,
                        bbox={
                            "facecolor": "white",
                            "alpha": 0.74,
                            "linewidth": 0.0,
                            "boxstyle": "round,pad=0.18",
                        },
                        zorder=3.8,
                    )
            else:
                draw_axis = primary if conversion_scale is not None else base_axis
                if conversion_scale is None and guide.axis_target == "y_primary":
                    if value_hidden_by_axis_break(draw_axis, axis_name="y", value=draw_value):
                        continue
                    mapped_value = transform_axis_break_value(draw_axis, axis_name="y", value=draw_value)
                    if mapped_value is None:
                        continue
                    draw_value = mapped_value
                line = draw_axis.axhline(
                    draw_value,
                    color=color,
                    linewidth=max(0.9, stroke.line_width_pt * 0.85),
                    alpha=min(0.92, stroke.line_alpha + 0.08),
                    linestyle="--",
                    label="_nolegend_",
                    zorder=3.6,
                )
                _tag_reference_guide_artist(line, guide)
                if guide.label:
                    primary.text(
                        label_x,
                        draw_value,
                        guide.label,
                        transform=label_transform_axis.get_yaxis_transform(),
                        ha=label_ha,
                        va="center",
                        fontsize=typography.legend_font_size_pt,
                        color=color,
                        bbox={
                            "facecolor": "white",
                            "alpha": 0.74,
                            "linewidth": 0.0,
                            "boxstyle": "round,pad=0.18",
                        },
                        zorder=3.8,
                    )
        applied_line = True

    autofix_ids: list[str] = []
    if applied_line:
        autofix_ids.append("reference_line_overlay")
    if applied_band:
        autofix_ids.append("reference_band_overlay")
    if not autofix_ids:
        return rendered
    return replace(
        rendered,
        qa_report=_append_autofixes(rendered.qa_report, autofix_ids=tuple(autofix_ids)),
    )


__all__ = [
    "ReferenceGuideOptions",
    "ReferenceGuidePayloadDict",
    "apply_reference_guides",
    "normalize_reference_guides_payload",
    "reference_guides_from_payload",
]
