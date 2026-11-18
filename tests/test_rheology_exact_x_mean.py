"""Repeat averaging agrees with the production parser and figure-task tables."""
from copy import deepcopy
import csv
import math

import pytest

from sciplot_core.plot_document.errors import DocumentError
from sciplot_core.plot_transforms import builtin_executor, execute_node
from sciplot_core.plot_transforms.schema import ordered_nodes
from sciplot_core.semantic_sources.models import RheologySweepSample
from sciplot_core.semantic_sources.rheology_replicates import _coalesce_replicate_sweep_samples
from sciplot_core.semantic_sources.rheology_workbooks import _write_rheology_sweep_comparison_workbook
from sciplot_core.workflow.rheology_bundle import _sweep_metric_sources


UNITS = {"x": "rad/s", "storage_modulus": "Pa", "loss_modulus": "Pa", "complex_viscosity": "mPa·s"}


def _dataset(identifier, rows, first_row):
    return {"id": identifier,
            "columns": {name: {"label": name, "unit": unit, "values": [row.get(name) for row in rows]}
                        for name, unit in UNITS.items()},
            "provenance": {"sources": [{"source_id": identifier, "sha256": ("a" if identifier == "first" else "b") * 64,
                "table_selection": {"sheet": None, "header_rows": [0],
                    "data_start_row": first_row, "data_end_row": first_row + len(rows)},
                "column_indices": {name: index for index, name in enumerate(UNITS)},
                "rows": list(range(first_row, first_row + len(rows)))}], "transforms": []}}


def test_exact_x_mean_matches_original_grouping_metric_tables_and_analysis(tmp_path):
    from sciplot_core.materials_rules.analysis import compute_analysis_metrics
    from sciplot_core.semantic_sources.rheology_sweep_sources import _RHEOLOGY_FREQUENCY_OUTPUT_METRICS

    close_frequency = 1.000000000001
    # Repeated x in one replicate contributes each finite observation. An x
    # missing G′ only stays available to G″, while an entirely empty x drops.
    left = ({"x": 10., "storage_modulus": 100., "loss_modulus": 9., "complex_viscosity": 200.},
            {"x": 1., "storage_modulus": 40.}, {"x": 1., "storage_modulus": 60.},
            {"x": 2., "loss_modulus": 14.}, {"x": 8.})
    right = ({"x": 1., "storage_modulus": 110., "loss_modulus": 8.},
             {"x": 2., "loss_modulus": 18.}, {"x": close_frequency, "storage_modulus": 77., "loss_modulus": 13.},
             {"x": 10., "storage_modulus": 120., "complex_viscosity": 400.})
    singleton = ({"x": 10., "storage_modulus": 200., "loss_modulus": 7., "complex_viscosity": 100.},
                 {"x": 1., "storage_modulus": 169., "loss_modulus": 11.},
                 {"x": 1., "storage_modulus": 171., "loss_modulus": 17.})
    metric_units = {name: unit for name, unit in UNITS.items() if name != "x"}
    raw = [RheologySweepSample(condition, tmp_path / name, "Angular Frequency", "rad/s", metric_units, rows)
           for condition, name, rows in (("A · 210 °C", "left", left), ("B · 150 °C", "single", singleton),
                                          ("A · 210 °C", "right", right))]
    old = _coalesce_replicate_sweep_samples(raw)
    assert [sample.sample for sample in old] == ["A · 210 °C", "B · 150 °C"]
    assert old[1] is raw[1] and old[1].rows == singleton

    kind = "rheology_mean_exact_x"
    node = {"id": "aggregate", "kind": kind, "inputs": ["first", "second"], "output": "mean",
            "parameters": {"x_column": "x"}, "executor": builtin_executor(kind), "determinism": "deterministic"}
    sources = {"first": _dataset("first", left, 3), "second": _dataset("second", right, 10)}
    assert ordered_nodes([node], list(sources)) == [node]
    actual, key = execute_node(node, sources)
    columns = actual["columns"]
    assert columns["x"]["values"] == [row["x"] for row in old[0].rows] == [1., close_frequency, 2., 10.]
    assert columns["storage_modulus"]["values"] == [70., 77., None, 110.]
    assert columns["loss_modulus"]["values"] == [8., 13., 16., 9.]
    assert columns["complex_viscosity"]["values"] == [None, None, None, 300.]
    assert list(actual["provenance"]["sources"]) == [source["provenance"]["sources"][0] for source in sources.values()]
    step = actual["provenance"]["transforms"][-1]
    assert step["cache_key"] == key
    assert step["details"]["contributor_counts"] == {"storage_modulus": [3, 1, 0, 2],
                                                     "loss_modulus": [1, 1, 2, 1], "complex_viscosity": [0, 0, 0, 2]}
    assert step["details"]["row_origins"][0] == [{"source_id": "first", "row": 4},
                                                   {"source_id": "first", "row": 5}, {"source_id": "second", "row": 10}]

    # Read actual old terminal tables too: both retain x=2 but only G″ has y.
    workbook = tmp_path / "prepared.xlsx"
    _write_rheology_sweep_comparison_workbook(old, workbook, comparison_sheet="Frequency_Comparison",
        metrics=tuple(item for item in _RHEOLOGY_FREQUENCY_OUTPUT_METRICS if item[0] in metric_units))
    old_sources = _sweep_metric_sources(workbook, output_dir=tmp_path / "bundle",
        request={"rule_id": "rheology_frequency_sweep", "template": "point_line"})
    assert [stem for stem, _, _ in old_sources][:2] == ["freq_storage_modulus", "freq_loss_modulus"]
    for stem, file, _options in old_sources:
        with file.open(newline="", encoding="utf-8") as stream:
            table = list(csv.reader(stream))[3:]
        assert [float(row[0]) for row in table[:4]] == columns["x"]["values"]
        values = [float(row[1]) if row[1] else None for row in table[:4]]
        assert values == columns[stem.removeprefix("freq_")]["values"]
    metrics = compute_analysis_metrics(source_path=workbook, processed_source=workbook,
        semantic={"rule_id": "rheology_frequency_sweep", "axis_plan": {"y": {"canonical_unit": "Pa"}}},
        output_dir=tmp_path / "analysis")
    assert [(row["value"], row["unit"]) for row in metrics] == [(70., "Pa"), (169., "Pa")]

    # Even adjacent binary64 values remain distinct in the reducer, regardless
    # of the historical workbook's own cell serialization precision.
    adjacent = deepcopy(sources)
    adjacent_x = math.nextafter(1., math.inf)
    adjacent["second"]["columns"]["x"]["values"][2] = adjacent_x
    reduced, _ = execute_node(node, adjacent)
    assert reduced["columns"]["x"]["values"][:2] == [1., adjacent_x]

    # A singleton never gets a mean node. Reject incompatible units and the
    # original bundled descriptor; no historical identity can name this node.
    for invalid in ({**node, "inputs": ["first"]}, {**node, "executor": builtin_executor()}):
        with pytest.raises(DocumentError) as error:
            execute_node(invalid, sources)
        assert error.value.reason_code == "transform_node_invalid"
    mismatched = deepcopy(sources)
    mismatched["second"]["columns"]["storage_modulus"]["unit"] = "MPa"
    with pytest.raises(DocumentError) as error:
        execute_node(node, mismatched)
    assert error.value.reason_code == "transform_sweep_columns_invalid"


def test_managed_exact_x_mean_rebuilds_from_its_originals_and_cache(tmp_path):
    import json

    from sciplot_core.foundation.file_hashing import file_sha256
    from sciplot_core.plot_engine.managed_sources import load_sources
    from sciplot_core.plot_ir import compile_document, create_managed_document
    from sciplot_core.plot_transforms import resolve_transforms
    from test_plot_ir import managed_example

    template, binding, _ = managed_example()
    for source, text in zip(binding["data_sources"], ("0,2\n1,\n2,4\n", "1,1\n2,2\n3,3\n"), strict=True):
        file = tmp_path / (source["source_id"] + ".csv")
        file.write_text("Time,Signal\ns,V\n" + text)
        source.update(path=str(file), sha256=file_sha256(file))
    kind = "rheology_mean_exact_x"
    mean = {"id": "aggregate", "kind": kind, "inputs": ["A-normalized", "B-normalized"], "output": "mean",
            "parameters": {"x_column": "column:0"}, "executor": builtin_executor(kind), "determinism": "deterministic"}
    # Backwards list order verifies graph scheduling, not execution order in the request.
    binding["transforms"].insert(0, mean)
    for axis in ("x", "y"):
        binding["slots"]["slot:A"][axis]["source_id"] = "mean"
    document = create_managed_document(template, binding, plot_id="mean-example")
    datasets = load_sources(document, "ordinary_xy")
    first = resolve_transforms(document, datasets)
    assert first["executed"] == ["normalize-A", "normalize-B", "aggregate"]
    first_ir = compile_document(first["document"])
    first_series = first_ir["series"][0]
    assert first_series["x"] == [0, 1, 2, 3]
    assert first_series["y"] == [.5, 1 / 3, (1 + 2 / 3) / 2, 1.]
    assert first["datasets"]["mean"]["provenance"]["transforms"][-1]["details"]["row_origins"][2] == [
        {"source_id": "A", "row": 4}, {"source_id": "B", "row": 3}]

    reopened = json.loads(json.dumps(first["document"]))
    second = resolve_transforms(reopened, load_sources(reopened, "ordinary_xy"))
    assert compile_document(second["document"]) == first_ir
    cached = resolve_transforms(reopened, load_sources(reopened, "ordinary_xy"), cache=first["cache"])
    assert cached["reused"] == first["executed"]
