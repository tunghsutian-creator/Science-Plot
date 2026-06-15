from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from src.text_normalization import normalize_label, normalize_unit


@dataclass
class RheologySeries:
    sample: str
    x_label: str
    y_label: str
    x_unit: str
    y_unit: str
    data: pd.DataFrame


def _clean_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    return str(value).strip()


def _read_excel(path: str | Path, sheet_name: str | int = 0) -> pd.DataFrame:
    raw = pd.read_excel(path, sheet_name=sheet_name, header=None)
    return raw.dropna(axis=1, how="all")


def _row_has_content(row: pd.Series) -> bool:
    return any(_clean_text(value) for value in row.tolist())


def _ensure_rheology_layout(raw: pd.DataFrame, *, table_name: str, block_width: int) -> None:
    if raw.shape[0] < 4:
        raise ValueError(f"{table_name} must include at least 4 rows.")
    if raw.shape[1] == 0:
        raise ValueError(f"{table_name} does not contain any usable columns.")
    if raw.shape[1] % block_width != 0:
        raise ValueError(f"{table_name} must contain {block_width} columns per sample.")
    if not _row_has_content(raw.iloc[0]):
        raise ValueError(f"{table_name} is missing the metric label row.")
    if not _row_has_content(raw.iloc[1]):
        raise ValueError(f"{table_name} is missing the sample row.")
    if not _row_has_content(raw.iloc[2]):
        raise ValueError(f"{table_name} is missing the unit row.")


def _is_complex_modulus_label(value: object) -> bool:
    label = _clean_text(value).casefold()
    compact = "".join(ch for ch in label if ch.isalnum())
    return ("complex" in compact and "modulus" in compact) or "g*" in label or "|g*|" in label


def _frequency_block_width(raw: pd.DataFrame) -> int:
    if raw.shape[1] % 6 == 0 and all(
        _is_complex_modulus_label(raw.iloc[0, start + 5]) for start in range(0, raw.shape[1], 6)
    ):
        return 6
    if raw.shape[1] % 5 == 0:
        return 5
    raise ValueError("Frequency sweep table must contain 5 or 6 columns per sample.")


def load_frequency_sweep_metrics(path: str | Path, sheet_name: str | int = 0) -> dict[str, list[RheologySeries]]:
    raw = _read_excel(path, sheet_name=sheet_name)
    block_width = _frequency_block_width(raw)
    _ensure_rheology_layout(raw, table_name="Frequency sweep table", block_width=block_width)

    metric_series: dict[str, list[RheologySeries]] = {
        "storage_modulus": [],
        "loss_modulus": [],
        "loss_factor": [],
        "complex_viscosity": [],
        "complex_modulus": [],
    }
    for start in range(0, raw.shape[1], block_width):
        labels = [_clean_text(raw.iloc[0, start + idx]) for idx in range(block_width)]
        sample = _clean_text(raw.iloc[1, start])
        units = [_clean_text(raw.iloc[2, start + idx]) for idx in range(block_width)]
        block = raw.iloc[3:, start : start + block_width].copy().reset_index(drop=True)
        columns = ["x", "storage_modulus", "loss_modulus", "loss_factor"]
        metric_offsets = {
            "storage_modulus": 1,
            "loss_modulus": 2,
            "loss_factor": 3,
        }
        if block_width == 6:
            columns.extend(["complex_viscosity", "complex_modulus"])
            metric_offsets["complex_viscosity"] = 4
            metric_offsets["complex_modulus"] = 5
        elif _is_complex_modulus_label(labels[4]):
            columns.append("complex_modulus")
            metric_offsets["complex_modulus"] = 4
        else:
            columns.append("complex_viscosity")
            metric_offsets["complex_viscosity"] = 4
        block.columns = columns
        block = block.apply(pd.to_numeric, errors="coerce").dropna(how="all")
        if "complex_modulus" not in block.columns:
            block["complex_modulus"] = (
                block["storage_modulus"].pow(2).add(block["loss_modulus"].pow(2)).pow(0.5)
            )

        x_label = normalize_label(labels[0] or "ω")
        x_unit = normalize_unit(units[0])
        labels_by_metric = {key: labels[offset] for key, offset in metric_offsets.items()}
        units_by_metric = {key: units[offset] for key, offset in metric_offsets.items()}
        labels_by_metric.setdefault("complex_modulus", "Complex Modulus")
        units_by_metric.setdefault(
            "complex_modulus",
            units_by_metric.get("storage_modulus") or units_by_metric.get("loss_modulus") or "Pa",
        )

        for key in ("storage_modulus", "loss_modulus", "loss_factor", "complex_viscosity", "complex_modulus"):
            if key not in block.columns:
                continue
            y_label = normalize_label(labels_by_metric.get(key) or key)
            y_unit = normalize_unit(units_by_metric.get(key) or "")
            pair = block[["x", key]].dropna().rename(columns={key: "y"}).reset_index(drop=True)
            if pair.empty:
                continue
            metric_series[key].append(
                RheologySeries(
                    sample=sample or f"Sample_{start // block_width + 1}",
                    x_label=x_label,
                    y_label=y_label,
                    x_unit=x_unit,
                    y_unit=y_unit,
                    data=pair,
                )
            )

    return {key: series_list for key, series_list in metric_series.items() if series_list}


def load_temperature_sweep_metrics(path: str | Path, sheet_name: str | int = 0) -> dict[str, list[RheologySeries]]:
    raw = _read_excel(path, sheet_name=sheet_name)
    _ensure_rheology_layout(raw, table_name="Temperature sweep table", block_width=5)

    metric_series: dict[str, list[RheologySeries]] = {
        "storage_modulus": [],
        "complex_viscosity": [],
    }
    metric_map = [
        ("storage_modulus", 1),
        ("complex_viscosity", 4),
    ]

    for start in range(0, raw.shape[1], 5):
        labels = [_clean_text(raw.iloc[0, start + idx]) for idx in range(5)]
        sample = _clean_text(raw.iloc[1, start])
        units = [_clean_text(raw.iloc[2, start + idx]) for idx in range(5)]
        block = raw.iloc[3:, start : start + 5].copy().reset_index(drop=True)
        block.columns = ["x", "storage_modulus", "loss_modulus", "loss_factor", "complex_viscosity"]
        block = block.apply(pd.to_numeric, errors="coerce").dropna(how="all")

        x_label = normalize_label("Temperature")
        x_unit = normalize_unit(units[0] or "°C")

        for key, offset in metric_map:
            y_label = normalize_label(labels[offset] or key)
            y_unit = normalize_unit(units[offset])
            pair = block[["x", key]].dropna().rename(columns={key: "y"}).reset_index(drop=True)
            if pair.empty:
                continue
            metric_series[key].append(
                RheologySeries(
                    sample=sample or f"Sample_{start // 5 + 1}",
                    x_label=x_label,
                    y_label=y_label,
                    x_unit=x_unit,
                    y_unit=y_unit,
                    data=pair,
                )
            )

    return metric_series


def load_stress_relaxation_metric(
    path: str | Path,
    metric_name: str = "σ/σ₀",
    sheet_name: str | int = 0,
) -> list[RheologySeries]:
    raw = _read_excel(path, sheet_name=sheet_name)
    _ensure_rheology_layout(raw, table_name="Stress relaxation table", block_width=4)

    metric_key = normalize_label(metric_name)

    series_list: list[RheologySeries] = []
    for start in range(0, raw.shape[1], 4):
        labels = [_clean_text(raw.iloc[0, start + idx]) for idx in range(4)]
        sample_candidates = [_clean_text(raw.iloc[1, start + idx]) for idx in range(4)]
        sample = next((value for value in sample_candidates if value), "")
        units = [_clean_text(raw.iloc[2, start + idx]) for idx in range(4)]
        block = raw.iloc[3:, start : start + 4].copy().reset_index(drop=True)
        block.columns = ["time", "strain", "stress", "normalized_stress"]
        block = block.apply(pd.to_numeric, errors="coerce").dropna(how="all")

        y_label_lookup = [normalize_label(label) for label in labels]
        try:
            y_index = y_label_lookup.index(metric_key)
        except ValueError as exc:
            raise ValueError(
                f"Metric {metric_key!r} not found in stress relaxation block {start // 4 + 1}."
            ) from exc

        metric_column = ["time", "strain", "stress", "normalized_stress"][y_index]
        pair = (
            block[["time", metric_column]]
            .dropna()
            .rename(columns={"time": "x", metric_column: "y"})
            .reset_index(drop=True)
        )
        if pair.empty:
            continue

        series_list.append(
            RheologySeries(
                sample=sample or f"Sample_{start // 4 + 1}",
                x_label=normalize_label(labels[0] or "t"),
                y_label=metric_key,
                x_unit=normalize_unit(units[0]),
                y_unit=normalize_unit(units[y_index]),
                data=pair,
            )
        )

    return series_list
