from __future__ import annotations

import argparse
import json
import math
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd

from sciplot_core._utils import json_safe
from sciplot_core.materials_rules import (
    _ftir_peak_position_metrics,
    _interior_local_peak_position_metrics,
    _paired_extreme_position_metrics,
    _stress_relaxation_metrics,
    compute_analysis_metrics,
    get_rule,
    semantic_payload_from_rule,
)
from sciplot_core.semantic import prepare_semantic_source


def _check(check_id: str, passed: bool, evidence: Any) -> dict[str, Any]:
    return {
        "id": check_id,
        "status": "passed" if passed else "failed",
        "evidence": json_safe(evidence),
    }


def _write_paired_table(
    path: Path,
    *,
    headers: list[str],
    units: list[str],
    samples: list[str],
    rows: list[list[float]],
) -> None:
    pd.DataFrame([headers, units, samples, *rows]).to_csv(
        path, header=False, index=False
    )


def _row_map(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(row["metric"]): row for row in rows}


def _value_matches(
    rows: dict[str, dict[str, Any]], metric: str, expected: float
) -> bool:
    row = rows.get(metric)
    return bool(
        row
        and row.get("status") == "ok"
        and math.isclose(float(row["value"]), expected, rel_tol=0.0, abs_tol=1e-9)
    )


def _optional_real_fixture_checks(
    repo_root: Path, working_root: Path
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    fixture_root = repo_root / ".local" / "reference_data" / "real_world"

    gpc_source = fixture_root / "gpc_sec_chromatogram"
    if gpc_source.exists():
        gpc_semantic = semantic_payload_from_rule(
            get_rule("gpc_sec_chromatogram"), confidence=1.0
        )
        gpc_result = prepare_semantic_source(
            gpc_source,
            output_dir=working_root / "real_gpc",
            semantic=gpc_semantic,
        )
        gpc_processed = Path(str(gpc_result["processed_source"]))
        gpc_rows = _row_map(
            _paired_extreme_position_metrics(
                gpc_processed,
                metric_name="peak_elution_time_min",
                x_unit="min",
                extreme="maximum",
                y_tokens=("detector response",),
            )
        )
        expected_gpc = {
            "peak_elution_time_min[Sample 8]": 18.6833333333333,
            "peak_elution_time_min[Sample 9]": 18.7333333333333,
        }
        checks.append(
            _check(
                "local_gpc_peak_times",
                all(
                    _value_matches(gpc_rows, metric, value)
                    for metric, value in expected_gpc.items()
                ),
                {
                    "fixture": str(gpc_source),
                    "metrics": gpc_rows,
                    "expected": expected_gpc,
                },
            )
        )
    else:
        checks.append(
            _check(
                "local_gpc_peak_times",
                True,
                {"fixture": str(gpc_source), "status": "not_present_optional"},
            )
        )

    ftir_source = fixture_root / "ftir_headerless" / "A40-20.CSV"
    if ftir_source.exists():
        ftir_semantic = semantic_payload_from_rule(
            get_rule("ftir_spectrum"), confidence=1.0
        )
        ftir_result = prepare_semantic_source(
            ftir_source,
            output_dir=working_root / "real_ftir",
            semantic=ftir_semantic,
        )
        ftir_processed = Path(str(ftir_result["processed_source"]))
        ftir_rows = _row_map(_ftir_peak_position_metrics(ftir_processed))
        checks.append(
            _check(
                "local_ftir_transmittance_trough",
                _value_matches(ftir_rows, "strongest_peak_position", 1633.894),
                {
                    "fixture": str(ftir_source),
                    "metrics": ftir_rows,
                    "expected_wavenumber_cm-1": 1633.894,
                },
            )
        )
    else:
        checks.append(
            _check(
                "local_ftir_transmittance_trough",
                True,
                {"fixture": str(ftir_source), "status": "not_present_optional"},
            )
        )
    return checks


def run_analysis_contract_probe(
    *,
    output_root: Path,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    root = output_root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    repository = (repo_root or Path.cwd()).expanduser().resolve()
    checks: list[dict[str, Any]] = []

    stress_path = root / "stress_relaxation_multi.csv"
    _write_paired_table(
        stress_path,
        headers=["Time", "Normalized stress", "Time", "Normalized stress"],
        units=["s", "sigma/sigma0", "s", "sigma/sigma0"],
        samples=["Alpha", "Alpha", "Beta", "Beta"],
        rows=[
            [0.0, 0.2, 0.0, 1.0],
            [1.0, 1.0, 1.0, 0.75],
            [2.0, 0.75, 2.0, 0.5],
            [3.0, 0.25, 3.0, 0.25],
        ],
    )
    stress_rows = _row_map(_stress_relaxation_metrics(stress_path))
    stress_expected = {
        "final_normalized_value[Alpha]": 0.25,
        "t50_s[Alpha]": 2.5,
        "final_normalized_value[Beta]": 0.25,
        "t50_s[Beta]": 2.0,
    }
    checks.append(
        _check(
            "stress_relaxation_all_paired_series",
            set(stress_rows) == set(stress_expected)
            and all(
                _value_matches(stress_rows, metric, value)
                for metric, value in stress_expected.items()
            ),
            {"metrics": stress_rows, "expected": stress_expected},
        )
    )

    noisy_stress_path = root / "stress_relaxation_noisy_crossings.csv"
    _write_paired_table(
        noisy_stress_path,
        headers=["Time", "Normalized stress"],
        units=["s", "sigma/sigma0"],
        samples=["Noisy", "Noisy"],
        rows=[
            [0.0, 1.0],
            [1.0, 0.4],
            [2.0, 0.7],
            [3.0, 0.3],
            [4.0, -0.1],
        ],
    )
    noisy_stress_rows = _row_map(
        _stress_relaxation_metrics(noisy_stress_path)
    )
    noisy_t50 = noisy_stress_rows.get("t50_s") or {}
    checks.append(
        _check(
            "stress_relaxation_noisy_t50_skipped",
            (
                _value_matches(
                    noisy_stress_rows,
                    "final_normalized_value",
                    -0.1,
                )
                and noisy_t50.get("status") == "skipped"
                and "more than once"
                in str(noisy_t50.get("reason") or "")
            ),
            {"metrics": noisy_stress_rows},
        )
    )

    ftir_path = root / "ftir_modes_multi.csv"
    _write_paired_table(
        ftir_path,
        headers=["Wavenumber", "Transmittance", "Wavenumber", "Absorbance"],
        units=["cm^-1", "%", "cm^-1", "a.u."],
        samples=["Percent T", "Percent T", "Abs", "Abs"],
        rows=[
            [1000.0, 90.0, 2000.0, 0.1],
            [1100.0, 20.0, 2100.0, 0.2],
            [1200.0, 85.0, 2200.0, 0.9],
        ],
    )
    ftir_rows = _row_map(_ftir_peak_position_metrics(ftir_path))
    ftir_expected = {
        "strongest_peak_position[Percent T]": 1100.0,
        "strongest_peak_position[Abs]": 2200.0,
    }
    checks.append(
        _check(
            "ftir_mode_aware_strict_pairs",
            set(ftir_rows) == set(ftir_expected)
            and all(
                _value_matches(ftir_rows, metric, value)
                for metric, value in ftir_expected.items()
            ),
            {"metrics": ftir_rows, "expected": ftir_expected},
        )
    )

    gpc_path = root / "gpc_multi.csv"
    _write_paired_table(
        gpc_path,
        headers=[
            "Elution time",
            "Detector response",
            "Elution time",
            "Detector response",
        ],
        units=["min", "mV", "min", "mV"],
        samples=["Sample 8", "Sample 8", "Sample 9", "Sample 9"],
        rows=[
            [10.0, 0.0, 20.0, 0.0],
            [11.0, 5.0, 21.0, 1.0],
            [12.0, 1.0, 22.0, 9.0],
        ],
    )
    gpc_rows = _row_map(
        _paired_extreme_position_metrics(
            gpc_path,
            metric_name="peak_elution_time_min",
            x_unit="min",
            extreme="maximum",
            y_tokens=("detector response",),
        )
    )
    gpc_expected = {
        "peak_elution_time_min[Sample 8]": 11.0,
        "peak_elution_time_min[Sample 9]": 22.0,
    }
    checks.append(
        _check(
            "gpc_response_strict_pairs",
            set(gpc_rows) == set(gpc_expected)
            and all(
                _value_matches(gpc_rows, metric, value)
                for metric, value in gpc_expected.items()
            ),
            {"metrics": gpc_rows, "expected": gpc_expected},
        )
    )

    xrd_path = root / "xrd_multi.csv"
    _write_paired_table(
        xrd_path,
        headers=["2theta", "Intensity", "2theta", "Intensity"],
        units=["degree", "count", "degree", "count"],
        samples=["PDA-I", "PDA-I", "PDA-Br", "PDA-Br"],
        rows=[
            [8.0, 1.0, 7.0, 8.0],
            [9.0, 10.0, 8.0, 1.0],
            [10.0, 2.0, 9.0, 0.0],
        ],
    )
    xrd_rows = _row_map(
        _paired_extreme_position_metrics(
            xrd_path,
            metric_name="main_peak_2theta",
            x_unit="degree",
            extreme="maximum",
            y_tokens=("intensity",),
        )
    )
    xrd_expected = {"main_peak_2theta[PDA-I]": 9.0, "main_peak_2theta[PDA-Br]": 7.0}
    checks.append(
        _check(
            "xrd_all_strict_pairs",
            set(xrd_rows) == set(xrd_expected)
            and all(
                _value_matches(xrd_rows, metric, value)
                for metric, value in xrd_expected.items()
            ),
            {"metrics": xrd_rows, "expected": xrd_expected},
        )
    )

    saxs_path = root / "saxs_multi.csv"
    _write_paired_table(
        saxs_path,
        headers=["q", "Intensity", "q", "Intensity"],
        units=["nm^-1", "a.u.", "nm^-1", "a.u."],
        samples=[
            "Boundary maximum",
            "Boundary maximum",
            "Interior peak",
            "Interior peak",
        ],
        rows=[
            [1.0, 9.0, 10.0, 1.0],
            [2.0, 8.0, 11.0, 5.0],
            [3.0, 7.0, 12.0, 2.0],
            [4.0, 6.0, 13.0, 1.0],
        ],
    )
    saxs_rows = _row_map(
        _interior_local_peak_position_metrics(
            saxs_path,
            metric_name="main_scattering_peak_q",
            x_unit="nm^-1",
            y_tokens=("intensity",),
        )
    )
    boundary_row = saxs_rows.get("main_scattering_peak_q[Boundary maximum]", {})
    checks.append(
        _check(
            "saxs_boundary_maximum_not_peak",
            boundary_row.get("status") == "skipped"
            and "No interior peak" in str(boundary_row.get("reason"))
            and _value_matches(
                saxs_rows, "main_scattering_peak_q[Interior peak]", 11.0
            ),
            {"metrics": saxs_rows},
        )
    )

    amplitude_contracts: dict[str, Any] = {}
    amplitude_ok = True
    for rule_id in ("rheology_strain_sweep", "rheology_stress_sweep"):
        semantic = semantic_payload_from_rule(get_rule(rule_id), confidence=1.0)
        y_axis = semantic["axis_plan"]["y"]
        analysis = semantic["analysis_plan"][0]
        amplitude_contracts[rule_id] = {"y_axis": y_axis, "analysis": analysis}
        amplitude_ok = amplitude_ok and (
            y_axis["canonical_label"] == "Storage modulus"
            and y_axis["display_label"] == "Storage modulus, G′ (Pa)"
            and "storage modulus" in analysis["required_inputs"]
        )
    checks.append(
        _check("amplitude_storage_modulus_contract", amplitude_ok, amplitude_contracts)
    )

    amplitude_path = root / "amplitude_dispatch.xlsx"
    pd.DataFrame(
        [
            [
                "Strain",
                "Storage Modulus",
                "Loss Modulus",
                "Loss Factor",
                "Strain.1",
                "Storage Modulus.1",
                "Loss Modulus.1",
                "Loss Factor.1",
            ],
            ["Alpha", "Alpha", "Alpha", "Alpha", "Beta", "Beta", "Beta", "Beta"],
            ["%", "Pa", "Pa", "1", "%", "Pa", "Pa", "1"],
            [0.01, 10.0, 500.0, 0.9, 0.02, 30.0, 700.0, 0.1],
            [0.10, 20.0, 900.0, 0.2, 0.20, 10.0, 800.0, 0.8],
            [1.00, 5.0, 100.0, 0.1, 2.00, 20.0, 100.0, 0.2],
        ]
    ).to_excel(amplitude_path, header=False, index=False)
    amplitude_semantic = semantic_payload_from_rule(
        get_rule("rheology_strain_sweep"), confidence=1.0
    )
    amplitude_rows = _row_map(
        compute_analysis_metrics(
            source_path=amplitude_path,
            processed_source=None,
            semantic=amplitude_semantic,
            output_dir=root / "amplitude_metrics",
        )
    )
    amplitude_expected = {
        "peak_modulus_strain_percent[Alpha]": 0.10,
        "peak_modulus_strain_percent[Beta]": 0.02,
    }
    checks.append(
        _check(
            "amplitude_dispatch_uses_only_storage_modulus",
            set(amplitude_rows) == set(amplitude_expected)
            and all(
                _value_matches(amplitude_rows, metric, value)
                for metric, value in amplitude_expected.items()
            ),
            {
                "metrics": amplitude_rows,
                "expected": amplitude_expected,
                "input_layout": "xlsx_sample_then_unit_with_distractor_loss_columns",
            },
        )
    )

    time_path = root / "time_dispatch_with_storage_distractor.csv"
    _write_paired_table(
        time_path,
        headers=[
            "Time",
            "Complex Modulus",
            "Time",
            "Storage Modulus",
        ],
        units=["s", "Pa", "s", "Pa"],
        samples=["Complex", "Complex", "Storage distractor", "Storage distractor"],
        rows=[
            [0.0, 10.0, 0.0, 1000.0],
            [1.0, 30.0, 1.0, 5000.0],
            [2.0, 20.0, 2.0, 9000.0],
        ],
    )
    time_semantic = semantic_payload_from_rule(
        get_rule("rheology_time_sweep"), confidence=1.0
    )
    time_rows = _row_map(
        compute_analysis_metrics(
            source_path=time_path,
            processed_source=None,
            semantic=time_semantic,
            output_dir=root / "time_metrics",
        )
    )
    checks.append(
        _check(
            "time_dispatch_uses_only_complex_modulus",
            set(time_rows) == {"peak_modulus_time_s"}
            and _value_matches(time_rows, "peak_modulus_time_s", 1.0),
            {"metrics": time_rows},
        )
    )

    frequency_path = root / "frequency_grouped_metrics.xlsx"
    pd.DataFrame(
        [
            [
                "Angular Frequency",
                "Storage Modulus",
                "Loss Modulus",
                "Loss Factor",
                "Complex Viscosity",
                "Angular Frequency.1",
                "Storage Modulus.1",
                "Loss Modulus.1",
                "Loss Factor.1",
                "Complex Viscosity.1",
            ],
            ["Alpha"] * 5 + ["Beta"] * 5,
            ["rad/s", "Pa", "Pa", "1", "Pa·s"] * 2,
            [10.0, 12.0, 4.0, 0.33, 2.0, 10.0, 25.0, 6.0, 0.24, 3.0],
            [1.0, 10.0, 3.0, 0.3, 10.0, 1.0, 20.0, 5.0, 0.25, 20.0],
        ]
    ).to_excel(frequency_path, header=False, index=False)
    frequency_semantic = semantic_payload_from_rule(
        get_rule("rheology_frequency_sweep"), confidence=1.0
    )
    frequency_rows = _row_map(
        compute_analysis_metrics(
            source_path=frequency_path,
            processed_source=None,
            semantic=frequency_semantic,
            output_dir=root / "frequency_metrics",
        )
    )
    frequency_expected = {
        "terminal_modulus[Alpha]": 10.0,
        "terminal_modulus[Beta]": 20.0,
    }
    checks.append(
        _check(
            "frequency_grouped_terminal_metrics",
            set(frequency_rows) == set(frequency_expected)
            and all(
                _value_matches(frequency_rows, metric, value)
                for metric, value in frequency_expected.items()
            ),
            {"metrics": frequency_rows, "expected": frequency_expected},
        )
    )

    temperature_path = root / "temperature_grouped_metrics.xlsx"
    pd.DataFrame(
        [
            [
                "Temperature",
                "Storage Modulus",
                "Loss Modulus",
                "Loss Factor",
                "Complex Viscosity",
                "Temperature.1",
                "Storage Modulus.1",
                "Loss Modulus.1",
                "Loss Factor.1",
                "Complex Viscosity.1",
            ],
            ["Alpha"] * 5 + ["Beta"] * 5,
            ["C", "Pa", "Pa", "1", "Pa·s"] * 2,
            [0.0, 100.0, 10.0, 0.1, 10.0, 0.0, 80.0, 8.0, 0.2, 8.0],
            [1.0, 100.0, 11.0, 0.4, 9.0, 1.0, 70.0, 9.0, 0.3, 7.0],
            [2.0, 0.0, 12.0, 0.2, 8.0, 2.0, 60.0, 10.0, 0.5, 6.0],
            [3.0, 0.0, 13.0, 0.1, 7.0, 3.0, 50.0, 11.0, 0.4, 5.0],
        ]
    ).to_excel(temperature_path, header=False, index=False)
    temperature_semantic = semantic_payload_from_rule(
        get_rule("rheology_temperature_sweep"), confidence=1.0
    )
    temperature_rows = _row_map(
        compute_analysis_metrics(
            source_path=temperature_path,
            processed_source=None,
            semantic=temperature_semantic,
            output_dir=root / "temperature_metrics",
        )
    )
    temperature_expected = {
        "maximum_tan_delta[Alpha]": 0.4,
        "maximum_tan_delta[Beta]": 0.5,
        "temperature_at_maximum_tan_delta_C[Alpha]": 1.0,
        "temperature_at_maximum_tan_delta_C[Beta]": 2.0,
        "softening_temperature_candidate[Alpha]": 1.0,
        "softening_temperature_candidate[Beta]": 0.0,
    }
    checks.append(
        _check(
            "temperature_grouped_metrics",
            set(temperature_rows) == set(temperature_expected)
            and all(
                _value_matches(temperature_rows, metric, value)
                for metric, value in temperature_expected.items()
            ),
            {"metrics": temperature_rows, "expected": temperature_expected},
        )
    )

    with tempfile.TemporaryDirectory(prefix="sciplot_analysis_contract_") as temp_dir:
        checks.extend(_optional_real_fixture_checks(repository, Path(temp_dir)))

    failed = [item["id"] for item in checks if item["status"] != "passed"]
    payload = {
        "kind": "sciplot_analysis_contract_probe",
        "version": 1,
        "status": "passed" if not failed else "failed",
        "summary": {
            "check_count": len(checks),
            "passed_count": len(checks) - len(failed),
            "failed_ids": failed,
        },
        "checks": checks,
        "limitations": [
            "Synthetic tables prove deterministic paired-column behavior, not real-data authorization.",
            "The SAXS calculator reports discrete interior local maxima without smoothing or peak assignment.",
        ],
    }
    (root / "analysis_contract_probe.json").write_text(
        json.dumps(json_safe(payload), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return payload


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Probe SciPlot deterministic analysis contracts."
    )
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    payload = run_analysis_contract_probe(output_root=args.out, repo_root=args.repo)
    print(json.dumps(json_safe(payload), indent=2, ensure_ascii=False))
    return 0 if payload["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["run_analysis_contract_probe"]
