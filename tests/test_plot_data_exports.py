"""Delivered CSVs preserve all source measurements when imported again."""

import csv

import pytest
from pathlib import Path

from sciplot_core.plot_data.exports import build_plot_data_exports
from sciplot_core.source_tables.curve_tables import load_curve_table


def export(tmp_path, content):
    source = tmp_path / "source.csv"
    source.write_text(content, encoding="utf-8")
    records = build_plot_data_exports({"processed_source": str(source)}, destination=tmp_path / "data")
    return Path(records[0]["path"])


def test_single_header_delivery_roundtrip_preserves_first_measurements(tmp_path):
    path = export(tmp_path, "Time (s),Stress (Pa)\n0,10\n1,20\n2,30\n")
    series = load_curve_table(path)[0]
    assert series.data.values.tolist() == [[0., 10.], [1., 20.], [2., 30.]]
    assert (series.x_unit, series.y_unit) == ("s", "Pa")
    second = build_plot_data_exports({"processed_source": str(path)}, destination=tmp_path / "second")
    assert Path(second[0]["path"]).read_bytes() == path.read_bytes()


def test_three_metadata_rows_are_preserved_including_dimensionless_units(tmp_path):
    for unit_row in ("s,Pa", "1,1", ",", "s,a.u."):
        content = f"Time,Stress\n{unit_row}\nsample,sample\n0,10\n1,20\n"
        path = export(tmp_path, content)
        assert list(csv.reader(path.read_text().splitlines())) == list(csv.reader(content.splitlines()))


def test_numeric_first_measurements_are_not_unit_and_sample_metadata(tmp_path):
    for first in ("1,1", "0,10"):
        path = export(tmp_path, f"Time (s),Stress (Pa)\n{first}\n2,20\n3,30\n")
        assert len(load_curve_table(path)[0].data) == 3


def test_missing_measurements_do_not_become_metadata_and_ambiguous_rows_are_rejected(tmp_path):
    for missing in ("N/A", "NA", "", "missing", "—"):
        path = export(tmp_path, f"Time (s),Stress (Pa)\n1,{missing}\n2,20\n3,30\n")
        rows = list(csv.reader(path.read_text().splitlines()))
        assert rows[3][0] == "1"
        assert rows[4:] == [["2", "20"], ["3", "30"]]
    path = export(tmp_path, "Time,Stress\ns,Pa\n123,123\n0,10\n1,20\n")
    assert load_curve_table(path)[0].sample == "123"
    with pytest.raises(ValueError, match="Ambiguous CSV header"):
        export(tmp_path, "X,Y\n1,1\n123,123\n2,20\n")
