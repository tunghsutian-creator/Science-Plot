from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

import pandas as pd

from src.data_loader import CurveSeries
from src.text_normalization import canonicalize_token, normalize_label, normalize_unit


@dataclass(frozen=True)
class RawSeriesSpec:
    x_col: int
    y_col: int
    header_row: int
    data_start_row: int
    x_label: str
    y_label: str
    x_unit: str = ""
    y_unit: str = ""
    sample_name: str | None = None
    sample_col: int | None = None


@dataclass(frozen=True)
class RawPlotIntent:
    experiment_family: str
    model: str
    recommended_template: str
    reason: str
    series_specs: tuple[RawSeriesSpec, ...] = ()
    metric_columns: tuple[str, ...] = ()
    xscale: str | None = None
    yscale: str | None = None
    reverse_x: bool | None = None
    baseline: str | None = None

    @property
    def supports_curve_series(self) -> bool:
        return bool(self.series_specs)

    @property
    def semantic_signals(self) -> tuple[str, ...]:
        signals = [
            f"Detected {self.experiment_family} plot source.",
            self.reason,
        ]
        if self.series_specs:
            first = self.series_specs[0]
            signals.append(f"Mapped {first.x_label} to X and {first.y_label} to Y.")
        if self.metric_columns:
            signals.append(f"Detected metrics: {', '.join(self.metric_columns)}.")
        return tuple(signals)

    @property
    def preview_overrides(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "experiment_family": self.experiment_family,
            "recommended_action": "add_as_plot_source",
            "recommendation_reason": self.reason,
        }
        if self.xscale is not None:
            payload["xscale"] = self.xscale
        if self.yscale is not None:
            payload["yscale"] = self.yscale
        if self.reverse_x is not None:
            payload["reverse_x"] = self.reverse_x
        if self.baseline is not None:
            payload["baseline"] = self.baseline
        return payload


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    return str(value).strip()


def _token(value: Any) -> str:
    return canonicalize_token(_clean_text(value))


def _looks_numeric(value: Any) -> bool:
    text = _clean_text(value)
    if not text:
        return False
    try:
        float(text)
    except ValueError:
        return False
    return True


def _row_tokens(raw: pd.DataFrame, row_index: int) -> list[str]:
    if row_index >= raw.shape[0]:
        return []
    return [_token(value) for value in raw.iloc[row_index].tolist()]


def _token_matches(token: str, accepted: set[str]) -> bool:
    if not token:
        return False
    return token in accepted or any(part and part in token for part in accepted)


def _header_row_with(raw: pd.DataFrame, required: tuple[set[str], ...], *, limit: int = 12) -> int | None:
    max_rows = min(limit, raw.shape[0])
    for row_index in range(max_rows):
        tokens = _row_tokens(raw, row_index)
        if all(any(_token_matches(token, accepted) for token in tokens) for accepted in required):
            return row_index
    return None


def _columns_matching(raw: pd.DataFrame, header_row: int, accepted: set[str]) -> list[int]:
    matches: list[int] = []
    for col, value in enumerate(raw.iloc[header_row].tolist()):
        token = _token(value)
        if _token_matches(token, accepted):
            matches.append(col)
    return matches


def _unit_row_index(raw: pd.DataFrame, header_row: int, columns: tuple[int, ...]) -> int | None:
    candidate = header_row + 1
    if candidate >= raw.shape[0] or not columns:
        return None
    values = [_clean_text(raw.iloc[candidate, col]) for col in columns]
    if not any(values):
        return None
    numeric_count = sum(_looks_numeric(value) for value in values)
    return None if numeric_count == len(values) else candidate


def _label_and_unit(raw_label: str) -> tuple[str, str]:
    label = _clean_text(raw_label)
    unit = ""
    match = re.search(r"^(?P<label>.+?)\s*[\(\[](?P<unit>.+?)[\)\]]\s*$", label)
    if match is not None:
        label = match.group("label")
        unit = match.group("unit")
    elif "_" in label:
        left, right = label.split("_", 1)
        if left and right:
            label = left
            unit = right
    return normalize_label(label), normalize_unit(unit)


def _spec(
    raw: pd.DataFrame,
    *,
    family: str,
    x_col: int,
    y_col: int,
    header_row: int,
    sample_col: int | None = None,
    sample_name: str | None = None,
) -> RawSeriesSpec:
    unit_row = _unit_row_index(raw, header_row, (x_col, y_col))
    data_start_row = (unit_row + 1) if unit_row is not None else header_row + 1
    x_label, parsed_x_unit = _label_and_unit(_clean_text(raw.iloc[header_row, x_col]))
    y_label, parsed_y_unit = _label_and_unit(_clean_text(raw.iloc[header_row, y_col]))
    x_unit = normalize_unit(_clean_text(raw.iloc[unit_row, x_col])) if unit_row is not None else parsed_x_unit
    y_unit = normalize_unit(_clean_text(raw.iloc[unit_row, y_col])) if unit_row is not None else parsed_y_unit
    default_sample = {
        "rheology": y_label,
        "chromatography": y_label,
        "thermal": "TGA",
        "spectroscopy": "Spectrum",
        "scattering": "Scattering",
        "swelling_gel": "Sample",
        "mechanical": "Sample",
    }.get(family, "Sample")
    return RawSeriesSpec(
        x_col=x_col,
        y_col=y_col,
        header_row=header_row,
        data_start_row=data_start_row,
        x_label=x_label,
        y_label=y_label,
        x_unit=x_unit,
        y_unit=y_unit,
        sample_name=sample_name or default_sample,
        sample_col=sample_col,
    )


def _sample_column(raw: pd.DataFrame, header_row: int) -> int | None:
    for col, value in enumerate(raw.iloc[header_row].tolist()):
        token = _token(value)
        if token in {"sample", "sample id", "polymer", "id", "ide", "specimen"}:
            return col
    return None


def _dedupe_labels(labels: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for label in labels:
        cleaned = normalize_label(label) or label
        token = canonicalize_token(cleaned)
        if not cleaned or token in seen:
            continue
        seen.add(token)
        result.append(cleaned)
    return tuple(result)


def _path_or_header_mentions(text: str, words: tuple[str, ...]) -> bool:
    token = canonicalize_token(text)
    return any(word in token for word in words)


def _detect_block_metric_replicates(raw: pd.DataFrame, source_path: Path | None) -> RawPlotIntent | None:
    if raw.shape[0] < 3 or raw.shape[1] < 3:
        return None
    first_row = [_clean_text(value) for value in raw.iloc[0].tolist()]
    second_row = [_clean_text(value) for value in raw.iloc[1].tolist()]
    block_names: list[str] = []
    metric_names: list[str] = []
    for col, group_name in enumerate(first_row):
        if not group_name or _looks_numeric(group_name):
            continue
        group_header = second_row[col] if col < len(second_row) else ""
        if _token(group_header) not in {"sample", "sample id", "specimen", "id"} and "样品" not in group_header:
            continue
        metrics_in_block: list[str] = []
        for metric_col in range(col + 1, min(col + 4, raw.shape[1])):
            header = second_row[metric_col]
            if not header:
                continue
            header_token = _token(header)
            if header_token in {"sample", "sample id", "specimen", "id"} or "样品" in header:
                continue
            values = pd.to_numeric(raw.iloc[2:, metric_col], errors="coerce")
            if values.notna().any():
                metrics_in_block.append(header)
        if metrics_in_block:
            block_names.append(group_name)
            metric_names.extend(metrics_in_block)

    if len(block_names) < 2 or not metric_names:
        return None

    text = " ".join(
        [
            str(source_path or ""),
            " ".join(first_row),
            " ".join(second_row),
        ]
    )
    family = "impact" if _path_or_header_mentions(
        text,
        ("impact", "resistence", "resistance", "foam", "izod", "charpy", "kj/m2", "kj/m²", "energy"),
    ) else "metrics"
    return RawPlotIntent(
        experiment_family=family,
        model="replicate_table",
        recommended_template="bar" if family == "impact" else "box",
        reason=(
            "Detected a grouped impact/metrics workbook with replicate measurements per sample group."
            if family == "impact"
            else "Detected a grouped metrics workbook with replicate measurements per sample group."
        ),
        metric_columns=_dedupe_labels(metric_names),
    )


def _detect_metrics_table(raw: pd.DataFrame) -> RawPlotIntent | None:
    header_row = _header_row_with(raw, ({"sample", "specimen", "composition", "group"},), limit=2)
    if header_row is None or header_row + 1 >= raw.shape[0]:
        return None
    headers = [_clean_text(value) for value in raw.iloc[header_row].tolist()]
    numeric_metric_headers: list[str] = []
    for col, header in enumerate(headers):
        data = pd.to_numeric(raw.iloc[header_row + 1 :, col], errors="coerce")
        if data.notna().any() and _token(header) not in {"sample", "specimen"}:
            if not re.fullmatch(r"[a-zA-Z%/.0-9\-]+", header or "") or any(
                word in _token(header)
                for word in ("impact", "strength", "density", "modulus", "elongation", "fraction")
            ):
                numeric_metric_headers.append(normalize_label(header) or f"Metric {col + 1}")
    if len(numeric_metric_headers) < 2:
        return None
    family = "impact" if any("impact" in _token(header) or "foam" in _token(header) for header in headers) else "metrics"
    return RawPlotIntent(
        experiment_family=family,
        model="table_summary",
        recommended_template="table_figure",
        reason="Detected a compact sample metrics table; plotting every numeric column would hide table semantics.",
        metric_columns=_dedupe_labels(numeric_metric_headers),
    )


def detect_raw_plot_intent(raw: pd.DataFrame, source_path: Path | None = None) -> RawPlotIntent | None:
    compact = raw.dropna(how="all").dropna(axis=1, how="all")
    if compact.empty:
        return None

    rheology_header = _header_row_with(
        compact,
        (
            {"angular frequency", "frequency", "ω"},
            {"storage modulus", "g'"},
            {"loss modulus", 'g"'},
        ),
    )
    if rheology_header is not None:
        x_col = _columns_matching(compact, rheology_header, {"angular frequency", "frequency", "ω"})[0]
        y_cols = _columns_matching(
            compact,
            rheology_header,
            {"storage modulus", "loss modulus", "complex viscosity", "loss factor", "tan delta", "g'", 'g"'},
        )
        return RawPlotIntent(
            experiment_family="rheology",
            model="frequency_metric_sheet",
            recommended_template="point_line",
            reason="Detected a raw rheology frequency sweep with modulus/viscosity metrics.",
            series_specs=tuple(
                _spec(compact, family="rheology", x_col=x_col, y_col=y_col, header_row=rheology_header)
                for y_col in y_cols
                if y_col != x_col
            ),
            xscale="log",
            yscale="log",
            reverse_x=False,
        )

    tensile_header = _header_row_with(
        compact,
        (
            {"strain", "elongation", "extension"},
            {"stress", "force", "load"},
        ),
    )
    if tensile_header is not None:
        x_col = _columns_matching(compact, tensile_header, {"strain", "elongation", "extension"})[0]
        y_col = _columns_matching(compact, tensile_header, {"stress", "force", "load"})[0]
        return RawPlotIntent(
            experiment_family="mechanical",
            model="tensile_curve",
            recommended_template="curve",
            reason="Detected a raw mechanical stress/force versus strain table.",
            series_specs=(
                _spec(
                    compact,
                    family="mechanical",
                    x_col=x_col,
                    y_col=y_col,
                    header_row=tensile_header,
                    sample_name=source_path.stem if source_path else "Sample",
                ),
            ),
            xscale="linear",
            yscale="linear",
            reverse_x=False,
        )

    ftir_header = _header_row_with(
        compact,
        (
            {"wavenumber", "wavelength"},
            {"transmittance", "absorbance", "%t", "intensity"},
        ),
    )
    if ftir_header is not None:
        x_col = _columns_matching(compact, ftir_header, {"wavenumber", "wavelength"})[0]
        y_col = _columns_matching(compact, ftir_header, {"transmittance", "absorbance", "%t", "intensity"})[0]
        return RawPlotIntent(
            experiment_family="spectroscopy",
            model="curve_table",
            recommended_template="curve",
            reason="Detected spectroscopy trace columns with wavenumber/wavelength and response values.",
            series_specs=(
                _spec(
                    compact,
                    family="spectroscopy",
                    x_col=x_col,
                    y_col=y_col,
                    header_row=ftir_header,
                    sample_col=_sample_column(compact, ftir_header),
                ),
            ),
            xscale="linear",
            yscale="linear",
            reverse_x=_token(compact.iloc[ftir_header, x_col]) == "wavenumber",
            baseline="none",
        )

    thermal_header = _header_row_with(
        compact,
        (
            {"temp", "temperature", "temp c", "temp (c)"},
            {"weight", "heat flow", "mass", "dtg"},
        ),
    )
    if thermal_header is not None:
        x_col = _columns_matching(compact, thermal_header, {"temp", "temperature", "temp c", "temp (c)"})[0]
        y_col = _columns_matching(compact, thermal_header, {"weight", "heat flow", "mass", "dtg"})[0]
        return RawPlotIntent(
            experiment_family="thermal",
            model="curve_table",
            recommended_template="curve",
            reason="Detected thermal analysis columns with temperature and weight/heat-flow response.",
            series_specs=(
                _spec(compact, family="thermal", x_col=x_col, y_col=y_col, header_row=thermal_header),
            ),
            xscale="linear",
            yscale="linear",
            reverse_x=False,
        )

    scattering_header = _header_row_with(
        compact,
        (
            {"q", "q nm-1", "2theta", "2 theta", "2θ"},
            {"intensity", "counts", "count"},
        ),
    )
    if scattering_header is not None:
        x_col = _columns_matching(compact, scattering_header, {"q", "q nm-1", "2theta", "2 theta", "2θ"})[0]
        y_col = _columns_matching(compact, scattering_header, {"intensity", "counts", "count"})[0]
        return RawPlotIntent(
            experiment_family="scattering",
            model="curve_table",
            recommended_template="curve",
            reason="Detected scattering/diffraction columns with q or 2theta and intensity.",
            series_specs=(
                _spec(
                    compact,
                    family="scattering",
                    x_col=x_col,
                    y_col=y_col,
                    header_row=scattering_header,
                    sample_col=_sample_column(compact, scattering_header),
                ),
            ),
            xscale="linear",
            yscale="linear",
            reverse_x=False,
        )

    swelling_header = _header_row_with(
        compact,
        (
            {"time", "time h", "time hr", "time min"},
            {"swelling ratio", "swelling", "gel fraction"},
        ),
    )
    if swelling_header is not None:
        x_col = _columns_matching(compact, swelling_header, {"time", "time h", "time hr", "time min"})[0]
        y_col = _columns_matching(compact, swelling_header, {"swelling ratio", "swelling"})[0]
        return RawPlotIntent(
            experiment_family="swelling_gel",
            model="curve_table",
            recommended_template="point_line",
            reason="Detected swelling/gel time-series columns with sample grouping.",
            series_specs=(
                _spec(
                    compact,
                    family="swelling_gel",
                    x_col=x_col,
                    y_col=y_col,
                    header_row=swelling_header,
                    sample_col=_sample_column(compact, swelling_header),
                ),
            ),
            xscale="linear",
            yscale="linear",
            reverse_x=False,
        )

    chromatography_header = _header_row_with(
        compact,
        (
            {"time", "retention time", "elution volume", "volume"},
            {"rayleigh ratio", "dri", "ri", "uv", "detector", "signal"},
        ),
    )
    if chromatography_header is not None:
        x_cols = _columns_matching(compact, chromatography_header, {"time", "retention time", "elution volume", "volume"})
        y_cols = _columns_matching(compact, chromatography_header, {"rayleigh ratio", "dri", "ri", "uv", "detector", "signal"})
        specs: list[RawSeriesSpec] = []
        for y_col in y_cols:
            preceding_x = max((col for col in x_cols if col < y_col), default=x_cols[0])
            specs.append(_spec(compact, family="chromatography", x_col=preceding_x, y_col=y_col, header_row=chromatography_header))
        if specs:
            return RawPlotIntent(
                experiment_family="chromatography",
                model="curve_table",
                recommended_template="curve",
                reason="Detected chromatography/GPC detector traces against elution time or volume.",
                series_specs=tuple(specs),
                xscale="linear",
                yscale="linear",
                reverse_x=False,
            )

    block_metrics = _detect_block_metric_replicates(compact, source_path)
    if block_metrics is not None:
        return block_metrics

    metrics = _detect_metrics_table(compact)
    if metrics is not None:
        return metrics

    return None


def curve_series_from_raw_intent(
    raw: pd.DataFrame,
    intent: RawPlotIntent,
    *,
    source_path: Path | None = None,
) -> list[CurveSeries]:
    if not intent.series_specs:
        raise ValueError("Raw plot intent does not contain curve series specs.")
    compact = raw.dropna(how="all").dropna(axis=1, how="all")
    series_list: list[CurveSeries] = []
    for spec_index, spec in enumerate(intent.series_specs, start=1):
        data_rows = compact.iloc[spec.data_start_row :].copy()
        x_values = pd.to_numeric(data_rows.iloc[:, spec.x_col], errors="coerce")
        y_values = pd.to_numeric(data_rows.iloc[:, spec.y_col], errors="coerce")
        frame = pd.DataFrame({"x": x_values, "y": y_values})
        if spec.sample_col is not None and spec.sample_col < compact.shape[1]:
            frame["sample"] = data_rows.iloc[:, spec.sample_col].map(_clean_text).replace("", pd.NA)
        frame = frame.dropna(subset=["x", "y"]).reset_index(drop=True)
        if frame.empty:
            continue
        if "sample" in frame.columns and frame["sample"].notna().any():
            for sample_name, sample_frame in frame.groupby("sample", sort=False):
                sample_data = sample_frame[["x", "y"]].reset_index(drop=True)
                if sample_data.empty:
                    continue
                series_list.append(
                    CurveSeries(
                        sample=str(sample_name),
                        x_label=spec.x_label or "X",
                        y_label=spec.y_label or "Y",
                        x_unit=spec.x_unit,
                        y_unit=spec.y_unit,
                        data=sample_data,
                    )
                )
        else:
            sample_name = spec.sample_name or (source_path.stem if source_path else f"Series {spec_index}")
            series_list.append(
                CurveSeries(
                    sample=sample_name,
                    x_label=spec.x_label or "X",
                    y_label=spec.y_label or "Y",
                    x_unit=spec.x_unit,
                    y_unit=spec.y_unit,
                    data=frame[["x", "y"]].reset_index(drop=True),
                )
            )
    if not series_list:
        raise ValueError("No numeric curve series could be prepared from the raw plot intent.")
    return series_list


__all__ = [
    "RawPlotIntent",
    "RawSeriesSpec",
    "curve_series_from_raw_intent",
    "detect_raw_plot_intent",
]
