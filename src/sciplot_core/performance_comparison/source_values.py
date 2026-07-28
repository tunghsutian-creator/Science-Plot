"""Normalize and validate scalar values from performance source rows."""

from __future__ import annotations

import math
import re
import pandas as pd
from sciplot_core.performance_comparison.models import (
    PerformanceComparisonError,
)


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
    "scatter_axis": frozenset({"scatteraxis", "axis", "xyaxis", "散点轴", "坐标轴"}),
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
    "marker_line_color": frozenset(
        {
            "markerlinecolor",
            "markerlinecolour",
            "symbollinecolor",
            "标记轮廓色",
            "符号轮廓色",
        }
    ),
    "marker_fill_color": frozenset(
        {
            "markerfillcolor",
            "markerfillcolour",
            "symbolfillcolor",
            "标记填充色",
            "符号填充色",
        }
    ),
    "legend_label": frozenset({"legendlabel", "indexlabel", "图例文字", "索引文字"}),
    "legend_group": frozenset({"legendgroup", "indexgroup", "图例分组", "索引分组"}),
    "legend_identity": frozenset(
        {"legendidentity", "markeridentity", "图例身份", "标记身份"}
    ),
    "legend_column": frozenset({"legendcolumn", "indexcolumn", "图例列", "索引列"}),
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
