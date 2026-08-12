from __future__ import annotations

from pathlib import Path

import pytest

from sciplot_core.semantic_sources.ftir_sources import (
    resolve_ftir_scientific_transform,
)


def _write_rows(path: Path, rows: list[tuple[object, ...]]) -> None:
    path.write_text(
        "\n".join(",".join(str(value) for value in row) for row in rows) + "\n",
        encoding="utf-8",
    )


def test_headerless_transform_preserves_values_source_order_and_rule_owned_x_axis(
    tmp_path: Path,
) -> None:
    rows_by_source = {
        tmp_path / "second.csv": [
            ("row-a", 4300.0, 0.0),
            ("row-b", 900.0, 42.0),
            ("row-c", -15.0, 3.0),
        ],
        tmp_path / "first.csv": [
            ("row-a", -25.0, 0.0),
            ("row-b", 700.0, 35.0),
            ("row-c", 4500.0, 8.0),
        ],
    }
    for source, rows in rows_by_source.items():
        _write_rows(source, rows)

    resolved = resolve_ftir_scientific_transform(tmp_path)
    contract = resolved.contract.to_payload()
    expected_sources = tuple(
        sorted(rows_by_source, key=lambda path: path.name.casefold())
    )

    assert resolved.selected_sources == expected_sources
    assert tuple(series.sample for series in resolved.series) == tuple(
        source.stem for source in expected_sources
    )
    for series, source in zip(resolved.series, expected_sources, strict=True):
        expected_points = tuple(
            (float(x_value), float(y_value))
            for _tag, x_value, y_value in rows_by_source[source]
        )
        assert series.points == expected_points
        assert (series.x_label, series.x_unit) == ("Wavenumber", "cm^-1")
        assert (series.y_label, series.y_unit) == ("Spectral response", "")
        assert (series.diagnostics or {})["ftir_response_mode"] == "unknown"

    assert contract["semantic_family"] == "ftir_spectrum"
    assert contract["anchor"] == {"scope": "none", "selections": []}
    assert contract["retain_anchor"] is None
    assert contract["normalizer"] == {
        "scope": "none",
        "operation": "none",
        "output_metric": "spectral_response",
        "output_unit": "",
    }
    assert contract["x_coordinate_policy"] == {
        "operation": "preserve_source_coordinate_and_order",
        "metric": "wavenumber",
        "unit": "cm^-1",
        "source_row_order_preserved": True,
        "sorting_applied": False,
        "interpolation_applied": False,
    }
    assert contract["output"] | {"series": []} == {
        "x_metric": "wavenumber",
        "x_label": "Wavenumber",
        "x_unit": "cm^-1",
        "y_metric": "spectral_response",
        "y_label": "Spectral response",
        "y_unit": "",
        "response_mode": "unknown",
        "series_order": [source.stem for source in expected_sources],
        "explicit_series_order_applied": False,
        "series": [],
    }
    for columns, evidence in zip(
        contract["source_columns"], contract["output"]["series"], strict=True
    ):
        assert columns["x"]["unit"] == ""
        assert columns["x"]["authority"] == "selected_rule_axis_contract"
        assert evidence["candidate_row_count"] == len(
            rows_by_source[Path(evidence["source"])]
        )
        assert evidence["retained_point_count"] == evidence["candidate_row_count"]
        assert evidence["excluded_point_count"] == 0
        assert evidence["excluded_by_reason"] == {
            "empty_pair": 0,
            "partial_or_nonnumeric": 0,
            "nonfinite": 0,
        }

    reversed_order = [source.stem for source in reversed(expected_sources)]
    reordered = resolve_ftir_scientific_transform(
        tmp_path,
        series_order=reversed_order,
    )
    assert [series.sample for series in reordered.series] == reversed_order
    assert reordered.selected_sources == tuple(reversed(expected_sources))
    assert reordered.contract.output["explicit_series_order_applied"] is True


def test_structured_transform_preserves_explicit_identity_units_and_sample_row(
    tmp_path: Path,
) -> None:
    source = tmp_path / "declared.csv"
    declared_sample = f"{source.stem}-sample"
    source_rows = [(5100.0, 0.0), (850.0, 0.4), (250.0, 0.2)]
    _write_rows(
        source,
        [
            ("Wavenumber", "Absorbance"),
            ("cm^-1", "a.u."),
            (declared_sample, declared_sample),
            *source_rows,
        ],
    )

    resolved = resolve_ftir_scientific_transform(source)
    series = resolved.series[0]
    contract = resolved.contract.to_payload()

    assert series.sample == declared_sample
    assert series.points == tuple(source_rows)
    assert (series.x_label, series.x_unit) == ("Wavenumber", "cm^-1")
    assert (series.y_label, series.y_unit) == ("Absorbance", "a.u.")
    assert (series.diagnostics or {})["ftir_response_mode"] == "absorbance"
    assert contract["output"]["y_metric"] == "spectral_response"
    assert contract["output"]["y_label"] == "Absorbance"
    assert contract["output"]["y_unit"] == "a.u."
    assert contract["output"]["response_mode"] == "absorbance"
    assert contract["source_columns"][0]["header_row_index"] == 0
    assert contract["source_columns"][0]["data_start_row_index"] == 3

    missing_units = tmp_path / "missing_units.csv"
    missing_unit_rows = [(4050.0, 0.0), (350.0, 9.0)]
    _write_rows(
        missing_units,
        [("Wavenumber", "Transmittance"), *missing_unit_rows],
    )
    missing = resolve_ftir_scientific_transform(missing_units)
    assert missing.series[0].points == tuple(missing_unit_rows)
    assert (missing.series[0].y_label, missing.series[0].y_unit) == (
        "Transmittance",
        "",
    )
    assert missing.contract.output["response_mode"] == "transmittance"
    assert missing.contract.source_columns[0]["x"]["unit"] == ""
    assert missing.contract.source_columns[0]["response"]["unit"] == ""


@pytest.mark.parametrize("second_header", ["Absorbance", "Spectral response"])
def test_transform_rejects_mixed_or_incomplete_response_identity(
    tmp_path: Path,
    second_header: str,
) -> None:
    rows = [(900.0, 1.0), (800.0, 2.0)]
    _write_rows(tmp_path / "first.csv", [("Wavenumber", "Transmittance"), *rows])
    _write_rows(tmp_path / "second.csv", [("Wavenumber", second_header), *rows])

    with pytest.raises(ValueError, match="response modes cannot share one figure"):
        resolve_ftir_scientific_transform(tmp_path)


@pytest.mark.parametrize(
    ("bad_row", "message"),
    [
        ((600.0, ""), "partial or nonnumeric"),
        ((600.0, "Inf"), "nonfinite"),
    ],
)
def test_headerless_transform_rejects_incomplete_selected_pairs(
    tmp_path: Path,
    bad_row: tuple[object, object],
    message: str,
) -> None:
    source = tmp_path / "invalid.csv"
    _write_rows(source, [(800.0, 1.0), bad_row, (400.0, 0.0)])

    with pytest.raises(ValueError, match=message):
        resolve_ftir_scientific_transform(source)


def test_each_ftir_file_is_read_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "single_read.csv"
    _write_rows(source, [(5000.0, 0.0), (300.0, 25.0)])

    import sciplot_core.semantic_sources.ftir_sources as ftir_sources

    original = ftir_sources.read_raw_table
    calls: list[Path] = []

    def counted_reader(path: Path, **kwargs: object):
        calls.append(Path(path).resolve())
        return original(path, **kwargs)

    monkeypatch.setattr(ftir_sources, "read_raw_table", counted_reader)

    resolved = resolve_ftir_scientific_transform(source)

    assert resolved.selected_sources == (source.resolve(),)
    assert calls == [source.resolve()]


def test_headerless_intake_filename_uses_one_display_sample(tmp_path: Path) -> None:
    group = "sample-group"
    source = tmp_path / f"{group}__{group}.csv"
    _write_rows(source, [(900.0, 1.0), (500.0, 2.0)])

    resolved = resolve_ftir_scientific_transform(source)

    assert [series.sample for series in resolved.series] == [group]
    assert resolved.contract.output["series_order"] == [group]
