from __future__ import annotations

import csv
import json
import math
import re
from io import StringIO
from pathlib import Path
from typing import Any

import pandas as pd

from sciplot_core._utils import decode_text, existing_file_sha256, slug

_TABLE_SUFFIXES = {".csv", ".tsv", ".txt", ".tab", ".dat", ".xlsx", ".xls"}
_UNIT_SUFFIXES = (
    "MPa",
    "kPa",
    "Pa",
    "mN",
    "Nm",
    "N",
    "mm",
    "um",
    "μm",
    "µm",
    "cm",
    "m",
    "°C",
    "C",
    "K",
    "s",
    "h",
    "%",
    "1",
)


def build_plot_data_exports(manifest: dict[str, Any], *, destination: Path) -> list[dict[str, Any]]:
    """Write the user-facing four-row CSV for the current plotted data.

    The delivery surface intentionally contains data only, never analysis
    metrics, raw archives, manifests, or renderer diagnostics.  A persisted
    processed source is preferred because it is the exact table selected for
    the plot.  When a source table is unavailable, the saved Veusz spec is the
    next-best deterministic source and preserves the plotted series values.
    """

    destination = destination.expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    project_name = _project_name(manifest)

    source = _data_source(manifest)
    source_table = _load_source_table(source) if source is not None else None
    if source_table is not None and not source_table.empty:
        output = destination / f"{project_name}_plot_data.csv"
        _write_four_row_csv(source_table, output, sample_hint=_sample_hint(manifest, source))
        return [_data_record(output, source=source, source_kind="processed_source")]

    records: list[dict[str, Any]] = []
    for index, spec_path in enumerate(_spec_paths(manifest), start=1):
        spec = _read_json(spec_path)
        table = _spec_to_table(spec, manifest=manifest, spec_path=spec_path)
        if table is None or table.empty:
            continue
        stem = project_name if index == 1 else f"{project_name}_{index:02d}"
        output = destination / f"{stem}_plot_data.csv"
        _write_table_csv(table, output)
        records.append(_data_record(output, source=spec_path, source_kind="veusz_spec"))
    return records


def _project_name(manifest: dict[str, Any]) -> str:
    output = manifest.get("output")
    if isinstance(output, str) and output.strip():
        return slug(Path(output).name)
    return slug(str(manifest.get("project") or "sciplot"))


def _data_source(manifest: dict[str, Any]) -> Path | None:
    result = manifest.get("result") if isinstance(manifest.get("result"), dict) else {}
    values: list[object] = [
        result.get("processed_source"),
        result.get("data_snapshot_source"),
        manifest.get("processed_source"),
        manifest.get("input"),
    ]
    request = manifest.get("request") if isinstance(manifest.get("request"), dict) else {}
    values.append(request.get("input"))
    for value in values:
        if not isinstance(value, str) or not value.strip():
            continue
        candidate = Path(value).expanduser()
        if candidate.exists():
            return candidate.resolve()
    return None


def _load_source_table(source: Path | None) -> pd.DataFrame | None:
    if source is None:
        return None
    if source.is_dir():
        files = sorted(path for path in source.rglob("*") if path.is_file() and path.suffix.casefold() in _TABLE_SUFFIXES)
        if len(files) != 1:
            preferred = [
                path
                for path in files
                if any(token in path.stem.casefold() for token in ("comparison", "plotting", "prepared", "processed"))
            ]
            if len(preferred) != 1:
                return None
            files = preferred
        source = files[0] if files else None
    if source is None or not source.exists() or not source.is_file():
        return None
    suffix = source.suffix.casefold()
    try:
        if suffix in {".xlsx", ".xls"}:
            return pd.read_excel(source, sheet_name=0, header=None)
        text = decode_text(source)
        for index, line in enumerate(text.splitlines()):
            if "Interval data:" in line:
                header = line.split("Interval data:", maxsplit=1)[1].lstrip("\t, ")
                return pd.read_csv(
                    StringIO("\n".join([header, *text.splitlines()[index + 1 :]])),
                    sep="\t",
                    header=None,
                    engine="python",
                )
        tab_count = text.count("\t")
        comma_count = text.count(",")
        separator = "\t" if suffix in {".tsv", ".tab", ".dat"} or tab_count > comma_count else ","
        return pd.read_csv(StringIO(text), sep=separator, header=None, engine="python")
    except (OSError, ValueError, TypeError, pd.errors.ParserError):
        return None


def _spec_paths(manifest: dict[str, Any]) -> list[Path]:
    result = manifest.get("result") if isinstance(manifest.get("result"), dict) else {}
    values: list[object] = []
    values.extend(manifest.get("veusz_specs", []) if isinstance(manifest.get("veusz_specs"), list) else [])
    values.extend([manifest.get("veusz_spec"), result.get("veusz_spec")])
    paths: list[Path] = []
    seen: set[Path] = set()
    for value in values:
        if not isinstance(value, str) or not value.strip():
            continue
        path = Path(value).expanduser().resolve()
        if path in seen or not path.is_file():
            continue
        paths.append(path)
        seen.add(path)
    return paths


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _sample_hint(manifest: dict[str, Any], source: Path | None) -> str:
    semantic = manifest.get("semantic") if isinstance(manifest.get("semantic"), dict) else {}
    samples = semantic.get("samples") if isinstance(semantic.get("samples"), list) else []
    names = [str(item.get("name")) for item in samples if isinstance(item, dict) and str(item.get("name") or "").strip()]
    if len(names) == 1:
        return names[0]
    if source is not None and source.is_file():
        return source.stem
    if source is not None and source.is_dir() and source.name not in {"source", "processed", "studio"}:
        return source.name
    return ""


def _write_four_row_csv(table: pd.DataFrame, output: Path, *, sample_hint: str) -> None:
    normalized = table.copy()
    if not _looks_like_four_row_table(normalized):
        names = [str(value).strip() for value in normalized.iloc[0].tolist()] if not normalized.empty else []
        units = [_unit_from_label(value) for value in names]
        comments = [sample_hint] * len(names)
        normalized = pd.DataFrame([names, units, comments, *normalized.iloc[1:].values.tolist()])
    _write_table_csv(normalized, output)


def _looks_like_four_row_table(table: pd.DataFrame) -> bool:
    if table.shape[0] < 4 or table.shape[1] < 1:
        return False
    data = table.iloc[3:].apply(pd.to_numeric, errors="coerce")
    numeric_count = int(data.notna().sum().sum())
    if numeric_count < 2:
        return False
    first_rows = table.iloc[:3].fillna("").astype(str)
    return bool(first_rows.iloc[0].str.strip().any()) and bool(first_rows.iloc[2].str.strip().any())


def _spec_to_table(spec: dict[str, Any], *, manifest: dict[str, Any], spec_path: Path) -> pd.DataFrame | None:
    series = spec.get("series") if isinstance(spec.get("series"), list) else []
    if series:
        x_name, x_unit = _axis_descriptor(spec, manifest=manifest, axis="x")
        y_name, y_unit = _axis_descriptor(spec, manifest=manifest, axis="y")
        values: list[tuple[list[Any], list[Any], str]] = []
        for item in series:
            if not isinstance(item, dict):
                continue
            x_values = item.get("x_values") if isinstance(item.get("x_values"), list) else []
            y_values = item.get("y_values") if isinstance(item.get("y_values"), list) else []
            if not x_values or not y_values:
                continue
            label = str(item.get("label") or item.get("name") or "").strip()
            values.append((x_values, y_values, label))
        if not values:
            return None
        rows: list[list[Any]] = [[x_name, y_name] * len(values), [x_unit, y_unit] * len(values)]
        rows.append([label for _x, _y, label in values for _ in (0, 1)])
        for row_index in range(max(max(len(x), len(y)) for x, y, _label in values)):
            row: list[Any] = []
            for x_values, y_values, _label in values:
                row.extend(
                    [
                        x_values[row_index] if row_index < len(x_values) else "",
                        y_values[row_index] if row_index < len(y_values) else "",
                    ]
                )
            rows.append(row)
        return pd.DataFrame(rows)

    scalar = spec.get("scalar_field") if isinstance(spec.get("scalar_field"), dict) else {}
    x_values = scalar.get("x_values") if isinstance(scalar.get("x_values"), list) else []
    y_values = scalar.get("y_values") if isinstance(scalar.get("y_values"), list) else []
    z_values = scalar.get("z_values") if isinstance(scalar.get("z_values"), list) else []
    if not x_values or not y_values or not z_values:
        return None
    x_name, x_unit = _variable_descriptor(scalar.get("x_column"), fallback="x")
    y_name, y_unit = _variable_descriptor(scalar.get("y_column"), fallback="y")
    z_name, z_unit = _variable_descriptor(scalar.get("z_column"), fallback="z")
    sample = _sample_hint(manifest, spec_path.parent)
    rows: list[list[Any]] = [[x_name, y_name, z_name], [x_unit, y_unit, z_unit], [sample, sample, sample]]
    for y_index, y_value in enumerate(y_values):
        row_values = z_values[y_index] if y_index < len(z_values) and isinstance(z_values[y_index], list) else []
        for x_index, x_value in enumerate(x_values):
            z_value = row_values[x_index] if x_index < len(row_values) else ""
            rows.append([x_value, y_value, z_value])
    return pd.DataFrame(rows)


def _axis_descriptor(spec: dict[str, Any], *, manifest: dict[str, Any], axis: str) -> tuple[str, str]:
    semantic = manifest.get("semantic") if isinstance(manifest.get("semantic"), dict) else {}
    axis_plan = semantic.get("axis_plan") if isinstance(semantic.get("axis_plan"), dict) else {}
    axis_payload = axis_plan.get(axis) if isinstance(axis_plan.get(axis), dict) else {}
    unit_plan = semantic.get("unit_plan") if isinstance(semantic.get("unit_plan"), dict) else {}
    canonical_name = str(axis_payload.get("canonical_label") or "").strip()
    canonical_unit = str(unit_plan.get(axis) or axis_payload.get("canonical_unit") or "").strip()
    if canonical_name:
        return canonical_name, _display_unit(canonical_unit)
    axes = spec.get("axes") if isinstance(spec.get("axes"), dict) else {}
    axis_spec = axes.get(axis) if isinstance(axes.get(axis), dict) else {}
    return _split_label_unit(axis_spec.get("label"), fallback=axis)


def _variable_descriptor(value: object, *, fallback: str) -> tuple[str, str]:
    text = str(value or "").strip()
    if not text:
        return fallback, ""
    return _split_label_unit(text.replace("_", " "), fallback=fallback)


def _split_label_unit(value: object, *, fallback: str) -> tuple[str, str]:
    text = str(value or "").strip()
    if not text:
        return fallback, ""
    match = re.match(r"^(.*?)\s*\(([^()]*)\)\s*$", text)
    if match:
        return match.group(1).strip() or fallback, _display_unit(match.group(2).strip())
    for unit in _UNIT_SUFFIXES:
        if text.endswith(f"_{unit}") or text.endswith(f" {unit}"):
            return text[: -(len(unit) + 1)].replace("_", " ").strip() or fallback, _display_unit(unit)
    return text.replace("_", " "), ""


def _unit_from_label(value: object) -> str:
    text = str(value or "").strip()
    match = re.match(r"^(.*?)\s*\(([^()]*)\)\s*$", text)
    return _display_unit(match.group(2).strip()) if match else ""


def _display_unit(value: object) -> str:
    text = str(value or "").strip()
    return {"C": "°C", "um": "μm", "µm": "μm"}.get(text, text)


def _write_table_csv(table: pd.DataFrame, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    rows = table.fillna("").astype(object).values.tolist()
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        for row in rows:
            writer.writerow([_format_cell(value) for value in row])


def _format_cell(value: object) -> object:
    if value is None:
        return ""
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return ""
        return format(value, ".15g")
    return value


def _data_record(path: Path, *, source: Path | None, source_kind: str) -> dict[str, Any]:
    return {
        "path": str(path),
        "relative_path": str(Path("data") / path.name),
        "format": "csv",
        "source": str(source) if source is not None else None,
        "source_kind": source_kind,
        "exists": path.exists(),
        "sha256": existing_file_sha256(path),
    }


__all__ = ["build_plot_data_exports"]
