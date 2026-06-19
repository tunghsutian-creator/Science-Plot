from __future__ import annotations

import json
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from sciplot_core.render import json_safe

HANDOFF_VERSION = "1"

SIZE_PRESETS_MM = {
    "60x55": (60.0, 55.0),
    "120x55": (120.0, 55.0),
    "180x55": (180.0, 55.0),
    "60x110": (60.0, 110.0),
    "120x110": (120.0, 110.0),
    "180x110": (180.0, 110.0),
}

DEFAULT_FRAME_MM = {
    "left": 14.0,
    "right": 4.5,
    "top": 5.5,
    "bottom": 11.0,
}


def export_origin_handoff(input_path: Path, *, output_dir: Path | None = None) -> dict[str, Any]:
    """Create an OriginPro LabTalk handoff package for a completed SciPlot run.

    The package is intentionally a per-run script/data handoff, not a theme or
    template installer. OriginPro consumes the generated `.ogs` file and copied
    CSV data, then Origin itself saves the `.opju` project.
    """

    manifest_path = _resolve_manifest_path(input_path)
    manifest = _read_json(manifest_path)
    run_output = _resolve_run_output(manifest, manifest_path)
    target_dir = (output_dir or (run_output / "origin_handoff")).expanduser()
    _clear_handoff_dir(target_dir)

    data_dir = target_dir / "data"
    source_dir = target_dir / "source"
    preview_dir = target_dir / "preview"
    origin_dir = target_dir / "originpro"
    for path in (data_dir, source_dir, preview_dir, origin_dir):
        path.mkdir(parents=True, exist_ok=True)

    source_path = _source_path_for_handoff(manifest, manifest_path)
    copied_source = _copy_source_artifact(source_path, source_dir) if source_path else None
    copied_raw = _copy_raw_archive(manifest, source_dir)
    previews = _copy_previews(manifest, preview_dir)

    render_options = _render_options(manifest)
    graphs = _materialize_graph_tables(source_path, data_dir, render_options)
    project_slug = _slugify(str(run_output.name or "sciplot_origin_project")) or "sciplot_origin_project"
    opju_name = f"SciPlot_{project_slug}.opju"
    intent = {
        "kind": "sciplot_origin_handoff",
        "version": HANDOFF_VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "source_manifest": str(manifest_path),
        "run_output": str(run_output),
        "origin_entrypoint": "originpro/Build_SciPlot_Project.ogs",
        "origin_project": opju_name,
        "copied_source": str(copied_source.relative_to(target_dir)) if copied_source else None,
        "copied_raw": str(copied_raw.relative_to(target_dir)) if copied_raw else None,
        "previews": previews,
        "request": json_safe(manifest.get("request", {})),
        "semantic": json_safe(manifest.get("semantic", {})),
        "result": json_safe(manifest.get("result", {})),
        "graphs": graphs,
        "notes": [
            "SciPlot preprocessed the data; OriginPro receives CSV tables and LabTalk drawing commands.",
            "The generated OGS does not install themes, palettes, or graph templates.",
        ],
    }

    _write_json(target_dir / "sciplot_origin_intent.json", intent)
    _write_labtalk_script(origin_dir / "Build_SciPlot_Project.ogs", intent, render_options)
    _write_windows_runner(target_dir / "Run_in_Origin.cmd")
    _write_readme(target_dir / "README.md", intent)

    package_manifest = {
        "kind": "sciplot_origin_handoff_package",
        "version": HANDOFF_VERSION,
        "path": str(target_dir),
        "source_manifest": str(manifest_path),
        "origin_entrypoint": str(target_dir / "originpro" / "Build_SciPlot_Project.ogs"),
        "windows_runner": str(target_dir / "Run_in_Origin.cmd"),
        "origin_project": str(target_dir / opju_name),
        "graphs": len(graphs),
        "data_files": [graph["data_file"] for graph in graphs],
    }
    _write_json(target_dir / "manifest.json", package_manifest)
    return package_manifest


def _resolve_manifest_path(input_path: Path) -> Path:
    path = input_path.expanduser()
    if path.is_dir():
        path = path / "manifest.json"
    if not path.exists():
        raise FileNotFoundError(f"Origin handoff needs an existing run manifest: {input_path}")
    if path.name != "manifest.json":
        raise ValueError("Origin handoff input must be a SciPlot run output directory or manifest.json.")
    return path.resolve()


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}.")
    return payload


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _resolve_run_output(manifest: dict[str, Any], manifest_path: Path) -> Path:
    output = manifest.get("output")
    if isinstance(output, str) and output.strip():
        path = Path(output).expanduser()
        if not path.is_absolute():
            path = manifest_path.parent / path
        return path.resolve()
    return manifest_path.parent.resolve()


def _path_from_manifest(value: object, *, base: Path) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base / path
    return path


def _source_path_for_handoff(manifest: dict[str, Any], manifest_path: Path) -> Path | None:
    result = manifest.get("result") if isinstance(manifest.get("result"), dict) else {}
    for value in (result.get("processed_source"), result.get("input"), manifest.get("input")):
        path = _path_from_manifest(value, base=manifest_path.parent)
        if path and path.exists():
            return path.resolve()
    return None


def _clear_handoff_dir(path: Path) -> None:
    if not path.exists():
        return
    for name in (
        "data",
        "originpro",
        "preview",
        "source",
        "README.md",
        "Run_in_Origin.cmd",
        "manifest.json",
        "sciplot_origin_intent.json",
    ):
        target = path / name
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()


def _copy_source_artifact(source_path: Path, source_dir: Path) -> Path:
    destination = source_dir / "processed" / source_path.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source_path.is_dir():
        shutil.copytree(source_path, destination, dirs_exist_ok=True)
    else:
        shutil.copy2(source_path, destination)
    return destination


def _copy_raw_archive(manifest: dict[str, Any], source_dir: Path) -> Path | None:
    raw_archive = manifest.get("raw_archive") if isinstance(manifest.get("raw_archive"), dict) else {}
    raw_path = _path_from_manifest(raw_archive.get("path"), base=Path.cwd())
    if not raw_path or not raw_path.exists():
        return None
    destination = source_dir / "raw" / raw_path.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    if raw_path.is_dir():
        shutil.copytree(raw_path, destination, dirs_exist_ok=True)
    else:
        shutil.copy2(raw_path, destination)
    return destination


def _copy_previews(manifest: dict[str, Any], preview_dir: Path) -> list[str]:
    copied: list[str] = []
    figure_values = manifest.get("figures")
    if not isinstance(figure_values, list):
        return copied
    for value in figure_values:
        path = Path(str(value)).expanduser()
        if path.exists() and path.is_file():
            destination = preview_dir / path.name
            shutil.copy2(path, destination)
            copied.append(str(destination.relative_to(preview_dir.parent)))
    return copied


def _render_options(manifest: dict[str, Any]) -> dict[str, Any]:
    request = manifest.get("request") if isinstance(manifest.get("request"), dict) else {}
    result = manifest.get("result") if isinstance(manifest.get("result"), dict) else {}
    options: dict[str, Any] = {}
    semantic = manifest.get("semantic") if isinstance(manifest.get("semantic"), dict) else {}
    semantic_options = semantic.get("render_options") if isinstance(semantic.get("render_options"), dict) else {}
    options.update(semantic_options)
    request_options = request.get("render_options") if isinstance(request.get("render_options"), dict) else {}
    options.update(request_options)
    if "template" not in options and isinstance(result.get("template"), str):
        options["template"] = result["template"]
    return options


def _materialize_graph_tables(
    source_path: Path | None,
    data_dir: Path,
    render_options: dict[str, Any],
) -> list[dict[str, Any]]:
    if not source_path or not source_path.exists() or source_path.is_dir():
        return []
    suffix = source_path.suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        workbook = pd.ExcelFile(source_path)
        sheets = workbook.sheet_names
        preferred = [sheet for sheet in sheets if "comparison" in sheet.casefold()] or sheets[:1]
        graphs: list[dict[str, Any]] = []
        for sheet_name in preferred:
            frame = pd.read_excel(source_path, sheet_name=sheet_name, dtype=object)
            graphs.extend(
                _graphs_from_frame(
                    frame,
                    source_label=sheet_name,
                    data_dir=data_dir,
                    render_options=render_options,
                )
            )
        return graphs
    frame = _read_table(source_path)
    return _graphs_from_frame(frame, source_label=source_path.stem, data_dir=data_dir, render_options=render_options)


def _read_table(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".tsv":
        return pd.read_csv(path, sep="\t", dtype=object)
    return pd.read_csv(path, dtype=object)


def _graphs_from_frame(
    frame: pd.DataFrame,
    *,
    source_label: str,
    data_dir: Path,
    render_options: dict[str, Any],
) -> list[dict[str, Any]]:
    cleaned = frame.dropna(axis=0, how="all").dropna(axis=1, how="all")
    if cleaned.shape[1] < 2:
        return []
    data_start = _first_numeric_data_row(cleaned)
    meta = cleaned.iloc[:data_start]
    data = cleaned.iloc[data_start:].reset_index(drop=True)
    if data.empty:
        return []

    columns = [_strip_pandas_suffix(str(column)) for column in cleaned.columns]
    labels = _metadata_values(meta.iloc[0] if len(meta.index) >= 2 else None, len(columns))
    units = _metadata_values(meta.iloc[-1] if len(meta.index) >= 1 else None, len(columns))
    if _has_repeated_labels(labels):
        return _comparison_graphs(
            data,
            source_label=source_label,
            columns=columns,
            labels=labels,
            units=units,
            data_dir=data_dir,
            render_options=render_options,
        )
    return [_simple_graph(data, source_label, columns, units, data_dir, render_options)]


def _comparison_graphs(
    data: pd.DataFrame,
    *,
    source_label: str,
    columns: list[str],
    labels: list[str],
    units: list[str],
    data_dir: Path,
    render_options: dict[str, Any],
) -> list[dict[str, Any]]:
    sample_order = _unique_nonempty(labels)
    y_metrics = [
        metric
        for metric in _unique_nonempty(columns)
        if not _is_x_metric(metric)
        and any(labels[index] in sample_order and columns[index] == metric for index in range(len(columns)))
    ]
    graphs: list[dict[str, Any]] = []
    for metric in y_metrics:
        table = pd.DataFrame()
        x_label = ""
        x_unit = ""
        y_unit = ""
        series_labels: list[str] = []
        for sample in sample_order:
            indices = [index for index, label in enumerate(labels) if label == sample]
            x_index = _x_index_for_group(indices, columns)
            y_index = next((index for index in indices if columns[index] == metric), None)
            if x_index is None or y_index is None:
                continue
            if table.empty:
                x_label = columns[x_index]
                x_unit = units[x_index]
                table["X"] = _numeric_series(data.iloc[:, x_index])
            table[sample] = _numeric_series(data.iloc[:, y_index])
            y_unit = y_unit or units[y_index]
            series_labels.append(sample)
        if not table.empty and len(table.columns) >= 2:
            graphs.append(
                _write_graph_table(
                    table,
                    source_label=source_label,
                    y_label=metric,
                    x_label=x_label or "X",
                    x_unit=x_unit,
                    y_unit=y_unit,
                    series_labels=series_labels,
                    data_dir=data_dir,
                    render_options=render_options,
                )
            )
    return graphs or [_simple_graph(data, source_label, columns, units, data_dir, render_options)]


def _simple_graph(
    data: pd.DataFrame,
    source_label: str,
    columns: list[str],
    units: list[str],
    data_dir: Path,
    render_options: dict[str, Any],
) -> dict[str, Any]:
    x_index = next((index for index, column in enumerate(columns) if _is_x_metric(column)), 0)
    table = pd.DataFrame({"X": _numeric_series(data.iloc[:, x_index])})
    series_labels: list[str] = []
    y_units: list[str] = []
    for index, column in enumerate(columns):
        if index == x_index:
            continue
        values = _numeric_series(data.iloc[:, index])
        if values.notna().any():
            label = column or f"Y{index}"
            table[label] = values
            series_labels.append(label)
            y_units.append(units[index])
    if len(table.columns) < 2:
        raise ValueError("Origin handoff could not find numeric Y columns in the processed source.")
    y_label = "Value" if len(series_labels) > 1 else series_labels[0]
    return _write_graph_table(
        table,
        source_label=source_label,
        y_label=y_label,
        x_label=columns[x_index] or "X",
        x_unit=units[x_index],
        y_unit=next((unit for unit in y_units if unit), ""),
        series_labels=series_labels,
        data_dir=data_dir,
        render_options=render_options,
    )


def _write_graph_table(
    table: pd.DataFrame,
    *,
    source_label: str,
    y_label: str,
    x_label: str,
    x_unit: str,
    y_unit: str,
    series_labels: list[str],
    data_dir: Path,
    render_options: dict[str, Any],
) -> dict[str, Any]:
    table = table.dropna(axis=0, how="all")
    graph_id = _slugify(f"{source_label}_{y_label}") or "graph"
    filename = f"{graph_id}.csv"
    table.to_csv(data_dir / filename, index=False, encoding="utf-8-sig")
    return {
        "id": graph_id,
        "title": _title_from_parts(source_label, y_label),
        "source_label": source_label,
        "data_file": f"data/{filename}",
        "columns": [str(column) for column in table.columns],
        "x_column": "X",
        "y_columns": [str(column) for column in table.columns[1:]],
        "x_label": x_label,
        "x_unit": x_unit,
        "y_label": y_label,
        "y_unit": y_unit,
        "series_labels": series_labels,
        "render_options": {
            key: render_options[key]
            for key in (
                "size",
                "xscale",
                "yscale",
                "reverse_x",
                "reverse_y",
                "legend_position",
                "style_preset",
                "palette_preset",
            )
            if key in render_options
        },
    }


def _first_numeric_data_row(frame: pd.DataFrame) -> int:
    for index in range(len(frame.index)):
        values = frame.iloc[index]
        numeric_count = sum(_is_number(value) for value in values)
        if numeric_count >= min(2, len(values)):
            return index
    return 0


def _metadata_values(row: pd.Series | None, width: int) -> list[str]:
    if row is None:
        return ["" for _ in range(width)]
    values = []
    for index in range(width):
        value = row.iloc[index] if index < len(row.index) else ""
        values.append(_clean_cell(value))
    return values


def _has_repeated_labels(labels: list[str]) -> bool:
    nonempty = [label for label in labels if label]
    return len(set(nonempty)) < len(nonempty) and len(set(nonempty)) >= 2


def _unique_nonempty(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered


def _x_index_for_group(indices: list[int], columns: list[str]) -> int | None:
    for index in indices:
        if _is_x_metric(columns[index]):
            return index
    return indices[0] if indices else None


def _numeric_series(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _is_number(value: object) -> bool:
    try:
        if value is None or pd.isna(value):
            return False
        float(value)
    except (TypeError, ValueError):
        return False
    return True


def _clean_cell(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def _strip_pandas_suffix(value: str) -> str:
    return re.sub(r"\.\d+$", "", value).strip()


def _is_x_metric(value: str) -> bool:
    normalized = value.strip().casefold()
    return any(token in normalized for token in ("time", "frequency", "temperature", "strain", "x"))


def _title_from_parts(source_label: str, y_label: str) -> str:
    if source_label and y_label and y_label.casefold() not in source_label.casefold():
        return f"{source_label} - {y_label}"
    return source_label or y_label or "SciPlot graph"


def _slugify(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").lower()
    return re.sub(r"_+", "_", slug)


def _write_labtalk_script(path: Path, intent: dict[str, Any], render_options: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    graphs = intent.get("graphs") if isinstance(intent.get("graphs"), list) else []
    project_name = str(intent.get("origin_project") or "SciPlot_origin.opju")
    lines = [
        "// SciPlot OriginPro handoff script.",
        "// Generated as per-run LabTalk commands; it does not install themes or templates.",
        "// Run from Origin with:",
        '//   run.section("C:\\path\\originpro\\Build_SciPlot_Project.ogs", Main, "C:\\path\\to\\handoff\\");',
        "",
        "[Main]",
        'type -a "Building SciPlot OriginPro project from handoff package.";',
        "",
    ]
    if not graphs:
        lines.extend(
            [
                'type -b "No numeric graph tables were generated. Check sciplot_origin_intent.json.";',
                "return 0;",
                "",
            ]
        )
    for index, graph in enumerate(graphs, start=1):
        lines.extend(_graph_labtalk_lines(graph, index=index, render_options=render_options))
    lines.extend(
        [
            "",
            f'save -dix "%1{_lt_string(project_name)}";',
            f'type -a "Saved Origin project: %1{_lt_string(project_name)}";',
            'type -b "SciPlot Origin handoff complete.";',
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def _graph_labtalk_lines(graph: dict[str, Any], *, index: int, render_options: dict[str, Any]) -> list[str]:
    data_file = str(graph["data_file"]).replace("/", "\\")
    column_count = len(graph.get("columns", []))
    y_range = "2" if column_count == 2 else f"2:{column_count}"
    title = _lt_string(str(graph.get("title") or f"SciPlot Graph {index}"))
    x_title = _axis_title(str(graph.get("x_label") or "X"), str(graph.get("x_unit") or ""))
    y_title = _axis_title(str(graph.get("y_label") or "Y"), str(graph.get("y_unit") or ""))
    lines = [
        f"// Graph {index}: {title}",
        "newbook;",
        f'wbook.name$ = "SciPlot_Data_{index}";',
        f'impASC fname:="%1{_lt_string(data_file)}";',
        f"plotxy iy:=(1,{y_range}) plot:=202 ogl:=<new>;",
        f'page.longname$ = "{title}";',
        f'label -xb "{_lt_string(x_title)}";',
        f'label -yl "{_lt_string(y_title)}";',
        "legend -r;",
        *_size_labtalk_lines(str(render_options.get("size") or graph.get("render_options", {}).get("size") or "")),
        *_axis_labtalk_lines(render_options),
        *_series_style_labtalk_lines(graph, render_options),
        "",
    ]
    return lines


def _axis_title(label: str, unit: str) -> str:
    return f"{label} ({unit})" if unit else label


def _size_labtalk_lines(size_id: str) -> list[str]:
    if size_id not in SIZE_PRESETS_MM:
        return []
    width, height = SIZE_PRESETS_MM[size_id]
    layer_width = width - DEFAULT_FRAME_MM["left"] - DEFAULT_FRAME_MM["right"]
    layer_height = height - DEFAULT_FRAME_MM["top"] - DEFAULT_FRAME_MM["bottom"]
    return [
        f"// SciPlot size preset: {size_id}",
        f"double _sciplotPageW = {width} / 25.4 * page.resx;",
        f"double _sciplotPageH = {height} / 25.4 * page.resy;",
        "page -ps W $(_sciplotPageW);",
        "page -ps H $(_sciplotPageH);",
        "page -afu1;",
        "layer.unit = 4;",
        f"layer.left = {DEFAULT_FRAME_MM['left']};",
        f"layer.top = {DEFAULT_FRAME_MM['top']};",
        f"layer.width = {layer_width};",
        f"layer.height = {layer_height};",
    ]


def _axis_labtalk_lines(render_options: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    if str(render_options.get("xscale") or "").casefold() == "log":
        lines.append("layer.x.type = 2;")
    if str(render_options.get("yscale") or "").casefold() == "log":
        lines.append("layer.y.type = 2;")
    if render_options.get("reverse_x") is True:
        lines.append("layer.x.reverse = 1;")
    if render_options.get("reverse_y") is True:
        lines.append("layer.y.reverse = 1;")
    tick_count = render_options.get("tick_count")
    if isinstance(tick_count, int | float) and tick_count > 0:
        lines.append(f"layer.x.ticks = {int(tick_count)};")
        lines.append(f"layer.y.ticks = {int(tick_count)};")
    return lines


def _series_style_labtalk_lines(graph: dict[str, Any], render_options: dict[str, Any]) -> list[str]:
    labels = [str(label) for label in graph.get("y_columns", [])]
    style_by_series = {
        str(item.get("series_id") or ""): item
        for item in render_options.get("series_styles", [])
        if isinstance(item, dict)
    }
    lines = [
        "int _sciplotPlotIndex = 0;",
        "doc -e D {",
        "    _sciplotPlotIndex++;",
    ]
    for index, label in enumerate(labels, start=1):
        style = style_by_series.get(label, {})
        color = _rgb_from_hex(str(style.get("color") or ""))
        line_width = style.get("line_width") or render_options.get("line_width")
        marker_size = style.get("marker_size") or render_options.get("marker_size")
        if not color and line_width is None and marker_size is None:
            continue
        lines.append(f"    if(_sciplotPlotIndex == {index}) {{")
        if color:
            red, green, blue = color
            lines.append(f"        set %C -c color({red},{green},{blue});")
            lines.append(f"        set %C -cl color({red},{green},{blue});")
            lines.append(f"        set %C -csf color({red},{green},{blue});")
        if isinstance(line_width, int | float):
            lines.append(f"        set %C -w {round(float(line_width) * 500)};")
        if isinstance(marker_size, int | float):
            lines.append(f"        set %C -z {float(marker_size)};")
        lines.append("    };")
    lines.append("};")
    return lines


def _rgb_from_hex(value: str) -> tuple[int, int, int] | None:
    text = value.strip().lstrip("#")
    if not re.fullmatch(r"[0-9A-Fa-f]{6}", text):
        return None
    return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)


def _lt_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', "'")


def _write_windows_runner(path: Path) -> None:
    text = r"""@echo off
chcp 65001 >NUL
setlocal
set "ROOT=%~dp0"
set "ORIGIN_EXE=%~1"
if "%ORIGIN_EXE%"=="" set "ORIGIN_EXE=Origin64.exe"

echo Running SciPlot Origin handoff from:
echo   %ROOT%
echo.
echo If Origin64.exe is not on PATH, rerun this file with the full Origin64.exe path as the first argument.
echo.
"%ORIGIN_EXE%" -rs run.section("%ROOT%originpro\Build_SciPlot_Project.ogs", Main, "%ROOT%")
if errorlevel 1 (
  echo.
  echo Origin handoff failed. You can also run this manually inside Origin:
  echo run.section("%ROOT%originpro\Build_SciPlot_Project.ogs", Main, "%ROOT%")
  pause
  exit /b 1
)
echo.
echo Origin handoff complete.
pause
"""
    path.write_text(text, encoding="utf-8", newline="\r\n")


def _write_readme(path: Path, intent: dict[str, Any]) -> None:
    graph_count = len(intent.get("graphs", [])) if isinstance(intent.get("graphs"), list) else 0
    lines = [
        "# SciPlot OriginPro Handoff",
        "",
        "This package contains SciPlot-processed data and a generated OriginPro LabTalk script.",
        "It does not install Origin themes, palettes, or templates.",
        "",
        "## Run",
        "",
        "On a Windows machine with OriginPro installed, double-click:",
        "",
        "```text",
        "Run_in_Origin.cmd",
        "```",
        "",
        "If Origin is not on PATH, run the command file with the full path to `Origin64.exe` as the first argument.",
        "",
        "Manual Origin command:",
        "",
        "```text",
        'run.section("C:\\path\\to\\originpro\\Build_SciPlot_Project.ogs", Main, "C:\\path\\to\\handoff\\")',
        "```",
        "",
        "## Contents",
        "",
        f"- Graph tables: {graph_count}",
        f"- Origin script: `{intent['origin_entrypoint']}`",
        f"- Expected Origin project: `{intent['origin_project']}`",
        "- Audit intent: `sciplot_origin_intent.json`",
        "- SciPlot previews: `preview/`",
        "- Copied processed/raw sources: `source/`",
        "",
        "SciPlot has already preprocessed the source data.",
        "OriginPro receives CSV tables plus explicit drawing commands.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


__all__ = ["export_origin_handoff"]
