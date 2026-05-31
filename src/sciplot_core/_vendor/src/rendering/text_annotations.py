from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from typing import TypedDict

import matplotlib as mpl
from matplotlib.axes import Axes

from src import plot_style
from src.rendering.advanced_plot_axes import primary_axis, secondary_y_axis
from src.rendering.artist_tags import tag_interaction_artist
from src.rendering.axis_breaks import axis_break_panel_axes
from src.rendering.extra_axes import extra_axis_binding_mode
from src.rendering.models import QAReport, RenderedPlot, RenderOptions
from src.rendering.overlay_coordinates import mapped_axis_value_anchor, secondary_y_conversion_scale

_VALID_COORDINATE_SPACES = frozenset({"axes_fraction", "data"})
_VALID_HORIZONTAL_ALIGNMENTS = frozenset({"left", "center", "right"})
_VALID_VERTICAL_ALIGNMENTS = frozenset({"bottom", "center", "top"})
_VALID_Y_AXIS_TARGETS = frozenset({"y_primary", "y_secondary"})
_VALID_ANNOTATION_STYLES = frozenset({"plain", "callout"})


class TextAnnotationPayloadDict(TypedDict):
    id: str
    enabled: bool
    text: str
    coordinate_space: str
    x: float
    y: float
    y_axis_target: str
    horizontal_alignment: str
    vertical_alignment: str
    display_style: str
    connector_enabled: bool
    target_x: float
    target_y: float
    target_y_axis_target: str


@dataclass(frozen=True)
class TextAnnotationOptions:
    id: str
    enabled: bool = True
    text: str = ""
    coordinate_space: str = "axes_fraction"
    x: float = 0.5
    y: float = 0.95
    y_axis_target: str = "y_primary"
    horizontal_alignment: str = "center"
    vertical_alignment: str = "top"
    display_style: str = "plain"
    connector_enabled: bool = False
    target_x: float = 0.5
    target_y: float = 0.5
    target_y_axis_target: str = "y_primary"


def _string(value: object, *, field_name: str, default: str) -> str:
    cleaned = str(value if value is not None else default).strip() or default
    if not cleaned:
        raise ValueError(f"`{field_name}` must not be blank.")
    return cleaned


def _finite_float(value: object, *, field_name: str, default: float) -> float:
    if value is None:
        numeric = default
    elif isinstance(value, int | float | str):
        numeric = float(value)
    else:
        raise ValueError(f"`{field_name}` must be numeric.")
    if not math.isfinite(numeric):
        raise ValueError(f"`{field_name}` must be a finite number.")
    return numeric


def _enum(
    value: object,
    *,
    field_name: str,
    default: str,
    allowed: frozenset[str],
) -> str:
    resolved = _string(value, field_name=field_name, default=default).lower()
    if resolved not in allowed:
        raise ValueError(f"`{field_name}` must be one of {', '.join(sorted(allowed))}.")
    return resolved


def _iter_annotation_maps(value: object) -> tuple[Mapping[str, object], ...]:
    if value is None:
        return ()
    if not isinstance(value, Iterable) or isinstance(value, (str, bytes, bytearray, Mapping)):
        raise ValueError("`text_annotations` must be a list of mappings.")
    items: list[Mapping[str, object]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise ValueError("`text_annotations` items must be mappings.")
        items.append(item)
    return tuple(items)


def normalize_text_annotations_payload(value: object) -> tuple[TextAnnotationPayloadDict, ...] | None:
    items = _iter_annotation_maps(value)
    if not items:
        return None
    normalized: list[TextAnnotationPayloadDict] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(items):
        annotation_id = _string(
            item.get("id"),
            field_name=f"text_annotations[{index}].id",
            default=f"text-annotation-{index + 1}",
        )
        if annotation_id in seen_ids:
            raise ValueError("`text_annotations` ids must be unique.")
        seen_ids.add(annotation_id)
        normalized.append(
            {
                "id": annotation_id,
                "enabled": bool(item.get("enabled", True)),
                "text": str(item.get("text", "")).strip(),
                "coordinate_space": _enum(
                    item.get("coordinate_space"),
                    field_name=f"text_annotations[{index}].coordinate_space",
                    default="axes_fraction",
                    allowed=_VALID_COORDINATE_SPACES,
                ),
                "x": _finite_float(
                    item.get("x"),
                    field_name=f"text_annotations[{index}].x",
                    default=0.5,
                ),
                "y": _finite_float(
                    item.get("y"),
                    field_name=f"text_annotations[{index}].y",
                    default=0.95,
                ),
                "y_axis_target": _enum(
                    item.get("y_axis_target"),
                    field_name=f"text_annotations[{index}].y_axis_target",
                    default="y_primary",
                    allowed=_VALID_Y_AXIS_TARGETS,
                ),
                "horizontal_alignment": _enum(
                    item.get("horizontal_alignment"),
                    field_name=f"text_annotations[{index}].horizontal_alignment",
                    default="center",
                    allowed=_VALID_HORIZONTAL_ALIGNMENTS,
                ),
                "vertical_alignment": _enum(
                    item.get("vertical_alignment"),
                    field_name=f"text_annotations[{index}].vertical_alignment",
                    default="top",
                    allowed=_VALID_VERTICAL_ALIGNMENTS,
                ),
                "display_style": _enum(
                    item.get("display_style"),
                    field_name=f"text_annotations[{index}].display_style",
                    default="plain",
                    allowed=_VALID_ANNOTATION_STYLES,
                ),
                "connector_enabled": bool(item.get("connector_enabled", False)),
                "target_x": _finite_float(
                    item.get("target_x"),
                    field_name=f"text_annotations[{index}].target_x",
                    default=0.5,
                ),
                "target_y": _finite_float(
                    item.get("target_y"),
                    field_name=f"text_annotations[{index}].target_y",
                    default=0.5,
                ),
                "target_y_axis_target": _enum(
                    item.get("target_y_axis_target"),
                    field_name=f"text_annotations[{index}].target_y_axis_target",
                    default="y_primary",
                    allowed=_VALID_Y_AXIS_TARGETS,
                ),
            }
        )
    return tuple(normalized)


def text_annotations_from_payload(value: object) -> tuple[TextAnnotationOptions, ...]:
    payload = normalize_text_annotations_payload(value)
    if payload is None:
        return ()
    return tuple(
        TextAnnotationOptions(
            id=item["id"],
            enabled=item["enabled"],
            text=item["text"],
            coordinate_space=item["coordinate_space"],
            x=item["x"],
            y=item["y"],
            y_axis_target=item["y_axis_target"],
            horizontal_alignment=item["horizontal_alignment"],
            vertical_alignment=item["vertical_alignment"],
            display_style=item["display_style"],
            connector_enabled=item["connector_enabled"],
            target_x=item["target_x"],
            target_y=item["target_y"],
            target_y_axis_target=item["target_y_axis_target"],
        )
        for item in payload
    )


def _y_axis_for_target(
    annotation: TextAnnotationOptions,
    *,
    rendered: RenderedPlot,
    target: str,
) -> Axes | None:
    if target == "y_secondary":
        return secondary_y_axis(rendered)
    return primary_axis(rendered)


def _validate_data_coordinate(
    *,
    label: str,
    x: float,
    y: float,
    options: RenderOptions,
) -> None:
    if options.xscale == "log" and x <= 0.0:
        raise ValueError(f"{label} on a log X axis requires a positive x value.")
    if options.yscale == "log" and y <= 0.0:
        raise ValueError(f"{label} on a log Y axis requires a positive y value.")


def _annotation_target_axis(
    annotation: TextAnnotationOptions,
    *,
    rendered: RenderedPlot,
) -> Axes | None:
    return _y_axis_for_target(annotation, rendered=rendered, target=annotation.y_axis_target)


def _annotation_bbox(annotation: TextAnnotationOptions) -> dict[str, object] | None:
    if annotation.display_style != "callout":
        return None
    return {
        "facecolor": "white",
        "alpha": 0.82,
        "linewidth": 0.0,
        "boxstyle": "round,pad=0.22",
    }


def apply_text_annotations(rendered: RenderedPlot, *, options: RenderOptions) -> RenderedPlot:
    annotations = tuple(
        annotation
        for annotation in text_annotations_from_payload(options.text_annotations)
        if annotation.enabled and annotation.text
    )
    primary = primary_axis(rendered)
    if primary is None or not annotations:
        return rendered

    typography = plot_style.current_typography()
    stroke = plot_style.current_stroke()
    palette = plot_style.get_categorical_palette(options.palette_preset, n_colors=max(1, len(annotations)))
    text_color = mpl.rcParams.get("text.color", "#111827")
    x_split_active = len(axis_break_panel_axes(rendered, axis_name="x")) > 1
    y_split_active = len(axis_break_panel_axes(rendered, axis_name="y")) > 1
    applied = False

    for index, annotation in enumerate(annotations):
        color = palette[index % len(palette)] if palette else text_color
        bbox = _annotation_bbox(annotation)
        text_axis = primary
        text_transform = primary.transAxes
        clip_on = False
        text_x = annotation.x
        text_y = annotation.y
        if annotation.coordinate_space == "data":
            target_axis = _annotation_target_axis(annotation, rendered=rendered)
            if target_axis is None:
                continue
            _validate_data_coordinate(
                label="Text annotation",
                x=annotation.x,
                y=annotation.y,
                options=options,
            )
            x_anchor = mapped_axis_value_anchor(rendered, axis_name="x", value=annotation.x)
            if x_anchor is None:
                continue
            text_x = x_anchor[1]
            text_axis = x_anchor[0] if x_split_active else target_axis
            text_transform = text_axis.transData
            if (
                annotation.y_axis_target == "y_secondary"
                and extra_axis_binding_mode(options.extra_y_axis) == "conversion"
            ):
                conversion_scale = secondary_y_conversion_scale(options)
                if conversion_scale is None:
                    continue
                if not x_split_active:
                    text_axis = primary
                    text_transform = primary.transData
                text_y = annotation.y / conversion_scale
            elif annotation.y_axis_target == "y_primary":
                y_anchor = mapped_axis_value_anchor(rendered, axis_name="y", value=annotation.y)
                if y_anchor is None:
                    continue
                y_axis, text_y = y_anchor
                if y_split_active or not x_split_active:
                    text_axis = y_axis
                    text_transform = y_axis.transData
            else:
                text_axis = target_axis
                text_transform = target_axis.transData
            clip_on = True

        if annotation.connector_enabled:
            connector_axis = _y_axis_for_target(
                annotation,
                rendered=rendered,
                target=annotation.target_y_axis_target,
            )
            if connector_axis is None:
                continue
            _validate_data_coordinate(
                label="Text annotation connector",
                x=annotation.target_x,
                y=annotation.target_y,
                options=options,
            )
            x_anchor = mapped_axis_value_anchor(rendered, axis_name="x", value=annotation.target_x)
            if x_anchor is None:
                continue
            connector_x = x_anchor[1]
            if x_split_active:
                connector_axis = x_anchor[0]
            connector_y = annotation.target_y
            connector_xycoords = connector_axis.transData
            if (
                annotation.target_y_axis_target == "y_secondary"
                and extra_axis_binding_mode(options.extra_y_axis) == "conversion"
            ):
                conversion_scale = secondary_y_conversion_scale(options)
                if conversion_scale is None:
                    continue
                connector_axis = primary
                connector_y = annotation.target_y / conversion_scale
                connector_xycoords = primary.transData
            elif annotation.target_y_axis_target == "y_primary":
                y_anchor = mapped_axis_value_anchor(rendered, axis_name="y", value=annotation.target_y)
                if y_anchor is None:
                    continue
                y_axis, connector_y = y_anchor
                if y_split_active or not x_split_active:
                    connector_axis = y_axis
                    connector_xycoords = y_axis.transData
            artist = text_axis.annotate(
                annotation.text,
                xy=(connector_x, connector_y),
                xycoords=connector_xycoords,
                xytext=(text_x, text_y),
                textcoords=text_transform,
                ha=annotation.horizontal_alignment,
                va=annotation.vertical_alignment,
                fontsize=typography.legend_font_size_pt,
                color=color,
                bbox=bbox,
                arrowprops={
                    "arrowstyle": "-",
                    "linewidth": max(0.8, stroke.line_width_pt * 0.75),
                    "color": color,
                    "alpha": min(0.9, stroke.line_alpha + 0.05),
                },
                annotation_clip=clip_on,
                zorder=4.0,
            )
            tag_interaction_artist(
                artist,
                payload_type="text_annotation",
                payload_id=annotation.id,
                kind="text_annotation",
                label=annotation.text,
                operations=("select", "quick_edit", "drag", "more"),
            )
            applied = True
            continue

        text_artist = text_axis.text(
            text_x,
            text_y,
            annotation.text,
            transform=text_transform,
            ha=annotation.horizontal_alignment,
            va=annotation.vertical_alignment,
            fontsize=typography.legend_font_size_pt,
            color=color,
            clip_on=clip_on,
            bbox=bbox,
            zorder=4.0,
        )
        tag_interaction_artist(
            text_artist,
            payload_type="text_annotation",
            payload_id=annotation.id,
            kind="text_annotation",
            label=annotation.text,
            operations=("select", "quick_edit", "drag", "more"),
        )
        applied = True

    if not applied:
        return rendered
    if rendered.qa_report is not None:
        qa_report = replace(
            rendered.qa_report,
            autofixes_applied=tuple(rendered.qa_report.autofixes_applied) + ("text_annotation_overlay",),
        )
    else:
        qa_report = QAReport(score=1.0, grade="solid", autofixes_applied=("text_annotation_overlay",))
    return replace(rendered, qa_report=qa_report)


__all__ = [
    "TextAnnotationOptions",
    "TextAnnotationPayloadDict",
    "apply_text_annotations",
    "normalize_text_annotations_payload",
    "text_annotations_from_payload",
]
