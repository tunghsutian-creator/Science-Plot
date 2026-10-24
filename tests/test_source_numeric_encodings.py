"""Generated scientific controls for explicitly versioned source numeric parsing."""

import json
import pandas as pd
import pytest
from sciplot_core.source_tables import load_curve_table


@pytest.mark.parametrize("dtype", [object, "str", "string"])
def test_source_numeric_encodings_keep_fixed_history_and_closed_grammar(dtype):
    from decimal import Decimal
    from sciplot_core.source_tables.parsing import (
        DECIMAL_ROUND_TRIP_ENCODING_V1, coerce_legacy_numeric_series, coerce_numeric_series,
    )
    tokens = ["0.12345678901234567", "0.00000000000000012345678901234567", "1.0000000000000002",
              "5e-324", "1e-325", "-1e309", "1_000", "１２", "1.2x", "1.0\x00", "1e2\x00x"]
    values = pd.Series(tokens, dtype=dtype, index=range(10, 21), name="original")
    frozen = coerce_legacy_numeric_series(values)
    assert [float(value).hex() for value in frozen.iloc[:6]] == [
        "0x1.f9add3746f659p-4", "0x1.cd2b297d889bcp-54", "0x1.0000000000001p+0",
        "0x0.0000000000001p-1022", "0x0.0p+0", "-inf",
    ]
    for encoding in (DECIMAL_ROUND_TRIP_ENCODING_V1, "decimal_float64_round_trip_v2"):
        result = coerce_numeric_series(values, encoding=encoding)
        assert [float(value).hex() for value in result.iloc[:6]] == [float(token).hex() for token in tokens[:6]]
        assert result.iloc[6:9].isna().all()
        assert result.index.equals(values.index) and result.name == "original"
        if encoding == DECIMAL_ROUND_TRIP_ENCODING_V1:
            assert result.iloc[9:].tolist() == [1., 100.]
        else:
            assert result.iloc[9:].isna().all()
    integers = coerce_numeric_series(pd.Series(["1", "2"], dtype=dtype))
    assert pd.api.types.is_integer_dtype(integers.dtype) and integers.tolist() == [1, 2]
    for integer in ("18446744073709551615", "+18446744073709551615", "000018446744073709551615"):
        unsigned = coerce_numeric_series(pd.Series([integer], dtype=dtype))
        assert pd.api.types.is_unsigned_integer_dtype(unsigned.dtype) and unsigned.iloc[0] == 18446744073709551615
    padded = coerce_numeric_series(pd.Series(["0" * 5000 + "1"], dtype=dtype))
    assert pd.api.types.is_integer_dtype(padded.dtype) and padded.iloc[0] == 1
    spaced = pd.Series(["0.12345678901234567e +0"], dtype=dtype)
    assert float(coerce_numeric_series(spaced).iloc[0]).hex() == "0x1.f9add3746f65ep-4"
    assert float(coerce_numeric_series(spaced, encoding=DECIMAL_ROUND_TRIP_ENCODING_V1).iloc[0]).hex() == "0x1.f9add3746f659p-4"
    decimals = coerce_numeric_series(pd.Series([Decimal("0.12345678901234567890"), Decimal("NaN")], dtype=object))
    assert decimals.iloc[0].hex() == "0x1.f9add3746f65fp-4" and pd.isna(decimals.iloc[1])
    signed_zero = coerce_numeric_series(pd.Series(["-0", "1.25"], dtype=dtype))
    assert float(signed_zero.iloc[0]).hex() == "-0x0.0p+0"


def test_saved_source_audit_selects_only_exact_frozen_arithmetic_candidates(tmp_path, monkeypatch):
    from sciplot_core.source_coverage import managed_documents
    from sciplot_core.source_coverage.file_snapshots import _stable_file_snapshot
    from sciplot_core.source_tables.parsing import DECIMAL_ROUND_TRIP_ENCODING, SOURCE_NUMERIC_ENCODING_KEY
    from sciplot_core.studio_render import derive_terminal_render_data_contract

    source = tmp_path / "old.csv"
    source.write_text("x,y\n1,-46374275.98665546187894517618789591e-8\n2,0.12345678901234567\n")
    snapshots = [_stable_file_snapshot(source, label="generated historical arithmetic")]
    request = {"template": "curve"}
    original = managed_documents._derive_prepared_data
    calls = []
    def recording(**kwargs):
        if kwargs.get("legacy_numeric_parser"):
            calls.append(kwargs["legacy_fused_digits"])
        return original(**kwargs)
    monkeypatch.setattr(managed_documents, "_derive_prepared_data", recording)
    for fused, expected in ((True, "-0x1.dadf61cd88d74p-2"), (False, "-0x1.dadf61cd88d72p-2")):
        units = derive_terminal_render_data_contract(request=request, terminal_sources=[source],
                    legacy_numeric_parser=True, legacy_fused_digits=fused)["units"]
        assert units[0]["y_values"][0].hex() == expected
        spec = {"source_request": request, "series": units, "axes": units[0]["axes"],
                "categorical": units[0]["categorical_contract"], "reference_guides": units[0]["reference_guides"],
                "direct_labels": units[0]["direct_labels"]}
        calls.clear()
        serialized = json.dumps(spec, sort_keys=True)
        assert managed_documents._verify_prepared_data(spec, snapshots)["status"] == "passed"
        assert json.dumps(spec, sort_keys=True) == serialized and SOURCE_NUMERIC_ENCODING_KEY not in spec
        assert calls == ([True] if fused else [True, False])
        with pytest.raises(ValueError, match="do not reproduce"):
            managed_documents._verify_prepared_data({**spec, SOURCE_NUMERIC_ENCODING_KEY: DECIMAL_ROUND_TRIP_ENCODING}, snapshots)
    assert source.read_text().startswith("x,y\n1,-46374275.98665546187894517618789591e-8\n")


def test_selected_performance_source_encoding_replays_v1_and_rejects_new_nul(tmp_path):
    from sciplot_core.foundation.file_hashing import file_sha256
    from sciplot_core.performance_comparison import PerformanceComparisonError, prepare_performance_comparison
    from sciplot_core.performance_veusz import build_performance_veusz_spec
    from sciplot_core.source_coverage.file_snapshots import _stable_file_snapshot
    from sciplot_core.source_coverage.managed_documents import _verify_prepared_data
    from sciplot_core.source_tables.parsing import DECIMAL_ROUND_TRIP_ENCODING_V1, SOURCE_NUMERIC_ENCODING_KEY
    source = tmp_path / "performance.csv"
    source.write_text("Material,Role,Metric,Value,Unit\nA,sample,x,7801618240358122768040689434.e-28\x00suffix,MPa\nA,sample,y,NaN,s\nB,sample,x,0.5,MPa\nB,sample,y,2,s\nC,reference,x,0.7,MPa\nC,reference,y,3,s\n")
    before = source.read_bytes()
    selection = {"kind": "sciplot_performance_metric_selection", "version": 1, "source_sha256": file_sha256(source),
        "x_metric": "x", "y_metric": "y", "scatter_x_display": "preserve_original", "unit_declarations": []}
    request = {"rule_id": "performance_comparison", "template": "scatter", "performance_selection": selection}
    payload = prepare_performance_comparison(source, template_id="scatter", selection=selection,
                source_numeric_encoding=DECIMAL_ROUND_TRIP_ENCODING_V1, compatibility_fused_digits=False)
    assert payload["source_observations"][0]["x_value"].hex() == "0x1.8f715edfa49e4p-1"
    assert payload["missing_pair_count"] == 1
    spec = build_performance_veusz_spec(payload=payload, request=request)
    assert spec[SOURCE_NUMERIC_ENCODING_KEY] == "decimal_float64_round_trip_v2"
    spec[SOURCE_NUMERIC_ENCODING_KEY] = DECIMAL_ROUND_TRIP_ENCODING_V1
    serialized = json.dumps(spec, sort_keys=True)
    assert _verify_prepared_data(spec, [_stable_file_snapshot(source, label="generated v1 performance")])["status"] == "passed"
    assert json.dumps(spec, sort_keys=True) == serialized
    with pytest.raises(PerformanceComparisonError) as error:
        prepare_performance_comparison(source, template_id="scatter", selection=selection)
    assert error.value.reason_code == "performance_numeric_value_invalid"
    assert source.read_bytes() == before


def test_file_numeric_modes_preserve_lexemes_and_native_cell_types(tmp_path):
    from sciplot_core.source_tables.parsing import DECIMAL_ROUND_TRIP_ENCODING_V1, coerce_frame_numeric_series
    from sciplot_core.source_tables.raw_readers import read_raw_table
    from sciplot_core.studio_render.table_io import _read_table
    token = "0.12345678901234567"
    for suffix in ("csv", "xlsx"):
        source = tmp_path / f"typed.{suffix}"
        frame = pd.DataFrame({"x": [1, 2, 3], "y": [token, "2.5", "3.5"],
                              "native_float": [1.25, 2.5, 3.5], "label": ["A", "B", "C"], "flag": [True, False, True]})
        if suffix == "xlsx":
            frame.to_excel(source, index=False)
        else:
            frame.to_csv(source, index=False)
        before = source.read_bytes()
        current, historical = _read_table(source), _read_table(source, legacy_numeric_parser=True)
        assert read_raw_table(source).iloc[1, 1] == token
        assert current["y"].iloc[0] == token
        assert coerce_frame_numeric_series(current["y"], current).iloc[0].hex() == "0x1.f9add3746f65ep-4"
        assert historical["y"].iloc[0].hex() == "0x1.f9add3746f659p-4"
        assert pd.api.types.is_integer_dtype(historical["x"].dtype)
        assert pd.api.types.is_bool_dtype(historical["flag"].dtype)
        assert historical["label"].tolist() == ["A", "B", "C"]
        assert historical["native_float"].tolist() == [1.25, 2.5, 3.5]
        assert source.read_bytes() == before
    for suffix, separator in (("csv", ","), ("tsv", "\t")):
        source = tmp_path / f"nul.{suffix}"
        rows = [["Time", "Stress"], ["s", "Pa"], ["A", "A"], ["1", token + "\x00suffix"], ["2", "2.5"], ["3", "3.5"]]
        source.write_text("\n".join(separator.join(row) for row in rows) + "\n")
        before = source.read_bytes()
        raw = read_raw_table(source)
        assert raw.iloc[3, 1] == token + "\x00suffix"
        assert load_curve_table(source)[0].data.to_dict(orient="list") == {"x": [2, 3], "y": [2.5, 3.5]}
        v1 = _read_table(source, source_numeric_encoding=DECIMAL_ROUND_TRIP_ENCODING_V1)
        old = _read_table(source, legacy_numeric_parser=True)
        assert coerce_frame_numeric_series(v1.iloc[:, 1], v1).iloc[2].hex() == "0x1.f9add3746f659p-4"
        assert coerce_frame_numeric_series(old.iloc[:, 1], old).iloc[2].hex() == "0x1.f9add3746f659p-4"
        assert source.read_bytes() == before



def test_component_numeric_encoding_preserves_its_original_v1_pipeline(tmp_path):
    from copy import deepcopy
    from sciplot_core.studio_render.models import StudioPreparationBlocked
    from sciplot_core.source_tables.parsing import DECIMAL_ROUND_TRIP_ENCODING_V1, SOURCE_NUMERIC_ENCODING_KEY
    from sciplot_core.source_coverage.file_snapshots import _stable_file_snapshot
    from sciplot_core.source_coverage.managed_documents import _verify_prepared_data
    from sciplot_core.studio_render import derive_terminal_render_data_contract
    source = tmp_path / "components.csv"
    source.write_text("Sample,Component,Value (MPa)\nA,first,7801618240358122768040689434.e-28\nA,second,2\n")
    before = source.read_bytes()
    request = {"template": "bar"}
    current = derive_terminal_render_data_contract(request=request, terminal_sources=[source])["units"]
    assert current[0]["y_values"][0].hex() == "0x1.8f715edfa49e5p-1"
    snapshots = [_stable_file_snapshot(source, label="generated v1 components")]
    for order, expected in ((True, "0x1.8f715edfa49e6p-1"), (False, "0x1.8f715edfa49e4p-1"), (None, "0x1.8f715edfa49e5p-1")):
        old = derive_terminal_render_data_contract(request=request, terminal_sources=[source],
                    source_numeric_encoding=DECIMAL_ROUND_TRIP_ENCODING_V1, legacy_fused_digits=order)["units"]
        assert old[0]["y_values"][0].hex() == expected
        spec = {"source_request": request, "series": old, "axes": old[0]["axes"],
                "categorical": old[0]["categorical_contract"], "reference_guides": old[0]["reference_guides"],
                "direct_labels": old[0]["direct_labels"], SOURCE_NUMERIC_ENCODING_KEY: DECIMAL_ROUND_TRIP_ENCODING_V1}
        serialized = json.dumps(spec, sort_keys=True)
        assert _verify_prepared_data(spec, snapshots)["status"] == "passed"
        assert json.dumps(spec, sort_keys=True) == serialized
        tampered = deepcopy(spec)
        tampered["series"][0]["y_values"][0] = float.fromhex("0x1.8f715edfa49e7p-1")
        with pytest.raises(ValueError, match="do not reproduce"):
            _verify_prepared_data(tampered, snapshots)
    assert source.read_bytes() == before
    source.write_bytes(before.replace(b"7801618240358122768040689434.e-28", b"7801618240358122768040689434.e-28\x00suffix"))
    with pytest.raises(StudioPreparationBlocked) as error:
        derive_terminal_render_data_contract(request=request, terminal_sources=[source])
    assert error.value.reason_code == "ambiguous_categorical_component_value"
