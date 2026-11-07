"""One governed admission preserves the saved plan and the full compiler contract."""

from copy import deepcopy
import json

import pytest

from sciplot_core import rheology_tts_spec as compiler
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.rheology_tts_style import prepare_tts_presentation


def _raw():
    return {"version": 1,
        "source_binding": {"sources": [{"path": "/generated/source.csv", "sha256": "a" * 64}],
                           "prepared_plan": {"path": "/generated/plan.json", "sha256": "b" * 64}},
        "transform_ledger": {"owner": "generated control", "operation": "supplied coordinates"},
        "figures": [{"id": "Supplied", "panels": [{"id": "a", "x_label": "x", "y_label": "y",
            "xscale": "log", "yscale": "log",
            "reference_lines": [{"axis": "y", "value": 10}],
            "series": [{"role": "measured_curve", "label": "duplicate", "color_index": 1,
                        "x": [3.0000000000000004, .125, 2, .125],
                        "y": [7.000000000000001, 5.25, 8.5, 6.75],
                        "error_values": [0, .1, .2, .3]}]}]}]}


def test_single_admission_preserves_complete_normalized_and_compiled_values(monkeypatch):
    raw = _raw()
    original = deepcopy(raw)
    expected_plan = prepare_tts_presentation(raw)
    expected_compiled = compiler.compile_tts_spec(expected_plan)
    seen = []
    actual_prepare = compiler.prepare_tts_presentation

    def prepare(value):
        seen.append(value)
        return actual_prepare(value)

    monkeypatch.setattr(compiler, "prepare_tts_presentation", prepare)
    normalized, compiled = compiler.prepare_and_compile_tts_spec(raw)
    assert seen == [raw]
    assert normalized == expected_plan and compiled == expected_compiled
    assert raw == original
    assert normalized["source_binding"] == compiled["source_binding"] == raw["source_binding"]
    assert normalized["transform_ledger"] == compiled["transform_ledger"] == raw["transform_ledger"]
    supplied = original["figures"][0]["panels"][0]["series"][0]
    series = compiled["figures"][0]["panels"][0]["series"][0]
    assert (series["x_values"], series["y_values"], series["error_values"]) == (
        supplied["x"], supplied["y"], supplied["error_values"])
    raw["figures"][0]["panels"][0]["series"][0]["y"][0] = 999
    raw["source_binding"]["sources"][0]["sha256"] = "c" * 64
    assert normalized == expected_plan and compiled == expected_compiled


@pytest.mark.parametrize("case", ["role", "style", "policy", "nonfinite", "ragged", "log_zero",
                                  "error_length", "negative_error", "bool_error", "rectangle", "version"])
def test_single_admission_keeps_governed_and_numeric_refusals(case):
    raw = _raw()
    panel = raw["figures"][0]["panels"][0]
    series = panel["series"][0]
    if case == "role":
        series["role"] = "invented"
    elif case == "style":
        series["marker"] = "none"
    elif case == "policy":
        raw["presentation_policy"] = {"kind": "invented"}
    elif case == "nonfinite":
        series["y"][0] = float("nan")
    elif case == "ragged":
        series["y"].append(9)
    elif case == "log_zero":
        series["x"][0] = 0
    elif case == "error_length":
        series["error_values"].append(.4)
    elif case == "negative_error":
        series["error_values"][0] = -1
    elif case == "bool_error":
        series["error_values"][0] = True
    elif case == "rectangle":
        panel["rect_mm"] = [1, 0, 60, 55]
    else:
        raw["version"] = 2
    with pytest.raises(ValueError):
        compiler.prepare_and_compile_tts_spec(raw)


def test_serialized_governed_plan_is_readmitted_after_mutation():
    normalized, _compiled = compiler.prepare_and_compile_tts_spec(_raw())
    external = json.loads(json.dumps(normalized))
    external["figures"][0]["panels"][0]["series"][0]["marker"] = "none"
    with pytest.raises(ValueError, match="raw fields are rejected"):
        compiler.compile_tts_spec(external)


def test_public_non_governed_compile_keeps_legacy_explicit_styles(monkeypatch):
    from test_rheology_tts_render import _spec

    def forbidden(_value):
        pytest.fail("Legacy explicit compilation unexpectedly entered governed preparation.")

    monkeypatch.setattr(compiler, "prepare_tts_presentation", forbidden)
    result = compiler.compile_tts_spec(_spec())
    assert "presentation_policy" not in result
    assert result["figures"][0]["panels"][0]["series"][0]["encoding"]["line"]["style"] == "dashed"


def test_prepared_workflow_binds_plan_then_prepares_once_before_creation(tmp_path, monkeypatch):
    from sciplot_core.workflow import rheology_tts_creation, rheology_tts_prepared

    source = tmp_path / "original.csv"
    source.write_text("x,y\n3,7\n.125,5.25\n2,8.5\n.125,6.75\n")
    raw = _raw()
    raw["source_binding"] = {"sources": [{"path": str(source), "sha256": file_sha256(source)}]}
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps(raw))
    request = tmp_path / "request.json"
    request.write_text(json.dumps({"version": 1, "prepared_plan": str(plan), "out": str(tmp_path / "Figures")}))
    original_bytes = source.read_bytes(), plan.read_bytes(), request.read_bytes()
    calls = []
    actual_prepare = compiler.prepare_tts_presentation

    def prepare(value):
        calls.append(deepcopy(value))
        return actual_prepare(value)

    def create(_path, _request, normalized, compiled, *_args, **_kwargs):
        assert len(calls) == 1
        binding = {"path": str(plan), "sha256": file_sha256(plan),
            "authority": "External AI processing; local plotting preserves the supplied numeric coordinates."}
        assert calls[0]["source_binding"]["prepared_plan"] == binding
        assert normalized["source_binding"]["prepared_plan"] == binding
        assert compiled["source_binding"] == normalized["source_binding"]
        assert "presentation_policy" in normalized and "template_id" in normalized["figures"][0]["panels"][0]
        return {"status": "ready", "scope": "pure admission prefix; native and publication are not executed"}

    monkeypatch.setattr(compiler, "prepare_tts_presentation", prepare)
    monkeypatch.setattr(rheology_tts_creation, "create_prepared_suite", create)
    result = rheology_tts_prepared.plot_prepared_suite.__wrapped__(request)
    assert result["status"] == "ready"
    assert (source.read_bytes(), plan.read_bytes(), request.read_bytes()) == original_bytes
    assert not (tmp_path / "Figures").exists() and not (tmp_path / ".sciplot").exists()
