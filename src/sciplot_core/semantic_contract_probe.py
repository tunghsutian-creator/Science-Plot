from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from sciplot_core._utils import json_safe
from sciplot_core.semantic import (
    _read_dma_temperature_series,
    _read_ftir_series,
    _read_ftir_series_list,
    _read_rheology_frequency_comparison_samples,
    _read_stress_relaxation_series_list,
    _read_stress_relaxation_source_series,
    prepare_semantic_source,
)
from sciplot_core.intake import (
    SAXS_SCALING_REVIEW_NOTE,
    converge_material_review_notes,
)

SEMANTIC_CONTRACT_PROBE_KIND = "sciplot_semantic_contract_probe"
SEMANTIC_CONTRACT_PROBE_VERSION = 2


def _check(
    check_id: str,
    label: str,
    passed: bool,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": check_id,
        "label": label,
        "status": "passed" if passed else "failed",
        "evidence": json_safe(evidence or {}),
    }


def _write_table(path: Path, rows: list[list[object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, header=False, index=False)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _raises_value_error(callback: Callable[[], object]) -> tuple[bool, str]:
    try:
        callback()
    except ValueError as exc:
        return True, str(exc)
    return False, ""


def _stress_interval_rows(
    *,
    strain: list[float],
    response: list[float],
) -> list[list[object]]:
    rows: list[list[object]] = [
        ["Project:", "Synthetic semantic contract"],
        ["Test:", "Synthetic stress relaxation"],
        ["Result:", "Stress relaxation"],
        ["Interval and data points:", 1, len(strain)],
        [
            "Interval data:",
            "Point No.",
            "Time",
            "Shear Strain",
            "Shear Stress",
        ],
        ["", "", "", "", ""],
        ["", "", "[s]", "[%]", "[Pa]"],
    ]
    rows.extend(
        ["", index + 1, float(index), strain_value, response_value]
        for index, (strain_value, response_value) in enumerate(
            zip(strain, response, strict=True)
        )
    )
    return rows


def _stress_multi_interval_rows() -> list[list[object]]:
    rows: list[list[object]] = [
        ["Project:", "Synthetic semantic contract"],
        ["Test:", "Synthetic multi-interval stress relaxation"],
        ["Result:", "Stress relaxation"],
    ]
    intervals = (
        (
            [0.0, 1.0, 2.0, 3.0, 4.0, 5.0],
            [1000.0, 900.0, 800.0, 700.0, 600.0, 500.0],
        ),
        (
            [0.0, 2.0, 4.0, 7.0, 9.7, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0],
            [1000.0, 800.0, 600.0, 400.0, 250.0, 100.0, 90.0, 80.0, 70.0, 60.0, 50.0],
        ),
    )
    for interval_index, (strain, response) in enumerate(intervals, start=1):
        rows.extend(
            [
                ["Interval and data points:", interval_index, len(strain)],
                [
                    "Interval data:",
                    "Point No.",
                    "Time",
                    "Shear Strain",
                    "Shear Stress",
                ],
                ["", "", "", "", ""],
                ["", "", "[s]", "[%]", "[Pa]"],
            ]
        )
        rows.extend(
            ["", index + 1, float(index), strain_value, response_value]
            for index, (strain_value, response_value) in enumerate(
                zip(strain, response, strict=True)
            )
        )
    return rows


def run_semantic_contract_probe(output_dir: str | Path) -> dict[str, Any]:
    root = Path(output_dir).expanduser().resolve()
    fixtures = root / "fixtures"
    runs = root / "runs"
    fixtures.mkdir(parents=True, exist_ok=True)
    runs.mkdir(parents=True, exist_ok=True)

    stress_source = fixtures / "stress_ramp_hold.csv"
    _write_table(
        stress_source,
        _stress_interval_rows(
            strain=[0.0, 2.0, 4.0, 7.0, 9.7, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0],
            response=[1000.0, 800.0, 600.0, 400.0, 250.0, 100.0, 90.0, 80.0, 70.0, 60.0, 50.0],
        ),
    )
    stress_series = _read_stress_relaxation_source_series(stress_source)[0]
    stress_result = prepare_semantic_source(
        stress_source,
        output_dir=runs / "stress",
        semantic={"semantic_family": "rheology_stress_relaxation"},
    )
    stress_diagnostics = stress_series.diagnostics or {}
    stress_step = stress_result["transform_steps"][0]
    stress_source_normalizations = stress_step["parameters"]["source_normalizations"]

    no_platform_source = fixtures / "stress_without_hold.csv"
    _write_table(
        no_platform_source,
        _stress_interval_rows(
            strain=[float(value) for value in range(11)],
            response=[100.0 - float(value) for value in range(11)],
        ),
    )
    platform_blocked, platform_error = _raises_value_error(
        lambda: _read_stress_relaxation_source_series(no_platform_source)
    )

    multi_interval_source = fixtures / "stress_multi_interval_reset.csv"
    _write_table(
        multi_interval_source,
        _stress_multi_interval_rows(),
    )
    multi_interval_series = _read_stress_relaxation_source_series(
        multi_interval_source
    )[0]
    multi_interval_diagnostics = multi_interval_series.diagnostics or {}

    wide_stress_source = fixtures / "stress_wide.csv"
    _write_table(
        wide_stress_source,
        [
            ["Time", "Shear stress"],
            ["s", "Pa"],
            ["Wide sample", "Wide sample"],
            [0.0, 0.0],
            [1.0, 50.0],
            [2.0, 25.0],
        ],
    )
    wide_stress = _read_stress_relaxation_source_series(wide_stress_source)[0]
    normalized_source = fixtures / "stress_already_normalized.csv"
    _write_table(
        normalized_source,
        [
            ["Time", "Normalized stress"],
            ["s", "sigma/sigma0"],
            ["Normalized sample", "Normalized sample"],
            [0.0, 1.0],
            [1.0, 0.8],
            [2.0, 0.6],
        ],
    )
    already_normalized = _read_stress_relaxation_source_series(normalized_source)[0]
    modulus_source = fixtures / "relaxation_modulus_only.csv"
    _write_table(
        modulus_source,
        [
            ["Time", "Relaxation modulus"],
            ["s", "Pa"],
            ["Modulus sample", "Modulus sample"],
            [0.0, 100.0],
            [1.0, 80.0],
            [2.0, 60.0],
        ],
    )
    modulus_blocked, modulus_error = _raises_value_error(
        lambda: _read_stress_relaxation_source_series(modulus_source)
    )

    dma_source = fixtures / "dma_temperature_display_units.csv"
    _write_table(
        dma_source,
        [
            ["Temperature (°C)", "Storage Modulus (kPa) Probe"],
            [50.0, 80_000.0],
            [75.0, 40_000.0],
            [100.0, -0.5],
        ],
    )
    dma_before = _sha256(dma_source)
    dma_series = _read_dma_temperature_series(dma_source)[0]
    dma_result = prepare_semantic_source(
        dma_source,
        output_dir=runs / "dma_temperature",
        semantic={"semantic_family": "dma_temperature_sweep"},
    )
    dma_after = _sha256(dma_source)
    dma_step = dma_result["transform_steps"][0]
    dma_parameters = dma_step["parameters"]
    dma_diagnostics = dma_parameters["source_selections"][0]
    dma_processed = pd.read_csv(
        Path(str(dma_result["processed_source"])),
        header=None,
    )

    dma_kelvin_source = fixtures / "dma_temperature_kelvin_gpa.csv"
    _write_table(
        dma_kelvin_source,
        [
            ["Temperature (K)", "Storage Modulus (GPa) Kelvin Probe"],
            [273.15, 0.08],
            [298.15, 0.04],
        ],
    )
    dma_kelvin_before = _sha256(dma_kelvin_source)
    dma_kelvin_result = prepare_semantic_source(
        dma_kelvin_source,
        output_dir=runs / "dma_temperature_kelvin",
        semantic={"semantic_family": "dma_temperature_sweep"},
    )
    dma_kelvin_after = _sha256(dma_kelvin_source)
    dma_kelvin_diagnostics = dma_kelvin_result["transform_steps"][0]["parameters"][
        "source_selections"
    ][0]
    dma_kelvin_processed = pd.read_csv(
        Path(str(dma_kelvin_result["processed_source"])),
        header=None,
    )

    dma_celsius_row_source = fixtures / "dma_temperature_c_unit_row.csv"
    _write_table(
        dma_celsius_row_source,
        [
            ["Temperature", "Storage Modulus"],
            ["C", "Pa"],
            ["Celsius row probe", "Celsius row probe"],
            [10.0, 2_000_000.0],
            [20.0, 1_000_000.0],
        ],
    )
    dma_celsius_row_before = _sha256(dma_celsius_row_source)
    dma_celsius_row_series = _read_dma_temperature_series(dma_celsius_row_source)[0]
    dma_celsius_row_after = _sha256(dma_celsius_row_source)

    dma_missing_modulus_source = fixtures / "dma_missing_modulus_unit.csv"
    _write_table(
        dma_missing_modulus_source,
        [
            ["Temperature (°C)", "Storage Modulus Missing Probe"],
            [50.0, 80.0],
            [75.0, 40.0],
        ],
    )
    dma_missing_temperature_source = fixtures / "dma_missing_temperature_unit.csv"
    _write_table(
        dma_missing_temperature_source,
        [
            ["Temperature", "Storage Modulus (MPa) Missing Probe"],
            ["Sample C", "Sample C"],
            [50.0, 80.0],
            [75.0, 40.0],
        ],
    )
    dma_unknown_modulus_source = fixtures / "dma_unknown_modulus_unit.csv"
    _write_table(
        dma_unknown_modulus_source,
        [
            ["Temperature (°C)", "Storage Modulus (psi) Unknown Probe"],
            [50.0, 80.0],
            [75.0, 40.0],
        ],
    )
    dma_unknown_temperature_source = fixtures / "dma_unknown_temperature_unit.csv"
    _write_table(
        dma_unknown_temperature_source,
        [
            ["Temperature (°F)", "Storage Modulus (MPa) Unknown Probe"],
            [50.0, 80.0],
            [75.0, 40.0],
        ],
    )
    dma_temperature_rate_source = fixtures / "dma_temperature_rate_unit.csv"
    _write_table(
        dma_temperature_rate_source,
        [
            ["Temperature (K/min)", "Storage Modulus (MPa) Rate Probe"],
            [50.0, 80.0],
            [75.0, 40.0],
        ],
    )
    dma_modulus_rate_source = fixtures / "dma_modulus_rate_unit.csv"
    _write_table(
        dma_modulus_rate_source,
        [
            ["Temperature (°C)", "Storage Modulus (MPa/min) Rate Probe"],
            [50.0, 80.0],
            [75.0, 40.0],
        ],
    )
    dma_fail_closed_sources = (
        dma_missing_modulus_source,
        dma_missing_temperature_source,
        dma_unknown_modulus_source,
        dma_unknown_temperature_source,
        dma_temperature_rate_source,
        dma_modulus_rate_source,
    )
    dma_fail_closed_hashes_before = {
        path.name: _sha256(path) for path in dma_fail_closed_sources
    }
    (
        dma_missing_modulus_blocked,
        dma_missing_modulus_error,
    ) = _raises_value_error(
        lambda: _read_dma_temperature_series(dma_missing_modulus_source)
    )
    (
        dma_missing_temperature_blocked,
        dma_missing_temperature_error,
    ) = _raises_value_error(
        lambda: _read_dma_temperature_series(dma_missing_temperature_source)
    )
    (
        dma_unknown_modulus_blocked,
        dma_unknown_modulus_error,
    ) = _raises_value_error(
        lambda: _read_dma_temperature_series(dma_unknown_modulus_source)
    )
    (
        dma_unknown_temperature_blocked,
        dma_unknown_temperature_error,
    ) = _raises_value_error(
        lambda: _read_dma_temperature_series(dma_unknown_temperature_source)
    )
    (
        dma_temperature_rate_blocked,
        dma_temperature_rate_error,
    ) = _raises_value_error(
        lambda: _read_dma_temperature_series(dma_temperature_rate_source)
    )
    (
        dma_modulus_rate_blocked,
        dma_modulus_rate_error,
    ) = _raises_value_error(
        lambda: _read_dma_temperature_series(dma_modulus_rate_source)
    )
    dma_fail_closed_hashes_after = {
        path.name: _sha256(path) for path in dma_fail_closed_sources
    }

    dma_partial_unit_dir = fixtures / "dma_partial_unit_scope"
    dma_partial_unit_dir.mkdir(parents=True, exist_ok=True)
    dma_partial_valid_source = dma_partial_unit_dir / "valid.csv"
    dma_partial_invalid_source = dma_partial_unit_dir / "invalid.csv"
    _write_table(
        dma_partial_valid_source,
        [
            ["Temperature (°C)", "Storage Modulus (MPa) Valid"],
            [50.0, 80.0],
            [75.0, 40.0],
        ],
    )
    _write_table(
        dma_partial_invalid_source,
        [
            ["Temperature (°F)", "Storage Modulus (MPa) Invalid"],
            [50.0, 80.0],
            [75.0, 40.0],
        ],
    )
    dma_partial_hashes_before = {
        path.name: _sha256(path)
        for path in (
            dma_partial_valid_source,
            dma_partial_invalid_source,
        )
    }
    dma_partial_blocked, dma_partial_error = _raises_value_error(
        lambda: prepare_semantic_source(
            dma_partial_unit_dir,
            output_dir=runs / "dma_partial_unit_scope",
            semantic={"semantic_family": "dma_temperature_sweep"},
        )
    )
    dma_partial_hashes_after = {
        path.name: _sha256(path)
        for path in (
            dma_partial_valid_source,
            dma_partial_invalid_source,
        )
    }

    saxs_source = fixtures / "saxs_log_domain.csv"
    _write_table(
        saxs_source,
        [
            ["q", "Intensity", "q", "Intensity"],
            ["nm^-1", "a.u.", "nm^-1", "a.u."],
            ["Sample A", "Sample A", "Sample B", "Sample B"],
            [-1.0, 5.0, 0.0, 2.0],
            [0.0, 4.0, 0.1, 0.0],
            [0.1, 3.0, 0.2, 4.0],
            [0.2, 0.0, 0.3, 3.0],
            [0.3, -1.0, 0.4, -2.0],
            [0.4, 2.0, 0.5, 1.0],
        ],
    )
    saxs_before = _sha256(saxs_source)
    saxs_result = prepare_semantic_source(
        saxs_source,
        output_dir=runs / "saxs",
        semantic={"semantic_family": "saxs_profile"},
    )
    saxs_after = _sha256(saxs_source)
    saxs_step = saxs_result["transform_steps"][0]
    saxs_diagnostics = saxs_step["parameters"]["source_selections"]

    transmittance_source = fixtures / "ftir_transmittance.csv"
    _write_table(
        transmittance_source,
        [
            ["Wavenumber", "%T"],
            ["cm^-1", "%"],
            ["Transmittance sample", "Transmittance sample"],
            [4000.0, 90.0],
            [3000.0, 82.0],
            [2000.0, 75.0],
            [1000.0, 65.0],
        ],
    )
    absorbance_source = fixtures / "ftir_absorbance.csv"
    _write_table(
        absorbance_source,
        [
            ["Wavenumber", "Absorbance"],
            ["cm^-1", "a.u."],
            ["Absorbance sample", "Absorbance sample"],
            [4000.0, 0.05],
            [3000.0, 0.12],
            [2000.0, 0.3],
            [1000.0, 0.18],
        ],
    )
    headerless_source = fixtures / "ftir_headerless_percent_t.csv"
    _write_table(
        headerless_source,
        [
            [4000.0, 90.0],
            [3000.0, 82.0],
            [2000.0, 75.0],
            [1000.0, 65.0],
        ],
    )
    transmittance = _read_ftir_series(transmittance_source)[0]
    absorbance = _read_ftir_series(absorbance_source)[0]
    headerless = _read_ftir_series(headerless_source)[0]
    mixed_ftir_dir = fixtures / "ftir_mixed_modes"
    mixed_ftir_dir.mkdir(parents=True, exist_ok=True)
    _write_table(
        mixed_ftir_dir / "percent_t.csv",
        [
            ["Wavenumber", "Transmittance"],
            ["cm^-1", "%"],
            ["Percent T", "Percent T"],
            [4000.0, 90.0],
            [2000.0, 75.0],
        ],
    )
    _write_table(
        mixed_ftir_dir / "absorbance.csv",
        [
            ["Wavenumber", "Absorbance"],
            ["cm^-1", "a.u."],
            ["Abs", "Abs"],
            [4000.0, 0.1],
            [2000.0, 0.3],
        ],
    )
    mixed_ftir_blocked, mixed_ftir_error = _raises_value_error(
        lambda: _read_ftir_series_list(mixed_ftir_dir)
    )

    partial_ftir_dir = fixtures / "ftir_partial_scope"
    partial_ftir_dir.mkdir(parents=True, exist_ok=True)
    _write_table(
        partial_ftir_dir / "valid.csv",
        [
            ["Wavenumber", "Transmittance"],
            ["cm^-1", "%"],
            ["Valid FTIR", "Valid FTIR"],
            [4000.0, 90.0],
            [2000.0, 75.0],
        ],
    )
    (partial_ftir_dir / "malformed.csv").write_text(
        "not,a,usable,spectrum\n",
        encoding="utf-8",
    )
    partial_ftir_blocked, partial_ftir_error = _raises_value_error(
        lambda: _read_ftir_series_list(partial_ftir_dir)
    )

    partial_stress_dir = fixtures / "stress_partial_scope"
    partial_stress_dir.mkdir(parents=True, exist_ok=True)
    _write_table(
        partial_stress_dir / "valid.csv",
        _stress_interval_rows(
            strain=[0.0, 2.0, 4.0, 7.0, 9.7, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0],
            response=[1000.0, 800.0, 600.0, 400.0, 250.0, 100.0, 90.0, 80.0, 70.0, 60.0, 50.0],
        ),
    )
    (partial_stress_dir / "malformed.csv").write_text(
        "not,a,stress,relaxation\n",
        encoding="utf-8",
    )
    partial_stress_blocked, partial_stress_error = _raises_value_error(
        lambda: _read_stress_relaxation_series_list(partial_stress_dir)
    )

    partial_sweep_dir = fixtures / "rheology_partial_scope"
    partial_sweep_dir.mkdir(parents=True, exist_ok=True)
    _write_table(
        partial_sweep_dir / "valid.csv",
        [
            ["Angular Frequency", "Storage Modulus"],
            ["rad/s", "Pa"],
            [1.0, 1000.0],
            [10.0, 900.0],
        ],
    )
    (partial_sweep_dir / "malformed.csv").write_text(
        "not,a,rheology,sweep\n",
        encoding="utf-8",
    )
    partial_sweep_blocked, partial_sweep_error = _raises_value_error(
        lambda: _read_rheology_frequency_comparison_samples(partial_sweep_dir)
    )

    viscosity_sweep_dir = fixtures / "rheology_viscosity_units"
    viscosity_sweep_dir.mkdir(parents=True, exist_ok=True)
    viscosity_source = viscosity_sweep_dir / "viscosity_probe.csv"
    _write_table(
        viscosity_source,
        [
            [
                "Angular Frequency",
                "Storage Modulus",
                "Loss Modulus",
                "Loss Factor",
                "Complex Viscosity",
            ],
            ["rad/s", "Pa", "Pa", "1", "mPa·s"],
            [1.0, 1000.0, 500.0, 0.5, 500_000.0],
            [10.0, 900.0, 450.0, 0.5, 50_000.0],
        ],
    )
    viscosity_before = _sha256(viscosity_source)
    viscosity_source_values = [
        float(value)
        for value in pd.to_numeric(
            pd.read_csv(viscosity_source, header=None).iloc[2:, 4],
            errors="coerce",
        ).dropna()
    ]
    viscosity_sample = _read_rheology_frequency_comparison_samples(viscosity_sweep_dir)[
        0
    ]
    viscosity_canonical_values = [
        row.get("complex_viscosity") for row in viscosity_sample.rows
    ]
    viscosity_result = prepare_semantic_source(
        viscosity_sweep_dir,
        output_dir=runs / "rheology_viscosity_units",
        semantic={"semantic_family": "rheology_frequency"},
    )
    viscosity_processed = pd.read_excel(
        Path(str(viscosity_result["processed_source"])),
        sheet_name="Frequency_Comparison",
        header=None,
    )
    viscosity_after = _sha256(viscosity_source)
    viscosity_step = viscosity_result["transform_steps"][0]
    viscosity_inventory = viscosity_step["parameters"]["unit_conversions"]
    viscosity_provenance = viscosity_inventory[0]["metrics"]["complex_viscosity"]

    unsupported_viscosity_dir = fixtures / "rheology_unsupported_units"
    unsupported_viscosity_dir.mkdir(parents=True, exist_ok=True)
    _write_table(
        unsupported_viscosity_dir / "unsupported.csv",
        [
            [
                "Angular Frequency",
                "Storage Modulus",
                "Complex Viscosity",
            ],
            ["rad/s", "Pa", "arbitrary viscosity unit"],
            [1.0, 1000.0, 500_000.0],
            [10.0, 900.0, 50_000.0],
        ],
    )
    unsupported_viscosity_blocked, unsupported_viscosity_error = _raises_value_error(
        lambda: _read_rheology_frequency_comparison_samples(unsupported_viscosity_dir)
    )

    confirmed_viscosity_dir = fixtures / "confirmed_rheology_viscosity_units"
    confirmed_viscosity_dir.mkdir(parents=True, exist_ok=True)
    confirmed_viscosity_source = confirmed_viscosity_dir / "confirmed_viscosity.csv"
    _write_table(
        confirmed_viscosity_source,
        [
            ["Opaque independent", "Opaque elastic", "Opaque flow"],
            ["rad/s", "Pa", "mPa·s"],
            [1.0, 1000.0, 500_000.0],
            [10.0, 900.0, 50_000.0],
        ],
    )
    confirmed_viscosity_columns = [
        {
            "file_name": confirmed_viscosity_source.name,
            "source_path": str(confirmed_viscosity_source),
            "columns": [
                {
                    "index": 0,
                    "name": "Angular Frequency",
                    "confirmed_type": "numeric",
                    "role": "x",
                },
                {
                    "index": 1,
                    "name": "Storage Modulus",
                    "confirmed_type": "numeric",
                    "role": "y",
                },
                {
                    "index": 2,
                    "name": "Complex Viscosity",
                    "confirmed_type": "numeric",
                    "role": "y",
                },
            ],
        }
    ]
    confirmed_viscosity_before = _sha256(confirmed_viscosity_source)
    confirmed_viscosity_result = prepare_semantic_source(
        confirmed_viscosity_dir,
        output_dir=runs / "confirmed_rheology_viscosity_units",
        semantic={"semantic_family": "rheology_frequency"},
        column_confirmations=confirmed_viscosity_columns,
    )
    confirmed_viscosity_after = _sha256(confirmed_viscosity_source)
    confirmed_viscosity_processed = pd.read_excel(
        Path(str(confirmed_viscosity_result["processed_source"])),
        sheet_name="Frequency_Comparison",
        header=None,
    )
    confirmed_viscosity_inventory = confirmed_viscosity_result["transform_steps"][0][
        "parameters"
    ]["unit_conversions"]
    confirmed_viscosity_provenance = confirmed_viscosity_inventory[0]["metrics"][
        "complex_viscosity"
    ]

    confirmed_partial_dir = fixtures / "confirmed_rheology_partial_scope"
    confirmed_partial_dir.mkdir(parents=True, exist_ok=True)
    confirmed_valid_source = confirmed_partial_dir / "valid.csv"
    confirmed_bad_unit_source = confirmed_partial_dir / "bad_unit.csv"
    confirmed_bad_parse_source = confirmed_partial_dir / "bad_parse.csv"
    _write_table(
        confirmed_valid_source,
        [
            ["Opaque x", "Opaque modulus", "Opaque viscosity"],
            ["rad/s", "Pa", "mPa·s"],
            [1.0, 1000.0, 500_000.0],
            [10.0, 900.0, 50_000.0],
        ],
    )
    _write_table(
        confirmed_bad_unit_source,
        [
            ["Opaque x", "Opaque modulus", "Opaque viscosity"],
            ["rad/s", "Pa", "MPa/min"],
            [1.0, 1000.0, 500_000.0],
            [10.0, 900.0, 50_000.0],
        ],
    )
    _write_table(
        confirmed_bad_parse_source,
        [
            ["Opaque x", "Opaque modulus", "Opaque viscosity"],
            ["rad/s", "Pa", "mPa·s"],
            ["not numeric", "not numeric", "not numeric"],
        ],
    )

    def confirmed_columns(source_path: Path) -> dict[str, Any]:
        return {
            "file_name": source_path.name,
            "source_path": str(source_path),
            "columns": [
                {
                    "index": 0,
                    "name": "Angular Frequency",
                    "confirmed_type": "numeric",
                    "role": "x",
                },
                {
                    "index": 1,
                    "name": "Storage Modulus",
                    "confirmed_type": "numeric",
                    "role": "y",
                },
                {
                    "index": 2,
                    "name": "Complex Viscosity",
                    "confirmed_type": "numeric",
                    "role": "y",
                },
            ],
        }

    confirmed_partial_sources = (
        confirmed_valid_source,
        confirmed_bad_unit_source,
        confirmed_bad_parse_source,
    )
    confirmed_partial_hashes_before = {
        path.name: _sha256(path) for path in confirmed_partial_sources
    }
    confirmed_partial_blocked, confirmed_partial_error = _raises_value_error(
        lambda: prepare_semantic_source(
            confirmed_partial_dir,
            output_dir=runs / "confirmed_rheology_partial_scope",
            semantic={"semantic_family": "rheology_frequency"},
            column_confirmations=[
                confirmed_columns(path) for path in confirmed_partial_sources
            ],
        )
    )
    confirmed_partial_hashes_after = {
        path.name: _sha256(path) for path in confirmed_partial_sources
    }

    saxs_review_request = {
        "rule_id": "saxs_profile",
        "review_notes": ["Prepared by SciPlot from the selected data mapping."],
    }
    saxs_review_changed = converge_material_review_notes(saxs_review_request)
    saxs_review_second_change = converge_material_review_notes(saxs_review_request)
    non_saxs_review_request = {
        "rule_id": "xrd_pattern",
        "review_notes": [
            "Prepared by SciPlot from the selected data mapping.",
            SAXS_SCALING_REVIEW_NOTE,
        ],
    }
    non_saxs_review_changed = converge_material_review_notes(non_saxs_review_request)

    checks = [
        _check(
            "stress_hold_onset_contract",
            "Stress relaxation crops loading, resets time, and uses the hold-onset response as sigma0",
            (
                stress_series.x_label == "Elapsed time"
                and stress_series.points[0] == (1.0, 0.9)
                and stress_diagnostics.get("hold_target_strain") == 10.0
                and stress_diagnostics.get("hold_onset_source_time") == 5.0
                and stress_diagnostics.get("normalization_baseline_value") == 100.0
                and stress_diagnostics.get("excluded_loading_points") == 5
                and "elapsed_time = source_time" in str(
                    stress_diagnostics.get("time_reset_definition")
                )
                and stress_source_normalizations[0].get(
                    "normalization_baseline_value"
                )
                == 100.0
            ),
            {
                "first_output_point": stress_series.points[0],
                "diagnostics": stress_diagnostics,
                "transform_source_normalizations": stress_source_normalizations,
            },
        ),
        _check(
            "stress_missing_platform_blocked",
            "Stress relaxation blocks a control signal without a terminal hold platform",
            platform_blocked and "platform" in platform_error.casefold(),
            {"error": platform_error},
        ),
        _check(
            "stress_interval_identity_contract",
            "Stress relaxation pairs reset time values within one explicit interval",
            (
                multi_interval_series.points[0] == (1.0, 0.9)
                and multi_interval_diagnostics.get("hold_interval_index") == 2
                and multi_interval_diagnostics.get(
                    "hold_interval_selection_policy"
                )
                == "last_common_selected_interval"
                and multi_interval_diagnostics.get(
                    "excluded_prior_interval_points"
                )
                == 6
                and multi_interval_diagnostics.get(
                    "hold_onset_source_time"
                )
                == 5.0
            ),
            {
                "points": multi_interval_series.points,
                "diagnostics": multi_interval_diagnostics,
            },
        ),
        _check(
            "stress_wide_fallback_contract",
            "Wide stress curves use the first finite non-zero response and retain only positive log-domain time",
            (
                wide_stress.points == ((1.0, 1.0), (2.0, 0.5))
                and (wide_stress.diagnostics or {}).get(
                    "normalization_baseline_time"
                )
                == 1.0
                and (wide_stress.diagnostics or {}).get("normalization_fallback")
                == "no_control_signal_first_finite_nonzero_response"
                and (wide_stress.diagnostics or {}).get(
                    "excluded_nonpositive_time_count"
                )
                == 1
                and already_normalized.points
                == ((1.0, 0.8), (2.0, 0.6))
                and (already_normalized.diagnostics or {}).get(
                    "normalization_applied"
                )
                is False
            ),
            {
                "wide_points": wide_stress.points,
                "wide_diagnostics": wide_stress.diagnostics,
                "already_normalized_points": already_normalized.points,
                "already_normalized_diagnostics": already_normalized.diagnostics,
            },
        ),
        _check(
            "stress_modulus_not_relabelled_as_stress",
            "Relaxation modulus is blocked until a distinct G/G0 contract exists",
            modulus_blocked
            and "separate G/G0 axis" in modulus_error,
            {"error": modulus_error},
        ),
        _check(
            "dma_temperature_display_unit_contract",
            "DMA temperature keeps Pa canonical lineage while displaying E-prime in MPa",
            (
                dma_before == dma_after
                and dma_series.y_label == "Storage modulus, E′"
                and dma_series.y_unit == "MPa"
                and dma_series.points
                == (
                    (50.0, 80.0),
                    (75.0, 40.0),
                    (100.0, -0.0005),
                )
                and dma_parameters.get("canonical_y_unit") == "Pa"
                and dma_parameters.get("display_y_unit") == "MPa"
                and dma_parameters.get("canonical_to_display_factor") == 1.0e-6
                and dma_diagnostics.get("source_x_unit") == "°C"
                and dma_diagnostics.get("canonical_x_unit") == "°C"
                and dma_diagnostics.get("display_x_unit") == "°C"
                and dma_diagnostics.get("source_x_unit_detection")
                == "detected_from_header"
                and dma_diagnostics.get("source_x_to_display_factor") == 1.0
                and dma_diagnostics.get("source_x_to_display_offset") == 0.0
                and dma_diagnostics.get("x_conversion_method") == "identity_celsius"
                and dma_diagnostics.get("source_y_unit") == "kPa"
                and dma_diagnostics.get("source_y_unit_detection")
                == "detected_from_header"
                and dma_diagnostics.get("source_to_canonical_factor") == 1.0e3
                and dma_diagnostics.get("canonical_to_display_factor") == 1.0e-6
                and dma_diagnostics.get("source_to_display_factor") == 1.0e-3
                and dma_processed.iat[1, 1] == "MPa"
                and float(dma_processed.iat[3, 1]) == 80.0
            ),
            {
                "source_sha256_before": dma_before,
                "source_sha256_after": dma_after,
                "points": dma_series.points,
                "transform_parameters": dma_parameters,
            },
        ),
        _check(
            "dma_temperature_negative_noise_diagnostic",
            "DMA negative acquisition noise is preserved and explicitly counted before y-min display clipping",
            (
                dma_diagnostics.get("negative_display_point_count") == 1
                and dma_diagnostics.get("minimum_negative_display_value") == -0.0005
                and dma_diagnostics.get("maximum_negative_to_positive_peak_fraction")
                == 6.25e-6
                and dma_diagnostics.get("default_y_min_clipped_point_count") == 1
                and dma_parameters.get("negative_display_point_count") == 1
                and dma_parameters.get("default_y_min_clipped_point_count") == 1
                and "Preserve finite negative"
                in str(dma_diagnostics.get("negative_value_policy"))
                and float(dma_processed.iat[5, 1]) == -0.0005
            ),
            {
                "diagnostics": dma_diagnostics,
                "processed_tail_value": dma_processed.iat[5, 1],
            },
        ),
        _check(
            "dma_kelvin_temperature_conversion_contract",
            "DMA Kelvin temperatures convert to Celsius while GPa follows the source-to-Pa-to-MPa ledger",
            (
                dma_kelvin_before == dma_kelvin_after
                and dma_kelvin_diagnostics.get("source_x_unit") == "K"
                and dma_kelvin_diagnostics.get("display_x_unit") == "°C"
                and dma_kelvin_diagnostics.get("source_x_to_display_factor") == 1.0
                and dma_kelvin_diagnostics.get("source_x_to_display_offset") == -273.15
                and dma_kelvin_diagnostics.get("x_conversion_method")
                == "kelvin_to_celsius"
                and dma_kelvin_diagnostics.get("source_y_unit") == "GPa"
                and dma_kelvin_diagnostics.get("source_to_canonical_factor") == 1.0e9
                and dma_kelvin_diagnostics.get("canonical_to_display_factor") == 1.0e-6
                and dma_kelvin_diagnostics.get("source_to_display_factor") == 1.0e3
                and dma_kelvin_processed.iat[1, 0] == "°C"
                and dma_kelvin_processed.iat[1, 1] == "MPa"
                and float(dma_kelvin_processed.iat[3, 0]) == 0.0
                and float(dma_kelvin_processed.iat[3, 1]) == 80.0
                and float(dma_kelvin_processed.iat[4, 0]) == 25.0
                and float(dma_kelvin_processed.iat[4, 1]) == 40.0
            ),
            {
                "source_sha256_before": dma_kelvin_before,
                "source_sha256_after": dma_kelvin_after,
                "diagnostics": dma_kelvin_diagnostics,
                "processed_points": [
                    [
                        dma_kelvin_processed.iat[row_index, 0],
                        dma_kelvin_processed.iat[row_index, 1],
                    ]
                    for row_index in (3, 4)
                ],
            },
        ),
        _check(
            "dma_celsius_adjacent_unit_row_contract",
            "DMA accepts plain C and Pa only when they are explicitly present in an adjacent unit row",
            (
                dma_celsius_row_before == dma_celsius_row_after
                and dma_celsius_row_series.x_unit == "°C"
                and dma_celsius_row_series.y_unit == "MPa"
                and dma_celsius_row_series.points == ((10.0, 2.0), (20.0, 1.0))
                and (dma_celsius_row_series.diagnostics or {}).get("source_x_unit")
                == "°C"
                and (dma_celsius_row_series.diagnostics or {}).get(
                    "source_x_unit_detection"
                )
                == "detected_from_adjacent_unit_row"
                and (dma_celsius_row_series.diagnostics or {}).get("source_y_unit")
                == "Pa"
                and (dma_celsius_row_series.diagnostics or {}).get(
                    "source_y_unit_detection"
                )
                == "detected_from_adjacent_unit_row"
            ),
            {
                "source_sha256_before": dma_celsius_row_before,
                "source_sha256_after": dma_celsius_row_after,
                "points": dma_celsius_row_series.points,
                "diagnostics": dma_celsius_row_series.diagnostics,
            },
        ),
        _check(
            "dma_missing_units_fail_closed",
            "DMA never assumes Celsius or Pa when a source unit is absent",
            (
                dma_missing_modulus_blocked
                and "Missing DMA storage-modulus unit" in dma_missing_modulus_error
                and dma_missing_temperature_blocked
                and "Missing DMA temperature unit" in dma_missing_temperature_error
                and dma_fail_closed_hashes_before == dma_fail_closed_hashes_after
            ),
            {
                "modulus_error": dma_missing_modulus_error,
                "temperature_error": dma_missing_temperature_error,
                "source_sha256_before": dma_fail_closed_hashes_before,
                "source_sha256_after": dma_fail_closed_hashes_after,
            },
        ),
        _check(
            "dma_unsupported_units_fail_closed",
            "DMA rejects unsupported temperature and storage-modulus units instead of relabelling raw values",
            (
                dma_unknown_modulus_blocked
                and "Unsupported DMA storage-modulus unit" in dma_unknown_modulus_error
                and "psi" in dma_unknown_modulus_error
                and dma_unknown_temperature_blocked
                and "Unsupported DMA temperature unit" in dma_unknown_temperature_error
                and "°F" in dma_unknown_temperature_error
                and dma_fail_closed_hashes_before == dma_fail_closed_hashes_after
            ),
            {
                "modulus_error": dma_unknown_modulus_error,
                "temperature_error": dma_unknown_temperature_error,
                "source_sha256_before": dma_fail_closed_hashes_before,
                "source_sha256_after": dma_fail_closed_hashes_after,
            },
        ),
        _check(
            "dma_rate_units_not_scalar_units",
            "DMA requires a complete scalar unit and never reads K/min or MPa/min as K or MPa",
            (
                dma_temperature_rate_blocked
                and "Unsupported DMA temperature unit" in dma_temperature_rate_error
                and "K/min" in dma_temperature_rate_error
                and dma_modulus_rate_blocked
                and "Unsupported DMA storage-modulus unit"
                in dma_modulus_rate_error
                and "MPa/min" in dma_modulus_rate_error
                and dma_fail_closed_hashes_before == dma_fail_closed_hashes_after
            ),
            {
                "temperature_rate_error": dma_temperature_rate_error,
                "modulus_rate_error": dma_modulus_rate_error,
                "source_sha256_before": dma_fail_closed_hashes_before,
                "source_sha256_after": dma_fail_closed_hashes_after,
            },
        ),
        _check(
            "dma_partial_unit_scope_fails_closed",
            "A valid DMA file cannot hide an in-scope file with an unsupported unit",
            (
                dma_partial_blocked
                and "silent partial datasets are not allowed" in dma_partial_error
                and "Unsupported DMA temperature unit" in dma_partial_error
                and "invalid.csv" in dma_partial_error
                and dma_partial_hashes_before == dma_partial_hashes_after
            ),
            {
                "error": dma_partial_error,
                "source_sha256_before": dma_partial_hashes_before,
                "source_sha256_after": dma_partial_hashes_after,
            },
        ),
        _check(
            "saxs_positive_log_domain",
            "SAXS removes non-positive log-domain points per series without changing the source",
            (
                saxs_before == saxs_after
                and len(saxs_diagnostics) == 2
                and all(item.get("selected_point_count", 0) >= 2 for item in saxs_diagnostics)
                and any(item.get("excluded_nonpositive_q_count", 0) > 0 for item in saxs_diagnostics)
                and all(
                    item.get("excluded_nonpositive_intensity_count", 0) > 0
                    for item in saxs_diagnostics
                )
                and all(
                    "do not infer or remove offsets"
                    in str(item.get("intensity_offset_policy"))
                    for item in saxs_diagnostics
                )
                and all(
                    item.get("retained_positive_values_preserved_without_scaling")
                    is True
                    and item.get("sciplot_intensity_scale_factor") == 1.0
                    and item.get("sciplot_intensity_offset") == 0.0
                    and item.get("source_series_scaling_status")
                    == "not_validated_from_source_metadata"
                    and item.get("absolute_cross_series_intensity_comparison_validated")
                    is False
                    for item in saxs_diagnostics
                )
            ),
            {
                "source_sha256_before": saxs_before,
                "source_sha256_after": saxs_after,
                "series": saxs_diagnostics,
            },
        ),
        _check(
            "ftir_measurement_modes",
            "FTIR preserves percent-transmittance and absorbance measurement identities",
            (
                transmittance.y_label == "Transmittance"
                and transmittance.y_unit == "%"
                and absorbance.y_label == "Absorbance"
                and absorbance.y_unit == "a.u."
                and headerless.y_label == "Transmittance"
                and headerless.y_unit == "%"
            ),
            {
                "structured_percent_t": {
                    "label": transmittance.y_label,
                    "unit": transmittance.y_unit,
                },
                "structured_absorbance": {
                    "label": absorbance.y_label,
                    "unit": absorbance.y_unit,
                },
                "headerless_percent_t": {
                    "label": headerless.y_label,
                    "unit": headerless.y_unit,
                },
            },
        ),
        _check(
            "ftir_mixed_measurement_modes_blocked",
            "Transmittance and absorbance are not combined on one response axis",
            mixed_ftir_blocked
            and "separate figures" in mixed_ftir_error,
            {"error": mixed_ftir_error},
        ),
        _check(
            "partial_source_scope_blocked",
            "In-scope FTIR, stress-relaxation, and sweep files cannot be silently omitted",
            (
                partial_ftir_blocked
                and partial_stress_blocked
                and partial_sweep_blocked
                and "silent partial datasets are not allowed"
                in partial_ftir_error
                and "silent partial datasets are not allowed"
                in partial_stress_error
                and "silent partial datasets are not allowed"
                in partial_sweep_error
            ),
            {
                "ftir_error": partial_ftir_error,
                "stress_error": partial_stress_error,
                "sweep_error": partial_sweep_error,
            },
        ),
        _check(
            "rheology_complex_viscosity_canonical_unit",
            "Rheology frequency preserves source mPa-s viscosity as the canonical plotting unit with explicit provenance",
            (
                viscosity_before == viscosity_after
                and viscosity_sample.metric_units.get("complex_viscosity") == "mPa·s"
                and viscosity_canonical_values
                == viscosity_source_values
                and viscosity_processed.iat[2, 4] == "mPa·s"
                and [
                    float(viscosity_processed.iat[row_index, 4]) for row_index in (3, 4)
                ]
                == viscosity_canonical_values
                and viscosity_provenance.get("source_unit") == "mPa·s"
                and viscosity_provenance.get("output_unit") == "mPa·s"
                and viscosity_provenance.get("factor") == 1.0
                and viscosity_provenance.get("method") == "identity"
            ),
            {
                "source_sha256_before": viscosity_before,
                "source_sha256_after": viscosity_after,
                "source_complex_viscosity_mPa_s": viscosity_source_values,
                "canonical_complex_viscosity_mPa_s": (viscosity_canonical_values),
                "processed_output_unit": viscosity_processed.iat[2, 4],
                "processed_output_values": [
                    float(viscosity_processed.iat[row_index, 4]) for row_index in (3, 4)
                ],
                "expected_source_to_canonical_factor": 1.0,
                "transform_unit_conversions": viscosity_inventory,
            },
        ),
        _check(
            "rheology_unsupported_unit_fails_closed",
            "A rheology metric is never relabelled with a canonical unit when no validated conversion exists",
            (
                unsupported_viscosity_blocked
                and "Unsupported rheology unit" in unsupported_viscosity_error
                and "complex_viscosity" in unsupported_viscosity_error
                and "mPa·s" in unsupported_viscosity_error
            ),
            {"error": unsupported_viscosity_error},
        ),
        _check(
            "confirmed_rheology_complex_viscosity_canonical_unit",
            "Confirmed rheology columns preserve mPa-s values in the canonical workbook",
            (
                confirmed_viscosity_before == confirmed_viscosity_after
                and confirmed_viscosity_processed.iat[2, 4] == "mPa·s"
                and [
                    float(confirmed_viscosity_processed.iat[row_index, 4])
                    for row_index in (3, 4)
                ]
                == [500_000.0, 50_000.0]
                and confirmed_viscosity_provenance.get("source_unit") == "mPa·s"
                and confirmed_viscosity_provenance.get("output_unit") == "mPa·s"
                and confirmed_viscosity_provenance.get("factor") == 1.0
                and confirmed_viscosity_provenance.get("method")
                == "identity"
            ),
            {
                "source_sha256_before": confirmed_viscosity_before,
                "source_sha256_after": confirmed_viscosity_after,
                "processed_output_unit": confirmed_viscosity_processed.iat[2, 4],
                "processed_output_values": [
                    float(confirmed_viscosity_processed.iat[row_index, 4])
                    for row_index in (3, 4)
                ],
                "transform_unit_conversions": confirmed_viscosity_inventory,
            },
        ),
        _check(
            "confirmed_rheology_scope_fails_closed",
            "A confirmed rheology sample with invalid units or unparseable values blocks the whole confirmed scope",
            (
                confirmed_partial_blocked
                and "silent partial datasets are not allowed"
                in confirmed_partial_error
                and "bad_unit.csv" in confirmed_partial_error
                and "Unsupported confirmed rheology unit" in confirmed_partial_error
                and "bad_parse.csv" in confirmed_partial_error
                and "No numeric rheology sweep points" in confirmed_partial_error
                and confirmed_partial_hashes_before
                == confirmed_partial_hashes_after
            ),
            {
                "error": confirmed_partial_error,
                "source_sha256_before": confirmed_partial_hashes_before,
                "source_sha256_after": confirmed_partial_hashes_after,
            },
        ),
        _check(
            "saxs_review_note_converges_from_final_rule",
            "The final SAXS rule adds one honest scaling note and a later rule override removes it",
            (
                saxs_review_changed
                and not saxs_review_second_change
                and saxs_review_request["review_notes"].count(SAXS_SCALING_REVIEW_NOTE)
                == 1
                and non_saxs_review_changed
                and SAXS_SCALING_REVIEW_NOTE
                not in non_saxs_review_request["review_notes"]
                and "non-positive log-domain points were excluded"
                in SAXS_SCALING_REVIEW_NOTE
            ),
            {
                "saxs_notes": saxs_review_request["review_notes"],
                "non_saxs_notes": non_saxs_review_request["review_notes"],
                "idempotent_second_change": saxs_review_second_change,
            },
        ),
    ]

    repository = Path(__file__).resolve().parents[2]
    real_stress = (
        repository
        / ".local"
        / "reference_data"
        / "real_world"
        / "rheology_stress_relaxation"
        / "PA 240.csv"
    )
    if real_stress.exists():
        real_series = _read_stress_relaxation_source_series(real_stress)[0]
        real_onset = (real_series.diagnostics or {}).get("hold_onset_source_time")
        checks.append(
            _check(
                "real_stress_hold_onset",
                "Available PA stress-relaxation fixture detects the expected hold onset",
                isinstance(real_onset, int | float)
                and abs(float(real_onset) - 0.077) <= 0.015,
                {"source": str(real_stress), "hold_onset_source_time": real_onset},
            )
        )

    real_saxs = (
        repository
        / ".local"
        / "reference_data"
        / "real_world"
        / "saxs_profile"
        / "Fig3f_saxs_q_intensity.csv"
    )
    if real_saxs.exists():
        real_result = prepare_semantic_source(
            real_saxs,
            output_dir=runs / "real_saxs",
            semantic={"semantic_family": "saxs_profile"},
        )
        real_diagnostics = real_result["transform_steps"][0]["parameters"][
            "source_selections"
        ]
        excluded_counts = [
            int(item.get("excluded_nonpositive_intensity_count", 0))
            for item in real_diagnostics
        ]
        checks.append(
            _check(
                "real_saxs_zero_tail_accounting",
                "Available SAXS fixture records each sample's non-positive intensity tail",
                bool(excluded_counts)
                and all(3 <= count <= 12 for count in excluded_counts)
                and all(
                    item.get("retained_positive_values_preserved_without_scaling")
                    is True
                    and item.get("absolute_cross_series_intensity_comparison_validated")
                    is False
                    for item in real_diagnostics
                ),
                {
                    "source": str(real_saxs),
                    "excluded_nonpositive_intensity_counts": excluded_counts,
                    "source_scaling_status": [
                        item.get("source_series_scaling_status")
                        for item in real_diagnostics
                    ],
                },
            )
        )

    real_dma = (
        repository
        / ".local"
        / "reference_data"
        / "real_world"
        / "dma_temperature_sweep"
        / "Fig2b_storage_modulus_temperature.csv"
    )
    if real_dma.exists():
        real_dma_before = _sha256(real_dma)
        real_dma_result = prepare_semantic_source(
            real_dma,
            output_dir=runs / "real_dma_temperature",
            semantic={"semantic_family": "dma_temperature_sweep"},
        )
        real_dma_after = _sha256(real_dma)
        real_dma_parameters = real_dma_result["transform_steps"][0]["parameters"]
        real_dma_diagnostics = real_dma_parameters["source_selections"]
        real_dma_processed = pd.read_csv(
            Path(str(real_dma_result["processed_source"])),
            header=None,
        )
        real_dma_values = pd.concat(
            [
                pd.to_numeric(
                    real_dma_processed.iloc[3:, column_index],
                    errors="coerce",
                )
                for column_index in range(
                    1,
                    real_dma_processed.shape[1],
                    2,
                )
            ],
            ignore_index=True,
        ).dropna()
        checks.append(
            _check(
                "real_dma_temperature_display_units",
                "Available DMA temperature fixture renders scientific-scale MPa values with explicit negative-noise accounting",
                (
                    real_dma_before == real_dma_after
                    and not real_dma_values.empty
                    and 50.0 <= float(real_dma_values.max()) <= 80.0
                    and float(real_dma_values.min()) < 0.0
                    and real_dma_parameters.get("canonical_y_unit") == "Pa"
                    and real_dma_parameters.get("display_y_unit") == "MPa"
                    and real_dma_parameters.get("canonical_x_unit") == "°C"
                    and real_dma_parameters.get("display_x_unit") == "°C"
                    and real_dma_parameters.get("negative_display_point_count") == 1
                    and all(
                        item.get("source_x_unit") == "°C"
                        and item.get("x_conversion_method") == "identity_celsius"
                        and item.get("canonical_y_unit") == "Pa"
                        and item.get("display_y_unit") == "MPa"
                        for item in real_dma_diagnostics
                    )
                    and any(
                        item.get("negative_display_point_count") == 1
                        and float(
                            item.get(
                                "minimum_negative_display_value",
                                0.0,
                            )
                        )
                        < 0.0
                        and "Preserve finite negative"
                        in str(item.get("negative_value_policy"))
                        for item in real_dma_diagnostics
                    )
                ),
                {
                    "source": str(real_dma),
                    "source_sha256_before": real_dma_before,
                    "source_sha256_after": real_dma_after,
                    "display_minimum_MPa": float(real_dma_values.min()),
                    "display_maximum_MPa": float(real_dma_values.max()),
                    "negative_display_point_count": (
                        real_dma_parameters.get("negative_display_point_count")
                    ),
                    "series": real_dma_diagnostics,
                },
            )
        )

    failed = [check["id"] for check in checks if check["status"] != "passed"]
    payload = {
        "kind": SEMANTIC_CONTRACT_PROBE_KIND,
        "version": SEMANTIC_CONTRACT_PROBE_VERSION,
        "status": "passed" if not failed else "failed",
        "summary": {
            "check_count": len(checks),
            "passed_count": len(checks) - len(failed),
            "failed_ids": failed,
        },
        "checks": checks,
        "artifacts": {
            "root": str(root),
            "summary": str(root / "semantic_contract_probe.json"),
        },
        "limitations": [
            "Synthetic checks validate transformation contracts, not real-data scientific claims.",
            "Optional local real-world checks run only when their authorized fixtures are present.",
        ],
    }
    summary_path = root / "semantic_contract_probe.json"
    summary_path.write_text(
        json.dumps(json_safe(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the SciPlot semantic scientific-contract probe."
    )
    parser.add_argument("--out", required=True, help="Probe output directory.")
    args = parser.parse_args()
    payload = run_semantic_contract_probe(args.out)
    print(json.dumps(json_safe(payload), ensure_ascii=False, indent=2))
    return 0 if payload["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "SEMANTIC_CONTRACT_PROBE_KIND",
    "SEMANTIC_CONTRACT_PROBE_VERSION",
    "run_semantic_contract_probe",
]
