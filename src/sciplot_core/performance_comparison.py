"""Deterministic material-performance scatter and radar preparation.

The input contract is one tidy table.  Scientific values and literature
metadata remain source-bound; this module only validates, pivots, normalizes
declared radar scales, and derives presentation geometry for the production
Veusz document builder.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from sciplot_core._utils import decode_text, file_sha256, json_safe
from sciplot_core.materials_rules import format_unit_label
from sciplot_core.policy import (
    DEFAULT_PALETTE_COLORS,
    PERFORMANCE_ENVELOPE_FILL_TRANSPARENCY,
    PERFORMANCE_ENVELOPE_IRREGULARITY_FRACTION,
    PERFORMANCE_ENVELOPE_LINE_TRANSPARENCY,
    PERFORMANCE_ENVELOPE_PADDING_FRACTION,
    PERFORMANCE_MARKERS,
    PERFORMANCE_PANEL_HEIGHT_MM,
    PERFORMANCE_PANEL_WIDTH_MM,
    PERFORMANCE_REFERENCE_COLOR,
    PERFORMANCE_REFERENCE_PANEL_WIDTH_MM,
    PERFORMANCE_SCATTER_JITTER_HALFSPAN_FRACTION,
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
    scatter_min: float | None = None
    scatter_max: float | None = None
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
    envelope_include: bool
    legend_label: str
    legend_label_explicit: bool
    legend_group: str
    legend_identity: str
    legend_column: int
    legend_items_per_row: int
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
    "envelope_include": frozenset(
        {
            "envelopeinclude",
            "includeinenvelope",
            "包络纳入",
            "纳入包络",
        }
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
    "scatter_min": frozenset(
        {"scattermin", "scatteraxismin", "散点轴下限", "坐标轴下限"}
    ),
    "scatter_max": frozenset(
        {"scattermax", "scatteraxismax", "散点轴上限", "坐标轴上限"}
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
    "legend_label": frozenset(
        {"legendlabel", "indexlabel", "图例文字", "索引文字"}
    ),
    "legend_group": frozenset(
        {"legendgroup", "indexgroup", "图例分组", "索引分组"}
    ),
    "legend_identity": frozenset(
        {"legendidentity", "markeridentity", "图例身份", "标记身份"}
    ),
    "legend_column": frozenset(
        {"legendcolumn", "indexcolumn", "图例列", "索引列"}
    ),
    "legend_items_per_row": frozenset(
        {
            "legenditemsperrow",
            "indexitemsperrow",
            "图例每行条目数",
            "索引每行条目数",
        }
    ),
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
    return format_unit_label(value)


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


def _unique_bool(
    frame: pd.DataFrame,
    column: object | None,
    *,
    field: str,
    owner: str,
    default: bool,
) -> bool:
    if column is None:
        return default
    values: list[bool] = []
    true_tokens = {
        "true",
        "yes",
        "y",
        "include",
        "included",
        "是",
        "包含",
        "纳入",
    }
    false_tokens = {
        "false",
        "no",
        "n",
        "exclude",
        "excluded",
        "否",
        "不包含",
        "不纳入",
    }
    for index, value in frame[column].items():
        text = _text(value)
        if not text:
            continue
        parsed: bool | None = None
        try:
            number = float(value)
        except (TypeError, ValueError):
            number = math.nan
        if math.isfinite(number) and math.isclose(number, 1.0):
            parsed = True
        elif math.isfinite(number) and math.isclose(number, 0.0):
            parsed = False
        else:
            token = _token(value)
            if token in true_tokens:
                parsed = True
            elif token in false_tokens:
                parsed = False
        if parsed is None:
            raise PerformanceComparisonError(
                "performance_envelope_include_invalid",
                f"Row {int(index) + 2}: {field} must be true/false, "
                "yes/no, include/exclude, or 1/0.",
            )
        if parsed not in values:
            values.append(parsed)
    if len(values) > 1:
        raise PerformanceComparisonError(
            "performance_metadata_conflict",
            f"{owner} has conflicting {field} values: {values}.",
        )
    return values[0] if values else default


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
        "triangleleft": "triangleleft",
        "triangleright": "triangleright",
        "octogon": "octogon",
        "octagon": "octogon",
        "ellipsehorz": "ellipsehorz",
        "ellipsehorizontal": "ellipsehorz",
        "ellipsevert": "ellipsevert",
        "ellipsevertical": "ellipsevert",
        "star4": "star4",
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
                        not in {
                            "scatter_min",
                            "scatter_max",
                            "scale_min",
                            "scale_max",
                            "material_order",
                            "radar_order",
                        }
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
        scatter_min = _unique_float(
            metric_rows,
            "scatter_min" if "scatter_min" in metric_rows else None,
            field="ScatterMin",
            owner=owner,
        )
        scatter_max = _unique_float(
            metric_rows,
            "scatter_max" if "scatter_max" in metric_rows else None,
            field="ScatterMax",
            owner=owner,
        )
        if (
            scatter_min is not None
            and scatter_max is not None
            and not scatter_min < scatter_max
        ):
            raise PerformanceComparisonError(
                "performance_scatter_scale_invalid",
                f"{owner}: ScatterMin must be smaller than ScatterMax.",
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
                scatter_min=scatter_min,
                scatter_max=scatter_max,
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
            default="This work" if role == "sample" else "Literature",
        )
        envelope_include = _unique_bool(
            material_rows,
            (
                "envelope_include"
                if "envelope_include" in material_rows
                else None
            ),
            field="EnvelopeInclude",
            owner=owner,
            default=role == "sample",
        )
        legend_label = _unique_text(
            material_rows,
            "legend_label" if "legend_label" in material_rows else None,
            field="LegendLabel",
            owner=owner,
            default=str(material_id),
        )
        legend_label_explicit = bool(
            "legend_label" in material_rows
            and any(
                _text(value)
                for value in material_rows["legend_label"].tolist()
            )
        )
        legend_group = _unique_text(
            material_rows,
            "legend_group" if "legend_group" in material_rows else None,
            field="LegendGroup",
            owner=owner,
            default="This work" if role == "sample" else "Reference materials",
        )
        legend_identity = _unique_text(
            material_rows,
            (
                "legend_identity"
                if "legend_identity" in material_rows
                else None
            ),
            field="LegendIdentity",
            owner=owner,
            default=legend_label,
        )
        legend_column_value = _unique_float(
            material_rows,
            "legend_column" if "legend_column" in material_rows else None,
            field="LegendColumn",
            owner=owner,
        )
        legend_column = 1
        if legend_column_value is not None:
            if (
                legend_column_value not in {1.0, 2.0}
                or not math.isclose(
                    legend_column_value,
                    round(legend_column_value),
                )
            ):
                raise PerformanceComparisonError(
                    "performance_legend_column_invalid",
                    f"{owner}: LegendColumn must be 1 or 2.",
                )
            legend_column = int(round(legend_column_value))
        legend_items_per_row_value = _unique_float(
            material_rows,
            (
                "legend_items_per_row"
                if "legend_items_per_row" in material_rows
                else None
            ),
            field="LegendItemsPerRow",
            owner=owner,
        )
        legend_items_per_row = 1
        if legend_items_per_row_value is not None:
            if (
                legend_items_per_row_value not in {1.0, 2.0}
                or not math.isclose(
                    legend_items_per_row_value,
                    round(legend_items_per_row_value),
                )
            ):
                raise PerformanceComparisonError(
                    "performance_legend_items_per_row_invalid",
                    f"{owner}: LegendItemsPerRow must be 1 or 2.",
                )
            legend_items_per_row = int(
                round(legend_items_per_row_value)
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
                group=group,
                envelope_include=envelope_include,
                legend_label=legend_label,
                legend_label_explicit=legend_label_explicit,
                legend_group=legend_group,
                legend_identity=legend_identity,
                legend_column=legend_column,
                legend_items_per_row=legend_items_per_row,
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


def _axis_bounds(
    values: list[float],
    *,
    metric: PerformanceMetric,
) -> tuple[float, float]:
    minimum = min(values)
    maximum = max(values)
    span = maximum - minimum
    if math.isclose(span, 0.0):
        span = max(abs(minimum), 1.0) * 0.16
    padding = span * 0.08
    lower = (
        metric.scatter_min
        if metric.scatter_min is not None
        else minimum - padding
    )
    upper = (
        metric.scatter_max
        if metric.scatter_max is not None
        else maximum + padding
    )
    if lower > minimum and not math.isclose(lower, minimum):
        raise PerformanceComparisonError(
            "performance_scatter_bound_excludes_data",
            f"Metric {metric.metric_id!r}: ScatterMin {lower:g} excludes "
            f"the plotted minimum {minimum:g}.",
        )
    if upper < maximum and not math.isclose(upper, maximum):
        raise PerformanceComparisonError(
            "performance_scatter_bound_excludes_data",
            f"Metric {metric.metric_id!r}: ScatterMax {upper:g} excludes "
            f"the plotted maximum {maximum:g}.",
        )
    if not lower < upper:
        raise PerformanceComparisonError(
            "performance_scatter_scale_invalid",
            f"Metric {metric.metric_id!r}: scatter bounds must increase.",
        )
    return lower, upper


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


def _chaikin_closed_polygon(
    points: list[tuple[float, float]],
    *,
    iterations: int,
) -> list[tuple[float, float]]:
    smoothed = list(points)
    for _ in range(max(int(iterations), 0)):
        refined: list[tuple[float, float]] = []
        for start, end in zip(
            smoothed,
            [*smoothed[1:], smoothed[0]],
            strict=True,
        ):
            refined.extend(
                (
                    (
                        0.75 * start[0] + 0.25 * end[0],
                        0.75 * start[1] + 0.25 * end[1],
                    ),
                    (
                        0.25 * start[0] + 0.75 * end[0],
                        0.25 * start[1] + 0.75 * end[1],
                    ),
                )
            )
        smoothed = refined
    return smoothed


def _irregularize_polygon(
    points: list[tuple[float, float]],
    *,
    seed_key: str,
) -> list[tuple[float, float]]:
    if len(points) < 3:
        return points
    smoothed = _chaikin_closed_polygon(
        points,
        iterations=2 if len(points) <= 8 else 1,
    )
    centroid = (
        sum(point[0] for point in smoothed) / len(smoothed),
        sum(point[1] for point in smoothed) / len(smoothed),
    )
    digest = hashlib.sha256(seed_key.encode("utf-8")).digest()
    phase_3 = 2.0 * math.pi * int.from_bytes(digest[:4], "big") / (2**32)
    phase_5 = 2.0 * math.pi * int.from_bytes(digest[4:8], "big") / (2**32)
    result: list[tuple[float, float]] = []
    for point in smoothed:
        dx = point[0] - centroid[0]
        dy = point[1] - centroid[1]
        angle = math.atan2(dy, dx)
        modulation = (
            1.08
            + PERFORMANCE_ENVELOPE_IRREGULARITY_FRACTION
            * math.sin(3.0 * angle + phase_3)
            + 0.6
            * PERFORMANCE_ENVELOPE_IRREGULARITY_FRACTION
            * math.sin(5.0 * angle + phase_5)
        )
        result.append(
            (
                centroid[0] + modulation * dx,
                centroid[1] + modulation * dy,
            )
        )
    return result


def _expanded_envelope(
    points: list[tuple[float, float]],
    *,
    x_bounds: tuple[float, float],
    y_bounds: tuple[float, float],
    seed_key: str,
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
        x_min = min(point[0] for point in normalized)
        x_max = max(point[0] for point in normalized)
        y_min = min(point[1] for point in normalized)
        y_max = max(point[1] for point in normalized)
        center = (
            0.5 * (x_min + x_max),
            0.5 * (y_min + y_max),
        )
        x_radius = max(0.5 * (x_max - x_min) + radius, radius) * 1.12
        y_radius = max(0.5 * (y_max - y_min) + radius, radius) * 1.05
        superellipse_power = 3.6
        expanded = []
        for index in range(32):
            angle = 2.0 * math.pi * index / 32.0
            cosine = math.cos(angle)
            sine = math.sin(angle)
            expanded.append(
                (
                    center[0]
                    + x_radius
                    * math.copysign(
                        abs(cosine) ** (2.0 / superellipse_power),
                        cosine,
                    ),
                    center[1]
                    + y_radius
                    * math.copysign(
                        abs(sine) ** (2.0 / superellipse_power),
                        sine,
                    ),
                )
            )
    expanded = _irregularize_polygon(expanded, seed_key=seed_key)
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
    return {group: palette[0] for group in groups}


def _material_styles(
    comparison: PerformanceComparison,
    *,
    radar: bool,
) -> dict[str, dict[str, Any]]:
    identity_order = list(
        dict.fromkeys(
            material.legend_identity for material in comparison.materials
        )
    )
    if len(identity_order) > len(PERFORMANCE_MARKERS):
        raise PerformanceComparisonError(
            "performance_marker_capacity_exceeded",
            f"One comparison figure supports at most {len(PERFORMANCE_MARKERS)} "
            "unique legend/marker identities.",
        )
    identity_markers: dict[str, str] = {}
    marker_owners: dict[str, str] = {}
    for identity_index, identity in enumerate(identity_order):
        members = [
            material
            for material in comparison.materials
            if material.legend_identity == identity
        ]
        explicit_markers = list(
            dict.fromkeys(
                material.marker
                for material in members
                if material.marker is not None
            )
        )
        if len(explicit_markers) > 1:
            raise PerformanceComparisonError(
                "performance_legend_identity_marker_conflict",
                f"Legend identity {identity!r} declares conflicting markers: "
                + ", ".join(explicit_markers),
            )
        marker = (
            explicit_markers[0]
            if explicit_markers
            else PERFORMANCE_MARKERS[identity_index]
        )
        previous_identity = marker_owners.get(marker)
        if previous_identity is not None and previous_identity != identity:
            raise PerformanceComparisonError(
                "performance_marker_identity_duplicate",
                f"Legend identities {previous_identity!r} and {identity!r} "
                f"reuse marker {marker!r} in one comparison figure.",
            )
        marker_owners[marker] = identity
        identity_markers[identity] = marker

    sample_color = (DEFAULT_PALETTE_COLORS[1:] or DEFAULT_PALETTE_COLORS)[0]
    identity_indexes = {
        identity: index for index, identity in enumerate(identity_order)
    }
    styles: dict[str, dict[str, Any]] = {}
    for material in comparison.materials:
        identity_index = identity_indexes[material.legend_identity]
        marker = identity_markers[material.legend_identity]
        color = (
            (
                DEFAULT_PALETTE_COLORS[
                    1
                    + identity_index
                    % max(len(DEFAULT_PALETTE_COLORS) - 1, 1)
                ]
                if radar
                else sample_color
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
    seen_identities: set[str] = set()
    for material in comparison.materials:
        if material.legend_identity in seen_identities:
            continue
        members = [
            item
            for item in comparison.materials
            if item.legend_identity == material.legend_identity
        ]
        for field in (
            "role",
            "legend_label",
            "legend_label_explicit",
            "legend_group",
            "legend_column",
            "legend_items_per_row",
        ):
            values = list(
                dict.fromkeys(getattr(item, field) for item in members)
            )
            if len(values) > 1:
                raise PerformanceComparisonError(
                    "performance_legend_identity_conflict",
                    f"Legend identity {material.legend_identity!r} has "
                    f"conflicting {field} values: {values}.",
                )
        seen_identities.add(material.legend_identity)
        citations = list(
            dict.fromkeys(item.citation for item in members if item.citation)
        )
        items.append(
            {
                "material": material.legend_identity,
                "source_materials": [item.material_id for item in members],
                "role": material.role,
                "group": material.group,
                "legend_group": material.legend_group,
                "legend_column": material.legend_column,
                "legend_items_per_row": material.legend_items_per_row,
                "label": material.legend_label,
                "append_citation": not material.legend_label_explicit,
                "marker": styles[material.material_id]["marker"],
                "color": styles[material.material_id]["color"],
                "marker_fill_color": styles[material.material_id][
                    "marker_fill_color"
                ],
                "citation": "; ".join(citations),
                "journal": material.journal,
                "year": material.year,
                "doi": material.doi,
            }
        )
    return items


def _layout_payload(
    *,
    use_legend_panel: bool,
    legend_column_count: int = 1,
) -> dict[str, Any]:
    legend_column_count = max(1, min(int(legend_column_count), 2))
    legend_width_mm = (
        PERFORMANCE_REFERENCE_PANEL_WIDTH_MM * legend_column_count
        if use_legend_panel
        else 0.0
    )
    width_mm = (
        PERFORMANCE_PANEL_WIDTH_MM + legend_width_mm
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
            [legend_width_mm, PERFORMANCE_PANEL_HEIGHT_MM]
            if use_legend_panel
            else None
        ),
        "legend_column_count": (
            legend_column_count if use_legend_panel else 0
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


def _deterministic_scatter_x_values(
    comparison: PerformanceComparison,
    *,
    x_metric: PerformanceMetric,
) -> tuple[dict[str, float], list[dict[str, Any]]]:
    raw_values = {
        material.material_id: material.values[x_metric.metric_id]
        for material in comparison.materials
    }
    raw_span = max(raw_values.values()) - min(raw_values.values())
    if math.isclose(raw_span, 0.0):
        raw_span = max(abs(next(iter(raw_values.values()))), 1.0) * 0.16
    jitter_half_span = (
        raw_span * PERFORMANCE_SCATTER_JITTER_HALFSPAN_FRACTION
    )
    result = dict(raw_values)
    jitter_records: list[dict[str, Any]] = []
    buckets: dict[str, list[PerformanceMaterial]] = {}
    for material in comparison.samples:
        raw_value = raw_values[material.material_id]
        buckets.setdefault(f"{raw_value:.12g}", []).append(material)
    for raw_key, members in buckets.items():
        if len(members) <= 1:
            continue
        slots = [
            -jitter_half_span
            + 2.0 * jitter_half_span * index / float(len(members) - 1)
            for index in range(len(members))
        ]
        shuffled_members = sorted(
            members,
            key=lambda material: hashlib.sha256(
                (
                    f"{comparison.source_sha256}|{raw_key}|"
                    f"{material.material_id}"
                ).encode("utf-8")
            ).digest(),
        )
        for member, offset in zip(shuffled_members, slots, strict=True):
            source_value = raw_values[member.material_id]
            plotted_value = source_value + offset
            result[member.material_id] = plotted_value
            jitter_records.append(
                {
                    "material": member.material_id,
                    "source_x": source_value,
                    "offset": offset,
                    "plotted_x": plotted_value,
                }
            )
    transforms: list[dict[str, Any]] = []
    if jitter_records:
        transforms.append(
            {
                "id": "performance_scatter_repeated_x_jitter",
                "operation": "deterministic_horizontal_jitter",
                "implementation_ref": (
                    "sciplot_core.performance_comparison."
                    "_deterministic_scatter_x_values"
                ),
                "parameters": {
                    "policy": "stable_hash_shuffled_even_slots",
                    "scope": "Role=sample rows sharing the same source x value",
                    "half_span_fraction": (
                        PERFORMANCE_SCATTER_JITTER_HALFSPAN_FRACTION
                    ),
                    "source_metric": x_metric.metric_id,
                    "scientific_source_values_modified": False,
                },
                "records": jitter_records,
            }
        )
    return result, transforms


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
    plotted_x_values, visual_data_transforms = (
        _deterministic_scatter_x_values(
            comparison,
            x_metric=x_metric,
        )
    )
    x_values = [
        plotted_x_values[material.material_id]
        for material in comparison.materials
    ]
    y_values = [
        material.values[y_metric.metric_id] for material in comparison.materials
    ]
    x_bounds = _axis_bounds(x_values, metric=x_metric)
    y_bounds = _axis_bounds(y_values, metric=y_metric)
    styles = _material_styles(comparison, radar=False)
    identity_members: dict[str, list[PerformanceMaterial]] = {}
    for material in comparison.materials:
        identity_members.setdefault(material.legend_identity, []).append(
            material
        )
    series: list[dict[str, Any]] = []
    for legend_identity, members in identity_members.items():
        representative = members[0]
        roles = {material.role for material in members}
        colors = {
            styles[material.material_id]["color"] for material in members
        }
        markers = {
            styles[material.material_id]["marker"] for material in members
        }
        if len(roles) != 1 or len(colors) != 1 or len(markers) != 1:
            raise PerformanceComparisonError(
                "performance_scatter_identity_style_conflict",
                f"Legend identity {legend_identity!r} cannot share one scatter "
                "series because its observations have conflicting roles or "
                "styles.",
            )
        series.append(
            {
                "label": representative.legend_label,
                "legend_identity": legend_identity,
                "source_materials": [
                    material.material_id for material in members
                ],
                "source_x_values": [
                    material.values[x_metric.metric_id]
                    for material in members
                ],
                "x_values": [
                    plotted_x_values[material.material_id]
                    for material in members
                ],
                "y_values": [
                    material.values[y_metric.metric_id]
                    for material in members
                ],
                **styles[representative.material_id],
            }
        )
    envelopes: list[dict[str, Any]] = []
    envelope_samples = tuple(
        material
        for material in comparison.samples
        if material.envelope_include
    )
    for group, color in _sample_group_colors(envelope_samples).items():
        members = [
            material
            for material in envelope_samples
            if material.group == group
        ]
        polygon = _expanded_envelope(
            [
                (
                    plotted_x_values[material.material_id],
                    material.values[y_metric.metric_id],
                )
                for material in members
            ],
            x_bounds=x_bounds,
            y_bounds=y_bounds,
            seed_key=f"{comparison.source_sha256}|{group}",
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
                "line_hide": True,
            }
        )
    legend_items = _legend_items(comparison, styles)
    legend_column_count = max(
        (int(item["legend_column"]) for item in legend_items),
        default=1,
    )
    return {
        "kind": "sciplot_performance_comparison",
        "version": 2,
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
        "legend_items": legend_items,
        "layout": _layout_payload(
            use_legend_panel=True,
            legend_column_count=legend_column_count,
        ),
        "visual_data_transforms": visual_data_transforms,
        "material_count": len(comparison.materials),
        "series_count": len(series),
        "legend_item_count": len(legend_items),
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
                "label": material.legend_label,
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
    legend_items = _legend_items(comparison, styles)
    legend_column_count = max(
        (int(item["legend_column"]) for item in legend_items),
        default=1,
    )
    return {
        "kind": "sciplot_performance_comparison",
        "version": 2,
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
        "legend_items": legend_items,
        "layout": _layout_payload(
            use_legend_panel=use_legend_panel,
            legend_column_count=legend_column_count,
        ),
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
        "series_count": payload.get(
            "series_count",
            len(payload.get("series", [])),
        ),
        "legend_item_count": payload.get(
            "legend_item_count",
            len(payload.get("legend_items", [])),
        ),
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
                    "deterministic irregular smoothed enclosure with "
                    "normalized-axis padding; circle/capsule fallback"
                ),
                "sample_envelope_border": "hidden",
                "repeated_x_visual_jitter": payload.get(
                    "visual_data_transforms",
                    [],
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
