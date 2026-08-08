"""Resolve the private publication-digitized DSC single-curve contract."""

from __future__ import annotations

import csv
from dataclasses import dataclass
import math
from pathlib import Path
from typing import Any

from sciplot_core.figure_plan.dsc_provenance import (
    DSC_PUBLICATION_DIGITIZED_SOURCE_STATUS,
    DscDigitizedTraceFacts,
    read_dsc_provenance,
    validate_dsc_provenance,
)
from sciplot_core.figure_plan.errors import FigurePlanResolutionError
from sciplot_core.figure_plan.metric_binding import CartesianMetricBinding
from sciplot_core.figure_plan.plan import ResolvedFigurePlan
from sciplot_core.figure_plan.task import FigureTask
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.json_hashing import canonical_json_sha256


DSC_SINGLE_CURVE_RULE_ID = "dsc_curve"
DSC_SINGLE_CURVE_FIGURE_ID = "dsc_heat_flow_vs_temperature"
DSC_SINGLE_CURVE_SAMPLE_ORDER = ("UDC 2", "UDC 3", "UDC 4")
DSC_SINGLE_CURVE_SOURCE_STATUS = DSC_PUBLICATION_DIGITIZED_SOURCE_STATUS
_PROVENANCE_FILENAME = "digitization_provenance.json"


@dataclass(frozen=True, slots=True)
class DscSelectedInventory:
    """Stable identity of the only two selected DSC source files."""

    csv_sha256: str
    provenance_sha256: str
    source_sha256: str

    def to_payload(self) -> dict[str, str]:
        return {
            "csv_sha256": self.csv_sha256,
            "provenance_sha256": self.provenance_sha256,
            "source_sha256": self.source_sha256,
        }


@dataclass(frozen=True, slots=True)
class DscSingleCurveSourceFacts:
    """One validated view of the selected DSC CSV and its provenance."""

    source_sha256: str
    csv_sha256: str
    provenance_sha256: str
    sample_order: tuple[str, ...]
    point_counts: tuple[int, ...]
    temperature_unit: str
    heat_flow_unit: str
    source_data_status: str


@dataclass(frozen=True, slots=True)
class _DscCsvFacts:
    traces: tuple[DscDigitizedTraceFacts, ...]


def resolve_dsc_single_curve_plan(
    *,
    input_path: Path,
    request: dict[str, Any],
) -> ResolvedFigurePlan:
    """Resolve one private DSC task without enabling the runtime rule."""

    requested_template = request.get("template")
    if requested_template not in (None, "curve"):
        raise FigurePlanResolutionError(
            "dsc_single_curve_template_invalid",
            "The publication-digitized DSC contract supports only 'curve'.",
        )
    facts = load_dsc_single_curve_source_facts(input_path)
    task = FigureTask.with_metric_binding(
        figure_id=DSC_SINGLE_CURVE_FIGURE_ID,
        order=1,
        title="DSC heat flow vs temperature",
        metric_binding=CartesianMetricBinding(
            x_metric="temperature",
            y_metric="heat_flow",
        ),
        template="curve",
        artifact_stem=DSC_SINGLE_CURVE_FIGURE_ID,
        document_stem=DSC_SINGLE_CURVE_FIGURE_ID,
        sample_order=facts.sample_order,
        replicate_counts=tuple((sample, 1) for sample in facts.sample_order),
    )
    return ResolvedFigurePlan.planned(
        rule_id=DSC_SINGLE_CURVE_RULE_ID,
        selection_policy="registered_publication_digitized_single_curve",
        primary_figure_id=task.figure_id,
        tasks=(task,),
        source_sha256=facts.source_sha256,
    )


def load_dsc_single_curve_source_facts(
    input_path: Path,
) -> DscSingleCurveSourceFacts:
    """Read and validate one stable DSC CSV/provenance inventory exactly once."""

    source = _resolve_selected_csv(input_path)
    provenance_path, relocated_provenance = _resolve_provenance(source)
    if provenance_path is None:
        raise FigurePlanResolutionError(
            "dsc_single_curve_provenance_unavailable",
            "The DSC CSV requires its adjacent digitization provenance.",
        )

    try:
        inventory_before = _selected_inventory(source, provenance_path)
        csv_facts = _read_dsc_csv(source)
        provenance = _read_provenance(provenance_path)
        inventory_after = _selected_inventory(source, provenance_path)
    except FigurePlanResolutionError:
        raise
    except OSError as exc:
        raise FigurePlanResolutionError(
            "dsc_single_curve_source_unavailable",
            f"SciPlot could not read the DSC single-curve inventory: {exc}",
        ) from exc

    if inventory_after != inventory_before:
        raise FigurePlanResolutionError(
            "dsc_single_curve_source_changed_during_resolution",
            "The DSC CSV or its provenance changed during plan resolution.",
        )
    validate_dsc_provenance(
        provenance,
        csv_name=None if relocated_provenance else source.name,
        csv_sha256=inventory_after.csv_sha256,
        traces=csv_facts.traces,
    )
    return DscSingleCurveSourceFacts(
        source_sha256=inventory_after.source_sha256,
        csv_sha256=inventory_after.csv_sha256,
        provenance_sha256=inventory_after.provenance_sha256,
        sample_order=tuple(trace.sample for trace in csv_facts.traces),
        point_counts=tuple(trace.point_count for trace in csv_facts.traces),
        temperature_unit="C",
        heat_flow_unit="W/g",
        source_data_status=DSC_SINGLE_CURVE_SOURCE_STATUS,
    )


def _selected_inventory(source: Path, provenance: Path) -> DscSelectedInventory:
    csv_sha256 = file_sha256(source)
    provenance_sha256 = file_sha256(provenance)
    source_sha256 = canonical_json_sha256(
        {
            "kind": "sciplot_dsc_single_curve_source_inventory",
            "version": 1,
            "files": [
                {
                    "role": "digitized_csv",
                    "sha256": csv_sha256,
                },
                {
                    "role": "digitization_provenance",
                    "sha256": provenance_sha256,
                },
            ],
        },
        allow_nan=False,
    )
    return DscSelectedInventory(
        csv_sha256=csv_sha256,
        provenance_sha256=provenance_sha256,
        source_sha256=source_sha256,
    )


def _read_dsc_csv(source: Path) -> _DscCsvFacts:
    try:
        with source.open("r", encoding="utf-8", newline="") as handle:
            rows = [[cell.strip() for cell in row] for row in csv.reader(handle)]
    except (OSError, UnicodeError, csv.Error) as exc:
        raise FigurePlanResolutionError(
            "dsc_single_curve_contract_invalid",
            f"The DSC single-curve CSV could not be parsed: {exc}",
        ) from exc
    if len(rows) < 4 or any(len(row) != 6 for row in rows):
        _raise_contract_invalid("The DSC CSV must be one six-column curve table.")
    if rows[0] != ["Temperature", "Heat Flow"] * 3:
        _raise_contract_invalid("The DSC CSV headers are not canonical.")
    if rows[1] != ["°C", "W/g"] * 3:
        _raise_contract_invalid("The DSC CSV units must be °C and W/g.")
    expected_samples = [
        value for sample in DSC_SINGLE_CURVE_SAMPLE_ORDER for value in (sample, sample)
    ]
    if rows[2] != expected_samples:
        _raise_contract_invalid("The DSC CSV series order is not canonical.")

    traces: list[DscDigitizedTraceFacts] = []
    for series_index, sample in enumerate(DSC_SINGLE_CURVE_SAMPLE_ORDER):
        temperatures: list[float] = []
        heat_flows: list[float] = []
        trailing_gap = False
        for row_number, row in enumerate(rows[3:], start=4):
            x_text = row[series_index * 2]
            y_text = row[series_index * 2 + 1]
            if not x_text and not y_text:
                trailing_gap = True
                continue
            if not x_text or not y_text or trailing_gap:
                _raise_contract_invalid(
                    f"The DSC CSV has a split or non-trailing gap at row {row_number}."
                )
            try:
                temperature = float(x_text)
                heat_flow = float(y_text)
            except ValueError as exc:
                raise FigurePlanResolutionError(
                    "dsc_single_curve_contract_invalid",
                    f"The DSC CSV has a non-numeric value at row {row_number}.",
                ) from exc
            if not math.isfinite(temperature) or not math.isfinite(heat_flow):
                _raise_contract_invalid(
                    f"The DSC CSV has a non-finite value at row {row_number}."
                )
            if temperatures and temperature <= temperatures[-1]:
                _raise_contract_invalid(
                    f"The DSC temperature axis is not increasing at row {row_number}."
                )
            temperatures.append(temperature)
            heat_flows.append(heat_flow)
        if len(temperatures) < 2:
            _raise_contract_invalid(f"The DSC series {sample!r} has too few points.")
        peak_index = max(range(len(heat_flows)), key=heat_flows.__getitem__)
        traces.append(
            DscDigitizedTraceFacts(
                sample=sample,
                point_count=len(temperatures),
                temperature_min=temperatures[0],
                temperature_max=temperatures[-1],
                heat_flow_min=min(heat_flows),
                heat_flow_max=max(heat_flows),
                heat_flow_peak_temperature=temperatures[peak_index],
            )
        )
    return _DscCsvFacts(traces=tuple(traces))


def dsc_single_curve_source_sha256(source: Path) -> str | None:
    """Return the validated relocation-stable DSC source identity, if any."""

    try:
        return load_dsc_single_curve_source_facts(source).source_sha256
    except (FigurePlanResolutionError, OSError):
        return None


def _resolve_selected_csv(input_path: Path) -> Path:
    source = input_path.expanduser().resolve()
    if source.is_file():
        if source.suffix.casefold() in {".xls", ".xlsx"}:
            _raise_phase_source_unsupported()
        if source.suffix.casefold() == ".csv":
            return source
        raise FigurePlanResolutionError(
            "dsc_single_curve_source_unavailable",
            "The DSC single-curve source must be one readable CSV file.",
        )
    if not source.is_dir():
        raise FigurePlanResolutionError(
            "dsc_single_curve_source_unavailable",
            "The DSC single-curve source does not exist.",
        )
    files = tuple(path for path in source.rglob("*") if path.is_file())
    if any(path.suffix.casefold() in {".xls", ".xlsx"} for path in files):
        _raise_phase_source_unsupported()
    csv_files = tuple(path for path in files if path.suffix.casefold() == ".csv")
    if len(csv_files) != 1:
        raise FigurePlanResolutionError(
            "dsc_single_curve_source_unavailable",
            "The DSC single-curve source directory must contain exactly one CSV.",
        )
    return csv_files[0]


def _resolve_provenance(source: Path) -> tuple[Path | None, bool]:
    adjacent = source.with_name(_PROVENANCE_FILENAME)
    if adjacent.is_file():
        return adjacent, False
    try:
        from sciplot_core._paths import resolve_fixture_path
        from sciplot_core.materials_rules import get_rule

        fixture = resolve_fixture_path(
            str(get_rule(DSC_SINGLE_CURVE_RULE_ID).fixture_path or "")
        )
        registered_provenance = fixture.with_name(_PROVENANCE_FILENAME)
        if (
            fixture.is_file()
            and registered_provenance.is_file()
            and file_sha256(fixture) == file_sha256(source)
        ):
            return registered_provenance, True
    except (OSError, ValueError):
        pass
    return None, False


def _raise_phase_source_unsupported() -> None:
    raise FigurePlanResolutionError(
        "dsc_single_curve_phase_source_unsupported",
        "The `dsc_curve` single-curve contract does not accept cycle workbooks; "
        "an authorized future cycle source requires the separate `dsc_cycle` rule.",
    )


def _read_provenance(source: Path) -> dict[str, Any]:
    return read_dsc_provenance(source)


def _raise_contract_invalid(message: str) -> None:
    raise FigurePlanResolutionError("dsc_single_curve_contract_invalid", message)


__all__ = [
    "DSC_SINGLE_CURVE_FIGURE_ID",
    "DSC_SINGLE_CURVE_RULE_ID",
    "DSC_SINGLE_CURVE_SAMPLE_ORDER",
    "DSC_SINGLE_CURVE_SOURCE_STATUS",
    "DscSelectedInventory",
    "DscSingleCurveSourceFacts",
    "dsc_single_curve_source_sha256",
    "load_dsc_single_curve_source_facts",
    "resolve_dsc_single_curve_plan",
]
