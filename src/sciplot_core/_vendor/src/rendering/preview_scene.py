from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from src.rendering.source_table_preview import source_table_preview

NATIVE_PREVIEW_TEMPLATES = {
    "area_curve",
    "curve",
    "function_curve",
    "point_line",
    "scatter",
    "step_line",
}
DEFAULT_NATIVE_SCENE_SAMPLE_BUDGET = 2_000


def _numeric(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if np.isfinite(numeric) else None


def _payload_float(payload: dict[str, Any], key: str, default: float) -> float:
    numeric = _numeric(payload.get(key))
    return numeric if numeric is not None else default


def _range(values: list[float]) -> list[float]:
    if not values:
        return [0.0, 1.0]
    low = float(min(values))
    high = float(max(values))
    return [low, high if high != low else low + 1.0]


def _enabled_axis_conflict(options: dict[str, Any]) -> bool:
    for key in ("extra_x_axis", "extra_y_axis"):
        payload = options.get(key)
        if isinstance(payload, dict) and payload.get("enabled"):
            return True
    for key in ("x_axis_breaks", "y_axis_breaks"):
        for item in options.get(key) or []:
            if isinstance(item, dict) and item.get("enabled", True):
                return True
    return False


def _pixel_points(
    samples: list[dict[str, float]],
    *,
    plot_area: dict[str, float],
    x_range: list[float],
    y_range: list[float],
) -> list[list[float]]:
    x_low, x_high = x_range
    y_low, y_high = y_range
    x_span = x_high - x_low or 1.0
    y_span = y_high - y_low or 1.0
    left = plot_area["x"]
    top = plot_area["y"]
    width = plot_area["width"]
    height = plot_area["height"]
    points: list[list[float]] = []
    for sample in samples:
        x_pixel = left + ((sample["x"] - x_low) / x_span) * width
        y_pixel = top + height - ((sample["y"] - y_low) / y_span) * height
        points.append([round(float(x_pixel), 3), round(float(y_pixel), 3)])
    return points


def _bbox(points: list[list[float]]) -> dict[str, float]:
    if not points:
        return {"x": 0.0, "y": 0.0, "width": 0.0, "height": 0.0}
    x_values = [point[0] for point in points]
    y_values = [point[1] for point in points]
    left = min(x_values)
    top = min(y_values)
    return {
        "x": left,
        "y": top,
        "width": max(x_values) - left,
        "height": max(y_values) - top,
    }


def _padded_bbox(point: list[float], width: float, height: float) -> dict[str, float]:
    return {
        "x": round(point[0] - width / 2, 3),
        "y": round(point[1] - height / 2, 3),
        "width": round(width, 3),
        "height": round(height, 3),
    }


def _series_object_kind(template: str) -> str:
    if template == "scatter":
        return "series_points"
    if template == "area_curve":
        return "series_area"
    if template == "step_line":
        return "series_step_line"
    return "series_line"


def _fallback_diagnostic(reason: str) -> dict[str, Any]:
    return {
        "status_code": "native_preview_fallback",
        "fallback_reason": reason,
        "message": "Backend bitmap/PDF preview is required.",
    }


def _scene_object(
    *,
    object_id: str,
    kind: str,
    label: str,
    axis_id: str | None,
    bbox_pixels: dict[str, float],
    points: list[list[float]],
    payload_type: str,
    payload_id: str,
    operations: list[str],
    visible: bool = True,
    locked: bool = False,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": object_id,
        "kind": kind,
        "label": label,
        "bbox_pixels": bbox_pixels,
        "points": points,
        "payload_ref": {"type": payload_type, "id": payload_id},
        "operations": operations,
        "visible": visible,
        "locked": locked,
    }
    if axis_id is not None:
        payload["axis_id"] = axis_id
    return payload


def _overlay_payload(scene_object: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": scene_object["id"],
        "kind": scene_object["kind"],
        "payload_ref": scene_object["payload_ref"],
        "bbox_pixels": scene_object["bbox_pixels"],
        "points": scene_object["points"],
        "visible": scene_object["visible"],
        "locked": scene_object["locked"],
        "payload": payload,
    }


def _point_for_data(
    x_value: float,
    y_value: float,
    *,
    plot_area: dict[str, float],
    x_range: list[float],
    y_range: list[float],
) -> list[float]:
    return _pixel_points(
        [{"x": x_value, "y": y_value}],
        plot_area=plot_area,
        x_range=x_range,
        y_range=y_range,
    )[0]


def _point_for_annotation(
    payload: dict[str, Any],
    *,
    plot_area: dict[str, float],
    x_range: list[float],
    y_range: list[float],
) -> list[float]:
    x_value = _payload_float(payload, "x", 0.5)
    y_value = _payload_float(payload, "y", 0.5)
    if payload.get("coordinate_space") == "data":
        return _point_for_data(x_value, y_value, plot_area=plot_area, x_range=x_range, y_range=y_range)
    return [
        round(plot_area["x"] + x_value * plot_area["width"], 3),
        round(plot_area["y"] + (1.0 - y_value) * plot_area["height"], 3),
    ]


def _add_axis_and_legend_objects(
    *,
    objects: list[dict[str, Any]],
    plot_area: dict[str, float],
    options: dict[str, Any],
    series_label: str,
) -> None:
    x_axis_bbox = {
        "x": plot_area["x"],
        "y": plot_area["y"] + plot_area["height"] - 4,
        "width": plot_area["width"],
        "height": 8.0,
    }
    y_axis_bbox = {"x": plot_area["x"] - 4, "y": plot_area["y"], "width": 8.0, "height": plot_area["height"]}
    objects.extend(
        [
            _scene_object(
                object_id="plot:axis:x",
                kind="x_axis",
                label=str(options.get("x_label_override") or "X Axis"),
                axis_id="axis:primary",
                bbox_pixels=x_axis_bbox,
                points=[
                    [round(plot_area["x"], 3), round(plot_area["y"] + plot_area["height"], 3)],
                    [round(plot_area["x"] + plot_area["width"], 3), round(plot_area["y"] + plot_area["height"], 3)],
                ],
                payload_type="axis",
                payload_id="x",
                operations=["select", "quick_edit", "rename", "lock", "copy_settings"],
            ),
            _scene_object(
                object_id="plot:axis:y",
                kind="y_axis",
                label=str(options.get("y_label_override") or "Y Axis"),
                axis_id="axis:primary",
                bbox_pixels=y_axis_bbox,
                points=[
                    [round(plot_area["x"], 3), round(plot_area["y"], 3)],
                    [round(plot_area["x"], 3), round(plot_area["y"] + plot_area["height"], 3)],
                ],
                payload_type="axis",
                payload_id="y",
                operations=["select", "quick_edit", "rename", "lock", "copy_settings"],
            ),
            _scene_object(
                object_id="plot:legend:main",
                kind="legend",
                label="Legend",
                axis_id=None,
                bbox_pixels={
                    "x": round(plot_area["x"] + plot_area["width"] - 136, 3),
                    "y": round(plot_area["y"] + 16, 3),
                    "width": 120.0,
                    "height": 36.0,
                },
                points=[],
                payload_type="legend",
                payload_id="main",
                operations=["select", "quick_edit", "reorder", "rename", "lock", "visibility", "copy_settings"],
            ),
        ]
    )
    objects[-1]["entries"] = [{"id": "plot:series:0", "label": series_label}]


def _add_reference_guide_objects(
    *,
    objects: list[dict[str, Any]],
    overlays: list[dict[str, Any]],
    guides: list[dict[str, Any]],
    plot_area: dict[str, float],
    x_range: list[float],
    y_range: list[float],
) -> None:
    for guide in guides:
        guide_id = str(guide.get("id") or "guide")
        axis_target = str(guide.get("axis_target") or "y_primary")
        kind = str(guide.get("kind") or "line")
        if kind == "line":
            value = float(guide.get("value") or 0.0)
            if axis_target == "x":
                point = _point_for_data(value, y_range[0], plot_area=plot_area, x_range=x_range, y_range=y_range)
                points = [[point[0], plot_area["y"]], [point[0], plot_area["y"] + plot_area["height"]]]
            else:
                point = _point_for_data(x_range[0], value, plot_area=plot_area, x_range=x_range, y_range=y_range)
                points = [[plot_area["x"], point[1]], [plot_area["x"] + plot_area["width"], point[1]]]
        else:
            start = _payload_float(guide, "start", 0.0)
            end = _payload_float(guide, "end", 1.0)
            if axis_target == "x":
                first = _point_for_data(start, y_range[0], plot_area=plot_area, x_range=x_range, y_range=y_range)
                second = _point_for_data(end, y_range[1], plot_area=plot_area, x_range=x_range, y_range=y_range)
                points = [[first[0], plot_area["y"]], [second[0], plot_area["y"] + plot_area["height"]]]
            else:
                first = _point_for_data(x_range[0], start, plot_area=plot_area, x_range=x_range, y_range=y_range)
                second = _point_for_data(x_range[1], end, plot_area=plot_area, x_range=x_range, y_range=y_range)
                points = [[plot_area["x"], second[1]], [plot_area["x"] + plot_area["width"], first[1]]]
        scene_object = _scene_object(
            object_id=f"plot:guide:{guide_id}",
            kind=f"reference_guide_{'region' if kind != 'line' else 'line'}",
            label=str(guide.get("label") or "Reference Guide"),
            axis_id="axis:primary",
            bbox_pixels=_bbox(points),
            points=points,
            payload_type="reference_guide",
            payload_id=guide_id,
            operations=["select", "quick_edit", "drag", "visibility", "rename", "delete", "lock", "copy_settings"],
            visible=bool(guide.get("enabled", True)),
        )
        objects.append(scene_object)
        overlays.append(_overlay_payload(scene_object, guide))


def _add_annotation_objects(
    *,
    objects: list[dict[str, Any]],
    overlays: list[dict[str, Any]],
    text_annotations: list[dict[str, Any]],
    shape_annotations: list[dict[str, Any]],
    plot_area: dict[str, float],
    x_range: list[float],
    y_range: list[float],
) -> None:
    for annotation in text_annotations:
        annotation_id = str(annotation.get("id") or "text")
        point = _point_for_annotation(annotation, plot_area=plot_area, x_range=x_range, y_range=y_range)
        points = [point]
        if annotation.get("connector_enabled"):
            target_payload = dict(annotation)
            target_payload["x"] = target_payload.get("target_x", annotation.get("x", 0.5))
            target_payload["y"] = target_payload.get("target_y", annotation.get("y", 0.5))
            points.append(_point_for_annotation(target_payload, plot_area=plot_area, x_range=x_range, y_range=y_range))
        scene_object = _scene_object(
            object_id=f"plot:text_annotation:{annotation_id}",
            kind="text_annotation",
            label=str(annotation.get("text") or "Text Annotation"),
            axis_id="axis:primary",
            bbox_pixels=_padded_bbox(point, 96, 28),
            points=points,
            payload_type="text_annotation",
            payload_id=annotation_id,
            operations=["select", "quick_edit", "drag", "visibility", "rename", "delete", "lock", "copy_settings"],
            visible=bool(annotation.get("enabled", True)),
        )
        objects.append(scene_object)
        overlays.append(_overlay_payload(scene_object, annotation))

    for annotation in shape_annotations:
        annotation_id = str(annotation.get("id") or "shape")
        x_start = _payload_float(annotation, "x_start", 0.0)
        x_end = _payload_float(annotation, "x_end", 1.0)
        y_start = _payload_float(annotation, "y_start", 0.0)
        y_end = _payload_float(annotation, "y_end", 1.0)
        points = [
            _point_for_data(x_start, y_start, plot_area=plot_area, x_range=x_range, y_range=y_range),
            _point_for_data(x_end, y_start, plot_area=plot_area, x_range=x_range, y_range=y_range),
            _point_for_data(x_end, y_end, plot_area=plot_area, x_range=x_range, y_range=y_range),
            _point_for_data(x_start, y_end, plot_area=plot_area, x_range=x_range, y_range=y_range),
        ]
        shape_kind = str(annotation.get("kind") or "shape")
        scene_object = _scene_object(
            object_id=f"plot:shape_annotation:{annotation_id}",
            kind=f"shape_annotation_{shape_kind}",
            label=str(annotation.get("label") or shape_kind.title()),
            axis_id="axis:primary",
            bbox_pixels=_bbox(points),
            points=points,
            payload_type="shape_annotation",
            payload_id=annotation_id,
            operations=[
                "select",
                "quick_edit",
                "drag",
                "resize",
                "visibility",
                "rename",
                "delete",
                "lock",
                "copy_settings",
            ],
            visible=bool(annotation.get("enabled", True)),
        )
        objects.append(scene_object)
        overlays.append(_overlay_payload(scene_object, annotation))


def _add_function_and_fit_objects(
    *,
    objects: list[dict[str, Any]],
    overlays: list[dict[str, Any]],
    analytical_layers: list[dict[str, Any]],
    fit_options: dict[str, Any],
    plot_area: dict[str, float],
    x_range: list[float],
    y_range: list[float],
    series_points: list[list[float]],
) -> None:
    midpoint = y_range[0] + (y_range[1] - y_range[0]) / 2
    for layer in analytical_layers:
        layer_id = str(layer.get("id") or "function")
        x_start = _payload_float(layer, "x_start", x_range[0])
        x_end = _payload_float(layer, "x_end", x_range[1])
        points = [
            _point_for_data(x_start, midpoint, plot_area=plot_area, x_range=x_range, y_range=y_range),
            _point_for_data(x_end, midpoint, plot_area=plot_area, x_range=x_range, y_range=y_range),
        ]
        scene_object = _scene_object(
            object_id=f"plot:function:{layer_id}",
            kind="function_layer",
            label=str(layer.get("label") or layer.get("expression") or "Function"),
            axis_id="axis:primary",
            bbox_pixels=_bbox(points),
            points=points,
            payload_type="analytical_layer",
            payload_id=layer_id,
            operations=["select", "quick_edit", "drag", "visibility", "rename", "delete", "lock", "copy_settings"],
            visible=bool(layer.get("enabled", True)),
        )
        objects.append(scene_object)
        overlays.append(_overlay_payload(scene_object, layer))

    if fit_options.get("enabled"):
        model_id = str(fit_options.get("model_id") or "fit")
        scene_object = _scene_object(
            object_id=f"plot:fit_overlay:{model_id}",
            kind="fit_overlay",
            label=f"{model_id.replace('_', ' ').title()} Fit",
            axis_id="axis:primary",
            bbox_pixels=_bbox(series_points),
            points=series_points,
            payload_type="fit_overlay",
            payload_id=model_id,
            operations=["select", "quick_edit", "visibility", "rename", "delete", "lock", "copy_settings"],
            visible=True,
        )
        objects.append(scene_object)
        overlays.append(_overlay_payload(scene_object, fit_options))


def build_preview_scene(
    *,
    input_path: str | Path,
    sheet: str | int,
    template: str,
    options: dict[str, Any] | None = None,
    fit_options: dict[str, Any] | None = None,
    preview_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    path = Path(input_path)
    config_payload = preview_config or {}
    sample_budget = max(1, int(config_payload.get("native_scene_sample_budget") or DEFAULT_NATIVE_SCENE_SAMPLE_BUDGET))
    preview = source_table_preview(path, sheet=sheet, offset=0, limit=max(sample_budget + 10, 20))
    width = float(config_payload.get("pixel_width") or 800)
    height = float(config_payload.get("pixel_height") or 600)
    scale = float(config_payload.get("scale") or 1.0)
    rows = [list(row) for row in preview.rows]
    samples: list[dict[str, float]] = []
    for row in rows:
        if len(row) < 2:
            continue
        x_value = _numeric(row[0])
        y_value = _numeric(row[1])
        if x_value is None or y_value is None:
            continue
        samples.append({"x": x_value, "y": y_value})
    options_payload = options or {}
    fallback_reason: str | None = None
    if template not in NATIVE_PREVIEW_TEMPLATES:
        fallback_reason = "unsupported_template"
    elif not samples:
        fallback_reason = "missing_samples"
    elif len(samples) > sample_budget:
        fallback_reason = "sample_budget_exceeded"
    elif _enabled_axis_conflict(options_payload):
        fallback_reason = "advanced_axis_conflict"
    x_values = [sample["x"] for sample in samples]
    y_values = [sample["y"] for sample in samples]
    x_range = _range(x_values)
    y_range = _range(y_values)
    if not np.isfinite(x_range).all() or not np.isfinite(y_range).all():
        fallback_reason = "invalid_axes"
    native_supported = fallback_reason is None
    scene_samples = samples[:sample_budget]
    plot_area = {"x": width * 0.12, "y": height * 0.10, "width": width * 0.76, "height": height * 0.78}
    points = _pixel_points(scene_samples, plot_area=plot_area, x_range=x_range, y_range=y_range)
    series_object_kind = _series_object_kind(template)
    series_label = str(preview.column_headers[1] if len(preview.column_headers) > 1 else "Series")
    objects: list[dict[str, Any]] = []
    overlays: list[dict[str, Any]] = []
    if native_supported and samples:
        _add_axis_and_legend_objects(
            objects=objects,
            plot_area=plot_area,
            options=options_payload,
            series_label=series_label,
        )
        objects.append(
            _scene_object(
                object_id="plot:series:0",
                kind=series_object_kind,
                label=series_label,
                axis_id="axis:primary",
                bbox_pixels=_bbox(points),
                points=points,
                payload_type="series",
                payload_id="plot:series:0",
                operations=["select", "quick_edit", "drag_offset", "copy_settings", "visibility", "lock", "rename"],
            )
        )
        _add_reference_guide_objects(
            objects=objects,
            overlays=overlays,
            guides=list(options_payload.get("reference_guides") or []),
            plot_area=plot_area,
            x_range=x_range,
            y_range=y_range,
        )
        _add_annotation_objects(
            objects=objects,
            overlays=overlays,
            text_annotations=list(options_payload.get("text_annotations") or []),
            shape_annotations=list(options_payload.get("shape_annotations") or []),
            plot_area=plot_area,
            x_range=x_range,
            y_range=y_range,
        )
        _add_function_and_fit_objects(
            objects=objects,
            overlays=overlays,
            analytical_layers=list(options_payload.get("analytical_layers") or []),
            fit_options=fit_options or {},
            plot_area=plot_area,
            x_range=x_range,
            y_range=y_range,
            series_points=points,
        )
    return {
        "scene_id": f"preview-scene:{path.name}:{sheet}:{template}",
        "template": template,
        "sheet": sheet,
        "native_supported": native_supported,
        "fallback_reason": fallback_reason,
        "graph_revision": 1,
        "figure": {"pixel_width": int(width), "pixel_height": int(height), "scale": scale},
        "plot_area": plot_area,
        "axes": [
            {
                "id": "axis:primary",
                "role": "primary",
                "bbox_pixels": plot_area,
                "x_scale": str(options_payload.get("xscale") or "linear"),
                "y_scale": str(options_payload.get("yscale") or "linear"),
                "x_range": x_range,
                "y_range": y_range,
                "x_reversed": False,
                "y_reversed": False,
                "column_refs": {"x": "col-0", "y": "col-1"},
            }
        ],
        "series": [
            {
                "id": "plot:series:0",
                "label": series_label,
                "kind": template,
                "column_refs": {"x": "col-0", "y": "col-1"},
                "samples": scene_samples,
                "style_tokens": {
                    "style_preset": options_payload.get("style_preset") or "nature",
                    "palette_preset": options_payload.get("palette_preset"),
                    "visual_theme_id": options_payload.get("visual_theme_id"),
                },
                "hit_test": {"kind": "points" if template == "scatter" else "polyline", "tolerance": 12},
            }
        ]
        if samples
        else [],
        "objects": objects,
        "overlays": overlays,
        "budgets": {
            "native_scene_samples": sample_budget,
            "source_points": len(samples),
            "render_timeout_ms": 10_000,
        },
        "diagnostics": []
        if native_supported
        else [_fallback_diagnostic(str(fallback_reason or "unknown"))],
    }


__all__ = ["DEFAULT_NATIVE_SCENE_SAMPLE_BUDGET", "NATIVE_PREVIEW_TEMPLATES", "build_preview_scene"]
