"""Deterministic material-performance scatter and radar preparation.

The input contract is one tidy table.  Scientific values and literature
metadata remain source-bound; this module only validates, pivots, normalizes
declared radar scales, and derives presentation geometry for the production
Veusz document builder.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from sciplot_core._utils import decode_text, file_sha256, json_safe
from sciplot_core.policy import (
    DEFAULT_PALETTE_COLORS,
    PERFORMANCE_ENVELOPE_FILL_TRANSPARENCY,
    PERFORMANCE_ENVELOPE_LINE_TRANSPARENCY,
    PERFORMANCE_ENVELOPE_PADDING_FRACTION,
    PERFORMANCE_MARKERS,
    PERFORMANCE_PANEL_HEIGHT_MM,
    PERFORMANCE_PANEL_WIDTH_MM,
    PERFORMANCE_REFERENCE_COLOR,
    PERFORMANCE_REFERENCE_PANEL_WIDTH_MM,
    PERFORMANCE_SAMPLE_FILL_TRANSPARENCY,
    UNIFIED_BOTTOM_MARGIN_MM,
    UNIFIED_LEFT_MARGIN_MM,
    UNIFIED_RIGHT_MARGIN_MM,
    UNIFIED_TOP_MARGIN_MM,
    categorical_fill_color,
)

PERFORMANCE_COMPARISON_RULE_ID = "performance_comparison"
PERFORMANCE_SCATTER_TEMPLATE_ID = "scatter"
PERFORMANCE_RADAR_TEMPLATE_ID = "polar_curve"


class PerformanceComparisonError(ValueError):
    """Fail-closed source-contract error for performance comparisons."""

    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(message)


@dataclass(frozen=True)
class PerformanceMetric:
    metric_id: str
    display_label: str
    unit: str
    source_order: int
    scatter_axis: str | None = None
    radar_order: int | None = None
    direction: str | None = None
    scale_min: float | None = None
    scale_max: float | None = None

    @property
    def axis_label(self) -> str:
        return (
            f"{self.display_label} ({_display_unit(self.unit)})"
            if self.unit
            else self.display_label
        )

    @property
    def radar_label(self) -> str:
        arrow = "↑" if self.direction == "higher" else "↓"
        return f"{self.display_label} {arrow}"


@dataclass(frozen=True)
class PerformanceMaterial:
    material_id: str
    role: str
    group: str
    source_order: int
    material_order: float | None
    journal: str
    year: str
    doi: str
    marker: str | None
    values: dict[str, float]

    @property
    def citation(self) -> str:
        if self.journal and self.year:
            return f"{self.journal} ({self.year})"
        return self.journal or self.year


@dataclass(frozen=True)
class PerformanceComparison:
    source: Path
    source_sha256: str
    source_row_count: int
    metrics: tuple[PerformanceMetric, ...]
    materials: tuple[PerformanceMaterial, ...]

    @property
    def samples(self) -> tuple[PerformanceMaterial, ...]:
        return tuple(item for item in self.materials if item.role == "sample")

    @property
    def references(self) -> tuple[PerformanceMaterial, ...]:
        return tuple(item for item in self.materials if item.role == "reference")

    @property
    def scatter_metrics(self) -> tuple[PerformanceMetric, PerformanceMetric]:
        x_metrics = [item for item in self.metrics if item.scatter_axis == "x"]
        y_metrics = [item for item in self.metrics if item.scatter_axis == "y"]
        if len(x_metrics) != 1 or len(y_metrics) != 1:
            raise PerformanceComparisonError(
                "performance_scatter_axes_invalid",
                "Performance scatter data need exactly one metric marked x and "
                "one metric marked y in the ScatterAxis column.",
            )
        return x_metrics[0], y_metrics[0]

    @property
    def radar_metrics(self) -> tuple[PerformanceMetric, ...]:
        metrics = sorted(
            (item for item in self.metrics if item.radar_order is not None),
            key=lambda item: (int(item.radar_order or 0), item.source_order),
        )
        if len(metrics) < 3:
            raise PerformanceComparisonError(
                "performance_radar_needs_three_metrics",
                "Performance radar data need at least three metrics with a "
                "RadarOrder value.",
            )
        orders = [int(item.radar_order or 0) for item in metrics]
        if len(orders) != len(set(orders)):
            raise PerformanceComparisonError(
                "performance_radar_order_duplicate",
                "RadarOrder values must be unique across radar metrics.",
            )
        return tuple(metrics)


_HEADER_ALIASES: dict[str, frozenset[str]] = {
    "material": frozenset(
        {
            "material",
            "materialid",
            "materialname",
            "sample",
            "samplename",
            "材料",
            "样品",
            "样品名称",
        }
    ),
    "role": frozenset({"role", "datarole", "sourcetype", "角色", "类型"}),
    "group": frozenset(
        {"group", "samplegroup", "envelopegroup", "组", "样品组", "包络组"}
    ),
    "metric": frozenset(
        {"metric", "metricid", "property", "propertyid", "指标", "性能", "性能指标"}
    ),
    "value": frozenset({"value", "measurement", "数值", "值", "测试值"}),
    "unit": frozenset({"unit", "units", "单位"}),
    "display_label": frozenset(
        {"displaylabel", "metriclabel", "propertylabel", "显示名", "指标名称"}
    ),
    "scatter_axis": frozenset(
        {"scatteraxis", "axis", "xyaxis", "散点轴", "坐标轴"}
    ),
    "radar_order": frozenset(
        {"radarorder", "radaraxisorder", "雷达顺序", "雷达轴顺序"}
    ),
    "direction": frozenset(
        {"direction", "preferreddirection", "better", "方向", "优选方向"}
    ),
    "scale_min": frozenset(
        {"scalemin", "radarmin", "normalizationmin", "归一化下限", "雷达下限"}
    ),
    "scale_max": frozenset(
        {"scalemax", "radarmax", "normalizationmax", "归一化上限", "雷达上限"}
    ),
    "journal": frozenset({"journal", "publication", "期刊", "出版物"}),
    "year": frozenset({"year", "publicationyear", "年份", "发表年份"}),
    "doi": frozenset({"doi"}),
    "material_order": frozenset(
        {"materialorder", "sampleorder", "legendorder", "材料顺序", "图例顺序"}
    ),
    "marker": frozenset({"marker", "symbol", "标记", "符号"}),
}
_REQUIRED_COLUMNS = frozenset({"material", "role", "metric", "value", "unit"})
_ROLE_ALIASES = {
    "sample": "sample",
    "self": "sample",
    "own": "sample",
    "thiswork": "sample",
    "oursample": "sample",
    "样品": "sample",
    "自有样品": "sample",
    "本工作": "sample",
    "reference": "reference",
    "ref": "reference",
    "literature": "reference",
    "benchmark": "reference",
    "参考": "reference",
    "文献": "reference",
    "对照材料": "reference",
}
_DIRECTION_ALIASES = {
    "higher": "higher",
    "high": "higher",
    "maximize": "higher",
    "larger": "higher",
    "up": "higher",
    "越大越好": "higher",
    "高": "higher",
    "lower": "lower",
    "low": "lower",
    "minimize": "lower",
    "smaller": "lower",
    "down": "lower",
    "越小越好": "lower",
    "低": "lower",
}


def _token(value: object) -> str:
    return re.sub(r"[\W_]+", "", str(value or "").strip().casefold())


def _text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def _year_text(value: str) -> str:
    """Undo spreadsheet integer years materialized as decimal-looking text."""

    return re.sub(r"^(\d{4})\.0$", r"\1", value)


def _display_unit(value: str) -> str:
    superscript_map = str.maketrans(
        {
            "0": "⁰",
            "1": "¹",
            "2": "²",
            "3": "³",
            "4": "⁴",
            "5": "⁵",
            "6": "⁶",
            "7": "⁷",
            "8": "⁸",
            "9": "⁹",
            "+": "⁺",
            "-": "⁻",
            "−": "⁻",
        }
    )
    return re.sub(
        r"\^([+\-−]?\d+)",
        lambda match: match.group(1).translate(superscript_map),
        value,
    )


def _finite_float(value: object, *, field: str, row_number: int) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise PerformanceComparisonError(
            "performance_numeric_value_invalid",
            f"Row {row_number}: {field} must be numeric.",
        ) from exc
    if not math.isfinite(number):
        raise PerformanceComparisonError(
            "performance_numeric_value_nonfinite",
            f"Row {row_number}: {field} must be finite.",
        )
    return number


def _optional_float(value: object, *, field: str, row_number: int) -> float | None:
    if not _text(value):
        return None
    return _finite_float(value, field=field, row_number=row_number)


def _resolve_source(source: Path) -> Path:
    resolved = source.expanduser().resolve()
    if resolved.is_file():
        return resolved
    if not resolved.is_dir():
        raise FileNotFoundError(f"Performance comparison source not found: {resolved}")
    candidates = [
        path
        for path in sorted(resolved.rglob("*"))
        if path.is_file()
        and path.suffix.casefold() in {".csv", ".tsv", ".txt", ".xlsx", ".xls"}
    ]
    matching = [path for path in candidates if _source_has_required_headers(path)]
    if len(matching) != 1:
        raise PerformanceComparisonError(
            "performance_source_ambiguous",
            "Performance comparison directories need exactly one tidy table "
            f"with the required headers; found {len(matching)}.",
        )
    return matching[0]


def _read_text_table(path: Path) -> pd.DataFrame:
    text = decode_text(path)
    tab_count = text.count("\t")
    comma_count = text.count(",")
    separator: str | None
    if path.suffix.casefold() == ".tsv" or tab_count > comma_count:
        separator = "\t"
    elif path.suffix.casefold() == ".csv" or comma_count:
        separator = ","
    else:
        separator = None
    from io import StringIO

    return pd.read_csv(StringIO(text), sep=separator, engine="python")


def _read_source_frame(path: Path) -> pd.DataFrame:
    if path.suffix.casefold() in {".xlsx", ".xls"}:
        sheets = pd.read_excel(path, sheet_name=None)
        matching = [
            frame
            for frame in sheets.values()
            if _required_headers_present(frame.columns)
        ]
        if len(matching) != 1:
            raise PerformanceComparisonError(
                "performance_workbook_sheet_ambiguous",
                "Performance comparison workbooks need exactly one sheet with "
                f"the required headers; found {len(matching)}.",
            )
        return matching[0]
    return _read_text_table(path)


def _canonical_header_map(columns: Any) -> dict[str, object]:
    resolved: dict[str, object] = {}
    for column in columns:
        token = _token(column)
        matches = [
            field for field, aliases in _HEADER_ALIASES.items() if token in aliases
        ]
        if len(matches) > 1:
            raise PerformanceComparisonError(
                "performance_header_ambiguous",
                f"Column {column!r} matches multiple performance fields: {matches}.",
            )
        if not matches:
            continue
        field = matches[0]
        if field in resolved:
            raise PerformanceComparisonError(
                "performance_header_duplicate",
                f"Multiple columns map to the performance field {field!r}.",
            )
        resolved[field] = column
    return resolved


def _required_headers_present(columns: Any) -> bool:
    try:
        return _REQUIRED_COLUMNS <= set(_canonical_header_map(columns))
    except PerformanceComparisonError:
        return False


def _source_has_required_headers(path: Path) -> bool:
    try:
        if path.suffix.casefold() in {".xlsx", ".xls"}:
            sheets = pd.read_excel(path, sheet_name=None, nrows=1)
            return sum(
                _required_headers_present(frame.columns) for frame in sheets.values()
            ) == 1
        return _required_headers_present(_read_text_table(path).columns)
    except Exception:
        return False


def is_performance_comparison_source(source: str | Path) -> bool:
    """Return whether a path has the explicit tidy comparison header contract."""

    path = Path(source).expanduser()
    if path.is_file():
        return _source_has_required_headers(path)
    if not path.is_dir():
        return False
    matches = [
        item
        for item in sorted(path.rglob("*"))
        if item.is_file()
        and item.suffix.casefold() in {".csv", ".tsv", ".txt", ".xlsx", ".xls"}
        and _source_has_required_headers(item)
    ]
    return len(matches) == 1


def _unique_text(
    frame: pd.DataFrame,
    column: object | None,
    *,
    field: str,
    owner: str,
    default: str = "",
) -> str:
    if column is None:
        return default
    values = list(dict.fromkeys(_text(value) for value in frame[column] if _text(value)))
    if len(values) > 1:
        raise PerformanceComparisonError(
            "performance_metadata_conflict",
            f"{owner} has conflicting {field} values: {values}.",
        )
    return values[0] if values else default


def _unique_float(
    frame: pd.DataFrame,
    column: object | None,
    *,
    field: str,
    owner: str,
) -> float | None:
    if column is None:
        return None
    values: list[float] = []
    for index, value in frame[column].items():
        parsed = _optional_float(
            value,
            field=field,
            row_number=int(index) + 2,
        )
        if parsed is not None and not any(math.isclose(parsed, item) for item in values):
            values.append(parsed)
    if len(values) > 1:
        raise PerformanceComparisonError(
            "performance_metadata_conflict",
            f"{owner} has conflicting {field} values: {values}.",
        )
    return values[0] if values else None


def _normalized_role(value: object, *, row_number: int) -> str:
    role = _ROLE_ALIASES.get(_token(value))
    if role is None:
        raise PerformanceComparisonError(
            "performance_role_invalid",
            f"Row {row_number}: Role must identify sample/this work or "
            "reference/literature.",
        )
    return role


def _normalized_direction(value: str, *, metric_id: str) -> str | None:
    if not value:
        return None
    direction = _DIRECTION_ALIASES.get(_token(value))
    if direction is None:
        raise PerformanceComparisonError(
            "performance_direction_invalid",
            f"Metric {metric_id!r}: Direction must be higher or lower.",
        )
    return direction


def _normalized_scatter_axis(value: str, *, metric_id: str) -> str | None:
    if not value:
        return None
    axis = _token(value)
    if axis in {"x", "横轴"}:
        return "x"
    if axis in {"y", "纵轴"}:
        return "y"
    raise PerformanceComparisonError(
        "performance_scatter_axis_invalid",
        f"Metric {metric_id!r}: ScatterAxis must be x, y, or blank.",
    )


def _normalized_marker(value: str, *, material_id: str) -> str | None:
    if not value:
        return None
    marker = value.strip().casefold().replace("_", "")
    aliases = {
        "triangleup": "triangle",
        "triangle": "triangle",
        "triangledown": "triangledown",
        "circle": "circle",
        "square": "square",
        "diamond": "diamond",
        "pentagon": "pentagon",
        "hexagon": "hexagon",
        "star": "star",
        "cross": "cross",
        "plus": "plus",
    }
    normalized = aliases.get(marker)
    if normalized is None:
        raise PerformanceComparisonError(
            "performance_marker_invalid",
            f"Material {material_id!r}: unsupported marker {value!r}.",
        )
    return normalized


def load_performance_comparison(source: str | Path) -> PerformanceComparison:
    """Load and validate the tidy performance-comparison table."""

    source_path = _resolve_source(Path(source))
    frame = _read_source_frame(source_path).dropna(how="all").reset_index(drop=True)
    columns = _canonical_header_map(frame.columns)
    missing = sorted(_REQUIRED_COLUMNS - set(columns))
    if missing:
        raise PerformanceComparisonError(
            "performance_columns_missing",
            "Performance comparison table is missing required fields: "
            + ", ".join(missing),
        )
    if frame.empty:
        raise PerformanceComparisonError(
            "performance_table_empty",
            "Performance comparison table contains no data rows.",
        )

    normalized_rows: list[dict[str, Any]] = []
    material_first_order: dict[str, int] = {}
    metric_first_order: dict[str, int] = {}
    for index, row in frame.iterrows():
        row_number = int(index) + 2
        material_id = _text(row[columns["material"]])
        metric_id = _text(row[columns["metric"]])
        unit = _text(row[columns["unit"]])
        if not material_id or not metric_id or not unit:
            raise PerformanceComparisonError(
                "performance_required_value_missing",
                f"Row {row_number}: Material, Metric, and Unit must be non-empty.",
            )
        role = _normalized_role(row[columns["role"]], row_number=row_number)
        value = _finite_float(
            row[columns["value"]],
            field="Value",
            row_number=row_number,
        )
        material_first_order.setdefault(material_id, len(material_first_order))
        metric_first_order.setdefault(metric_id, len(metric_first_order))
        normalized_rows.append(
            {
                "material": material_id,
                "role": role,
                "metric": metric_id,
                "value": value,
                "unit": unit,
                "_source_row": row_number,
                **{
                    field: (
                        _text(row[column])
                        if field
                        not in {"scale_min", "scale_max", "material_order", "radar_order"}
                        else row[column]
                    )
                    for field, column in columns.items()
                    if field not in _REQUIRED_COLUMNS
                },
            }
        )
    normalized = pd.DataFrame(normalized_rows)

    metrics: list[PerformanceMetric] = []
    for metric_id, metric_rows in normalized.groupby("metric", sort=False):
        owner = f"Metric {metric_id!r}"
        unit = _unique_text(
            metric_rows,
            "unit",
            field="Unit",
            owner=owner,
        )
        display_label = _unique_text(
            metric_rows,
            "display_label" if "display_label" in metric_rows else None,
            field="DisplayLabel",
            owner=owner,
            default=str(metric_id),
        )
        scatter_axis = _normalized_scatter_axis(
            _unique_text(
                metric_rows,
                "scatter_axis" if "scatter_axis" in metric_rows else None,
                field="ScatterAxis",
                owner=owner,
            ),
            metric_id=str(metric_id),
        )
        radar_order_value = _unique_float(
            metric_rows,
            "radar_order" if "radar_order" in metric_rows else None,
            field="RadarOrder",
            owner=owner,
        )
        radar_order: int | None = None
        if radar_order_value is not None:
            if (
                radar_order_value < 1
                or not math.isclose(radar_order_value, round(radar_order_value))
            ):
                raise PerformanceComparisonError(
                    "performance_radar_order_invalid",
                    f"{owner}: RadarOrder must be a positive integer.",
                )
            radar_order = int(round(radar_order_value))
        direction = _normalized_direction(
            _unique_text(
                metric_rows,
                "direction" if "direction" in metric_rows else None,
                field="Direction",
                owner=owner,
            ),
            metric_id=str(metric_id),
        )
        scale_min = _unique_float(
            metric_rows,
            "scale_min" if "scale_min" in metric_rows else None,
            field="ScaleMin",
            owner=owner,
        )
        scale_max = _unique_float(
            metric_rows,
            "scale_max" if "scale_max" in metric_rows else None,
            field="ScaleMax",
            owner=owner,
        )
        if radar_order is not None:
            if direction is None or scale_min is None or scale_max is None:
                raise PerformanceComparisonError(
                    "performance_radar_scale_incomplete",
                    f"{owner}: radar metrics require Direction, ScaleMin, and "
                    "ScaleMax.",
                )
            if not scale_min < scale_max:
                raise PerformanceComparisonError(
                    "performance_radar_scale_invalid",
                    f"{owner}: ScaleMin must be smaller than ScaleMax.",
                )
        metrics.append(
            PerformanceMetric(
                metric_id=str(metric_id),
                display_label=display_label,
                unit=unit,
                source_order=metric_first_order[str(metric_id)],
                scatter_axis=scatter_axis,
                radar_order=radar_order,
                direction=direction,
                scale_min=scale_min,
                scale_max=scale_max,
            )
        )

    materials: list[PerformanceMaterial] = []
    for material_id, material_rows in normalized.groupby("material", sort=False):
        owner = f"Material {material_id!r}"
        roles = list(dict.fromkeys(str(value) for value in material_rows["role"]))
        if len(roles) != 1:
            raise PerformanceComparisonError(
                "performance_material_role_conflict",
                f"{owner} has conflicting Role values: {roles}.",
            )
        role = roles[0]
        group = _unique_text(
            material_rows,
            "group" if "group" in material_rows else None,
            field="Group",
            owner=owner,
            default="This work",
        )
        journal = _unique_text(
            material_rows,
            "journal" if "journal" in material_rows else None,
            field="Journal",
            owner=owner,
        )
        year = _year_text(
            _unique_text(
                material_rows,
                "year" if "year" in material_rows else None,
                field="Year",
                owner=owner,
            )
        )
        doi = _unique_text(
            material_rows,
            "doi" if "doi" in material_rows else None,
            field="DOI",
            owner=owner,
        )
        material_order = _unique_float(
            material_rows,
            "material_order" if "material_order" in material_rows else None,
            field="MaterialOrder",
            owner=owner,
        )
        marker = _normalized_marker(
            _unique_text(
                material_rows,
                "marker" if "marker" in material_rows else None,
                field="Marker",
                owner=owner,
            ),
            material_id=str(material_id),
        )
        values: dict[str, float] = {}
        for metric_id, value_rows in material_rows.groupby("metric", sort=False):
            if len(value_rows) != 1:
                raise PerformanceComparisonError(
                    "performance_material_metric_duplicate",
                    f"{owner} has {len(value_rows)} values for metric "
                    f"{metric_id!r}; replicate aggregation is not implicit.",
                )
            values[str(metric_id)] = float(value_rows.iloc[0]["value"])
        materials.append(
            PerformanceMaterial(
                material_id=str(material_id),
                role=role,
                group=group if role == "sample" else "Literature references",
                source_order=material_first_order[str(material_id)],
                material_order=material_order,
                journal=journal,
                year=year,
                doi=doi,
                marker=marker,
                values=values,
            )
        )
    materials.sort(
        key=lambda item: (
            item.material_order is None,
            item.material_order if item.material_order is not None else item.source_order,
            item.source_order,
        )
    )
    comparison = PerformanceComparison(
        source=source_path,
        source_sha256=file_sha256(source_path),
        source_row_count=len(normalized_rows),
        metrics=tuple(metrics),
        materials=tuple(materials),
    )
    if not comparison.samples:
        raise PerformanceComparisonError(
            "performance_samples_missing",
            "Performance comparison data need at least one Role=sample material.",
        )
    return comparison


def _axis_bounds(values: list[float]) -> tuple[float, float]:
    minimum = min(values)
    maximum = max(values)
    span = maximum - minimum
    if math.isclose(span, 0.0):
        span = max(abs(minimum), 1.0) * 0.16
    padding = span * 0.08
    return minimum - padding, maximum + padding


def _convex_hull(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    unique = sorted(set(points))
    if len(unique) <= 1:
        return unique

    def cross(
        origin: tuple[float, float],
        left: tuple[float, float],
        right: tuple[float, float],
    ) -> float:
        return (left[0] - origin[0]) * (right[1] - origin[1]) - (
            left[1] - origin[1]
        ) * (right[0] - origin[0])

    lower: list[tuple[float, float]] = []
    for point in unique:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0.0:
            lower.pop()
        lower.append(point)
    upper: list[tuple[float, float]] = []
    for point in reversed(unique):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0.0:
            upper.pop()
        upper.append(point)
    return lower[:-1] + upper[:-1]


def _circle_polygon(
    center: tuple[float, float],
    radius: float,
    *,
    point_count: int = 24,
) -> list[tuple[float, float]]:
    return [
        (
            center[0] + radius * math.cos(2.0 * math.pi * index / point_count),
            center[1] + radius * math.sin(2.0 * math.pi * index / point_count),
        )
        for index in range(point_count)
    ]


def _capsule_polygon(
    start: tuple[float, float],
    end: tuple[float, float],
    radius: float,
) -> list[tuple[float, float]]:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length = math.hypot(dx, dy)
    if math.isclose(length, 0.0):
        return _circle_polygon(start, radius)
    angle = math.atan2(dy, dx)
    points: list[tuple[float, float]] = []
    for index in range(9):
        theta = angle + math.pi / 2.0 + math.pi * index / 8.0
        points.append(
            (start[0] + radius * math.cos(theta), start[1] + radius * math.sin(theta))
        )
    for index in range(9):
        theta = angle - math.pi / 2.0 + math.pi * index / 8.0
        points.append(
            (end[0] + radius * math.cos(theta), end[1] + radius * math.sin(theta))
        )
    return points


def _expanded_envelope(
    points: list[tuple[float, float]],
    *,
    x_bounds: tuple[float, float],
    y_bounds: tuple[float, float],
) -> list[tuple[float, float]]:
    x_span = x_bounds[1] - x_bounds[0]
    y_span = y_bounds[1] - y_bounds[0]
    normalized = [
        (
            (x_value - x_bounds[0]) / x_span,
            (y_value - y_bounds[0]) / y_span,
        )
        for x_value, y_value in points
    ]
    hull = _convex_hull(normalized)
    radius = PERFORMANCE_ENVELOPE_PADDING_FRACTION
    if len(hull) == 1:
        expanded = _circle_polygon(hull[0], radius)
    elif len(hull) == 2:
        expanded = _capsule_polygon(hull[0], hull[1], radius)
    else:
        centroid = (
            sum(point[0] for point in hull) / len(hull),
            sum(point[1] for point in hull) / len(hull),
        )
        expanded = []
        for point in hull:
            dx = point[0] - centroid[0]
            dy = point[1] - centroid[1]
            length = math.hypot(dx, dy)
            if math.isclose(length, 0.0):
                expanded.append(point)
            else:
                expanded.append(
                    (
                        point[0] + radius * dx / length,
                        point[1] + radius * dy / length,
                    )
                )
    return [
        (
            x_bounds[0] + point[0] * x_span,
            y_bounds[0] + point[1] * y_span,
        )
        for point in expanded
    ]


def _sample_group_colors(
    materials: tuple[PerformanceMaterial, ...],
) -> dict[str, str]:
    groups = list(dict.fromkeys(item.group for item in materials if item.role == "sample"))
    palette = DEFAULT_PALETTE_COLORS[1:] or DEFAULT_PALETTE_COLORS
    if len(groups) > len(palette):
        raise PerformanceComparisonError(
            "performance_sample_group_capacity_exceeded",
            f"At most {len(palette)} sample envelope groups are supported in one figure.",
        )
    return {group: palette[index] for index, group in enumerate(groups)}


def _material_styles(
    comparison: PerformanceComparison,
    *,
    radar: bool,
) -> dict[str, dict[str, Any]]:
    if len(comparison.materials) > len(PERFORMANCE_MARKERS):
        raise PerformanceComparisonError(
            "performance_marker_capacity_exceeded",
            f"One comparison figure supports at most {len(PERFORMANCE_MARKERS)} "
            "materials with unique marker identities.",
        )
    group_colors = _sample_group_colors(comparison.materials)
    styles: dict[str, dict[str, Any]] = {}
    for index, material in enumerate(comparison.materials):
        marker = material.marker or PERFORMANCE_MARKERS[index]
        color = (
            (
                DEFAULT_PALETTE_COLORS[
                    1 + index % max(len(DEFAULT_PALETTE_COLORS) - 1, 1)
                ]
                if radar
                else group_colors[material.group]
            )
            if material.role == "sample"
            else PERFORMANCE_REFERENCE_COLOR
        )
        styles[material.material_id] = {
            "color": color,
            "marker": marker,
            "marker_fill_color": color if material.role == "sample" else "white",
            "marker_fill_hide": False,
            "role": material.role,
            "group": material.group,
        }
    return styles


def _legend_items(
    comparison: PerformanceComparison,
    styles: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for material in comparison.materials:
        items.append(
            {
                "material": material.material_id,
                "role": material.role,
                "group": material.group,
                "marker": styles[material.material_id]["marker"],
                "color": styles[material.material_id]["color"],
                "marker_fill_color": styles[material.material_id][
                    "marker_fill_color"
                ],
                "citation": material.citation,
                "journal": material.journal,
                "year": material.year,
                "doi": material.doi,
            }
        )
    return items


def _layout_payload(*, use_legend_panel: bool) -> dict[str, Any]:
    width_mm = (
        PERFORMANCE_PANEL_WIDTH_MM + PERFORMANCE_REFERENCE_PANEL_WIDTH_MM
        if use_legend_panel
        else PERFORMANCE_PANEL_WIDTH_MM
    )
    graph_right_margin = (
        width_mm - PERFORMANCE_PANEL_WIDTH_MM + UNIFIED_RIGHT_MARGIN_MM
    )
    return {
        "kind": "paired_60mm_performance_panels",
        "page_size_mm": [width_mm, PERFORMANCE_PANEL_HEIGHT_MM],
        "plot_panel_size_mm": [
            PERFORMANCE_PANEL_WIDTH_MM,
            PERFORMANCE_PANEL_HEIGHT_MM,
        ],
        "legend_panel_size_mm": (
            [PERFORMANCE_REFERENCE_PANEL_WIDTH_MM, PERFORMANCE_PANEL_HEIGHT_MM]
            if use_legend_panel
            else None
        ),
        "graph_margins_mm": {
            "left": UNIFIED_LEFT_MARGIN_MM,
            "right": graph_right_margin,
            "bottom": UNIFIED_BOTTOM_MARGIN_MM,
            "top": UNIFIED_TOP_MARGIN_MM,
        },
        "plot_region_mm": [
            PERFORMANCE_PANEL_WIDTH_MM
            - UNIFIED_LEFT_MARGIN_MM
            - UNIFIED_RIGHT_MARGIN_MM,
            PERFORMANCE_PANEL_HEIGHT_MM
            - UNIFIED_BOTTOM_MARGIN_MM
            - UNIFIED_TOP_MARGIN_MM,
        ],
        "outside_legend": False,
        "legend_uses_reserved_panel": use_legend_panel,
    }


def build_performance_scatter_payload(
    comparison: PerformanceComparison,
) -> dict[str, Any]:
    x_metric, y_metric = comparison.scatter_metrics
    missing = [
        material.material_id
        for material in comparison.materials
        if x_metric.metric_id not in material.values
        or y_metric.metric_id not in material.values
    ]
    if missing:
        raise PerformanceComparisonError(
            "performance_scatter_material_incomplete",
            "Every plotted material needs both scatter metrics; missing: "
            + ", ".join(missing),
        )
    x_values = [
        material.values[x_metric.metric_id] for material in comparison.materials
    ]
    y_values = [
        material.values[y_metric.metric_id] for material in comparison.materials
    ]
    x_bounds = _axis_bounds(x_values)
    y_bounds = _axis_bounds(y_values)
    styles = _material_styles(comparison, radar=False)
    series = [
        {
            "label": material.material_id,
            "x_values": [material.values[x_metric.metric_id]],
            "y_values": [material.values[y_metric.metric_id]],
            **styles[material.material_id],
        }
        for material in comparison.materials
    ]
    envelopes: list[dict[str, Any]] = []
    for group, color in _sample_group_colors(comparison.materials).items():
        members = [
            material
            for material in comparison.samples
            if material.group == group
        ]
        polygon = _expanded_envelope(
            [
                (
                    material.values[x_metric.metric_id],
                    material.values[y_metric.metric_id],
                )
                for material in members
            ],
            x_bounds=x_bounds,
            y_bounds=y_bounds,
        )
        envelopes.append(
            {
                "group": group,
                "members": [material.material_id for material in members],
                "x_values": [point[0] for point in polygon],
                "y_values": [point[1] for point in polygon],
                "line_color": color,
                "fill_color": categorical_fill_color(color),
                "line_transparency": PERFORMANCE_ENVELOPE_LINE_TRANSPARENCY,
                "fill_transparency": PERFORMANCE_ENVELOPE_FILL_TRANSPARENCY,
            }
        )
    return {
        "kind": "sciplot_performance_comparison",
        "version": 1,
        "template": PERFORMANCE_SCATTER_TEMPLATE_ID,
        "source": str(comparison.source),
        "source_sha256": comparison.source_sha256,
        "source_row_count": comparison.source_row_count,
        "x_metric": json_safe(x_metric.__dict__),
        "y_metric": json_safe(y_metric.__dict__),
        "x_label": x_metric.axis_label,
        "y_label": y_metric.axis_label,
        "x_bounds": list(x_bounds),
        "y_bounds": list(y_bounds),
        "series": series,
        "envelopes": envelopes,
        "legend_items": _legend_items(comparison, styles),
        "layout": _layout_payload(use_legend_panel=True),
        "material_count": len(comparison.materials),
        "sample_count": len(comparison.samples),
        "reference_count": len(comparison.references),
    }


def _normalized_radar_value(value: float, metric: PerformanceMetric) -> float:
    if (
        metric.scale_min is None
        or metric.scale_max is None
        or metric.direction not in {"higher", "lower"}
    ):
        raise PerformanceComparisonError(
            "performance_radar_scale_incomplete",
            f"Metric {metric.metric_id!r} has no complete radar scale.",
        )
    if value < metric.scale_min - 1e-12 or value > metric.scale_max + 1e-12:
        raise PerformanceComparisonError(
            "performance_radar_value_outside_scale",
            f"Metric {metric.metric_id!r} value {value:g} is outside the declared "
            f"[{metric.scale_min:g}, {metric.scale_max:g}] scale.",
        )
    fraction = (value - metric.scale_min) / (metric.scale_max - metric.scale_min)
    return fraction if metric.direction == "higher" else 1.0 - fraction


def build_performance_radar_payload(
    comparison: PerformanceComparison,
) -> dict[str, Any]:
    metrics = comparison.radar_metrics
    incomplete_samples = [
        material.material_id
        for material in comparison.samples
        if any(metric.metric_id not in material.values for metric in metrics)
    ]
    if incomplete_samples:
        raise PerformanceComparisonError(
            "performance_radar_sample_incomplete",
            "Every Role=sample material needs every radar metric so its filled "
            "polygon is complete; missing: " + ", ".join(incomplete_samples),
        )
    styles = _material_styles(comparison, radar=True)
    angles = [
        360.0 * index / len(metrics)
        for index in range(len(metrics))
    ]
    series: list[dict[str, Any]] = []
    for material in comparison.materials:
        material_angles: list[float] = []
        radii: list[float] = []
        raw_values: list[float] = []
        metric_ids: list[str] = []
        for angle, metric in zip(angles, metrics, strict=True):
            if metric.metric_id not in material.values:
                continue
            raw_value = material.values[metric.metric_id]
            material_angles.append(angle)
            radii.append(_normalized_radar_value(raw_value, metric))
            raw_values.append(raw_value)
            metric_ids.append(metric.metric_id)
        if not radii:
            raise PerformanceComparisonError(
                "performance_radar_reference_empty",
                f"Reference material {material.material_id!r} has no radar values.",
            )
        filled = material.role == "sample"
        if filled:
            material_angles.append(material_angles[0])
            radii.append(radii[0])
            raw_values.append(raw_values[0])
            metric_ids.append(metric_ids[0])
        series.append(
            {
                "label": material.material_id,
                "angles_degrees": material_angles,
                "radii": radii,
                "raw_values": raw_values,
                "metric_ids": metric_ids,
                "filled_polygon": filled,
                "fill_transparency": PERFORMANCE_SAMPLE_FILL_TRANSPARENCY,
                **styles[material.material_id],
            }
        )
    use_legend_panel = bool(
        comparison.references
        or len(comparison.samples) > 3
        or any(item.citation for item in comparison.materials)
    )
    return {
        "kind": "sciplot_performance_comparison",
        "version": 1,
        "template": PERFORMANCE_RADAR_TEMPLATE_ID,
        "source": str(comparison.source),
        "source_sha256": comparison.source_sha256,
        "source_row_count": comparison.source_row_count,
        "metrics": [json_safe(item.__dict__) for item in metrics],
        "axis_labels": [item.radar_label for item in metrics],
        "angles_degrees": angles,
        "normalization": {
            "kind": "declared_bounded_directional_score",
            "range": [0.0, 1.0],
            "outer_is_better": True,
            "higher_formula": "(value - scale_min) / (scale_max - scale_min)",
            "lower_formula": "(scale_max - value) / (scale_max - scale_min)",
            "values_outside_declared_bounds": "fail_closed",
        },
        "series": series,
        "legend_items": _legend_items(comparison, styles),
        "layout": _layout_payload(use_legend_panel=use_legend_panel),
        "material_count": len(comparison.materials),
        "sample_count": len(comparison.samples),
        "reference_count": len(comparison.references),
    }


def prepare_performance_comparison(
    source: str | Path,
    *,
    template_id: str,
) -> dict[str, Any]:
    """Return the validated source-bound payload for one production template."""

    comparison = load_performance_comparison(source)
    if template_id == PERFORMANCE_SCATTER_TEMPLATE_ID:
        return build_performance_scatter_payload(comparison)
    if template_id == PERFORMANCE_RADAR_TEMPLATE_ID:
        return build_performance_radar_payload(comparison)
    raise PerformanceComparisonError(
        "performance_template_invalid",
        "Performance comparisons support the scatter and polar_curve "
        f"(radar) templates, not {template_id!r}.",
    )


def performance_transform_parameters(payload: dict[str, Any]) -> dict[str, Any]:
    """Return lineage parameters shared by Studio and workflow evidence."""

    result = {
        "template": payload["template"],
        "source_sha256": payload["source_sha256"],
        "source_row_count": payload["source_row_count"],
        "material_count": payload["material_count"],
        "sample_count": payload["sample_count"],
        "reference_count": payload["reference_count"],
        "legend_panel_reserved": bool(
            payload.get("layout", {}).get("legend_uses_reserved_panel")
        ),
        "plot_region_mm": payload.get("layout", {}).get("plot_region_mm"),
        "scientific_values_modified": False,
    }
    if payload["template"] == PERFORMANCE_SCATTER_TEMPLATE_ID:
        result.update(
            {
                "x_metric": payload["x_metric"]["metric_id"],
                "y_metric": payload["y_metric"]["metric_id"],
                "sample_envelope_method": (
                    "convex hull with deterministic normalized-axis padding; "
                    "circle/capsule fallback for one or two collinear points"
                ),
                "sample_envelope_groups": [
                    {
                        "group": item["group"],
                        "members": item["members"],
                    }
                    for item in payload["envelopes"]
                ],
            }
        )
    else:
        result.update(
            {
                "metric_ids": [
                    item["metric_id"] for item in payload.get("metrics", [])
                ],
                "normalization": payload.get("normalization"),
                "sample_polygons_filled": True,
                "reference_series_markers_only": True,
            }
        )
    return json_safe(result)


__all__ = [
    "PERFORMANCE_COMPARISON_RULE_ID",
    "PERFORMANCE_PANEL_HEIGHT_MM",
    "PERFORMANCE_PANEL_WIDTH_MM",
    "PERFORMANCE_RADAR_TEMPLATE_ID",
    "PERFORMANCE_SCATTER_TEMPLATE_ID",
    "PerformanceComparison",
    "PerformanceComparisonError",
    "PerformanceMaterial",
    "PerformanceMetric",
    "build_performance_radar_payload",
    "build_performance_scatter_payload",
    "is_performance_comparison_source",
    "load_performance_comparison",
    "performance_transform_parameters",
    "prepare_performance_comparison",
]
