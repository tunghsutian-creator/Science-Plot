"""CSV projection preserves independent dataset lengths and float identity."""

from copy import deepcopy
import csv
import json

import pytest

from test_managed_backend import managed_ir
from sciplot_core.plot_document import DocumentError
from sciplot_core.plot_engine.errors import EngineError
from sciplot_core.plot_engine.managed_delivery_data import project_data
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
    result = project_data(path, tmp_path / "attempt", "001_figure", expected=identity(ir))
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
        project_data(path, tmp_path / "attempt", "001_figure", expected=identity(ir))
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
        project_data(path, tmp_path / "attempt", "001_figure", expected=expected)
    assert caught.value.reason_code == ("plot_ir_hash_mismatch" if change == "tampered_values" else "managed_delivery_ir_changed")
    assert not (tmp_path / "attempt").exists()
