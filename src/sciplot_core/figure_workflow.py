from __future__ import annotations

import csv
import json
import math
import os
import shutil
import subprocess
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import fitz
import pandas as pd

from sciplot_core._utils import existing_file_sha256, json_safe
from sciplot_core.delivery import build_minimal_user_delivery
from sciplot_core.figure_profiles import (
    FigureProfile,
    figure_profile_render_options,
    get_figure_profile,
)
from sciplot_core.policy import DEFAULT_EXPORT_FORMATS_POLICY
from sciplot_core.qa import run_qa
from sciplot_core.render import render_to_dir


PLOT_READY_REQUEST_KIND = "sciplot_plot_ready_figure_request"
SHARED_SCALAR_STRIP_SPEC_KIND = "sciplot_shared_scalar_strip_spec"
SUPPORTED_FIGURE_EXPORTS = ("pdf", "tiff_300")


def _read_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Figure request must be a JSON object: {path}")
    return payload


def _resolve_path(value: object, *, base_dir: Path, field: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Figure request must define a non-empty `{field}` path.")
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    resolved = path.resolve()
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    return resolved


def _plain_filename(value: object, *, fallback: str) -> str:
    name = str(value or fallback).strip()
    if not name or Path(name).name != name:
        raise ValueError(f"Figure id must be a plain filename stem: {value!r}")
    if Path(name).suffix:
        raise ValueError(f"Figure id must not include a suffix: {name!r}")
    return name


def _normalize_exports(value: object) -> tuple[str, ...]:
    candidates = value if isinstance(value, list | tuple) else list(DEFAULT_EXPORT_FORMATS_POLICY)
    normalized = tuple(str(item).strip().casefold() for item in candidates if str(item).strip())
    if set(normalized) != set(SUPPORTED_FIGURE_EXPORTS) or len(normalized) != 2:
        required = ", ".join(SUPPORTED_FIGURE_EXPORTS)
        raise ValueError(
            "Plot-ready figure packages require the canonical editable handoff pair: "
            f"{required}."
        )
    return SUPPORTED_FIGURE_EXPORTS


def _archive_existing_documents(output_dir: Path) -> Path | None:
    project_dir = output_dir / "project"
    documents = sorted(project_dir.glob("*.vsz")) if project_dir.exists() else []
    if not documents:
        return None
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    archive_dir = output_dir / "archive" / timestamp / "project"
    archive_dir.mkdir(parents=True, exist_ok=True)
    for document in documents:
        shutil.copy2(document, archive_dir / document.name)
    return archive_dir


def _prepare_managed_output(output_dir: Path) -> Path | None:
    output_dir.mkdir(parents=True, exist_ok=True)
    archive = _archive_existing_documents(output_dir)
    for name in ("figures", "project", "specs", "plot_data", ".sciplot_work", "delivery"):
        path = output_dir / name
        if path.exists():
            shutil.rmtree(path)
        path.mkdir(parents=True, exist_ok=True)
    for name in ("manifest.json", "qa_report.json", "request_snapshot.json"):
        path = output_dir / name
        if path.exists():
            path.unlink()
    return archive


def _copy_export(source: Path, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return destination


def _canonical_figure_path(figures_dir: Path, figure_id: str, fmt: str) -> Path:
    if fmt == "pdf":
        return figures_dir / f"{figure_id}.pdf"
    return figures_dir / f"{figure_id}_300dpi.tiff"


def _curve_figure(
    *,
    item: dict[str, Any],
    profile: FigureProfile,
    request_dir: Path,
    output_dir: Path,
    exports: tuple[str, ...],
) -> dict[str, Any]:
    figure_id = _plain_filename(item.get("id"), fallback=profile.profile_id)
    source = _resolve_path(item.get("data"), base_dir=request_dir, field=f"figures[{figure_id}].data")
    if source.suffix.casefold() != ".csv":
        raise ValueError(
            f"Curve profile `{profile.profile_id}` requires an already plot-ready CSV: {source}"
        )
    overrides = item.get("options") if isinstance(item.get("options"), dict) else {}
    options = figure_profile_render_options(profile.profile_id, overrides=overrides)
    work_dir = output_dir / ".sciplot_work" / figure_id
    result = render_to_dir(
        source,
        template=str(profile.template),
        output_dir=work_dir,
        options=options,
        export_formats=exports,
    )
    layout_issues = [
        issue
        for report in result.get("qa_reports", [])
        if isinstance(report, dict)
        for issue in report.get("issues", [])
        if isinstance(issue, dict)
    ]
    if layout_issues:
        raise RuntimeError(f"Curve profile `{profile.profile_id}` failed layout QA: {layout_issues}")

    copied_exports: dict[str, Path] = {}
    for record in result.get("exports", []):
        if not isinstance(record, dict):
            continue
        fmt = str(record.get("format") or "")
        source_export = Path(str(record.get("path") or "")).expanduser()
        if fmt in exports and source_export.is_file():
            copied_exports[fmt] = _copy_export(
                source_export,
                _canonical_figure_path(output_dir / "figures", figure_id, fmt),
            )
    missing = [fmt for fmt in exports if fmt not in copied_exports]
    if missing:
        raise RuntimeError(f"Curve `{figure_id}` did not export: {', '.join(missing)}")

    documents = [
        Path(str(value)).expanduser()
        for value in result.get("veusz_documents", [])
        if Path(str(value)).expanduser().is_file()
    ]
    specs = [
        Path(str(value)).expanduser()
        for value in result.get("veusz_specs", [])
        if Path(str(value)).expanduser().is_file()
    ]
    if len(documents) != 1 or len(specs) != 1:
        raise RuntimeError(f"Curve `{figure_id}` must produce one VSZ and one Veusz spec.")
    document = _copy_export(documents[0], output_dir / "project" / f"{figure_id}.vsz")
    spec = _copy_export(specs[0], output_dir / "specs" / f"{figure_id}.json")
    plot_data = _copy_export(source, output_dir / "plot_data" / f"{figure_id}_plot_data.csv")
    return {
        "id": figure_id,
        "profile_id": profile.profile_id,
        "figure_kind": profile.figure_kind,
        "source_data": str(source),
        "plot_data": str(plot_data),
        "document": str(document),
        "spec": str(spec),
        "exports": {fmt: str(path) for fmt, path in copied_exports.items()},
        "qa_contract": deepcopy(profile.qa_contract),
        "layout_reports": result.get("qa_reports", []),
    }


def _clean_panel_values(
    item: dict[str, Any],
    *,
    request_dir: Path,
    figure_id: str,
) -> dict[str, Any]:
    sample = str(item.get("sample") or "").strip()
    if not sample:
        raise ValueError(f"Cloud `{figure_id}` has a panel without a sample name.")
    source = _resolve_path(
        item.get("data"),
        base_dir=request_dir,
        field=f"figures[{figure_id}].panels[{sample}].data",
    )
    if source.suffix.casefold() != ".csv":
        raise ValueError(f"Cloud panel `{sample}` requires a plot-ready CSV: {source}")
    frame = pd.read_csv(source)
    x_column = str(item.get("x_column") or "").strip()
    value_column = str(item.get("value_column") or "").strip()
    if not x_column or not value_column:
        raise ValueError(
            f"Cloud panel `{sample}` must name `x_column` and `value_column`; "
            "the figure workflow never guesses scientific columns."
        )
    missing = [column for column in (x_column, value_column) if column not in frame.columns]
    if missing:
        raise ValueError(f"Cloud panel `{sample}` is missing column(s): {', '.join(missing)}")
    x_values = pd.to_numeric(frame[x_column], errors="coerce")
    z_values = pd.to_numeric(frame[value_column], errors="coerce")
    invalid = x_values.isna() | z_values.isna()
    if bool(invalid.any()):
        rows = [int(index) + 2 for index in frame.index[invalid].tolist()]
        raise ValueError(
            f"Cloud panel `{sample}` contains nonnumeric plot data at CSV row(s): {rows}"
        )
    pairs = sorted(
        ((float(x), float(z)) for x, z in zip(x_values, z_values, strict=True)),
        key=lambda pair: pair[0],
    )
    if len(pairs) < 2:
        raise ValueError(f"Cloud panel `{sample}` needs at least two numeric points.")
    if any(not math.isfinite(value) for pair in pairs for value in pair):
        raise ValueError(f"Cloud panel `{sample}` contains non-finite values.")
    if any(left[0] >= right[0] for left, right in zip(pairs, pairs[1:])):
        raise ValueError(f"Cloud panel `{sample}` x values must be unique.")
    return {
        "sample": sample,
        "source": str(source),
        "x_column": x_column,
        "value_column": value_column,
        "x_values": [pair[0] for pair in pairs],
        "z_values": [pair[1] for pair in pairs],
    }


def _required_float(options: dict[str, Any], key: str) -> float:
    try:
        value = float(options[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Shared-colorbar cloud requires an explicit numeric `{key}`.") from exc
    if not math.isfinite(value):
        raise ValueError(f"Shared-colorbar cloud `{key}` must be finite.")
    return value


def _float_list(value: object, *, field: str) -> list[float]:
    if not isinstance(value, list | tuple) or not value:
        raise ValueError(f"Shared-colorbar cloud requires an explicit non-empty `{field}` list.")
    result: list[float] = []
    for item in value:
        try:
            number = float(item)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Cloud `{field}` values must be numeric.") from exc
        if not math.isfinite(number):
            raise ValueError(f"Cloud `{field}` values must be finite.")
        result.append(number)
    return result


def build_shared_scalar_strip_spec(
    panels: list[dict[str, Any]],
    *,
    profile_id: str = "relative_gradient_strip_v1",
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    profile = get_figure_profile(profile_id)
    if profile.figure_kind != "shared_scalar_strip":
        raise ValueError(f"Figure profile `{profile_id}` is not a shared scalar strip.")
    if not 1 <= len(panels) <= 6:
        raise ValueError("Shared scalar strips support one to six panels.")
    merged = deepcopy(profile.render_options)
    merged.update(deepcopy(options or {}))
    z_min = _required_float(merged, "z_min")
    z_max = _required_float(merged, "z_max")
    if z_max <= z_min:
        raise ValueError("Shared-colorbar cloud requires z_max > z_min.")
    z_ticks = _float_list(merged.get("z_ticks"), field="z_ticks")
    if any(tick < z_min or tick > z_max for tick in z_ticks):
        raise ValueError("Every cloud z tick must lie inside the explicit shared color range.")
    if any(left >= right for left, right in zip(z_ticks, z_ticks[1:])):
        raise ValueError("Cloud z ticks must be strictly increasing.")
    x_min = _required_float(merged, "x_min")
    x_max = _required_float(merged, "x_max")
    if x_max <= x_min:
        raise ValueError("Shared scalar strip requires x_max > x_min.")
    x_ticks = _float_list(merged.get("x_ticks"), field="x_ticks")
    x_minor_ticks = _float_list(merged.get("x_minor_ticks"), field="x_minor_ticks")

    page_width, page_height = profile.size_mm
    outer_left = float(merged["panel_outer_left_mm"])
    outer_right = float(merged["panel_outer_right_mm"])
    gap = float(merged["panel_gap_mm"])
    panel_width = (outer_right - outer_left - gap * (len(panels) - 1)) / len(panels)
    if panel_width <= 0:
        raise ValueError("Shared scalar strip panel geometry has no positive plotting width.")
    panel_specs: list[dict[str, Any]] = []
    for index, panel in enumerate(panels):
        x_values = [float(value) for value in panel["x_values"]]
        z_values = [float(value) for value in panel["z_values"]]
        if len(x_values) != len(z_values) or len(x_values) < 2:
            raise ValueError(f"Cloud panel `{panel.get('sample')}` has incompatible x/value arrays.")
        left = outer_left + index * (panel_width + gap)
        right = left + panel_width
        panel_specs.append(
            {
                **deepcopy(panel),
                "data_name": f"panel_{index + 1}_field",
                "left_mm": left,
                "right_mm": right,
                "below_range_count": sum(value < z_min for value in z_values),
                "above_range_count": sum(value > z_max for value in z_values),
            }
        )

    return {
        "kind": SHARED_SCALAR_STRIP_SPEC_KIND,
        "version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "render_engine": "veusz",
        "qa_target": "veusz_export",
        "figure_profile_id": profile.profile_id,
        "size_mm": [page_width, page_height],
        "style": {
            "font_family": profile.qa_contract["font_family"],
            "font_size_pt": profile.qa_contract["font_size_pt"],
            "axis_linewidth_pt": profile.qa_contract["axis_linewidth_pt"],
            "line_width_pt": profile.qa_contract["line_width_pt"],
            "tick_width_pt": profile.qa_contract["tick_width_pt"],
            "tick_length_pt": profile.qa_contract["tick_length_pt"],
            "minor_tick_width_pt": profile.qa_contract["minor_tick_width_pt"],
            "minor_tick_length_pt": profile.qa_contract["minor_tick_length_pt"],
            "foreground_color": "#273034",
        },
        "axes": {
            "x": {
                "label": str(merged["x_label_override"]),
                "min": x_min,
                "max": x_max,
                "ticks": x_ticks,
                "minor_ticks": x_minor_ticks,
            }
        },
        "scalar": {
            "name": str(merged["z_label_override"]),
            "unit": str(merged["z_unit_override"]),
            "min": z_min,
            "max": z_max,
            "ticks": z_ticks,
            "colormap_name": str(merged["colormap_name"]),
            "color_invert": bool(merged.get("color_invert")),
            "shared_across_panels": True,
        },
        "geometry": {
            "outer_frame_x_mm": [outer_left, outer_right],
            "panel_top_mm": float(merged["panel_top_mm"]),
            "panel_bottom_mm": float(merged["panel_bottom_mm"]),
            "panel_gap_mm": gap,
            "panel_width_mm": panel_width,
            "colorbar_frame_mm": [
                float(merged["colorbar_left_mm"]),
                float(merged["panel_top_mm"]),
                float(merged["colorbar_right_mm"]),
                float(merged["panel_bottom_mm"]),
            ],
            "colorbar_tick_label_x_mm": float(merged["colorbar_left_mm"]) - 1.45,
            "colorbar_title_center_x_mm": 0.5
            * (float(merged["colorbar_left_mm"]) + float(merged["colorbar_right_mm"])),
        },
        "panels": panel_specs,
        "display_transform": {
            "id": "profile_extrusion",
            "kind": "one_dimensional_profile_repeated_vertically",
            "scientific_values_changed": False,
            "purpose": "display_only_scalar_strip",
        },
        "qa_contract": deepcopy(profile.qa_contract),
    }


def _mm(value: float) -> str:
    return f"{float(value):g}mm"


def _pt(value: float) -> str:
    return f"{float(value):g}pt"


def _tick_label(value: float) -> str:
    if math.isclose(value, round(value), abs_tol=1e-9):
        text = str(int(round(value)))
    else:
        text = f"{value:g}"
    return text.replace("-", "−")


def _add_hidden_axis(interface: Any, name: str, *, vertical: bool = False) -> None:
    interface.Add("axis", name=name, autoadd=False)
    interface.To(name)
    if vertical:
        interface.Set("direction", "vertical")
    interface.Set("Line/hide", True)
    interface.Set("Label/hide", True)
    interface.Set("TickLabels/hide", True)
    interface.Set("MajorTicks/hide", True)
    interface.Set("MinorTicks/hide", True)
    interface.To("..")


def _add_relative_label(
    interface: Any,
    *,
    name: str,
    label: str,
    x_mm: float,
    y_mm: float,
    page_width_mm: float,
    page_height_mm: float,
    style: dict[str, Any],
    align_horz: str = "centre",
) -> None:
    interface.Add("label", name=name, autoadd=False)
    interface.To(name)
    interface.Set("label", label)
    interface.Set("xPos", [x_mm / page_width_mm])
    interface.Set("yPos", [y_mm / page_height_mm])
    interface.Set("positioning", "relative")
    interface.Set("alignHorz", align_horz)
    interface.Set("alignVert", "centre")
    interface.Set("Text/font", str(style["font_family"]))
    interface.Set("Text/size", _pt(float(style["font_size_pt"])))
    interface.Set("Text/color", str(style["foreground_color"]))
    interface.Set("Text/bold", False)
    interface.Set("Background/hide", True)
    interface.Set("Border/hide", True)
    interface.To("..")


def apply_shared_scalar_strip_spec(interface: Any, spec: dict[str, Any]) -> None:
    style = spec["style"]
    page_width, page_height = (float(value) for value in spec["size_mm"])
    scalar = spec["scalar"]
    axes = spec["axes"]
    geometry = spec["geometry"]
    panels = spec["panels"]
    panel_top = float(geometry["panel_top_mm"])
    panel_bottom = float(geometry["panel_bottom_mm"])
    graph_bottom_margin = page_height - panel_bottom

    for panel in panels:
        row = [float(value) for value in panel["z_values"]]
        interface.SetData2D(
            str(panel["data_name"]),
            [row, row],
            xcent=[float(value) for value in panel["x_values"]],
            ycent=[0.0, 1.0],
        )
    interface.SetData2D(
        "shared_colorbar_data",
        [
            [float(scalar["min"]), float(scalar["max"])],
            [float(scalar["min"]), float(scalar["max"])],
        ],
        xcent=[0.0, 1.0],
        ycent=[0.0, 1.0],
    )

    interface.Set("StyleSheet/Font/font", str(style["font_family"]))
    interface.Set("StyleSheet/Font/size", _pt(float(style["font_size_pt"])))
    interface.Set("StyleSheet/Line/width", _pt(float(style["line_width_pt"])))
    interface.Set("width", _mm(page_width))
    interface.Set("height", _mm(page_height))
    interface.Add("page", name="page1", autoadd=False)
    interface.To("page1")
    interface.Set("width", _mm(page_width))
    interface.Set("height", _mm(page_height))
    interface.Set("Background/color", "white")
    interface.Set("Background/hide", False)

    colorbar_left, _top, colorbar_right, _bottom = (
        float(value) for value in geometry["colorbar_frame_mm"]
    )
    colorbar_graph_left = 0.2
    colorbar_graph_right = page_width - (colorbar_right + 0.4)
    colorbar_graph_width = page_width - colorbar_graph_left - colorbar_graph_right
    interface.Add("graph", name="colorbar_graph", autoadd=False)
    interface.To("colorbar_graph")
    interface.Set("leftMargin", _mm(colorbar_graph_left))
    interface.Set("rightMargin", _mm(colorbar_graph_right))
    interface.Set("topMargin", _mm(panel_top))
    interface.Set("bottomMargin", _mm(graph_bottom_margin))
    interface.Set("Background/hide", True)
    interface.Set("Border/hide", True)
    _add_hidden_axis(interface, "x")
    _add_hidden_axis(interface, "y", vertical=True)
    interface.Add("image", name="gradient_legend_image", autoadd=False)
    interface.To("gradient_legend_image")
    interface.Set("data", "shared_colorbar_data")
    interface.Set("min", float(scalar["min"]))
    interface.Set("max", float(scalar["max"]))
    interface.Set("colorScaling", "linear")
    interface.Set("colorMap", str(scalar["colormap_name"]))
    interface.Set("colorInvert", bool(scalar.get("color_invert")))
    interface.Set("mapping", "bounds")
    interface.Set("hide", True)
    interface.To("..")
    interface.Add("colorbar", name="gradient_colorbar", autoadd=False)
    interface.To("gradient_colorbar")
    interface.Set("widgetName", "gradient_legend_image")
    interface.Set("label", " ")
    interface.Set("min", float(scalar["min"]))
    interface.Set("max", float(scalar["max"]))
    interface.Set("autoMirror", False)
    interface.Set("outerticks", True)
    interface.Set("direction", "vertical")
    interface.Set("reflect", True)
    interface.Set("Line/color", str(style["foreground_color"]))
    interface.Set("Line/width", _pt(float(style["axis_linewidth_pt"])))
    interface.Set("Label/hide", True)
    interface.Set("TickLabels/hide", True)
    interface.Set("MajorTicks/width", _pt(float(style["tick_width_pt"])))
    interface.Set("MajorTicks/length", _pt(float(style["tick_length_pt"])))
    interface.Set("MajorTicks/manualTicks", [float(value) for value in scalar["ticks"]])
    interface.Set("MinorTicks/hide", True)
    interface.Set("horzPosn", "manual")
    interface.Set("vertPosn", "manual")
    interface.Set("width", _mm(colorbar_right - colorbar_left))
    interface.Set("height", _mm(panel_bottom - panel_top))
    interface.Set(
        "horzManual",
        (colorbar_left - colorbar_graph_left) / colorbar_graph_width,
    )
    interface.Set("vertManual", 0.0)
    interface.Set("Border/color", str(style["foreground_color"]))
    interface.Set("Border/width", _pt(float(style["axis_linewidth_pt"])))
    interface.To("..")
    interface.To("..")

    x_axis = axes["x"]
    for index, panel in enumerate(panels, start=1):
        graph_name = f"graph_{index}"
        interface.Add("graph", name=graph_name, autoadd=False)
        interface.To(graph_name)
        interface.Set("leftMargin", _mm(float(panel["left_mm"])))
        interface.Set("rightMargin", _mm(page_width - float(panel["right_mm"])))
        interface.Set("topMargin", _mm(panel_top))
        interface.Set("bottomMargin", _mm(graph_bottom_margin))
        interface.Set("Background/hide", True)
        interface.Set("Border/hide", False)
        interface.Set("Border/color", str(style["foreground_color"]))
        interface.Set("Border/width", _pt(float(style["axis_linewidth_pt"])))
        interface.Add("axis", name="x", autoadd=False)
        interface.To("x")
        interface.Set("label", " ")
        interface.Set("min", float(x_axis["min"]))
        interface.Set("max", float(x_axis["max"]))
        interface.Set("autoMirror", False)
        interface.Set("outerticks", True)
        interface.Set("Line/color", str(style["foreground_color"]))
        interface.Set("Line/width", _pt(float(style["axis_linewidth_pt"])))
        interface.Set("Label/hide", True)
        interface.Set("TickLabels/hide", True)
        interface.Set("MajorTicks/width", _pt(float(style["tick_width_pt"])))
        interface.Set("MajorTicks/length", _pt(float(style["tick_length_pt"])))
        interface.Set("MajorTicks/manualTicks", [float(value) for value in x_axis["ticks"]])
        interface.Set("MinorTicks/hide", False)
        interface.Set("MinorTicks/width", _pt(float(style["minor_tick_width_pt"])))
        interface.Set("MinorTicks/length", _pt(float(style["minor_tick_length_pt"])))
        interface.Set("MinorTicks/manualTicks", [float(value) for value in x_axis["minor_ticks"]])
        interface.To("..")
        _add_hidden_axis(interface, "y", vertical=True)
        interface.Add("image", name="relative_gradient_field", autoadd=False)
        interface.To("relative_gradient_field")
        interface.Set("data", str(panel["data_name"]))
        interface.Set("min", float(scalar["min"]))
        interface.Set("max", float(scalar["max"]))
        interface.Set("colorScaling", "linear")
        interface.Set("colorMap", str(scalar["colormap_name"]))
        interface.Set("colorInvert", bool(scalar.get("color_invert")))
        interface.Set("mapping", "bounds")
        interface.Set("drawMode", "rectangles")
        interface.To("..")
        interface.To("..")

        center_x = 0.5 * (float(panel["left_mm"]) + float(panel["right_mm"]))
        _add_relative_label(
            interface,
            name=f"title_{index}",
            label=str(panel["sample"]),
            x_mm=center_x,
            y_mm=page_height - 2.25,
            page_width_mm=page_width,
            page_height_mm=page_height,
            style=style,
        )
        for tick_index, tick in enumerate(x_axis["ticks"], start=1):
            fraction = (float(tick) - float(x_axis["min"])) / (
                float(x_axis["max"]) - float(x_axis["min"])
            )
            x_mm = float(panel["left_mm"]) + fraction * (
                float(panel["right_mm"]) - float(panel["left_mm"])
            )
            align = "left" if tick_index == 1 else "right" if tick_index == len(x_axis["ticks"]) else "centre"
            _add_relative_label(
                interface,
                name=f"tick_{index}_{tick_index}",
                label=_tick_label(float(tick)),
                x_mm=x_mm,
                y_mm=6.2,
                page_width_mm=page_width,
                page_height_mm=page_height,
                style=style,
                align_horz=align,
            )

    colorbar_center = 0.5 * (colorbar_left + colorbar_right)
    _add_relative_label(
        interface,
        name="colorbar_title",
        label=str(scalar["name"]),
        x_mm=colorbar_center,
        y_mm=page_height - 1.25,
        page_width_mm=page_width,
        page_height_mm=page_height,
        style=style,
    )
    _add_relative_label(
        interface,
        name="colorbar_unit",
        label=str(scalar["unit"]),
        x_mm=colorbar_center,
        y_mm=page_height - 4.0,
        page_width_mm=page_width,
        page_height_mm=page_height,
        style=style,
    )
    colorbar_tick_x = float(geometry["colorbar_tick_label_x_mm"])
    colorbar_y_min = graph_bottom_margin
    colorbar_y_max = page_height - panel_top
    for index, tick in enumerate(scalar["ticks"], start=1):
        fraction = (float(tick) - float(scalar["min"])) / (
            float(scalar["max"]) - float(scalar["min"])
        )
        _add_relative_label(
            interface,
            name=f"colorbar_tick_{index}",
            label=_tick_label(float(tick)),
            x_mm=colorbar_tick_x,
            y_mm=colorbar_y_min + fraction * (colorbar_y_max - colorbar_y_min),
            page_width_mm=page_width,
            page_height_mm=page_height,
            style=style,
            align_horz="right",
        )
    _add_relative_label(
        interface,
        name="shared_x_label",
        label=str(x_axis["label"]),
        x_mm=0.5 * (float(geometry["outer_frame_x_mm"][0]) + float(geometry["outer_frame_x_mm"][1])),
        y_mm=1.65,
        page_width_mm=page_width,
        page_height_mm=page_height,
        style=style,
    )

    interface.Add("rect", name="page_export_background", autoadd=False)
    interface.To("page_export_background")
    interface.Set("positioning", "relative")
    interface.Set("xPos", [0.5])
    interface.Set("yPos", [0.5])
    interface.Set("width", [1.0])
    interface.Set("height", [1.0])
    interface.Set("Fill/color", "white")
    interface.Set("Fill/hide", False)
    interface.Set("Border/hide", True)
    interface.To("..")
    interface.To("..")


def _write_cloud_plot_data(path: Path, panels: list[dict[str, Any]], *, scalar_name: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    maximum_rows = max(len(panel["x_values"]) for panel in panels)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                value
                for _panel in panels
                for value in ("Thickness position", scalar_name)
            ]
        )
        writer.writerow([value for _panel in panels for value in ("mm", "mm^-1")])
        writer.writerow([value for panel in panels for value in (panel["sample"], panel["sample"])])
        for row_index in range(maximum_rows):
            row: list[object] = []
            for panel in panels:
                if row_index < len(panel["x_values"]):
                    row.extend([panel["x_values"][row_index], panel["z_values"][row_index]])
                else:
                    row.extend(["", ""])
            writer.writerow(row)
    return path


def _cloud_figure(
    *,
    item: dict[str, Any],
    profile: FigureProfile,
    request_dir: Path,
    output_dir: Path,
    exports: tuple[str, ...],
) -> dict[str, Any]:
    figure_id = _plain_filename(item.get("id"), fallback=profile.profile_id)
    panel_items = item.get("panels")
    if not isinstance(panel_items, list) or not panel_items:
        raise ValueError(f"Cloud `{figure_id}` requires a non-empty `panels` list.")
    panels = [
        _clean_panel_values(panel, request_dir=request_dir, figure_id=figure_id)
        for panel in panel_items
        if isinstance(panel, dict)
    ]
    if len(panels) != len(panel_items):
        raise ValueError(f"Cloud `{figure_id}` panel entries must be JSON objects.")
    options = item.get("options") if isinstance(item.get("options"), dict) else {}
    spec_payload = build_shared_scalar_strip_spec(
        panels,
        profile_id=profile.profile_id,
        options=options,
    )
    spec = output_dir / "specs" / f"{figure_id}.json"
    spec.write_text(json.dumps(json_safe(spec_payload), indent=2, ensure_ascii=False), encoding="utf-8")
    document = output_dir / "project" / f"{figure_id}.vsz"
    from sciplot_core.studio import _save_veusz_document_from_spec, export_studio_document

    _save_veusz_document_from_spec(document, spec_payload, spec_path=spec)
    export_payload = export_studio_document(document, formats=list(exports))
    copied_exports: dict[str, Path] = {}
    for record in export_payload.get("exports", []):
        if not isinstance(record, dict):
            continue
        fmt = str(record.get("format") or "")
        source_export = Path(str(record.get("path") or "")).expanduser()
        if fmt in exports and source_export.is_file():
            copied_exports[fmt] = _copy_export(
                source_export,
                _canonical_figure_path(output_dir / "figures", figure_id, fmt),
            )
    missing = [fmt for fmt in exports if fmt not in copied_exports]
    if missing:
        raise RuntimeError(f"Cloud `{figure_id}` did not export: {', '.join(missing)}")
    plot_data = _write_cloud_plot_data(
        output_dir / "plot_data" / f"{figure_id}_plot_data.csv",
        panels,
        scalar_name=str(spec_payload["scalar"]["name"]),
    )
    return {
        "id": figure_id,
        "profile_id": profile.profile_id,
        "figure_kind": profile.figure_kind,
        "source_data": [panel["source"] for panel in panels],
        "plot_data": str(plot_data),
        "document": str(document),
        "spec": str(spec),
        "exports": {fmt: str(path) for fmt, path in copied_exports.items()},
        "qa_contract": deepcopy(profile.qa_contract),
        "geometry": deepcopy(spec_payload["geometry"]),
        "display_transform": deepcopy(spec_payload["display_transform"]),
        "range_diagnostics": [
            {
                "sample": panel["sample"],
                "below_range_count": panel["below_range_count"],
                "above_range_count": panel["above_range_count"],
            }
            for panel in spec_payload["panels"]
        ],
    }


def _alignment_checks(
    request: dict[str, Any],
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_id = {record["id"]: record for record in records}
    groups = request.get("alignment_groups")
    if not isinstance(groups, list):
        groups = []
    checks: list[dict[str, Any]] = []
    for index, group in enumerate(groups, start=1):
        if not isinstance(group, dict):
            raise ValueError("Every alignment group must be a JSON object.")
        curve_id = str(group.get("curve") or "")
        cloud_id = str(group.get("cloud") or "")
        if curve_id not in by_id or cloud_id not in by_id:
            raise ValueError(f"Alignment group {index} references an unknown curve or cloud id.")
        curve_profile = get_figure_profile(by_id[curve_id]["profile_id"])
        cloud_record = by_id[cloud_id]
        curve_geometry = (
            by_id[curve_id].get("pdf_geometry")
            if isinstance(by_id[curve_id].get("pdf_geometry"), dict)
            else {}
        )
        cloud_geometry = (
            cloud_record.get("pdf_geometry")
            if isinstance(cloud_record.get("pdf_geometry"), dict)
            else {}
        )
        curve_frame = curve_geometry.get("plot_frame_x_mm") or curve_profile.qa_contract.get(
            "plot_frame_x_mm"
        )
        cloud_frame = cloud_geometry.get("outer_frame_x_mm") or (
            cloud_record.get("geometry", {}).get("outer_frame_x_mm")
            if isinstance(cloud_record.get("geometry"), dict)
            else None
        )
        passed = (
            isinstance(curve_frame, list)
            and isinstance(cloud_frame, list)
            and len(curve_frame) == len(cloud_frame) == 2
            and all(abs(float(left) - float(right)) <= 0.02 for left, right in zip(curve_frame, cloud_frame))
        )
        checks.append(
            {
                "id": f"alignment_{curve_id}_to_{cloud_id}",
                "curve": curve_id,
                "cloud": cloud_id,
                "curve_frame_x_mm": curve_frame,
                "cloud_frame_x_mm": cloud_frame,
                "tolerance_mm": 0.02,
                "passed": passed,
            }
        )
    return checks


def _rect_mm(rect: fitz.Rect) -> list[float]:
    points_to_mm = 25.4 / 72.0
    return [
        round(float(value) * points_to_mm, 4)
        for value in (rect.x0, rect.y0, rect.x1, rect.y1)
    ]


def _rect_matches(actual: list[float], expected: list[float], *, tolerance_mm: float) -> bool:
    return len(actual) == len(expected) and all(
        abs(float(left) - float(right)) <= tolerance_mm
        for left, right in zip(actual, expected, strict=True)
    )


def _pdf_geometry_checks(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    tolerance_mm = 0.03
    for record in records:
        profile = get_figure_profile(record["profile_id"])
        pdf = Path(record["exports"]["pdf"])
        spec = _read_json_object(Path(record["spec"]))
        with fitz.open(pdf) as rendered:
            page = rendered[0]
            page_size = [
                float(page.rect.width) * 25.4 / 72.0,
                float(page.rect.height) * 25.4 / 72.0,
            ]
            drawings = page.get_drawings()
            drawing_rects = [
                _rect_mm(drawing["rect"])
                for drawing in drawings
                if drawing.get("type") == "s"
            ]
            text_dict = page.get_text("dict")
            plain_text = page.get_text("text")
        expected_size = list(profile.size_mm)
        size_passed = all(
            abs(actual - expected) <= 0.1
            for actual, expected in zip(page_size, expected_size, strict=True)
        )
        checks.append(
            {
                "id": f"{record['id']}_pdf_physical_size",
                "passed": size_passed,
                "expected_mm": expected_size,
                "actual_mm": [round(value, 3) for value in page_size],
                "tolerance_mm": 0.1,
            }
        )

        if record["figure_kind"] == "curve":
            style = spec.get("style") if isinstance(spec.get("style"), dict) else {}
            margins = style.get("margins_mm") if isinstance(style.get("margins_mm"), dict) else {}
            expected_frame = [
                float(margins.get("left")),
                float(profile.size_mm[0]) - float(margins.get("right")),
            ]
            horizontal_axes = [
                rect
                for rect in drawing_rects
                if abs(rect[0] - expected_frame[0]) <= tolerance_mm
                and abs(rect[2] - expected_frame[1]) <= tolerance_mm
                and abs(rect[3] - rect[1]) <= 0.1
            ]
            frame_passed = bool(horizontal_axes)
            record["pdf_geometry"] = {
                "plot_frame_x_mm": expected_frame if frame_passed else None,
                "matching_horizontal_strokes": horizontal_axes,
            }
            x_axis = spec.get("axes", {}).get("x", {})
            y_axis = spec.get("axes", {}).get("y", {})
            document_text = Path(record["document"]).read_text(encoding="utf-8")
            x_minor_ticks_required = "x_minor_interval_mm" in profile.qa_contract
            required_visible_minor_axes = 1 + int(x_minor_ticks_required)
            minor_tick_passed = (
                (not x_minor_ticks_required or bool(x_axis.get("minor_ticks")))
                and bool(y_axis.get("minor_ticks"))
                and document_text.count("Set('MinorTicks/hide', False)")
                >= required_visible_minor_axes
            )
            filled_markers = bool(spec.get("series")) and all(
                series.get("marker") != "none"
                and series.get("marker_fill_color") == series.get("color")
                for series in spec.get("series", [])
            )
            checks.extend(
                [
                    {
                        "id": f"{record['id']}_pdf_plot_frame_x",
                        "passed": frame_passed,
                        "expected_mm": expected_frame,
                        "matching_strokes": horizontal_axes,
                        "tolerance_mm": tolerance_mm,
                    },
                    {
                        "id": f"{record['id']}_rendered_minor_ticks",
                        "passed": minor_tick_passed,
                        "x_minor_tick_count": len(x_axis.get("minor_ticks") or []),
                        "y_minor_tick_count": len(y_axis.get("minor_ticks") or []),
                        "x_explicit_minor_ticks_required": x_minor_ticks_required,
                    },
                    {
                        "id": f"{record['id']}_filled_markers",
                        "passed": filled_markers,
                        "marker_size_pt": spec.get("style", {}).get("marker_size_pt"),
                    },
                ]
            )
            continue

        expected_panels = [
            [
                float(panel["left_mm"]),
                float(spec["geometry"]["panel_top_mm"]),
                float(panel["right_mm"]),
                float(spec["geometry"]["panel_bottom_mm"]),
            ]
            for panel in spec.get("panels", [])
        ]
        matched_panels = [
            next(
                (
                    actual
                    for actual in drawing_rects
                    if _rect_matches(actual, expected, tolerance_mm=tolerance_mm)
                ),
                None,
            )
            for expected in expected_panels
        ]
        expected_colorbar = [
            float(value)
            for value in spec.get("geometry", {}).get("colorbar_frame_mm", [])
        ]
        matched_colorbars = [
            actual
            for actual in drawing_rects
            if _rect_matches(actual, expected_colorbar, tolerance_mm=tolerance_mm)
        ]
        sample_names = [str(panel["sample"]) for panel in spec.get("panels", [])]
        sample_fonts: dict[str, str] = {}
        for block in text_dict.get("blocks", []):
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = str(span.get("text") or "").strip()
                    if text in sample_names:
                        sample_fonts[text] = str(span.get("font") or "")
        regular_titles = (
            set(sample_fonts) == set(sample_names)
            and all("bold" not in font.casefold() for font in sample_fonts.values())
        )
        singular_label = (
            "Thickness position (mm)" in plain_text
            and "Thickness positions (mm)" not in plain_text
        )
        colorbar_tick_x = float(spec["geometry"]["colorbar_tick_label_x_mm"])
        colorbar_ticks_left = colorbar_tick_x < expected_colorbar[0]
        panel_passed = bool(expected_panels) and all(value is not None for value in matched_panels)
        colorbar_passed = len(matched_colorbars) == 1
        record["pdf_geometry"] = {
            "outer_frame_x_mm": (
                [
                    expected_panels[0][0],
                    expected_panels[-1][2],
                ]
                if panel_passed
                else None
            ),
            "panel_frames_mm": matched_panels,
            "colorbar_frame_mm": matched_colorbars[0] if colorbar_passed else None,
        }
        checks.extend(
            [
                {
                    "id": f"{record['id']}_pdf_panel_frames",
                    "passed": panel_passed,
                    "expected_mm": expected_panels,
                    "actual_mm": matched_panels,
                    "tolerance_mm": tolerance_mm,
                },
                {
                    "id": f"{record['id']}_pdf_colorbar_frame",
                    "passed": colorbar_passed,
                    "expected_mm": expected_colorbar,
                    "actual_mm": matched_colorbars,
                    "tolerance_mm": tolerance_mm,
                },
                {
                    "id": f"{record['id']}_pdf_sample_titles_regular",
                    "passed": regular_titles,
                    "fonts": sample_fonts,
                },
                {
                    "id": f"{record['id']}_pdf_singular_thickness_label",
                    "passed": singular_label,
                },
                {
                    "id": f"{record['id']}_colorbar_tick_labels_left",
                    "passed": colorbar_ticks_left,
                    "tick_label_x_mm": colorbar_tick_x,
                    "colorbar_left_mm": expected_colorbar[0],
                },
            ]
        )
    return checks


def _profile_checks(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for record in records:
        document = Path(record["document"])
        spec = _read_json_object(Path(record["spec"]))
        checks.extend(
            [
                {
                    "id": f"{record['id']}_vsz_exists",
                    "passed": document.is_file() and document.stat().st_size > 0,
                },
                {
                    "id": f"{record['id']}_profile_bound",
                    "passed": spec.get("figure_profile_id") == record["profile_id"],
                },
                {
                    "id": f"{record['id']}_pdf_tiff_pair",
                    "passed": set(record["exports"]) == set(SUPPORTED_FIGURE_EXPORTS),
                },
            ]
        )
        if record["figure_kind"] == "shared_scalar_strip":
            scalar = spec.get("scalar") if isinstance(spec.get("scalar"), dict) else {}
            panels = spec.get("panels") if isinstance(spec.get("panels"), list) else []
            checks.extend(
                [
                    {
                        "id": f"{record['id']}_one_shared_colorbar",
                        "passed": scalar.get("shared_across_panels") is True,
                    },
                    {
                        "id": f"{record['id']}_single_color_contract",
                        "passed": bool(panels)
                        and all(spec.get("scalar", {}).get("min") is not None for _panel in panels),
                    },
                    {
                        "id": f"{record['id']}_display_extrusion_declared",
                        "passed": spec.get("display_transform", {}).get("scientific_values_changed") is False,
                    },
                    {
                        "id": f"{record['id']}_sample_titles_regular",
                        "passed": record["qa_contract"].get("sample_title_weight") == "regular",
                    },
                    {
                        "id": f"{record['id']}_colorbar_ticks_left",
                        "passed": record["qa_contract"].get("colorbar_tick_side") == "left",
                    },
                ]
            )
    return checks


def _delivery_inputs(records: list[dict[str, Any]]) -> tuple[
    list[tuple[str, Path]],
    list[tuple[str, Path]],
    list[tuple[str, Path]],
]:
    figures: list[tuple[str, Path]] = []
    data_files: list[tuple[str, Path]] = []
    documents: list[tuple[str, Path]] = []
    for record in records:
        figure_id = record["id"]
        for fmt, path_value in record["exports"].items():
            path = Path(path_value)
            name = f"{figure_id}.pdf" if fmt == "pdf" else f"{figure_id}_300dpi.tiff"
            figures.append((name, path))
        data_files.append((f"{figure_id}_plot_data.csv", Path(record["plot_data"])))
        documents.append((f"{figure_id}.vsz", Path(record["document"])))
    return figures, data_files, documents


def _delivery_verification(
    delivery_dir: Path,
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    expected_top_level = {
        "data",
        "pdf",
        "tiff",
        "project",
        "Open_in_Veusz.command",
    }
    actual_top_level = {path.name for path in delivery_dir.iterdir()}
    artifact_checks: list[dict[str, Any]] = []
    for record in records:
        figure_id = str(record["id"])
        pairs = [
            (
                "plot_data",
                Path(record["plot_data"]),
                delivery_dir / "data" / f"{figure_id}_plot_data.csv",
            ),
            (
                "vsz",
                Path(record["document"]),
                delivery_dir / "project" / f"{figure_id}.vsz",
            ),
            (
                "pdf",
                Path(record["exports"]["pdf"]),
                delivery_dir / "pdf" / f"{figure_id}.pdf",
            ),
            (
                "tiff_300",
                Path(record["exports"]["tiff_300"]),
                delivery_dir / "tiff" / f"{figure_id}_300dpi.tiff",
            ),
        ]
        for artifact_kind, source, copied in pairs:
            source_hash = existing_file_sha256(source)
            copied_hash = existing_file_sha256(copied)
            artifact_checks.append(
                {
                    "figure_id": figure_id,
                    "artifact_kind": artifact_kind,
                    "source": str(source),
                    "delivery": str(copied),
                    "source_sha256": source_hash,
                    "delivery_sha256": copied_hash,
                    "passed": bool(source_hash and source_hash == copied_hash),
                }
            )
    launcher = delivery_launcher_dry_run(
        delivery_dir,
        [f"{record['id']}.vsz" for record in records],
    )
    top_level_passed = actual_top_level == expected_top_level
    return {
        "passed": (
            top_level_passed
            and bool(artifact_checks)
            and all(item["passed"] for item in artifact_checks)
            and launcher["passed"]
        ),
        "top_level": {
            "passed": top_level_passed,
            "expected": sorted(expected_top_level),
            "actual": sorted(actual_top_level),
        },
        "artifact_hashes": artifact_checks,
        "launcher_dry_run": launcher,
    }


def run_plot_ready_figure_request(
    request_path: Path,
    *,
    output_dir: Path,
) -> dict[str, Any]:
    resolved_request = request_path.expanduser().resolve()
    request = _read_json_object(resolved_request)
    if request.get("kind") != PLOT_READY_REQUEST_KIND:
        raise ValueError(
            f"Figure request `kind` must be `{PLOT_READY_REQUEST_KIND}`; "
            "this workflow never infers raw-data processing."
        )
    exports = _normalize_exports(request.get("exports"))
    figures = request.get("figures")
    if not isinstance(figures, list) or not figures:
        raise ValueError("Figure request requires a non-empty `figures` list.")
    resolved_output = output_dir.expanduser().resolve()
    archive = _prepare_managed_output(resolved_output)
    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for raw_item in figures:
        if not isinstance(raw_item, dict):
            raise ValueError("Every figure request entry must be a JSON object.")
        profile_id = str(raw_item.get("profile") or "").strip()
        profile = get_figure_profile(profile_id)
        figure_id = _plain_filename(raw_item.get("id"), fallback=profile.profile_id)
        if figure_id in seen_ids:
            raise ValueError(f"Duplicate figure id: {figure_id}")
        seen_ids.add(figure_id)
        if profile.figure_kind == "curve":
            record = _curve_figure(
                item=raw_item,
                profile=profile,
                request_dir=resolved_request.parent,
                output_dir=resolved_output,
                exports=exports,
            )
        elif profile.figure_kind == "shared_scalar_strip":
            record = _cloud_figure(
                item=raw_item,
                profile=profile,
                request_dir=resolved_request.parent,
                output_dir=resolved_output,
                exports=exports,
            )
        else:
            raise ValueError(f"Unsupported figure kind: {profile.figure_kind}")
        records.append(record)

    pdf_geometry_checks = _pdf_geometry_checks(records)
    profile_checks = _profile_checks(records)
    alignment_checks = _alignment_checks(request, records)
    checks = [*profile_checks, *pdf_geometry_checks, *alignment_checks]
    custom_status = "passed" if checks and all(check["passed"] for check in checks) else "failed"
    artifact_qa = run_qa(resolved_output)
    qa_payload = {
        "kind": "sciplot_plot_ready_figure_qa",
        "version": 1,
        "status": (
            "passed"
            if custom_status == "passed" and artifact_qa.get("status") == "passed"
            else "failed"
        ),
        "profile_checks": profile_checks,
        "pdf_geometry_checks": pdf_geometry_checks,
        "alignment_checks": alignment_checks,
        "artifact_qa": artifact_qa,
    }
    (resolved_output / "qa_report.json").write_text(
        json.dumps(json_safe(qa_payload), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    if qa_payload["status"] != "passed":
        raise RuntimeError(f"Plot-ready figure QA failed: {resolved_output / 'qa_report.json'}")

    delivery_inputs = _delivery_inputs(records)
    delivery = build_minimal_user_delivery(
        resolved_output / "delivery",
        figures=delivery_inputs[0],
        data_files=delivery_inputs[1],
        veusz_documents=delivery_inputs[2],
    )
    delivery_verification = _delivery_verification(
        resolved_output / "delivery",
        records,
    )
    qa_payload["delivery_verification"] = delivery_verification
    qa_payload["status"] = (
        "passed"
        if qa_payload["status"] == "passed" and delivery_verification["passed"]
        else "failed"
    )
    (resolved_output / "qa_report.json").write_text(
        json.dumps(json_safe(qa_payload), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    if qa_payload["status"] != "passed":
        raise RuntimeError(f"Plot-ready delivery QA failed: {resolved_output / 'qa_report.json'}")
    manifest = {
        "kind": "sciplot_plot_ready_figure_result",
        "version": 1,
        "status": "ready",
        "generated_at": datetime.now(UTC).isoformat(),
        "request_path": str(resolved_request),
        "request": json_safe(request),
        "output_dir": str(resolved_output),
        "exports": list(exports),
        "figures": records,
        "veusz_documents": [record["document"] for record in records],
        "archive": str(archive) if archive is not None else None,
        "qa": qa_payload,
        "delivery": delivery,
        "delivery_verification": delivery_verification,
        "scientific_processing": {
            "performed": False,
            "contract": "plot_ready_data_only",
            "note": "No normalization, smoothing, interpolation, differentiation, or raw-data parsing is performed.",
        },
    }
    manifest_path = resolved_output / "manifest.json"
    manifest_path.write_text(
        json.dumps(json_safe(manifest), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return {
        "kind": "sciplot_plot_ready_figure_result",
        "status": "ready",
        "output_dir": str(resolved_output),
        "manifest": str(manifest_path),
        "qa_report": str(resolved_output / "qa_report.json"),
        "delivery": str(resolved_output / "delivery"),
        "figures": records,
    }


def delivery_launcher_dry_run(delivery_dir: Path, documents: list[str]) -> dict[str, Any]:
    launcher = delivery_dir / "Open_in_Veusz.command"
    results: list[dict[str, Any]] = []
    for document in documents:
        process = subprocess.run(
            [str(launcher), document],
            text=True,
            capture_output=True,
            check=False,
            env={**os.environ, "SCIPLOT_LAUNCH_DRY_RUN": "1"},
        )
        results.append(
            {
                "document": document,
                "returncode": process.returncode,
                "stdout": process.stdout.strip(),
                "stderr": process.stderr.strip(),
            }
        )
    return {
        "passed": bool(results) and all(item["returncode"] == 0 for item in results),
        "results": results,
    }


__all__ = [
    "PLOT_READY_REQUEST_KIND",
    "SHARED_SCALAR_STRIP_SPEC_KIND",
    "apply_shared_scalar_strip_spec",
    "build_shared_scalar_strip_spec",
    "delivery_launcher_dry_run",
    "run_plot_ready_figure_request",
]
