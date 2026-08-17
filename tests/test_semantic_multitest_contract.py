from pathlib import Path

import pandas as pd
import pytest

import sciplot_core.semantic_sources.rheology_confirmation as rheology_confirmation
import sciplot_core.semantic_sources.rheology_interval as rheology_interval
import sciplot_core.semantic_sources.rheology_sweep_sources as rheology_sweep_sources
import sciplot_core.semantic_sources.stress_relaxation_sources as stress_sources
from sciplot_core.semantic import (
    _read_rheology_temperature_comparison_samples,
    _read_stress_relaxation_series_list,
    _read_tensile_workbook_directory,
    classify_source,
)
from sciplot_core.semantic_sources.rheology_interval import (
    _read_rheology_interval_series_list,
)


def _instrument_block(sample: str, *, temperature: bool) -> str:
    if temperature:
        return "\n".join(
            [
                f"Test:\t{sample}",
                "Result:\tTemperature ramp 1",
                "Interval and data points:\t1\t3",
                "Interval data:\tPoint No.\tTemperature\tStorage Modulus\tAngular Frequency",
                "\t\t\t",
                "\t\t[°C]\t[Pa]\t[rad/s]",
                "\t1\t200\t1000\t6.28",
                "\t2\t190\t1200\t6.28",
                "\t3\t180\t1400\t6.28",
            ]
        )
    rows = [
        f"Test:\t{sample}",
        "Result:\tStep strain 1",
        "Interval and data points:\t1\t10",
        "Interval data:\tPoint No.\tTime\tShear Strain\tShear Stress",
        "\t\t\t\t",
        "\t\t[s]\t[%]\t[Pa]",
    ]
    strains = (1.0, 3.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0)
    stresses = (100.0, 95.0, 90.0, 80.0, 72.0, 65.0, 59.0, 54.0, 50.0, 47.0)
    rows.extend(
        f"\t{index}\t{index / 10:.1f}\t{strain}\t{stress}"
        for index, (strain, stress) in enumerate(
            zip(strains, stresses, strict=True),
            start=1,
        )
    )
    return "\n".join(rows)


def _write_utf16(path: Path, text: str) -> None:
    path.write_text(text + "\n", encoding="utf-16")


def test_temperature_export_uses_declared_independent_variable_and_all_tests(
    tmp_path: Path,
) -> None:
    source = tmp_path / "TEMP3.csv"
    _write_utf16(
        source,
        "Project:\tTemperature Sweep\n\n"
        + _instrument_block("E0", temperature=True)
        + "\n\n"
        + _instrument_block("E2", temperature=True),
    )

    semantic = classify_source(source)
    samples = _read_rheology_temperature_comparison_samples(source)

    assert semantic["rule_id"] == "rheology_temperature_sweep"
    assert [sample.sample for sample in samples] == ["E0", "E2"]
    assert all(
        [row["x"] for row in sample.rows] == [200.0, 190.0, 180.0] for sample in samples
    )


def test_stress_relaxation_uses_internal_test_labels_and_deduplicates_exports(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "relaxation"
    source_dir.mkdir()
    combined = (
        "Project:\tRelaxation Test\n\n"
        + _instrument_block("E2", temperature=False)
        + "\n\n"
        + _instrument_block("E3", temperature=False)
    )
    _write_utf16(source_dir / "wrong_name_a.csv", combined)
    _write_utf16(source_dir / "wrong_name_b.csv", combined)

    series = _read_stress_relaxation_series_list(source_dir)

    assert [item.sample for item in series] == ["E2", "E3"]
    assert all(
        (item.diagnostics or {})["equivalent_source_file_count"] == 2 for item in series
    )
    assert all(item.x_label == "Time" for item in series)
    assert all(item.points[0] == (0.1, 1.0) for item in series)
    assert all(
        (item.diagnostics or {})["normalization_baseline_time"] == 0.1
        and (item.diagnostics or {})["excluded_hold_onset_points"] == 0
        and (item.diagnostics or {})["time_reset_applied"] is False
        for item in series
    )


@pytest.mark.parametrize(
    ("module", "attribute", "invoke"),
    (
        (
            rheology_sweep_sources,
            "_read_raw_table_normalized",
            lambda source: _read_rheology_temperature_comparison_samples(source),
        ),
        (
            rheology_confirmation,
            "_confirmed_rheology_sweep_sample",
            lambda source: rheology_confirmation._read_confirmed_rheology_sweep_samples(
                source,
                [{"file_name": "source.csv"}],
                x_label="Angular Frequency",
                default_x_unit="rad/s",
                metrics=(),
            ),
        ),
        (
            rheology_interval,
            "_read_rheology_interval_series",
            lambda source: _read_rheology_interval_series_list(
                source,
                y_candidates=("creepcompliance",),
                y_label="Creep compliance",
                y_unit="1/Pa",
            ),
        ),
        (
            stress_sources,
            "_read_stress_relaxation_source_series",
            lambda source: _read_stress_relaxation_series_list(source),
        ),
    ),
    ids=("automatic_sweep", "confirmed_sweep", "interval", "stress_relaxation"),
)
def test_directory_readers_do_not_relabel_programming_failures(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    module,
    attribute: str,
    invoke,
) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "source.csv").touch()

    def fail_reader(*_args, **_kwargs):
        raise RuntimeError("reader invariant failed")

    monkeypatch.setattr(module, attribute, fail_reader)

    with pytest.raises(RuntimeError, match="reader invariant failed"):
        invoke(source_dir)


def test_creep_directory_rejects_a_partial_interval_dataset(tmp_path: Path) -> None:
    source_dir = tmp_path / "creep"
    source_dir.mkdir()
    _write_utf16(
        source_dir / "valid.csv",
        "\n".join(
            [
                "Test:\tvalid",
                "Result:\tCreep 1",
                "Interval and data points:\t1\t2",
                "Interval data:\tPoint No.\tTime\tCreep Compliance",
                "\t\t[s]\t1/Pa",
                "\t1\t0.1\t0.000001",
                "\t2\t0.2\t0.000002",
            ]
        ),
    )
    _write_utf16(
        source_dir / "invalid.csv",
        "\n".join(
            [
                "Test:\tinvalid",
                "Result:\tCreep 1",
                "Interval and data points:\t1\t2",
                "Interval data:\tPoint No.\tTime\tCreep Compliance",
                "\t\t[s]\t",
                "\t1\t0.1\t0.000003",
                "\t2\t0.2\t0.000004",
            ]
        ),
    )

    with pytest.raises(
        ValueError,
        match=(
            "silent partial datasets are not allowed.*invalid\\.csv.*"
            "unit is missing"
        ),
    ):
        _read_rheology_interval_series_list(
            source_dir,
            y_candidates=("creepcompliance",),
            y_label="Creep compliance",
            y_unit="1/Pa",
            preferred_result_tokens=("creep",),
        )


def test_tensile_workbook_metadata_label_outranks_filename_sample_code(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "2mm"
    source_dir.mkdir()
    workbook = source_dir / "e2.xlsx"
    with pd.ExcelWriter(workbook) as writer:
        pd.DataFrame(
            [
                ["Tensile strain", "Tensile stress"],
                ["%", "MPa"],
                ["e2 2mm", "e2 2mm"],
                [0.0, 0.0],
                [1.0, 10.0],
                [2.0, 15.0],
            ]
        ).to_excel(
            writer,
            sheet_name="Representative_Curve",
            header=False,
            index=False,
        )
        pd.DataFrame(
            {
                "Specimen": ["e2-1", "e2-2"],
                "Tensile Strength (MPa)": [15.0, 14.0],
                "Tensile Modulus (MPa)": [800.0, 780.0],
                "Elongation at Break (%)": [2.0, 1.8],
            }
        ).to_excel(writer, sheet_name="All_Specimens", index=False)
        pd.DataFrame([["label", "e2 2mm"]]).to_excel(
            writer,
            sheet_name="DataStudio_Metadata",
            header=False,
            index=False,
        )

    series, summary_rows = _read_tensile_workbook_directory(source_dir)

    assert [item.sample for item in series] == ["e2 2mm"]
    assert {row["sample"] for row in summary_rows} == {"e2 2mm"}
