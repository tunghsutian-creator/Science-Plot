"""Read and unit-normalize DMA temperature sweep series."""

from __future__ import annotations

import re
from pathlib import Path
import pandas as pd
from sciplot_core.foundation.text_values import (
    clean_text as _clean_text,
    token as _token,
)

from sciplot_core.source_tables import (
    read_raw_table,
)

from sciplot_core.semantic_sources.models import (
    CurveSeriesPayload,
)

from sciplot_core.semantic_sources.table_scanning import (
    _float,
)

from sciplot_core.semantic_sources.rheology_sweep_sources import (
    _sweep_source_files,
)


def _dma_modulus_unit(
    value: object,
    *,
    exact: bool = False,
) -> tuple[str, float] | None:
    pattern = r"^\s*[\[(]?\s*(?P<unit>[gmk]?pa)\s*[\])]?\s*$"
    for candidate in _dma_unit_candidates(value, exact=exact):
        match = re.fullmatch(pattern, candidate, flags=re.IGNORECASE)
        if match is None:
            continue
        normalized = match.group("unit").casefold()
        return {
            "gpa": ("GPa", 1.0e9),
            "mpa": ("MPa", 1.0e6),
            "kpa": ("kPa", 1.0e3),
            "pa": ("Pa", 1.0),
        }[normalized]
    return None


_DMA_CANONICAL_MODULUS_UNIT = "Pa"


_DMA_DISPLAY_MODULUS_UNIT = "MPa"


_DMA_CANONICAL_TO_DISPLAY_FACTOR = 1.0e-6


_DMA_CANONICAL_TEMPERATURE_UNIT = "°C"


def _dma_unit_candidates(value: object, *, exact: bool) -> tuple[str, ...]:
    text = _clean_text(value)
    if exact:
        return (text,)
    bracketed = tuple(
        _clean_text(candidate)
        for candidate in re.findall(r"[\[(]\s*([^\])]+?)\s*[\])]", text)
        if _clean_text(candidate)
    )
    if bracketed:
        return bracketed
    # Unbracketed headers may end in a standalone unit (for example,
    # ``Temperature °C``).  Restrict that compatibility path to the complete
    # trailing token so rate labels such as ``K/min`` and ``MPa/min`` cannot
    # be mistaken for temperature or modulus units.
    trailing = text.rsplit(maxsplit=1)[-1] if text else ""
    return (trailing,)


def _dma_temperature_unit(
    value: object,
    *,
    exact: bool = False,
) -> tuple[str, float, float, str] | None:
    celsius_pattern = (
        r"^\s*[\[(]?\s*(?:(?:°|o)\s*|deg(?:ree)?s?\s*)?c"
        r"\s*[\])]?\s*$"
    )
    kelvin_pattern = r"^\s*[\[(]?\s*k\s*[\])]?\s*$"
    for raw_candidate in _dma_unit_candidates(value, exact=exact):
        candidate = (
            raw_candidate.replace("℃", "°C")
            .replace("º", "°")
            .replace("˚", "°")
            .replace("K", "K")
        )
        folded = candidate.casefold().strip(" []()")
        if folded == "celsius" or re.fullmatch(
            celsius_pattern,
            candidate,
            flags=re.IGNORECASE,
        ):
            return "°C", 1.0, 0.0, "identity_celsius"
        if folded == "kelvin" or re.fullmatch(
            kelvin_pattern,
            candidate,
            flags=re.IGNORECASE,
        ):
            return "K", 1.0, -273.15, "kelvin_to_celsius"
    return None


def _dma_explicit_unknown_unit(value: object) -> str | None:
    text = _clean_text(value)
    candidates = re.findall(r"[\[(]\s*([^\])]+?)\s*[\])]", text)
    for candidate in candidates:
        cleaned = _clean_text(candidate)
        if cleaned and _float(cleaned) is None:
            return cleaned
    return None


def _dma_temperature_sample_label(
    raw: pd.DataFrame,
    *,
    header_index: int,
    y_index: int,
    y_header: str,
    fallback: str,
) -> str:
    label = re.sub(r"storage\s*modulus", "", y_header, flags=re.IGNORECASE)
    label = re.sub(r"\([^)]*\)", "", label)
    label = re.sub(r"\b[GMk]?Pa\b", "", label, flags=re.IGNORECASE)
    label = _clean_text(label).strip(" _-:;,/")
    if label:
        return label
    for row_index in range(header_index + 1, min(raw.shape[0], header_index + 4)):
        value = _clean_text(raw.iat[row_index, y_index])
        if (
            not value
            or _float(value) is not None
            or _dma_modulus_unit(value, exact=True) is not None
        ):
            continue
        return value
    return fallback


def _read_dma_temperature_series(source: Path) -> list[CurveSeriesPayload]:
    raw = read_raw_table(source).dropna(axis=1, how="all").dropna(how="all")
    best: tuple[int, list[tuple[int, int]]] | None = None
    for row_index in range(raw.shape[0]):
        headers = [_clean_text(value) for value in raw.iloc[row_index].tolist()]
        pairs = [
            (column_index, column_index + 1)
            for column_index in range(len(headers) - 1)
            if "temperature" in _token(headers[column_index])
            and "storagemodulus" in _token(headers[column_index + 1])
        ]
        if pairs and (best is None or len(pairs) > len(best[1])):
            best = (row_index, pairs)
    if best is None:
        raise ValueError(
            f"Could not find repeated temperature/storage-modulus pairs in {source}."
        )

    header_index, pairs = best
    series_list: list[CurveSeriesPayload] = []
    for pair_index, (x_index, y_index) in enumerate(pairs, start=1):
        x_header = _clean_text(raw.iat[header_index, x_index])
        y_header = _clean_text(raw.iat[header_index, y_index])
        x_unit_match = _dma_temperature_unit(x_header)
        x_unit_detection = "detected_from_header"
        if x_unit_match is None:
            for row_index in range(
                header_index + 1, min(raw.shape[0], header_index + 4)
            ):
                x_unit_match = _dma_temperature_unit(
                    raw.iat[row_index, x_index],
                    exact=True,
                )
                if x_unit_match is not None:
                    x_unit_detection = "detected_from_adjacent_unit_row"
                    break
        if x_unit_match is None:
            unknown_x_unit = _dma_explicit_unknown_unit(x_header)
            if unknown_x_unit is not None:
                raise ValueError(
                    "Unsupported DMA temperature unit "
                    f"`{unknown_x_unit}` in {source}; expected °C/C or K."
                )
            raise ValueError(
                f"Missing DMA temperature unit in {source}; "
                "expected °C/C or K in the temperature header or an "
                "adjacent unit row."
            )
        (
            source_x_unit,
            x_factor_to_display,
            x_offset_to_display,
            x_conversion_method,
        ) = x_unit_match

        y_unit_match = _dma_modulus_unit(y_header)
        y_unit_detection = "detected_from_header"
        if y_unit_match is None:
            for row_index in range(
                header_index + 1,
                min(raw.shape[0], header_index + 4),
            ):
                y_unit_match = _dma_modulus_unit(
                    raw.iat[row_index, y_index],
                    exact=True,
                )
                if y_unit_match is not None:
                    y_unit_detection = "detected_from_adjacent_unit_row"
                    break
        if y_unit_match is None:
            unknown_y_unit = _dma_explicit_unknown_unit(y_header)
            if unknown_y_unit is not None:
                raise ValueError(
                    "Unsupported DMA storage-modulus unit "
                    f"`{unknown_y_unit}` in {source}; "
                    "expected Pa, kPa, MPa, or GPa."
                )
            raise ValueError(
                f"Missing DMA storage-modulus unit in {source}; "
                "expected Pa, kPa, MPa, or GPa in the storage-modulus "
                "header or an adjacent unit row."
            )
        source_unit, factor_to_pa = y_unit_match
        sample = _dma_temperature_sample_label(
            raw,
            header_index=header_index,
            y_index=y_index,
            y_header=y_header,
            fallback=f"{source.stem} {pair_index}" if len(pairs) > 1 else source.stem,
        )
        factor_to_display = factor_to_pa * _DMA_CANONICAL_TO_DISPLAY_FACTOR
        points: list[tuple[float, float]] = []
        negative_display_values: list[float] = []
        for row_index in range(header_index + 1, raw.shape[0]):
            x_value = _float(raw.iat[row_index, x_index])
            y_value = _float(raw.iat[row_index, y_index])
            if x_value is None or y_value is None:
                continue
            display_x_value = x_value * x_factor_to_display + x_offset_to_display
            # Compose the recorded source -> Pa -> MPa factors before
            # applying them so MPa inputs retain their reported decimal
            # precision instead of acquiring multiply/divide round-off.
            display_y_value = y_value * factor_to_display
            points.append((display_x_value, display_y_value))
            if display_y_value < 0.0:
                negative_display_values.append(display_y_value)
        if not points:
            continue
        display_values = [y_value for _x_value, y_value in points]
        positive_display_peak = max(
            (value for value in display_values if value > 0.0),
            default=0.0,
        )
        negative_to_positive_peak_fraction = (
            max(abs(value) for value in negative_display_values) / positive_display_peak
            if negative_display_values and positive_display_peak > 0.0
            else None
        )
        series_list.append(
            CurveSeriesPayload(
                sample=sample,
                x_label="Temperature",
                x_unit="°C",
                y_label="Storage modulus, E′",
                y_unit=_DMA_DISPLAY_MODULUS_UNIT,
                points=tuple(points),
                diagnostics={
                    "source_file": str(source),
                    "source_x_header": x_header,
                    "source_y_header": y_header,
                    "source_x_unit": source_x_unit,
                    "source_x_unit_detection": x_unit_detection,
                    "canonical_x_unit": (_DMA_CANONICAL_TEMPERATURE_UNIT),
                    "display_x_unit": _DMA_CANONICAL_TEMPERATURE_UNIT,
                    "source_x_to_display_factor": x_factor_to_display,
                    "source_x_to_display_offset": x_offset_to_display,
                    "x_conversion_method": x_conversion_method,
                    "x_conversion_path": (
                        f"{source_x_unit} -> {_DMA_CANONICAL_TEMPERATURE_UNIT} display"
                    ),
                    "source_y_unit": source_unit,
                    "source_y_unit_detection": y_unit_detection,
                    "canonical_y_unit": _DMA_CANONICAL_MODULUS_UNIT,
                    "display_y_unit": _DMA_DISPLAY_MODULUS_UNIT,
                    "source_to_canonical_factor": factor_to_pa,
                    "canonical_to_display_factor": (_DMA_CANONICAL_TO_DISPLAY_FACTOR),
                    "source_to_display_factor": factor_to_display,
                    "conversion_path": (
                        f"{source_unit} -> "
                        f"{_DMA_CANONICAL_MODULUS_UNIT} canonical -> "
                        f"{_DMA_DISPLAY_MODULUS_UNIT} display"
                    ),
                    # Retain the legacy key for readers of existing ledgers.
                    "conversion_factor_to_Pa": factor_to_pa,
                    "source_point_count": len(points),
                    "display_point_count": len(points),
                    "display_minimum": min(display_values),
                    "display_maximum": max(display_values),
                    "negative_display_point_count": len(negative_display_values),
                    "minimum_negative_display_value": (
                        min(negative_display_values)
                        if negative_display_values
                        else None
                    ),
                    "maximum_negative_to_positive_peak_fraction": (
                        negative_to_positive_peak_fraction
                    ),
                    "default_y_min_clipped_point_count": len(negative_display_values),
                    "negative_value_policy": (
                        "Preserve finite negative acquisition values in the "
                        "processed table; the registered y_min=0 display "
                        "bound may clip them visually, and every potentially "
                        "clipped point is counted here."
                    ),
                },
            )
        )
    if not series_list:
        raise ValueError(f"No numeric DMA temperature curves found in {source}.")
    return series_list


def _read_dma_temperature_series_list(source: Path) -> list[CurveSeriesPayload]:
    series_list: list[CurveSeriesPayload] = []
    errors: list[str] = []
    for path in _sweep_source_files(source):
        try:
            series_list.extend(_read_dma_temperature_series(path))
        except ValueError as exc:
            errors.append(f"{path.name}: {exc}")
    if errors:
        raise ValueError(
            "DMA temperature preparation rejected one or more in-scope "
            "source files; silent partial datasets are not allowed "
            f"({'; '.join(errors)})."
        )
    if not series_list:
        raise ValueError(f"No DMA temperature-sweep tables found under {source}.")
    return series_list
