from pathlib import Path

from sciplot_core.semantic import (
    _read_rheology_temperature_comparison_samples,
    _read_stress_relaxation_series_list,
    classify_source,
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
    assert all([row["x"] for row in sample.rows] == [200.0, 190.0, 180.0] for sample in samples)


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
        (item.diagnostics or {})["equivalent_source_file_count"] == 2
        for item in series
    )
    assert all(len(item.points) >= 2 for item in series)
