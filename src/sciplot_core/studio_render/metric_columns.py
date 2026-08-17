"""Select metric column pairs and derive stable labels and units."""

from __future__ import annotations

from typing import Any
import pandas as pd
from sciplot_core.materials_rules import (
    format_unit_label,
)

from sciplot_core.studio_render.models import (
    StudioPreparationBlocked,
)


def _xy_pairs_for_request(
    numeric: pd.DataFrame,
    *,
    request: dict[str, Any],
    strict_metric_binding: bool = False,
) -> list[tuple[Any, Any]]:
    metric_pair = _preferred_metric_pair(request)
    if metric_pair is not None:
        x_metric, y_metric = metric_pair
        pairs = _metric_xy_pairs(numeric, x_metric=x_metric, y_metric=y_metric)
        if pairs:
            return pairs
        if strict_metric_binding:
            raise StudioPreparationBlocked(
                "terminal_source_binding_metric_unavailable",
                "The bound terminal table has no exact columns for "
                f"{x_metric!r} and {y_metric!r}; SciPlot will not substitute.",
            )
        if str(request.get("rule_id") or "").strip() == "rheology_frequency_sweep":
            raise StudioPreparationBlocked(
                "figure_metric_unavailable",
                "The frequency-sweep figure requests "
                f"{y_metric!r}, but the prepared source has no matching "
                "metric column. SciPlot will not substitute another metric.",
            )
    return _xy_pairs(numeric)


def _xy_pairs(numeric: pd.DataFrame) -> list[tuple[Any, Any]]:
    columns = list(numeric.columns)
    if len(columns) >= 4 and len(columns) % 2 == 0:
        even_columns = columns[0::2]
        odd_columns = columns[1::2]
        if _columns_look_like_repeated_x(even_columns):
            return list(zip(even_columns, odd_columns, strict=True))
    return [(columns[0], column) for column in columns[1:]]


def _columns_look_like_repeated_x(columns: list[Any]) -> bool:
    cleaned = [
        _clean_column_label(column).split(".")[0].casefold() for column in columns
    ]
    return len(set(cleaned)) == 1 or all(
        label in {"x", "time", "temperature", "frequency"} for label in cleaned
    )


def _preferred_metric_pair(request: dict[str, Any]) -> tuple[str, str] | None:
    x_metric = _clean_metric_id(request.get("x_metric"))
    y_metric = _clean_metric_id(request.get("y_metric"))
    rule_id = str(request.get("rule_id") or "").strip()
    study_model = (
        request.get("study_model")
        if isinstance(request.get("study_model"), dict)
        else {}
    )
    figure_queue = (
        study_model.get("figure_queue")
        if isinstance(study_model.get("figure_queue"), list)
        else []
    )
    if (not x_metric or not y_metric) and figure_queue:
        first_figure = next(
            (item for item in figure_queue if isinstance(item, dict)), {}
        )
        x_metric = x_metric or _clean_metric_id(first_figure.get("x_metric"))
        y_metric = y_metric or _clean_metric_id(first_figure.get("y_metric"))
    if rule_id in {
        "rheology_frequency_sweep",
        "rheology_temperature_sweep",
        "rheology_strain_sweep",
        "rheology_stress_sweep",
        "rheology_time_sweep",
    }:
        if x_metric == "x":
            x_metric = ""
        if y_metric == "y":
            y_metric = ""
    if not x_metric or not y_metric:
        if rule_id == "rheology_frequency_sweep":
            x_metric = x_metric or "angular_frequency"
            y_metric = y_metric or "storage_modulus"
        elif rule_id == "rheology_temperature_sweep":
            x_metric = x_metric or "temperature"
            y_metric = y_metric or "storage_modulus"
        elif rule_id == "rheology_strain_sweep":
            x_metric = x_metric or "strain"
            y_metric = y_metric or "storage_modulus"
        elif rule_id == "rheology_stress_sweep":
            x_metric = x_metric or "stress"
            y_metric = y_metric or "storage_modulus"
        elif rule_id == "rheology_time_sweep":
            x_metric = x_metric or "time"
            y_metric = y_metric or "complex_modulus"
    if x_metric and y_metric:
        return x_metric, y_metric
    return None


def _clean_metric_id(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip().casefold().replace(" ", "_").replace("-", "_")


_METRIC_ALIASES: dict[str, tuple[str, ...]] = {
    "angular_frequency": ("angular frequency", "frequency", "omega"),
    "temperature": ("temperature", "temp"),
    "strain": ("strain", "shear strain", "gamma"),
    "stress": ("stress", "shear stress"),
    "time": ("time", "elapsed time"),
    "storage_modulus": (
        "storage modulus",
        "storage modulus, e'",
        "e'",
        "g'",
        "g prime",
    ),
    "loss_modulus": ("loss modulus", 'g"', "g double prime"),
    "loss_factor": ("loss factor", "tan delta", "tan_delta"),
    "complex_modulus": ("complex modulus", "complex shear modulus", "g*"),
    "complex_viscosity": ("complex viscosity", "viscosity"),
}


def _metric_xy_pairs(
    numeric: pd.DataFrame, *, x_metric: str, y_metric: str
) -> list[tuple[Any, Any]]:
    columns = list(numeric.columns)
    x_columns = [
        column for column in columns if _column_matches_metric(column, x_metric)
    ]
    y_columns = [
        column for column in columns if _column_matches_metric(column, y_metric)
    ]
    pairs: list[tuple[Any, Any]] = []
    for y_column in y_columns:
        suffix = _duplicate_column_suffix(y_column)
        x_column = next(
            (
                column
                for column in x_columns
                if _duplicate_column_suffix(column) == suffix
            ),
            x_columns[0] if x_columns else None,
        )
        if x_column is not None:
            pairs.append((x_column, y_column))
    return pairs


def _column_matches_metric(column: Any, metric: str) -> bool:
    aliases = _METRIC_ALIASES.get(metric, (metric,))
    label = _normal_metric_label(_column_base_label(column))
    return any(label == _normal_metric_label(alias) for alias in aliases)


def _column_base_label(column: Any) -> str:
    label = _clean_column_label(column)
    if "." in label:
        base, suffix = label.rsplit(".", maxsplit=1)
        if suffix.isdigit():
            return base
    return label


def _duplicate_column_suffix(column: Any) -> str:
    label = _clean_column_label(column)
    if "." in label:
        _base, suffix = label.rsplit(".", maxsplit=1)
        if suffix.isdigit():
            return suffix
    return ""


def _normal_metric_label(label: str) -> str:
    text = label.casefold().replace("′", "'").replace("δ", "delta")
    return "".join(
        character
        for character in text
        if character.isalnum() or character in {"'", '"', "*"}
    )


def _is_rheology_sweep_request(request: dict[str, Any] | None) -> bool:
    if not isinstance(request, dict):
        return False
    return str(request.get("rule_id") or "").strip() in {
        "rheology_frequency_sweep",
        "rheology_temperature_sweep",
    }


def _clean_column_label(column: Any) -> str:
    label = str(column).strip()
    return label or "value"


def _axis_label_from_column(frame: pd.DataFrame, column: Any) -> str:
    label = _clean_column_label(column)
    if column not in frame:
        return label
    unit = _unit_label_from_column(frame[column])
    if not unit or unit.casefold() in label.casefold():
        return label
    return f"{label} ({unit})"


def _unit_label_from_column(values: pd.Series) -> str:
    for value in values.tolist()[:8]:
        if pd.isna(value):
            continue
        text = str(value).strip().strip("[]")
        if not text:
            continue
        try:
            float(text)
            continue
        except ValueError:
            pass
        if text == "PA":
            continue
        if _is_unit_label(text.casefold()):
            return text
    return ""


def _series_label_from_column(
    values: pd.Series,
    *,
    fallback: str,
    metadata_order: str | None = None,
) -> str:
    metadata = [
        None if pd.isna(value) else _metadata_label(value)
        for value in values.tolist()[:2]
    ]
    if metadata_order == "unit_then_sample" and len(metadata) >= 2 and metadata[1]:
        return metadata[1]
    if metadata_order == "sample_then_unit" and metadata and metadata[0]:
        return metadata[0]
    leading = [
        str(value).strip()
        for value in values.tolist()[:4]
        if not pd.isna(value) and str(value).strip()
    ]
    if leading and all(_is_numeric_text(value) for value in leading):
        # Plain numeric observations are data, not a unit/sample metadata
        # prefix.  In particular, a series starting with 1, 2 previously
        # treated dimensionless ``1`` as a unit and mislabeled the series
        # with its second measured value.
        return fallback
    if len(leading) >= 2:
        first_is_unit = _is_unit_label(leading[0].casefold())
        second_is_unit = _is_unit_label(leading[1].casefold())
        if second_is_unit:
            # Comparison workbooks may store the sample label immediately
            # above the unit. Preserve numeric sample IDs and labels such as
            # `PA`, whose case-folded spelling is also the unit `Pa`.
            return leading[0]
        if first_is_unit and not second_is_unit:
            # Semantic tables may store unit first and sample second.
            return leading[1]
    strings: list[str] = []
    for value in values.tolist():
        if pd.isna(value):
            continue
        text = str(value).strip()
        if not text:
            continue
        try:
            float(text)
            continue
        except ValueError:
            strings.append(text)
    for text in reversed(strings):
        lowered = text.casefold()
        if not _is_unit_label(lowered):
            return text
    return fallback


def _metadata_label(value: Any) -> str:
    """Preserve integer-valued numeric sample IDs without a pandas ``.0`` suffix."""

    if isinstance(value, int | float):
        numeric = float(value)
        if numeric.is_integer():
            return str(int(numeric))
    return str(value).strip()


def _is_numeric_text(value: str) -> bool:
    try:
        float(value)
    except ValueError:
        return False
    return True


def _is_unit_label(label: str) -> bool:
    unit = label.strip().strip("[]").strip()
    normalized = format_unit_label(unit).casefold()
    return normalized in {
        "1",
        "%",
        "% °c⁻¹",
        "a.u.",
        "au",
        "c",
        "cm^-1",
        "cm⁻¹",
        "count",
        "degree",
        "degc",
        "hz",
        "g/mol",
        "g mol⁻¹",
        "kj/m2",
        "kj m⁻²",
        "min",
        "mins",
        "mv",
        "mn·m",
        "mpa",
        "mpa min⁻¹",
        "mpa·s",
        "mj m⁻³",
        "nm",
        "nm^-1",
        "nm⁻¹",
        "pa",
        "pa⁻¹",
        "pa·s",
        "rad/s",
        "rad s⁻¹",
        "s",
        "sec",
        "seconds",
        "um",
        "µm",
        "μm",
        "°c",
        "w/g",
        "w g⁻¹",
    }
