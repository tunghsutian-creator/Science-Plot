"""CSV projection preserves independent dataset lengths and float identity."""

from copy import deepcopy
import csv
import json

import pytest

from test_managed_backend import managed_ir
from sciplot_core.plot_document import DocumentError
from sciplot_core.plot_engine.errors import EngineError
from sciplot_core.plot_engine.managed_delivery_data import capture_plot_data, project_data
from sciplot_core.plot_ir import seal_ir


def identity(ir):
    return {key: ir[key] for key in ("ir_hash", "scientific_hash", "presentation_hash")}


def test_each_dataset_keeps_own_length_column_order_float_roundtrip_and_null(tmp_path):
    values = [1.2345678901234567, None, 0.36787944117144233]
    ir = managed_ir()
    columns = ir["datasets"]["raw:A"]["columns"]
    columns["column:1"]["values"] = values
    columns["column:0"]["values"] = [0, 1, 2]
    ir["datasets"]["raw:A"]["columns"] = {key: columns[key] for key in ("column:1", "column:0")}
    ir["series"][0].update(x=[0, 1, 2], y=values)
    reference = deepcopy(ir["datasets"]["raw:A"])
    reference.update(id="reference:short", columns={"reference": {"label": "1/e reference", "unit": "1", "values": [values[-1]]}})
    ir["datasets"]["reference:short"] = reference
    ir = seal_ir(ir)
    path = tmp_path / "sealed-ir.json"
    path.write_text(json.dumps(ir))
    before = path.read_bytes()
    result = project_data(capture_plot_data(path, expected=identity(ir)), tmp_path / "attempt", "001_figure")
    assert (tmp_path / "attempt" / result["ir"]["path"]).read_bytes() == before
    assert [item["row_count"] for item in result["datasets"]] == [3, 1]
    assert result["datasets"][0]["column_ids"] == ["column:1", "column:0"]
    for dataset, expected in zip(result["datasets"], [values, [values[-1]]], strict=True):
        with (tmp_path / "attempt" / dataset["path"]).open(newline="") as handle:
            rows = list(csv.reader(handle))
        decoded = [float(row[0]) if row[0] else None for row in rows[1:]]
        assert decoded == expected
        assert len(rows) == len(expected) + 1
    assert path.read_bytes() == before


def test_mismatched_columns_block_instead_of_padding_or_truncating(tmp_path):
    ir = managed_ir()
    ir["datasets"]["raw:A"]["columns"]["column:1"]["values"].append(4)
    path = tmp_path / "invalid-ir.json"
    path.write_text(json.dumps(ir))
    with pytest.raises(DocumentError) as caught:
        project_data(capture_plot_data(path, expected=identity(ir)), tmp_path / "attempt", "001_figure")
    assert caught.value.reason_code == "transform_ragged_dataset"
    assert not (tmp_path / "attempt").exists()


@pytest.mark.parametrize("change", ["tampered_values", "wrong_selected_hash"])
def test_ir_content_seal_and_selected_identity_checked_before_csv(tmp_path, change):
    ir = managed_ir()
    expected = identity(ir)
    if change == "tampered_values":
        # Change both projections to remain structurally valid, while retaining
        # the old self-reported hash. The existing IR validator must reject it.
        ir["datasets"]["raw:A"]["columns"]["column:1"]["values"][0] = 1.5
        ir["series"][0]["y"][0] = 1.5
    else:
        expected["ir_hash"] = "f" * 64
    path = tmp_path / "ir.json"
    path.write_text(json.dumps(ir))
    with pytest.raises((DocumentError, EngineError)) as caught:
        project_data(capture_plot_data(path, expected=expected), tmp_path / "attempt", "001_figure")
    assert caught.value.reason_code == ("plot_ir_hash_mismatch" if change == "tampered_values" else "managed_delivery_ir_changed")
    assert not (tmp_path / "attempt").exists()


def test_selected_csv_keeps_bound_columns_distinct_lengths_nulls_and_layer_provenance(tmp_path):
    from sciplot_core.plot_engine.managed_delivery_data import PlotData, plotted_dataset_csvs

    first = deepcopy(managed_ir()["datasets"]["raw:A"])
    first["columns"] = {
        "x": {"label": "Wavenumber", "unit": "cm^-1", "values": [780, 820, 870]},
        "unused": {"label": "Other measurement", "unit": "K", "values": [300, 302, 303]},
        "y": {"label": "Transmittance", "unit": "%", "values": [1.2345678901234567, None, 30]},
    }
    short = deepcopy(first)
    for column in short["columns"].values():
        column["values"] = column["values"][:1]
    layer = {"label": "Duplicate display name", "role": "measurement", "mappings": {"x": "x", "y": "y"},
             "marks": [{"id": "interpolated"}]}
    data = PlotData({}, {"datasets": {"original-input": first, "visible:long": first, "visible:short": short,
                                     "hidden": short},
                        "views": [{"id": "view:main", "layers": [
                            {**layer, "id": "long", "dataset_id": "visible:long"},
                            {**layer, "id": "short", "dataset_id": "visible:short"},
                            {**layer, "id": "hidden", "dataset_id": "hidden", "visible": False}]}],
                        "display_curves": {"interpolated": {"curve": {"x": [820], "y": [99]}}}})
    records = plotted_dataset_csvs(data, tmp_path, {"long": "A", "short": "B"})
    assert [record["dataset_id"] for record in records] == ["visible:long", "visible:short"]
    assert set(file.name for file in tmp_path.iterdir()) == {"001.csv", "002.csv"}
    assert [record["row_count"] for record in records] == [3, 1]
    assert [record["layers"][0]["sample"] for record in records] == ["A", "B"]
    assert all(record["column_ids"] == ["x", "y"] and record["layers"][0]["display_curve"] for record in records)
    assert [record["provenance"]["sources"][0]["sha256"] for record in records] == [
        first["provenance"]["sources"][0]["sha256"], short["provenance"]["sources"][0]["sha256"]]
    assert (tmp_path / "001.csv").read_text() == "Wavenumber,Transmittance\n780,1.2345678901234567\n820,\n870,30\n"
    assert (tmp_path / "002.csv").read_text() == "Wavenumber,Transmittance\n780,1.2345678901234567\n"
