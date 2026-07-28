"""Validate and read canonical impact replicate tables."""

from __future__ import annotations

import re
from pathlib import Path
from sciplot_core.foundation.text_values import (
    clean_text as _clean_text,
    token as _token,
)

from sciplot_core.source_tables import (
    read_raw_table,
)

from sciplot_core.semantic_sources.models import (
    ImpactReplicatePayload,
    _ImpactDataValidationError,
)

from sciplot_core.semantic_sources.table_scanning import (
    _float,
    _read_candidate_tables,
)


def _canonical_impact_unit(value: object) -> str | None:
    text = _clean_text(value)
    if not text:
        return None
    compact = (
        text.casefold()
        .replace("²", "2")
        .replace("^", "")
        .replace("−", "-")
        .replace("⁻", "-")
    )
    compact = re.sub(r"[\s·*/()\[\]{}]", "", compact)
    if "kj" in compact and ("m2" in compact or "m-2" in compact):
        return "kJ/m2"
    return None


def _validated_impact_unit(values: list[object]) -> str:
    explicit = [_clean_text(value) for value in values if _clean_text(value)]
    unknown = [value for value in explicit if _canonical_impact_unit(value) is None]
    if unknown:
        raise _ImpactDataValidationError(
            "Impact strength units must resolve to kJ/m2; unsupported values: "
            + ", ".join(sorted(set(unknown)))
        )
    return "kJ/m2"


def _impact_unit_candidate_from_header(header: str) -> str | None:
    bracketed = re.search(r"\(([^)]+)\)|\[([^\]]+)\]", header)
    if bracketed:
        candidate = next((group for group in bracketed.groups() if group), "")
        return candidate.strip() or None
    compact = header.casefold()
    if any(token in compact for token in ("kj", "mpa", "gpa", "j/", "m²", "m2", "m^2")):
        return header
    return None


def _impact_payload(
    groups: dict[str, list[float]], *, unit: str
) -> ImpactReplicatePayload:
    populated = [(sample, values) for sample, values in groups.items() if values]
    if not populated:
        raise ValueError("Impact table did not contain numeric impact values.")
    max_len = max(len(values) for _sample, values in populated)
    rows: list[tuple[object, ...]] = [
        tuple("Impact strength" for _sample, _values in populated),
        tuple(unit for _sample, _values in populated),
        tuple(sample for sample, _values in populated),
    ]
    for row_index in range(max_len):
        rows.append(
            tuple(
                values[row_index] if row_index < len(values) else ""
                for _sample, values in populated
            )
        )
    return ImpactReplicatePayload(
        rows=tuple(rows),
        samples=tuple(sample for sample, _values in populated),
        replicate_counts=tuple(len(values) for _sample, values in populated),
        values=tuple(tuple(values) for _sample, values in populated),
        unit=unit,
    )


def _read_impact_canonical_tables(source: Path) -> ImpactReplicatePayload:
    """Read three-label-row impact tables, preserving every workbook sheet."""

    parsed: list[tuple[str, str, list[float]]] = []
    unit_candidates: list[object] = []
    for table_name, raw in _read_candidate_tables(source):
        raw = raw.dropna(axis=1, how="all")
        if raw.shape[0] < 4:
            continue
        sheet_label = table_name.split(":", 1)[-1] if ":" in table_name else ""
        for column in range(raw.shape[1]):
            metric_token = _token(raw.iat[0, column])
            if not (
                metric_token == "re"
                or "impact" in metric_token
                or "冲击" in metric_token
            ):
                continue
            sample = _clean_text(raw.iat[2, column])
            if not sample:
                continue
            values = [
                value
                for row_index in range(3, raw.shape[0])
                if (value := _float(raw.iat[row_index, column])) is not None
            ]
            if not values:
                continue
            parsed.append((sheet_label, sample, values))
            unit_candidates.append(raw.iat[1, column])
    if not parsed:
        raise ValueError("Could not find a three-label-row impact table.")

    sample_counts = {
        sample: sum(1 for _sheet, candidate, _values in parsed if candidate == sample)
        for _sheet, sample, _values in parsed
    }
    groups: dict[str, list[float]] = {}
    for sheet_label, sample, values in parsed:
        label = (
            f"{sample} ({sheet_label})"
            if sample_counts[sample] > 1 and sheet_label
            else sample
        )
        groups.setdefault(label, []).extend(values)
    return _impact_payload(groups, unit=_validated_impact_unit(unit_candidates))


def read_impact_condition_payloads(
    source: Path,
) -> list[tuple[str, ImpactReplicatePayload]]:
    """Return independently controlled workbook sheets as separate figures."""

    if source.suffix.casefold() not in {".xlsx", ".xls", ".xlsm"}:
        return []
    conditions: list[tuple[str, ImpactReplicatePayload]] = []
    for table_name, raw in _read_candidate_tables(source):
        raw = raw.dropna(axis=1, how="all")
        if raw.shape[0] < 4:
            continue
        groups: dict[str, list[float]] = {}
        unit_candidates: list[object] = []
        for column in range(raw.shape[1]):
            metric_token = _token(raw.iat[0, column])
            if not (
                metric_token == "re"
                or "impact" in metric_token
                or "冲击" in metric_token
            ):
                continue
            sample = _clean_text(raw.iat[2, column])
            if not sample:
                continue
            values = [
                value
                for row_index in range(3, raw.shape[0])
                if (value := _float(raw.iat[row_index, column])) is not None
            ]
            if values:
                groups.setdefault(sample, []).extend(values)
                unit_candidates.append(raw.iat[1, column])
        if not groups:
            continue
        condition = table_name.split(":", 1)[-1] if ":" in table_name else table_name
        conditions.append(
            (
                condition,
                _impact_payload(
                    groups,
                    unit=_validated_impact_unit(unit_candidates),
                ),
            )
        )
    return conditions


def _read_impact_block_table(source: Path) -> ImpactReplicatePayload:
    raw = read_raw_table(source).dropna(axis=1, how="all")
    if raw.shape[0] < 3:
        raise ValueError("Impact block table needs at least three rows.")
    re_columns: list[tuple[str, int]] = []
    unit_candidates: list[object] = []
    for column in range(raw.shape[1]):
        header = _clean_text(raw.iat[1, column] if raw.shape[0] > 1 else "")
        header_token = _token(header)
        if not (
            header_token.startswith("re")
            or "impact" in header_token
            or "冲击" in header_token
        ):
            continue
        sample = ""
        for sample_column in range(column, -1, -1):
            candidate = _clean_text(raw.iat[0, sample_column])
            if candidate:
                sample = candidate
                break
        if not sample:
            sample = f"Sample {len(re_columns) + 1}"
        unit_candidate = _impact_unit_candidate_from_header(header)
        if unit_candidate:
            unit_candidates.append(unit_candidate)
        re_columns.append((sample, column))
    if not re_columns:
        raise ValueError("Could not find grouped impact strength columns.")
    groups: dict[str, list[float]] = {}
    for sample, column in re_columns:
        values = groups.setdefault(sample, [])
        for row_index in range(2, raw.shape[0]):
            value = _float(raw.iat[row_index, column])
            if value is not None:
                values.append(value)
    return _impact_payload(groups, unit=_validated_impact_unit(unit_candidates))


def _read_impact_compact_table(source: Path) -> ImpactReplicatePayload:
    raw = read_raw_table(source).dropna(how="all").dropna(axis=1, how="all")
    if raw.shape[0] < 2:
        raise ValueError(
            "Impact compact table needs a header and at least one data row."
        )
    headers = [_token(value) for value in raw.iloc[0].tolist()]
    sample_col = next(
        (
            index
            for index, token in enumerate(headers)
            if token in {"sample", "samplename"}
        ),
        None,
    )
    metric_col = next(
        (
            index
            for index, token in enumerate(headers)
            if "impact" in token or "冲击" in token
        ),
        None,
    )
    if sample_col is None or metric_col is None:
        raise ValueError("Impact compact table needs sample and impact columns.")
    unit_col = metric_col + 1 if metric_col + 1 < raw.shape[1] else None
    groups: dict[str, list[float]] = {}
    units: list[object] = []
    for row_index in range(1, raw.shape[0]):
        sample = _clean_text(raw.iat[row_index, sample_col])
        value = _float(raw.iat[row_index, metric_col])
        if not sample or value is None:
            continue
        groups.setdefault(sample, []).append(value)
        if unit_col is not None:
            unit = _clean_text(raw.iat[row_index, unit_col])
            if unit:
                units.append(unit)
    return _impact_payload(groups, unit=_validated_impact_unit(units))


def _read_impact_source(source: Path) -> ImpactReplicatePayload:
    if source.is_dir():
        sources = [
            path
            for path in sorted(source.rglob("*"))
            if path.is_file() and path.suffix.lower() in {".xlsx", ".xls", ".csv"}
        ]
    else:
        sources = [source]
    if not sources:
        raise ValueError(f"No impact-strength tables found under {source}.")
    groups: dict[str, list[float]] = {}
    errors: list[str] = []
    for path in sources:
        try:
            try:
                payload = _read_impact_canonical_tables(path)
            except _ImpactDataValidationError:
                raise
            except ValueError:
                try:
                    payload = _read_impact_block_table(path)
                except _ImpactDataValidationError:
                    raise
                except ValueError:
                    payload = _read_impact_compact_table(path)
        except _ImpactDataValidationError:
            raise
        except ValueError as exc:
            errors.append(f"{path.name}: {exc}")
            continue
        for sample, values in zip(payload.samples, payload.values, strict=True):
            groups.setdefault(sample, []).extend(values)
    if not groups:
        raise ValueError("Could not parse impact-strength tables: " + "; ".join(errors))
    return _impact_payload(groups, unit="kJ/m2")
