"""Generated original instrument exports retain condition and coordinate identity."""
from copy import deepcopy
import hashlib
import math

import pytest


def instrument_source(path, *, temperatures=(210, 190, 170, 150), magnitude=False):
    rows = ["Project:\tGenerated public control", "", "Test:\tAnonymous material", ""]
    for index, temperature in enumerate(temperatures):
        rows += [f"Result:\tFS {temperature} °C", "", "Interval and data points:\t1\t16",
                 "Interval data:\tPoint No.\tTemperature\tAngular Frequency\tStorage Modulus\tLoss Modulus\tLoss Factor\tShear Strain\tShear Stress\tTorque\tStatus\t" + ("Complex Viscosity" if magnitude else "Im(Complex Viscosity)"),
                 "\t\t\t\t\t\t\t\t\t\t\t", "\t\t[°C]\t[rad/s]\t[Pa]\t[Pa]\t[1]\t[%]\t[Pa]\t[mN·m]\t\t[mPa·s]"]
        for point in range(16):
            frequency = 100 / (point + 1)
            storage, loss = 500 - 100 * index + point, 30 + point
            observed = math.hypot(storage, loss) / frequency * 1000 if magnitude else storage / frequency * 1000
            rows.append(f"\t{point + 1}\t{temperature + .3 + point / 100}\t{frequency}\t{storage}\t{loss}\t{loss/storage}\t1\t5\t0.2\tTruStrain\t{observed}")
        rows.append("")
    path.write_text("\n".join(rows), encoding="utf-16")
    return path


def intent():
    return {"x": {"quantity": "angular_frequency", "unit": "rad/s"},
            "y": {"quantity": "complex_viscosity", "unit": "Pa s"}, "rule_id": "rheology_frequency_sweep"}


def test_default_frequency_keeps_each_result_condition_and_original_rows(tmp_path):
    from sciplot_core.semantic_sources.rheology_sweep_sources import _read_rheology_frequency_comparison_samples
    from sciplot_core.semantic_sources.preparation_support import _rheology_unit_conversion_inventory

    source = instrument_source(tmp_path / "anonymous.csv")
    before = source.read_bytes()
    samples = _read_rheology_frequency_comparison_samples(source)
    assert [sample.sample for sample in samples] == [f"Anonymous material · {temperature} °C" for temperature in (210, 190, 170, 150)]
    assert [len(sample.rows) for sample in samples] == [16] * 4
    for index, sample in enumerate(samples):
        assert [row["x"] for row in sample.rows] == [100 / (point + 1) for point in range(16)]
        assert [row["storage_modulus"] for row in sample.rows] == [500 - 100 * index + point for point in range(16)]
        assert sample.source == source
        assert sample.source_interval["nominal_temperature"] == (210, 190, 170, 150)[index]
        assert sample.source_interval["point_count"] == 16
        assert sample.source_interval["sample"] == "Anonymous material"
    assert all(item["source_interval"]["data_end_row"] - item["source_interval"]["data_start_row"] == 16
               for item in _rheology_unit_conversion_inventory(samples))
    assert source.read_bytes() == before


@pytest.mark.parametrize("magnitude", [False, True])
def test_explicit_frequency_intent_binds_original_intervals_and_magnitude(tmp_path, magnitude):
    from sciplot_core.task_semantic_plan import prepare_plan
    from sciplot_core.task_semantic_creation import build_managed_request as build_request
    from sciplot_core.plot_engine.contracts import validate_create
    from sciplot_core.plot_engine.managed_sources import load_sources
    from sciplot_core.plot_ir import create_managed_document
    from sciplot_core.plot_transforms import resolve_transforms

    source = instrument_source(tmp_path / "source.csv", magnitude=magnitude)
    original = source.read_bytes()
    value = intent()
    plan = prepare_plan([source], value)
    assert plan["decisions"] == []
    candidate = plan["sources"][0]["candidates"][0]
    assert candidate["format"] == "rheology_frequency_intervals"
    assert [block["point_count"] for block in candidate["blocks"]] == [16] * 4
    assert candidate["columns"][3]["header"] == "Angular Frequency"
    assert candidate["columns"][3]["unit"] == "[rad/s]"
    assert candidate["columns"][11]["quantity"] == ("complex_viscosity" if magnitude else "imaginary_complex_viscosity")
    state = {"request": {"intent": value}, "semantic_plan": plan, "semantic_choices": {},
             "intent_revision": 1, "task_dir": str(tmp_path / "task")}
    wire = validate_create(build_request(state))
    document = create_managed_document(wire["template_definition"], wire["data_binding"], plot_id="public-control")
    assert document["plot_type"] == "ManagedPlot"
    sources = document["scientific"]["data_sources"]
    assert len(sources) == 4 and all(item["sha256"] == hashlib.sha256(original).hexdigest() for item in sources)
    bound = load_sources(document, value["rule_id"])
    assert all("column:10" not in dataset["columns"] for dataset in bound.values())  # text Status unselected
    resolved = resolve_transforms(document, bound)
    spec = wire["template_definition"]["figure_spec"]
    layers = spec["views"][0]["layers"]
    assert [scale["transform"] for scale in spec["scales"]] == ["log", "log"]
    assert spec["views"][0]["axes"][0]["label"] == "ω (rad s⁻¹)"
    assert spec["views"][0]["axes"][1]["label"] == "|η*| (Pa s)"
    assert [layer["legend"]["label"] for layer in layers] == [f"Anonymous material · {temperature} °C" for temperature in (210, 190, 170, 150)]
    assert {slot["sample"] for slot in wire["data_binding"]["slots"].values()} == {"Anonymous material"}
    for index, layer in enumerate(layers):
        dataset = resolved["datasets"][layer["dataset_id"]]
        assert dataset["columns"]["x"]["values"] == [100 / (point + 1) for point in range(16)]
        assert dataset["columns"]["y"]["values"] == pytest.approx([
            math.hypot(500 - 100 * index + point, 30 + point) / (100 / (point + 1)) for point in range(16)])
        assert len(dataset["provenance"]["sources"][0]["rows"]) == 16
        steps = dataset["provenance"]["transforms"]
        assert any(step["details"].get("method") == "derived_from_storage_and_loss_modulus" for step in steps) is (not magnitude)
    assert source.read_bytes() == original


def test_imaginary_component_cannot_be_selected_as_magnitude_by_exact_header(tmp_path):
    from sciplot_core.task_semantic_plan import prepare_plan
    from sciplot_core.task_errors import TaskControlError

    source = instrument_source(tmp_path / "source.csv")
    value = intent()
    value["y"]["header"] = "Im(Complex Viscosity)"
    with pytest.raises(TaskControlError) as rejected:
        prepare_plan([source], value)
    assert rejected.value.reason_code == "semantic_coordinate_mapping_required"


def test_managed_text_source_requires_exclusively_formal_selected_columns(tmp_path):
    from sciplot_core.task_semantic_plan import prepare_plan
    from sciplot_core.task_semantic_creation import build_managed_request as build_request
    from sciplot_core.plot_ir import create_managed_document
    from sciplot_core.plot_engine.managed_sources import load_sources
    from sciplot_core.plot_engine.errors import EngineError

    source = instrument_source(tmp_path / "source.csv", temperatures=(190,), magnitude=True)
    value = intent()
    plan = prepare_plan([source], value)
    wire = build_request({"request": {"intent": value}, "semantic_plan": plan, "semantic_choices": {},
                          "intent_revision": 1, "task_dir": str(tmp_path / "task")})
    document = create_managed_document(wire["template_definition"], wire["data_binding"], plot_id="control")
    first = document["scientific"]["transforms"][0]
    for mutation in ("text_selected", "nonselect_consumer", "direct_mapping"):
        changed = deepcopy(document)
        if mutation == "text_selected":
            changed["scientific"]["transforms"][0]["parameters"]["columns"].append("column:10")
        elif mutation == "nonselect_consumer":
            changed["scientific"]["transforms"].append({**first, "id": "bypass", "output": "bypass", "kind": "scale", "parameters": {"columns": ["column:3"], "factor": 1}})
        else:
            changed["scientific"]["mappings"]["direct"] = {"x": {"source_id": first["inputs"][0]}, "y": {"source_id": first["inputs"][0]}}
        with pytest.raises(EngineError) as rejected:
            load_sources(changed, value["rule_id"])
        assert rejected.value.reason_code == "managed_source_nonnumeric"


@pytest.mark.parametrize("invalid_unit", ["", "kg"])
def test_derived_magnitude_checks_units_even_when_every_input_is_missing(invalid_unit):
    from sciplot_core.plot_transforms import builtin_executor, execute_node
    from sciplot_core.plot_document import DocumentError

    source = {"id": "raw", "columns": {"frequency": {"label": "Angular Frequency", "unit": "rad/s", "values": [None]},
              "storage": {"label": "Storage Modulus", "unit": invalid_unit, "values": [None]},
              "loss": {"label": "Loss Modulus", "unit": "Pa", "values": [None]}},
              "provenance": {"sources": [{"source_id": "raw", "sha256": "0" * 64,
                  "table_selection": {"sheet": None, "header_rows": [0], "data_start_row": 1, "data_end_row": 2},
                  "column_indices": {"frequency": 0, "storage": 1, "loss": 2}, "rows": [1]}], "transforms": []}}
    node = {"id": "derive", "kind": "rheology_complex_viscosity", "inputs": ["raw"], "output": "derived",
            "parameters": {"frequency_column": "frequency", "storage_column": "storage", "loss_column": "loss", "output_column": "magnitude", "output_unit": "Pa s"},
            "executor": builtin_executor(), "determinism": "deterministic"}
    with pytest.raises(DocumentError) as rejected:
        execute_node(node, {"raw": source})
    assert rejected.value.reason_code == "transform_rheology_invalid"
    source["columns"]["storage"]["unit"] = "Pa"
    derived, _key = execute_node(node, {"raw": source})
    assert derived["columns"]["magnitude"]["values"] == [None]


def test_multiple_original_test_names_are_not_relabelled_as_first_sample(tmp_path):
    from sciplot_core.task_semantic_plan import prepare_plan

    first = instrument_source(tmp_path / "first.csv", temperatures=(190,))
    second = instrument_source(tmp_path / "second.csv", temperatures=(150,))
    content = first.read_text(encoding="utf-16") + "\n" + second.read_text(encoding="utf-16").replace("Anonymous material", "Second original material")
    source = tmp_path / "combined.csv"
    source.write_text(content, encoding="utf-16")
    plan = prepare_plan([source], intent())
    blocks = plan["sources"][0]["candidates"][0]["blocks"]
    assert [block["sample"] for block in blocks] == ["Anonymous material", "Second original material"]
    assert [block["label"] for block in blocks] == ["Anonymous material · 190 °C", "Second original material · 150 °C"]
    assert [block["point_count"] for block in blocks] == [16, 16]


def test_mixed_known_and_unknown_result_conditions_are_not_merged(tmp_path):
    from sciplot_core.semantic_sources.rheology_sweep_sources import _read_rheology_frequency_comparison_samples

    source = instrument_source(tmp_path / "source.csv", temperatures=(190, 150))
    source.write_text(source.read_text(encoding="utf-16").replace("FS 150 °C", "Unspecified condition"), encoding="utf-16")
    with pytest.raises(ValueError, match="Mixed frequency Result metadata"):
        _read_rheology_frequency_comparison_samples(source)


def test_frequency_axis_unit_and_nonpositive_values_remain_explicit():
    from sciplot_core.task_semantic_frequency import frequency_axis
    from sciplot_core.task_errors import TaskControlError

    domain, _ticks, label, scale = frequency_axis("x", {"quantity": "angular_frequency"}, "Hz", [1, 10])
    assert label == "f (Hz)" and scale == "log" and domain[0] > 0
    with pytest.raises(TaskControlError) as rejected:
        frequency_axis("x", {"quantity": "angular_frequency"}, "rad/s", [0, 10])
    assert rejected.value.reason_code == "semantic_frequency_log_domain"
