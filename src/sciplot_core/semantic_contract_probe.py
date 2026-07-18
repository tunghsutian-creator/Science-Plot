from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from sciplot_core._utils import json_safe
from sciplot_core.semantic import (
    _read_ftir_series,
    _read_ftir_series_list,
    _read_rheology_frequency_comparison_samples,
    _read_stress_relaxation_series_list,
    _read_stress_relaxation_source_series,
    prepare_semantic_source,
)

SEMANTIC_CONTRACT_PROBE_KIND = "sciplot_semantic_contract_probe"
SEMANTIC_CONTRACT_PROBE_VERSION = 1


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
                and all(3 <= count <= 12 for count in excluded_counts),
                {
                    "source": str(real_saxs),
                    "excluded_nonpositive_intensity_counts": excluded_counts,
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
