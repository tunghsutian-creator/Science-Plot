"""A raw replicate with no G″ still contributes its measured frequency grid."""
from copy import deepcopy
import csv
from pathlib import Path

import pytest

from sciplot_core.plot_engine.managed_sources import load_sources
from sciplot_core.plot_ir import compile_document, create_managed_document
from sciplot_core.plot_transforms import resolve_transforms
from sciplot_core.task_semantic_creation import build_managed_request
from sciplot_core.task_semantic_plan import prepare_plan
from sciplot_core.semantic import prepare_semantic_source
from sciplot_core.semantic_sources.scientific_source import resolve_scientific_source
from sciplot_core.source_inspection.semantic_evidence import inspect_semantic_tables
from sciplot_core.workflow.frequency_managed_grouping import resolve_mean_group_blocks
from sciplot_core.workflow.frequency_managed_metrics import prepare_frequency_metric_group
from sciplot_core.workflow.rheology_bundle import _sweep_metric_sources
from test_frequency_interval_binding import instrument_source, intent


def test_sparse_measured_replicate_keeps_union_x_without_fabricating_loss_column(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    first = instrument_source(raw / "A.csv", temperatures=(210, 150), magnitude=True)
    second = instrument_source(raw / "B.csv", temperatures=(210, 150), magnitude=True)
    lines = second.read_text(encoding="utf-16").splitlines()
    for index, line in enumerate(lines):
        cells = line.split("\t")
        if len(cells) > 11 and cells[1] == "16":
            cells[3] = "0.5"
            lines[index] = "\t".join(cells)
    second.write_text("\n".join(lines).replace("Loss Modulus", "Unrelated Response"), encoding="utf-16")
    original = [path.read_bytes() for path in (first, second)]
    rule = "rheology_frequency_sweep"
    resolved = resolve_scientific_source(raw, rule_id=rule, template="point_line", request={})
    assert resolved is not None and resolved.figure_plan is not None
    domain, plan = resolved.domain, resolved.figure_plan
    observed = []
    for index, path in enumerate((first, second)):
        value = inspect_semantic_tables(path, rule_id=rule)
        observed.append({"path": str(path), "source_id": f"source:{index}", **value})
    groups = resolve_mean_group_blocks(domain, plan, observed)
    wanted = "Anonymous material · 210 °C"
    replicates = []
    for physical in groups[wanted]:
        source = next(row for row in observed if row["path"] == physical["path"])
        table = next(row for row in source["candidates"] if row["candidate_id"] == physical["table_id"])
        block = next(row for row in table["blocks"] if row["block_id"] == physical["block_id"])
        sample = next(item for item in domain.raw_samples if str(item.source) == physical["path"] and item.sample == wanted)
        replicates.append((sample, physical, block["columns"]))
    assert "loss_modulus" not in replicates[1][0].metric_units
    nodes = []
    bindings, final = prepare_frequency_metric_group(replicates, metric="loss_modulus", transforms=nodes)
    value = {**intent(), "y": {"quantity": "loss_modulus", "unit": "Pa"}}
    hints = prepare_plan([first], value)
    request = build_managed_request({"request": {"intent": value}, "semantic_plan": hints,
        "semantic_choices": {}, "intent_revision": 1, "task_dir": str(tmp_path / "task")})
    template, binding = request["template_definition"], request["data_binding"]
    view = template["figure_spec"]["views"][0]
    layer = next(item for item in view["layers"] if item["label"] == wanted)
    layer.update(dataset_id=final, mappings={"x": "x", "y": "loss_modulus"})
    view["layers"] = [layer]
    slot = binding["slots"][layer["id"]]
    slot["x"].update(source_id=final, column="x")
    slot["y"].update(source_id=final, column="loss_modulus")
    binding.update(data_sources=bindings, transforms=nodes, slots={layer["id"]: slot})
    document = create_managed_document(template, binding, plot_id="generated-sparse")
    execution = resolve_transforms(document, load_sources(document, rule))
    values = execution["datasets"]
    ir = compile_document(execution["document"])
    columns = ir["datasets"][final]["columns"]
    assert columns["x"]["values"][0] == 0.5 and columns["loss_modulus"]["values"][0] is None
    assert all(values[item]["columns"].get("loss_modulus") is None for item in nodes[-1]["inputs"][1:])
    legacy = domain.prepared_samples[0]
    assert columns["x"]["values"] == [row["x"] for row in legacy.rows]
    assert columns["loss_modulus"]["values"] == [row.get("loss_modulus") for row in legacy.rows]
    assert values[final]["provenance"]["transforms"][-1]["details"]["contributor_counts"]["loss_modulus"][0] == 0

    semantic = {"rule_id": rule, "semantic_family": "rheology_frequency", "axis_plan": {"y": {"canonical_unit": "Pa"}}}
    prepared = prepare_semantic_source(raw, output_dir=tmp_path / "prepared", semantic=semantic,
                                       resolved_scientific_source=resolved)
    tasks = _sweep_metric_sources(Path(prepared["processed_source"]), output_dir=tmp_path / "terminal",
        request={"rule_id": rule, "template": "point_line", "resolved_figure_plan": plan.to_payload()})
    output = next(path for stem, path, _ in tasks if stem == "freq_loss_modulus")
    with output.open(newline="", encoding="utf-8") as stream:
        assert list(csv.reader(stream))[3][:2] == ["0.5", ""]
    with pytest.raises(ValueError, match="available measured or derived metric"):
        prepare_frequency_metric_group(replicates[1:], metric="loss_modulus", transforms=[])
    assert [path.read_bytes() for path in (first, second)] == original


def test_frequency_graph_preserves_reported_magnitude_and_derives_before_averaging(tmp_path):
    import math

    from sciplot_core.plot_transforms import execute_node

    raw = tmp_path / "raw"
    raw.mkdir()
    first = instrument_source(raw / "A.csv", temperatures=(210, 150))
    second = instrument_source(raw / "B.csv", temperatures=(210, 150))
    third = instrument_source(raw / "C.csv", temperatures=(210, 150), magnitude=True)
    reported = third.read_text(encoding="utf-16").splitlines()
    for index, line in enumerate(reported):
        cells = line.split("\t")
        if len(cells) > 11 and cells[1] == "1":
            cells[11] = ""
            reported[index] = "\t".join(cells)
    third.write_text("\n".join(reported), encoding="utf-16")
    # In B the magnitude is independently measured, not the hypot of G′/G″.
    rows = second.read_text(encoding="utf-16").splitlines()
    for index, line in enumerate(rows):
        if "Torque" in line:
            rows[index] = line.replace("Torque", "Complex Modulus")
        elif "[mN·m]" in line:
            rows[index] = line.replace("[mN·m]", "[Pa]")
        else:
            cells = line.split("\t")
            if len(cells) > 11 and cells[1].isdigit():
                cells[9] = "1000"
                rows[index] = "\t".join(cells)
    second.write_text("\n".join(rows), encoding="utf-16")
    rule = "rheology_frequency_sweep"
    resolved = resolve_scientific_source(raw, rule_id=rule, template="point_line", request={})
    assert resolved is not None and resolved.figure_plan is not None
    domain, plan = resolved.domain, resolved.figure_plan
    sources = [{"path": str(path), "source_id": f"source:{index}", **inspect_semantic_tables(path, rule_id=rule)}
               for index, path in enumerate((first, second, third))]
    groups = resolve_mean_group_blocks(domain, plan, sources)
    name = "Anonymous material · 210 °C"
    replicates = []
    for physical in groups[name]:
        source = next(item for item in sources if item["path"] == physical["path"])
        [candidate] = source["candidates"]
        block = next(item for item in candidate["blocks"] if item["block_id"] == physical["block_id"])
        observed = next(sample for sample in domain.raw_samples if str(sample.source) == physical["path"] and sample.sample == name)
        replicates.append((observed, physical, block["columns"]))
    graph = []
    bindings, final = prepare_frequency_metric_group(replicates, metric="complex_modulus", transforms=graph)
    datasets = load_sources({"scientific": {"data_sources": bindings, "mappings": {}, "transforms": graph}}, rule)
    for node in graph:
        datasets[node["output"]], _ = execute_node(node, datasets)
    actual = datasets[final]["columns"]
    old = domain.prepared_samples[0]
    for metric, unit in (("complex_modulus", "Pa"), ("complex_viscosity", "mPa·s")):
        assert actual[metric]["unit"] == unit
        assert actual[metric]["values"] == [row[metric] for row in old.rows]
    assert actual["complex_modulus"]["values"][-1] == (2 * math.hypot(500, 30) + 1000.) / 3
    complete = [step for step in graph if step["kind"] == "rheology_frequency_complete"]
    assert [node["parameters"]["derivations"] for node in complete] == [
        ["complex_modulus", "complex_viscosity"], ["complex_viscosity"], ["complex_modulus"]]
    assert datasets[complete[2]["output"]]["columns"]["complex_viscosity"]["values"][0] is None
    assert datasets[final]["provenance"]["transforms"][-1]["details"]["contributor_counts"]["complex_viscosity"][-1] == 2
    invalid = deepcopy(datasets[complete[1]["inputs"][0]])
    invalid["columns"]["complex_modulus"]["values"][0] = None
    with pytest.raises(ValueError, match="requires.*modulus|needs measured or derived modulus"):
        execute_node(complete[1], {invalid["id"]: invalid})
    clobber = {**complete[1], "parameters": {"derivations": ["complex_modulus"]}}
    with pytest.raises(ValueError, match="Do not overwrite"):
        source = datasets[clobber["inputs"][0]]
        execute_node(clobber, {source["id"]: source})
