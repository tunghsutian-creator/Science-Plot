"""Public generated DMA control through the explicit Managed entrypoint."""
import math
from pathlib import Path

import pytest


@pytest.mark.comprehensive
def test_dma_managed_composes_canonical_pressure_steps_without_clipping_observations(tmp_path):
    import pymupdf

    from sciplot_core.plot_backends.managed import ManagedVeuszCompiler
    from sciplot_core.plot_engine.service import PlotService
    from sciplot_core.plot_engine.storage import load_head, read
    from sciplot_core.semantic_sources.dma_temperature_transform import resolve_dma_temperature_transform
    from sciplot_core.task_semantic_creation import build_managed_request
    from sciplot_core.task_semantic_plan import prepare_plan

    source = tmp_path / "Sample A.csv"
    source.write_text("Temperature (K),Sample A Storage Modulus (kPa)\n"
                      "273.15,1000\n283.15,-5\n293.15,570\n")
    original = source.read_bytes()
    old = resolve_dma_temperature_transform(source).series[0]
    intent = {
        "rule_id": "dma_temperature_sweep",
        "x": {"quantity": "temperature", "header": "Temperature (K)", "unit": "°C"},
        "y": {"quantity": "storage_modulus", "header": "Sample A Storage Modulus (kPa)", "unit": "MPa"},
    }
    plan = prepare_plan([source], intent)
    assert not plan["decisions"]
    managed = build_managed_request({"request": {"intent": intent}, "semantic_plan": plan,
                                     "semantic_choices": {}, "intent_revision": 1, "task_dir": str(tmp_path / "task")})
    binding = managed["data_binding"]
    steps = [item["parameters"] for item in binding["transforms"] if item["kind"] == "convert_unit"]
    assert [(step["from_unit"], step["to_unit"]) for step in steps] == [("K", "°C"), ("kPa", "Pa"), ("Pa", "MPa")]
    service = PlotService()
    compiler = ManagedVeuszCompiler(warm=False)
    try:
        result = service.create(managed)
        assert result["ready_to_use"], result
        head = load_head(Path(result["plot"]))
        ir = read(Path(head["binding"]["ir_path"]))
        layer = ir["views"][0]["layers"][0]
        assert all(scale["transform"] == "linear" for scale in ir["scales"])
        y_scale = next(scale for scale in ir["scales"] if scale["dimension"] == "y")
        assert y_scale["domain"][0] < -.005
        assert ir["guides"][0]["entries"][0]["label"] == old.sample
        columns = ir["datasets"][layer["dataset_id"]]["columns"]
        assert (columns["x"]["unit"], columns["y"]["unit"]) == (old.x_unit, old.y_unit) == ("°C", "MPa")
        assert columns["x"]["values"] == [temperature for temperature, _ in old.points]
        assert columns["y"]["values"] == [value * 1000. * 1e-6 for value in (1000., -5., 570.)]
        # The native DMA reader multiplies by the composed factor once;
        # the two sealed Managed steps round independently at canonical Pa.
        for value, (_, native_value) in zip(columns["y"]["values"], old.points, strict=True):
            assert abs(value - native_value) <= math.ulp(native_value)
        assert min(columns["y"]["values"]) == -.005
        assert compiler.audit_ir(ir, Path(head["binding"]["document"]))["status"] == "passed"
        with pymupdf.open(next(p["path"] for p in result["exports"] if p["format"] == "pdf")) as pdf:
            assert pdf[0].get_drawings()
    finally:
        compiler.close()
        service.close()
    assert source.read_bytes() == original
