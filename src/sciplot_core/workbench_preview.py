from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from sciplot_core._bootstrap import ensure_legacy_core
from sciplot_core.render import json_safe
from sciplot_core.semantic import classify_source, prepare_semantic_source
from sciplot_core.workbench_contract import normalize_render_options

ensure_legacy_core()

from src.plot_contract import load_plot_contract  # noqa: E402
from src.rendering.render_service import build_rendered_plots, close_rendered_plots  # noqa: E402


@dataclass(frozen=True)
class WorkbenchRenderJob:
    request: dict[str, Any]
    request_path: Path
    source: Path
    template: str
    render_options: dict[str, Any]
    semantic: dict[str, Any]
    route: str


def _load_request(request_path: Path) -> dict[str, Any]:
    payload = json.loads(request_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Plot request must be a JSON object.")
    return payload


def _resolve_request_path(value: object, *, base_dir: Path, field: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Plot request must define a non-empty `{field}` path.")
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()


def _read_json_if_exists(path: Path) -> dict[str, Any] | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _run_manifest_for_request(request_path: Path, request: dict[str, Any]) -> dict[str, Any] | None:
    project_manifest = _read_json_if_exists(request_path.parent / "intake_manifest.json") or {}
    last_run = project_manifest.get("last_run") if isinstance(project_manifest.get("last_run"), dict) else {}
    output_value = last_run.get("output") or request.get("output")
    if not isinstance(output_value, str) or not output_value.strip():
        return None
    manifest_path = Path(output_value).expanduser()
    if not manifest_path.is_absolute():
        manifest_path = request_path.parent / manifest_path
    manifest_path = manifest_path / "manifest.json"
    return _read_json_if_exists(manifest_path)


def _processed_source_from_manifest(manifest: dict[str, Any] | None) -> Path | None:
    if not isinstance(manifest, dict):
        return None
    result = manifest.get("result") if isinstance(manifest.get("result"), dict) else {}
    for key in ("processed_source", "input"):
        value = result.get(key)
        if isinstance(value, str) and value.strip():
            path = Path(value).expanduser()
            if path.exists():
                return path.resolve()
    return None


def resolve_workbench_render_job(
    request_path: str | Path,
    *,
    request_override: dict[str, Any] | None = None,
) -> WorkbenchRenderJob:
    resolved_request_path = Path(request_path).expanduser().resolve()
    base_dir = resolved_request_path.parent
    request = dict(request_override) if request_override is not None else _load_request(resolved_request_path)
    input_path = _resolve_request_path(request.get("input"), base_dir=base_dir, field="input")
    requested_rule_id = request.get("rule_id") if isinstance(request.get("rule_id"), str) else None
    semantic = classify_source(input_path, requested_rule_id=requested_rule_id)
    use_auto = request.get("recipe") == "auto" or (not request.get("recipe") and not request.get("template"))
    run_manifest = _run_manifest_for_request(resolved_request_path, request)

    if use_auto:
        template = str(request.get("template") or semantic["template"])
        render_options = dict(semantic.get("render_options") or {})
        if isinstance(request.get("render_options"), dict):
            render_options.update(request["render_options"])
        render_options = normalize_render_options(
            render_options,
            template=template,
        )
        source = _processed_source_from_manifest(run_manifest)
        if source is None:
            cache_dir = base_dir / "workbench_cache"
            prepared = prepare_semantic_source(
                input_path,
                output_dir=cache_dir,
                semantic=semantic,
                curation_path=None,
                series_order=request.get("series_order"),
                column_confirmations=request.get("column_confirmations"),
                replicate_mode=request.get("replicate_mode"),
            )
            source = Path(str(prepared["source"])).expanduser().resolve()
        return WorkbenchRenderJob(
            request=request,
            request_path=resolved_request_path,
            source=source,
            template=template,
            render_options=render_options,
            semantic=semantic,
            route="auto",
        )

    if request.get("recipe"):
        raise ValueError("Workbench preview currently supports auto and direct render requests.")

    template = request.get("template")
    if not isinstance(template, str) or not template.strip():
        raise ValueError("Plot requests without `recipe` must define a non-empty `template`.")
    render_options = request.get("render_options") if isinstance(request.get("render_options"), dict) else {}
    return WorkbenchRenderJob(
        request=request,
        request_path=resolved_request_path,
        source=input_path,
        template=template,
        render_options=normalize_render_options(
            render_options,
            template=template,
        ),
        semantic=semantic,
        route="render",
    )


def build_workbench_rendered_plots(
    request_path: str | Path,
    *,
    request_override: dict[str, Any] | None = None,
):
    job = resolve_workbench_render_job(request_path, request_override=request_override)
    rendered = build_rendered_plots(job.template, job.source, 0, **job.render_options)
    return job, rendered


def _clean_float(value: object) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    return numeric


def _line_points(line: Any) -> list[dict[str, float]]:
    x_data = np.asarray(line.get_xdata(orig=False), dtype=float)
    y_data = np.asarray(line.get_ydata(orig=False), dtype=float)
    points: list[dict[str, float]] = []
    for x_value, y_value in zip(x_data, y_data, strict=False):
        x = _clean_float(x_value)
        y = _clean_float(y_value)
        if x is None or y is None:
            continue
        points.append({"x": x, "y": y})
    return points


def _collection_points(collection: Any) -> list[dict[str, float]]:
    offsets = getattr(collection, "get_offsets", lambda: [])()
    points: list[dict[str, float]] = []
    for pair in np.asarray(offsets, dtype=float):
        if len(pair) < 2:
            continue
        x = _clean_float(pair[0])
        y = _clean_float(pair[1])
        if x is None or y is None:
            continue
        points.append({"x": x, "y": y})
    return points


def _series_color(artist: Any) -> str | None:
    color = None
    if hasattr(artist, "get_color"):
        color = artist.get_color()
    elif hasattr(artist, "get_facecolors"):
        colors = artist.get_facecolors()
        if len(colors):
            color = colors[0]
    if color is None:
        return None
    try:
        from matplotlib.colors import to_hex

        return str(to_hex(color))
    except Exception:
        return str(color)


def chart_spec_from_rendered(job: WorkbenchRenderJob, rendered: list[Any]) -> dict[str, Any]:
    contract = load_plot_contract()
    template_spec = contract.templates.get(job.template)
    figure = rendered[0].figure if rendered else None
    axes = figure.axes if figure is not None else []
    primary_ax = axes[0] if axes else None
    rows: list[dict[str, Any]] = []
    series: list[dict[str, Any]] = []
    x_limits: tuple[float | None, float | None] = (None, None)
    y_limits: tuple[float | None, float | None] = (None, None)

    if primary_ax is not None:
        raw_x_limits = primary_ax.get_xlim()
        raw_y_limits = primary_ax.get_ylim()
        x_limits = (_clean_float(raw_x_limits[0]), _clean_float(raw_x_limits[1]))
        y_limits = (_clean_float(raw_y_limits[0]), _clean_float(raw_y_limits[1]))
        for index, line in enumerate(primary_ax.lines):
            label = str(line.get_label() or f"series_{index + 1}")
            if not label or label.startswith("_"):
                continue
            series_id = f"s{len(series) + 1}"
            points = _line_points(line)
            series.append(
                {
                    "id": series_id,
                    "label": label,
                    "color": _series_color(line),
                    "kind": "line",
                    "visible": bool(line.get_visible()),
                    "points": len(points),
                }
            )
            rows.extend({"series": label, "seriesId": series_id, **point} for point in points)
        for index, collection in enumerate(primary_ax.collections):
            points = _collection_points(collection)
            if not points:
                continue
            label = str(collection.get_label() or f"points_{index + 1}")
            if not label or label.startswith("_"):
                label = f"points_{index + 1}"
            series_id = f"s{len(series) + 1}"
            series.append(
                {
                    "id": series_id,
                    "label": label,
                    "color": _series_color(collection),
                    "kind": "scatter",
                    "visible": bool(collection.get_visible()),
                    "points": len(points),
                }
            )
            rows.extend({"series": label, "seriesId": series_id, **point} for point in points)

    return {
        "kind": "sciplot_interactive_chart_spec",
        "chartType": "line" if job.template in {"curve", "point_line", "stacked_curve"} else job.template,
        "route": job.route,
        "template": job.template,
        "meta": {
            "title": primary_ax.get_title() if primary_ax is not None else "",
            "description": job.semantic.get("reason") or "",
            "footer": f"Rendered from {job.source.name}",
        },
        "xKey": "x",
        "yKey": "y",
        "seriesKey": "series",
        "xAxisLabel": primary_ax.get_xlabel() if primary_ax is not None else "",
        "yAxisLabel": primary_ax.get_ylabel() if primary_ax is not None else "",
        "axes": {
            "x": {
                "label": primary_ax.get_xlabel() if primary_ax is not None else "",
                "scale": primary_ax.get_xscale() if primary_ax is not None else "linear",
                "limits": list(x_limits),
                "reversed": bool(
                    x_limits[0] is not None and x_limits[1] is not None and x_limits[0] > x_limits[1]
                ),
            },
            "y": {
                "label": primary_ax.get_ylabel() if primary_ax is not None else "",
                "scale": primary_ax.get_yscale() if primary_ax is not None else "linear",
                "limits": list(y_limits),
                "reversed": bool(
                    y_limits[0] is not None and y_limits[1] is not None and y_limits[0] > y_limits[1]
                ),
            },
        },
        "summary": {
            "series_count": len(series),
            "point_count": len(rows),
            "x_limits": list(x_limits),
            "y_limits": list(y_limits),
        },
        "series": series,
        "data": rows,
        "contract": {
            "template": job.template,
            "editable_options": list(template_spec.editable_options) if template_spec is not None else [],
            "render_options": json_safe(job.render_options),
        },
    }


def build_chart_spec(
    request_path: str | Path,
    *,
    request_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    job, rendered = build_workbench_rendered_plots(request_path, request_override=request_override)
    try:
        return chart_spec_from_rendered(job, rendered)
    finally:
        close_rendered_plots(rendered)


__all__ = [
    "WorkbenchRenderJob",
    "build_chart_spec",
    "build_workbench_rendered_plots",
    "chart_spec_from_rendered",
    "resolve_workbench_render_job",
]
