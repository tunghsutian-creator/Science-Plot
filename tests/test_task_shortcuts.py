"""Typed entries remove transport chores without bypassing task review or guards."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from sciplot_core import task_shortcuts as shortcuts
from sciplot_core.cli.dispatch import tasks as dispatch
from sciplot_core.cli.parsers import build_parser
from sciplot_core.studio_core.annotation_schema import AnnotationOperationError
from sciplot_core.task_capabilities import task_capabilities
from sciplot_core.task_contract import TaskControlError
from sciplot_core.task_next_step import task_next_step


@pytest.fixture
def ready(monkeypatch):
    calls = []
    runtime = {"kind": "sciplot_doctor", "status": "ready",
               "checks": [{"status": "passed", "detail": "large readiness evidence"}]}
    monkeypatch.setattr(shortcuts, "doctor_payload", lambda: calls.append("doctor") or runtime)
    return calls, runtime


def test_create_retains_original_input_and_existing_question_without_invented_mapping(ready, monkeypatch):
    calls, _ = ready
    question = {"field": "column_mapping", "question_id": "a" * 64, "mapping_candidates": [{"id": "real cells"}]}
    result = {"kind": "sciplot_task", "status": "needs_input", "question": question}
    def start(request, *, task_dir, entry_intent=None, _prefer_managed=False):
        assert _prefer_managed
        calls.append((request, task_dir))
        return deepcopy(result)
    monkeypatch.setattr(shortcuts, "start_task", start)
    actual = shortcuts.create_task(Path("raw original.xlsx"), rule_id="uvvis_spectrum",
                                   template="curve", out=Path("/delivery"), task_dir=Path("/task"))
    assert calls == ["doctor", ({"version": 1, "action": "create", "source": "raw original.xlsx",
                                "rule_id": "uvvis_spectrum", "template": "curve", "out": "/delivery"}, Path("/task"))]
    assert actual == {**result, "doctor": {"kind": "sciplot_doctor", "status": "ready", "failed_checks": []}}


def test_create_preserves_profile_and_source_adjacent_default(ready, monkeypatch, tmp_path):
    requests = []
    monkeypatch.setattr(shortcuts, "start_task", lambda request, **kwargs: requests.append(request) or {"status": "complete"})
    shortcuts.create_task(Path("/original.csv"), profile=Path("/profile.json"))
    assert requests == [{"version": 1, "action": "create", "source": "/original.csv", "profile": "/profile.json"}]

    from sciplot_core.plan_preview import build_plan_preview
    from sciplot_core.task_semantic_creation import admit_raw_curve, build_managed_request

    raw = tmp_path / "UVvis.csv"
    original = b"Wavelength,Absorbance\nnm,a.u.\nSample A,Sample A\n400,1.5\n460,3.25\n500,-1\n"
    raw.write_bytes(original)
    plan = build_plan_preview(raw, request={"rule_id": "uvvis_spectrum"})
    request = {"version": 1, "action": "create", "source": str(raw)}
    candidate = {"request": request, "source_sha256": plan["preview_identity"]["source_tree_sha256"],
                 "task_dir": str(tmp_path / "task")}
    unmigrated = deepcopy(candidate)
    unmigrated["request"]["profile"] = "/existing/presentation-profile.json"
    assert not admit_raw_curve(unmigrated, plan)
    assert unmigrated["request"]["source"] == str(raw) and "intent" not in unmigrated["request"]
    assert admit_raw_curve(candidate, plan)
    assert candidate["initial_request"] == request
    assert candidate["plan_confirmation"]["figure_plan"] == plan["resolved_figure_plan"]["plan_sha256"]
    compiled = build_managed_request(candidate)
    binding = compiled["data_binding"]
    assert binding["data_sources"][0]["path"] == str(raw)
    assert {item["kind"] for item in binding["transforms"]} == {"select", "row_slice", "rename"}
    slot, = binding["slots"].values()
    assert (slot["sample"], slot["x_unit"], slot["y_unit"]) == ("Sample A", "nm", "a.u.")
    layer = compiled["template_definition"]["figure_spec"]["views"][0]["layers"][0]
    assert [mark["type"] for mark in layer["marks"]] == ["line"]

    from sciplot_core.plot_engine.managed_sources import load_sources
    from sciplot_core.plot_ir import create_managed_document
    from sciplot_core.plot_transforms import execute_node

    document = create_managed_document(compiled["template_definition"], binding, plot_id="uvvis-default")
    sources = load_sources(document, "uvvis_spectrum")
    for node in binding["transforms"]:
        sources[node["output"]], _ = execute_node(node, sources)
    values = sources[slot["x"]["source_id"]]["columns"]
    assert values["x"]["values"] == [400.0, 460.0, 500.0]
    assert values["y"]["values"] == [1.5, 3.25, -1.0]
    assert raw.read_bytes() == original
    assert [(row["metric"], row["value"], row["unit"]) for row in candidate["analysis_metrics"]] == [
        ("strongest_absorbance_wavelength_nm", 460, "nm")]

    for family, header, units, expected_labels, expected_scales, width in (
        ("dsc_curve", "Temperature,Heat flow", "C,W/g", ["Temperature (°C)", "Heat flow (W g⁻¹)"], ["linear", "linear"], 60),
        ("tga_curve", "Temperature,Mass", "C,%", ["Temperature (°C)", "Mass (%)"], ["linear", "linear"], 60),
        ("saxs_profile", "q,Intensity", "nm^-1,a.u.", ["q (nm⁻¹)", "Log intensity (a.u.)"], ["linear", "log"], 120),
        ("dtg_curve", "Temperature,Derivative mass", "C,%/C", ["Temperature (°C)", "DTG (% °C⁻¹)"], ["linear", "linear"], 60),
        ("xrd_pattern", "2theta,Intensity", "degree,a.u.", ["Diffraction angle (°)", "Intensity (a.u.)"], ["linear", "linear"], 60),
    ):
        path = tmp_path / (family + ".csv")
        points = "30,100\n100,94\n150,89\n" if family == "tga_curve" else "1,3\n2,6\n3,4\n"
        path.write_text(f"{header}\n{units}\nA,A\n" + points)
        plan = build_plan_preview(path, request={"rule_id": family})
        candidate = {"request": {**request, "source": str(path)}, "task_dir": str(tmp_path / family),
                     "source_sha256": plan["preview_identity"]["source_tree_sha256"]}
        assert admit_raw_curve(candidate, plan)
        built = build_managed_request(candidate)
        figure = built["template_definition"]["figure_spec"]
        assert [axis["label"] for axis in figure["views"][0]["axes"]] == expected_labels
        assert [scale["transform"] for scale in figure["scales"]] == expected_scales
        assert [scale["unit"] for scale in figure["scales"]] == units.split(",")
        assert figure["layout"] == {"width_mm": width, "height_mm": 55}
        reported = {row["metric"]: row for row in candidate["analysis_metrics"]}
        assert all(row["status"] == "ok" for row in reported.values())
        if family == "tga_curve":
            assert {key: (row["value"], row["unit"]) for key, row in reported.items()} == {
                "residual_mass_percent": (89, "%"), "t5_temperature_C": (100, "°C"), "t10_temperature_C": (150, "°C")}
        elif family == "dsc_curve":
            assert {key: row["value"] for key, row in reported.items()} == {
                "maximum_absolute_heat_flow_slope_temperature_C": 1, "maximum_absolute_heat_flow_temperature_C": 2}
            assert all("identity is assigned" in row["reason"] for row in reported.values())
        else:
            expected_metric = {"saxs_profile": "main_scattering_peak_q", "dtg_curve": "dtg_peak_temperature_C",
                               "xrd_pattern": "main_peak_2theta"}[family]
            assert reported[expected_metric]["value"] == 2
        if family == "xrd_pattern":
            unsigned = built
            assert [scale["domain"][0] for scale in figure["scales"]] == [0, 0]
            axis = figure["views"][0]["axes"][1]
            assert axis["visible"] and axis["label_visible"] and axis["ticks_mode"] == "fixed"
            assert not axis["ticks"] and axis["style"]["minor_ticks_visible"] is False

    for response, unit, values, expected_label, extremum in (
        ("Transmittance", "%", [90, 66, 92], "Transmittance (%)", "minimum"),
        ("Absorbance", "a.u.", [.10, .8, .5], "Absorbance (a.u.)", "maximum"),
        ("Spectral response", "a.u.", [.10, .8, .5], None, None),
    ):
        spectrum = tmp_path / (response + ".csv")
        x_values = [1500, 400, 1000]  # Descending display is not sorted source data.
        original = (f"Wavenumber,{response}\ncm^-1,{unit}\nA,A\n"
                    + "".join(f"{x},{y}\n" for x, y in zip(x_values, values, strict=True))).encode()
        spectrum.write_bytes(original)
        plan = build_plan_preview(spectrum, request={"rule_id": "ftir_spectrum"})
        state = {"request": {**request, "source": str(spectrum)}, "task_dir": str(tmp_path / response),
                 "source_sha256": plan["preview_identity"]["source_tree_sha256"]}
        assert admit_raw_curve(state, plan) == (expected_label is not None)
        if expected_label is None:
            assert state["request"]["source"] == str(spectrum)
            continue
        result = build_managed_request(state)
        spec = result["template_definition"]["figure_spec"]
        x, y = spec["scales"]
        assert (x["direction"], x["unit"]) == ("descending", "cm^-1")
        assert (y["quantity"], y["unit"]) == (response.lower(), unit)
        assert spec["views"][0]["axes"][1]["label"] == expected_label
        assert spec["layout"] == {"width_mm": 120, "height_mm": 55}
        metric, = state["analysis_metrics"]
        assert (metric["metric"], metric["value"], metric["unit"], metric["status"]) == (
            "observed_response_extremum_wavenumber_cm-1", 400., "cm⁻¹", "ok")
        assert extremum in metric["reason"] and "no spectral-band or chemical assignment" in metric["reason"]
        binding = result["data_binding"]
        doc = create_managed_document(result["template_definition"], binding, plot_id="ftir-original")
        data = load_sources(doc, "ftir_spectrum")
        for node in binding["transforms"]:
            data[node["output"]], _ = execute_node(node, data)
        coordinate = data[next(iter(binding["slots"].values()))["x"]["source_id"]]["columns"]
        assert coordinate["x"]["values"] == x_values and coordinate["y"]["values"] == values
        assert spectrum.read_bytes() == original

    multi = tmp_path / "FTIR-stack.csv"
    raw_stack = (b"Wavenumber,Transmittance,Wavenumber,Transmittance\ncm^-1,%,cm^-1,%\nA,A,B,B\n"
                 b"1500,90,1300,10\n400,66,500,13\n1000,92,1100,11\n")
    multi.write_bytes(raw_stack)
    plan = build_plan_preview(multi, request={"rule_id": "ftir_spectrum"})
    stack_state = {"request": {**request, "source": str(multi)}, "task_dir": str(tmp_path / "multi-task"),
                   "source_sha256": plan["preview_identity"]["source_tree_sha256"]}
    assert admit_raw_curve(stack_state, plan)
    result = build_managed_request(stack_state)
    spec = result["template_definition"]["figure_spec"]
    assert spec["layout"] == {"width_mm": 120, "height_mm": 110}
    assert spec["scales"][0]["direction"] == "descending"
    assert not spec["views"][0]["axes"][1]["ticks"]
    assert [layer["label"] for layer in spec["views"][0]["layers"]] == ["A", "B"]
    assert spec["views"][0]["axes"][0]["ticks"] == [1500, 1000, 500]
    assert [(row["metric"][-3:], row["value"]) for row in stack_state["analysis_metrics"]] == [("[A]", 400), ("[B]", 1300)]
    from sciplot_core.plot_grammar import compile_figure
    from sciplot_core.plot_grammar.current_view import resolve_current_view

    binding = result["data_binding"]
    doc = create_managed_document(result["template_definition"], binding, plot_id="ftir-stack")
    data = load_sources(doc, "ftir_spectrum")
    for node in binding["transforms"]:
        data[node["output"]], _ = execute_node(node, data)
    ir = compile_figure(spec, data, scientific_hash="0" * 64, presentation_hash="0" * 64)
    assert [label["text"] for label in ir["annotations"]] == ["A", "B"]
    a, b = spec["views"][0]["layers"]
    assert data[a["dataset_id"]]["columns"]["y"]["values"] == [90, 66, 92]
    assert data[b["dataset_id"]]["columns"]["y"]["values"] == [10, 13, 11]
    display_a = a["marks"][0]["id"]
    assert ir["display_curves"][display_a]["curve"]["y"] == [26.548000000000002, 2.5480000000000005, 28.548000000000002]
    changed = deepcopy(data)
    changed[b["dataset_id"]]["columns"]["y"]["values"][1] = 93
    new_spec = resolve_current_view(spec, changed)
    refreshed = compile_figure(new_spec, changed, scientific_hash="0" * 64, presentation_hash="0" * 64)
    assert refreshed["display_curves"][display_a]["curve"] != ir["display_curves"][display_a]["curve"]
    assert refreshed["display_curves"][display_a]["input_numeric_hash"] == ir["display_curves"][display_a]["input_numeric_hash"]
    assert refreshed["display_curves"][display_a]["stack_input_hash"] != ir["display_curves"][display_a]["stack_input_hash"]
    assert multi.read_bytes() == raw_stack

    gpc = tmp_path / "gpc.csv"
    chromatogram = b"Molar mass (g/mol),dW/dLogM\n9000,0.1\n3000,0.8\n1000,0.5\n"
    gpc.write_bytes(chromatogram)
    plan = build_plan_preview(gpc, request={"rule_id": "gpc_sec_chromatogram"})
    state = {"request": {**request, "source": str(gpc)}, "task_dir": str(tmp_path / "gpc-task"),
             "source_sha256": plan["preview_identity"]["source_tree_sha256"]}
    assert admit_raw_curve(state, plan)
    result = build_managed_request(state)
    spec = result["template_definition"]["figure_spec"]
    x, y = spec["scales"]
    assert (x["quantity"], x["unit"], x["transform"]) == ("molar_mass", "g/mol", "log")
    assert (y["quantity"], y["unit"]) == ("differential_weight_fraction", "1")
    original_y = state["semantic_plan"]["resolved_bindings"][0]["coordinates"]["y"]
    assert (original_y["observed_unit"], original_y["header"]) == ("", "dW/dLogM")
    assert spec["views"][0]["axes"][1]["label"] == "dW/dlog M"
    metric, = state["analysis_metrics"]
    assert (metric["metric"], metric["value"], metric["unit"], metric["status"]) == (
        "peak_molar_mass_g_mol", 3000., "g mol⁻¹", "ok")
    assert "no molecular-weight calibration is inferred from RI" in metric["reason"]
    binding = result["data_binding"]
    doc = create_managed_document(result["template_definition"], binding, plot_id="gpc-original")
    declaration, = doc["scientific"]["data_sources"][0]["metadata_confirmations"]
    assert declaration["value"] == "1" and declaration["source_sha256"] == state["source_hashes"][str(gpc)]
    assert declaration["evidence"] == {"kind": "registered_rule", "rule_id": "gpc_sec_chromatogram",
        "sheet": None, "row_index": 0, "column_index": 1, "text": "dW/dLogM"}
    wrong = deepcopy(doc)
    wrong["scientific"]["data_sources"][0]["metadata_confirmations"][0]["evidence"]["row_index"] = 1
    with pytest.raises(ValueError, match="Evidence cell text does not match"):
        load_sources(wrong, "gpc_sec_chromatogram")
    with pytest.raises(ValueError, match="Registered dimensionless GPC evidence"):
        load_sources(doc, "ordinary_xy")
    data = load_sources(doc, "gpc_sec_chromatogram")
    for node in binding["transforms"]:
        data[node["output"]], _ = execute_node(node, data)
    gpc_slot, = binding["slots"].values()
    coordinate = data[gpc_slot["x"]["source_id"]]["columns"]
    assert gpc_slot["sample"] == "gpc"
    assert coordinate["x"]["values"] == [9000, 3000, 1000] and coordinate["y"]["values"] == [.1, .8, .5]
    assert gpc.read_bytes() == chromatogram
    alternate = tmp_path / "gpc-adjacent.csv"
    alternate.write_bytes(chromatogram.replace(b"Molar mass (g/mol),dW/dLogM", b"Molar mass,dW/dLogM\ng/mol,\nA,A"))
    adjacent = build_plan_preview(alternate, request={"rule_id": "gpc_sec_chromatogram"})
    alternate_state = {"request": {**request, "source": str(alternate)}, "task_dir": str(tmp_path / "gpc-adjacent-task"),
                       "source_sha256": adjacent["preview_identity"]["source_tree_sha256"]}
    assert adjacent["status"] == "planned"
    assert admit_raw_curve(alternate_state, adjacent)
    adjacent_wire = build_managed_request(alternate_state)
    adjacent_binding = adjacent_wire["data_binding"]
    adjacent_source, = adjacent_binding["data_sources"]
    assert adjacent_source["table_selection"] == {"sheet": None, "header_rows": [0], "unit_row": 1,
                                                  "sample_row": 2, "data_start_row": 3, "data_end_row": 6}
    adjacent_slot, = adjacent_binding["slots"].values()
    assert adjacent_slot["sample"] == "A"
    assert alternate_state["analysis_metrics"] == state["analysis_metrics"]

    path = tmp_path / "signed-xrd.csv"
    path.write_text("2theta,Intensity\ndegree,a.u.\nB,B\n1,-3\n2,6\n3,4\n")
    plan = build_plan_preview(path, request={"rule_id": "xrd_pattern"})
    candidate = {"request": {**request, "source": str(path)}, "task_dir": str(tmp_path / "signed"),
                 "source_sha256": plan["preview_identity"]["source_tree_sha256"]}
    assert admit_raw_curve(candidate, plan)
    signed = build_managed_request(candidate)
    y = signed["template_definition"]["figure_spec"]["scales"][1]
    assert y["domain"][0] < -3 and y["domain_rule"]["minimum"] == {"mode": "auto_zero_if_nonnegative"}

    from test_current_view_lifecycle import _append, _domains, _patch
    from sciplot_core.plot_engine.current_unit_admission import prepare_current_update
    from sciplot_core.plot_engine.managed_resolution import resolve_science, resolved_metadata

    def saved(built, name):
        doc = create_managed_document(built["template_definition"], built["data_binding"], plot_id=name)
        return resolved_metadata(doc, rule_id="xrd_pattern", executors={})

    store = tmp_path / "update"
    initial = resolve_science(store, saved(unsigned, "xrd-original"))[0]
    added = saved(signed, "xrd-added")
    candidate, diff, _, execute = prepare_current_update(store, initial, _append(initial, added))
    assert execute and diff[0]["after"]["preserved_domain_rules"]["y"]["minimum"] == {"mode": "auto_zero_if_nonnegative"}
    assert _domains(resolve_science(store, candidate)[0])["scale:y"] == y["domain"]
    explicit = _patch(initial, [("scale:y", "scale.domain", {"minimum": {"mode": "fixed", "value": 0},
                                                          "maximum": {"mode": "auto"}})], scientific=True)
    fixed = prepare_current_update(store, initial, explicit)[0]
    candidate = prepare_current_update(store, fixed, _append(fixed, added))[0]
    assert _domains(resolve_science(store, candidate)[0])["scale:y"][0] == 0

    from hashlib import sha256
    from sciplot_core.plot_engine.managed_source_revision import source_value

    source = initial["scientific"]["data_sources"][0]
    target = "source:" + source["source_id"]
    revision = source_value(initial, target, root=store)
    updated = path.read_bytes().replace(b"B,B", b"A,A")
    Path(source["path"]).write_bytes(updated)
    revision["sha256"] = sha256(updated).hexdigest()
    for unit_context in revision["unit_context_bindings"]:
        unit_context["source_sha256"] = revision["sha256"]
    for before, expected in ((initial, y["domain"][0]), (fixed, 0)):
        candidate = prepare_current_update(store, before, _patch(before, [(target, "source.sha256", revision)], scientific=True))[0]
        assert _domains(resolve_science(store, candidate)[0])["scale:y"][0] == expected


@pytest.mark.parametrize("semantic", [False, True])
def test_create_cli_preserves_explicit_scientific_requirements(ready, monkeypatch, capsys, semantic):
    requests = []
    monkeypatch.setattr(shortcuts, "start_task", lambda request, **kwargs: requests.append(request) or {"status": "needs_input"})
    coordinates = ["--x", "wavenumber", "--y", "transmittance"] if semantic else []
    args = build_parser().parse_args(["task", "create", "/original.csv", "--rule", "ftir_spectrum",
        "--curve-display", "raw_overlay", "--summary-statistic", "raw_only", *coordinates, "--json"])
    assert dispatch.dispatch_task(args) == 0
    capsys.readouterr()
    assert requests[0]["curve_display"] == "raw_overlay"
    assert requests[0]["summary_statistic"] == "raw_only"
    assert requests[0].get("sources" if semantic else "source") == (["/original.csv"] if semantic else "/original.csv")


def test_semantic_cli_projects_scale_directions_without_reordering_sources(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(shortcuts, "create_task", lambda source, **kwargs: calls.append((source, kwargs)) or {"status": "needs_input"})
    args = build_parser().parse_args(["task", "create", "--source", "/second.csv", "--source", "/first.csv",
        "--x", "wavenumber", "--y", "transmittance", "--x-direction", "descending", "--y-direction", "ascending",
        "--curve-display", "raw_overlay", "--summary-statistic", "raw_only", "--json"])
    assert dispatch.dispatch_task(args) == 0
    capsys.readouterr()
    assert calls[0][0] is None
    assert calls[0][1]["sources"] == [Path("/second.csv"), Path("/first.csv")]
    assert calls[0][1]["intent"]["x"] == {"quantity": "wavenumber", "direction": "descending"}
    assert calls[0][1]["intent"]["y"] == {"quantity": "transmittance", "direction": "ascending"}
    assert calls[0][1]["curve_display"] == "raw_overlay"


def test_create_rejects_profile_conflict_before_runtime_or_task_allocation(ready, monkeypatch):
    calls, _ = ready
    monkeypatch.setattr(shortcuts, "start_task", lambda *_a, **_k: pytest.fail("allocated invalid task"))
    with pytest.raises(TaskControlError, match="复用配置"):
        shortcuts.create_task(Path("/original.csv"), rule_id="uvvis_spectrum", profile=Path("/profile.json"))
    assert calls == []


def test_runtime_failure_does_not_start_or_hide_repair(ready, monkeypatch):
    calls, runtime = ready
    runtime.update(status="blocked", next_actions=["repair exact missing runtime"],
                   checks=[{"status": "failed", "detail": "missing native runtime"}])
    monkeypatch.setattr(shortcuts, "start_task", lambda *_a, **_k: pytest.fail("allocated blocked task"))
    result = shortcuts.create_task(Path("/original.csv"))
    assert calls == ["doctor"] and result["reason_code"] == "runtime_not_ready"
    assert result["doctor"]["failed_checks"] == runtime["checks"]
    assert result["next_step"] == {"action": "repair_runtime", "next_actions": runtime["next_actions"]}


@pytest.fixture
def context(monkeypatch):
    value = {"status": "ok", "doctor": {"kind": "sciplot_doctor", "status": "ready", "failed_checks": []},
             "selected_figure": {"sample_styles": [{"sample": "Exact B", "unique": True},
                                                       {"sample": "Exact A", "unique": True}]},
             "request_template": {"version": 1, "action": "edit", "project": "/current/project",
                                  "figure_id": "secondary", "expected_document_sha256": "a" * 64, "operations": []}}
    calls = []
    monkeypatch.setattr(shortcuts, "edit_context", lambda *args, **kwargs: calls.append((args, kwargs)) or value)
    monkeypatch.setattr(shortcuts, "doctor_payload", lambda: pytest.fail("repeated context Doctor"))
    return value, calls


@pytest.mark.parametrize("all_samples,samples,expected", [
    (True, None, ["Exact B", "Exact A"]), (False, ["Exact A", "Exact B"], ["Exact A", "Exact B"]),
])
def test_style_binds_current_figure_sha_and_exact_selection_once(context, monkeypatch, all_samples, samples, expected):
    value, calls = context
    before = deepcopy(value)
    requests = []
    preview = {"kind": "sciplot_task", "status": "needs_review", "operation_id": "b" * 64,
               "preview": {"image": "/preview.png", "scientific_audit": {"status": "passed"}}}
    def start(request, *, task_dir, entry_intent=None):
        requests.append((request, task_dir))
        return deepcopy(preview)
    monkeypatch.setattr(shortcuts, "start_task", start)
    result = shortcuts.style_task(Path("/delivery with spaces"), samples=samples, all_samples=all_samples,
                                  width="0.7pt", color="#2878B5", figure_id="secondary", task_dir=Path("/task"))
    assert calls == [((Path("/delivery with spaces"),), {"operations": ["set_sample_style"], "figure_id": "secondary"})]
    assert requests == [({**value["request_template"], "operations": [{"op": "set_sample_style",
                          "samples": expected, "style": {"width": "0.7pt", "color": "#2878B5"}}]}, Path("/task"))]
    assert result == {**preview, "doctor": value["doctor"]}
    assert value == before  # No mutation of the inspected revision or implicit acceptance.


@pytest.mark.parametrize("kwargs", [{}, {"all_samples": True, "samples": ["A"]},
    {"all_samples": True}, {"all_samples": True, "width": ""},
    {"samples": []}, {"samples": ["A", "A"]}])
def test_invalid_style_intent_fails_before_context_or_task(monkeypatch, kwargs):
    monkeypatch.setattr(shortcuts, "edit_context", lambda *_a, **_k: pytest.fail("queried invalid intent"))
    monkeypatch.setattr(shortcuts, "start_task", lambda *_a, **_k: pytest.fail("allocated invalid intent"))
    options = {"width": "0.7pt", **kwargs}
    if kwargs == {"all_samples": True}:
        options.pop("width")
    with pytest.raises((TaskControlError, AnnotationOperationError)):
        shortcuts.style_task(Path("/project"), **options)


@pytest.mark.parametrize("targets,samples,code", [
    ([], None, "unknown_sample_style_target"),
    ([{"sample": "A", "unique": False}], None, "ambiguous_sample_style_target"),
    ([{"sample": "A", "unique": True}], ["a"], "unknown_sample_style_target"),
    ([{"sample": "A", "unique": False}], ["A"], "ambiguous_sample_style_target"),
])
def test_style_rejects_empty_ambiguous_or_inexact_targets_without_allocating(context, monkeypatch, targets, samples, code):
    value, _ = context
    value["selected_figure"]["sample_styles"] = targets
    monkeypatch.setattr(shortcuts, "start_task", lambda *_a, **_k: pytest.fail("allocated invalid target"))
    with pytest.raises(TaskControlError) as error:
        shortcuts.style_task(Path("/project"), samples=samples, all_samples=samples is None, width="0.7pt")
    assert error.value.reason_code == code


@pytest.mark.parametrize("reason", ["unfinished_task", "runtime_not_ready"])
def test_style_returns_existing_continuation_without_start_or_second_doctor(context, monkeypatch, reason):
    value, _ = context
    value.clear()
    value.update(status="blocked", reason_code=reason, next_step={"action": "original continuation"})
    monkeypatch.setattr(shortcuts, "start_task", lambda *_a, **_k: pytest.fail("started over existing blocker"))
    assert shortcuts.style_task(Path("/task"), all_samples=True, width="0.7pt") == value


@pytest.mark.parametrize("command,expected", [
    (["create", "/raw input.csv", "--rule", "uvvis_spectrum", "--template", "curve", "--out", "/out", "--task-dir", "/task"],
     ("create", Path("/raw input.csv"), {"rule_id": "uvvis_spectrum", "template": "curve", "profile": None, "out": Path("/out"), "task_dir": Path("/task")})),
    (["style", "/saved", "--sample", "B", "--sample", "A", "--width", "0.7pt", "--figure", "secondary"],
     ("style", Path("/saved"), {"samples": ["B", "A"], "all_samples": False, "width": "0.7pt", "color": None, "figure_id": "secondary", "task_dir": None})),
])
def test_cli_shortcuts_need_no_json_file_and_preserve_arguments(monkeypatch, capsys, command, expected):
    calls = []
    receipt = {"kind": "sciplot_task", "status": "needs_input", "doctor": {"status": "ready"}, "question": {"field": "rule_id"}}
    for name in ("create", "style"):
        monkeypatch.setattr(shortcuts, name + "_task", lambda target, _name=name, **kwargs: calls.append((_name, target, kwargs)) or deepcopy(receipt))
    monkeypatch.setattr(dispatch, "_object", lambda *_a: pytest.fail("read unnecessary JSON file"))
    args = build_parser().parse_args(["task", *command, "--json"])
    assert dispatch.dispatch_task(args) == 0
    assert calls == [expected] and json.loads(capsys.readouterr().out) == receipt


@pytest.mark.parametrize("arguments", [
    ["style", "/saved", "--width", "0.7pt"],
    ["style", "/saved", "--all-samples", "--sample", "A", "--width", "0.7pt"],
    ["resume", "/task"], ["resume", "/task", "--retry", "--response", "/answer.json"],
    ["resume", "/task", "--accept-preview", "--retry"],
])
def test_cli_mutually_exclusive_inputs_rejected_during_parse(arguments):
    with pytest.raises(SystemExit):
        build_parser().parse_args(["task", *arguments])


@pytest.mark.parametrize("arguments", [
    ["--accept-preview"], ["--accept-preview", "--expected-operation-id", "invalid"],
    ["--retry", "--expected-operation-id", "a" * 64],
    ["--response", "/missing.json", "--expected-operation-id", "a" * 64],
])
def test_cli_preview_binding_errors_fail_before_read_or_resume(monkeypatch, arguments):
    monkeypatch.setattr(dispatch, "resume_task", lambda *_a: pytest.fail("resumed without valid explicit binding"))
    monkeypatch.setattr(dispatch, "_object", lambda *_a: pytest.fail("read file before rejecting invalid combination"))
    args = build_parser().parse_args(["task", "resume", "/task", *arguments])
    with pytest.raises(TaskControlError):
        dispatch.dispatch_task(args)


@pytest.mark.parametrize("arguments,answer", [
    (["--accept-preview", "--expected-operation-id", "b" * 64], {"accept_preview": True, "expected_operation_id": "b" * 64}),
    (["--retry"], {"retry": True}),
])
def test_cli_resume_uses_caller_binding_without_reading_latest_task(monkeypatch, capsys, arguments, answer):
    calls = []
    monkeypatch.setattr(dispatch, "_object", lambda *_a: pytest.fail("read unnecessary JSON file"))
    monkeypatch.setattr(dispatch, "resume_task", lambda target, response, *, _public_mutation: calls.append((target, response, _public_mutation)) or {"status": "complete"})
    args = build_parser().parse_args(["task", "resume", "/task with spaces", *arguments, "--json"])
    assert dispatch.dispatch_task(args) == 0
    assert calls == [(Path("/task with spaces"), answer, True)]
    assert json.loads(capsys.readouterr().out) == {"status": "complete"}


def test_cli_resume_response_file_remains_compatible(tmp_path, monkeypatch):
    answer = {"accept_preview": False, "expected_operation_id": "a" * 64}
    path = tmp_path / "answer.json"
    path.write_text(json.dumps(answer))
    calls = []
    monkeypatch.setattr(dispatch, "resume_task", lambda target, response, *, _public_mutation: calls.append((response, _public_mutation)) or {"status": "cancelled"})
    args = build_parser().parse_args(["task", "resume", "/task", "--response", str(path)])
    assert dispatch.dispatch_task(args) == 0 and calls == [(answer, True)]


def test_guidance_carries_exact_current_arguments_without_shell_concatenation():
    state = {"status": "needs_review", "phase": "review", "request": {"action": "edit"},
             "task_dir": "/task with spaces/$(literal)", "operation_id": "b" * 64}
    result = task_next_step(state)
    assert result["cli_argv"] == ["sciplot", "task", "resume", state["task_dir"], "--accept-preview",
                                  "--expected-operation-id", "b" * 64, "--json"]
    assert result["response_template"] == {"accept_preview": True, "expected_operation_id": "b" * 64}
    state.update(status="blocked", phase="exporting")
    assert task_next_step(state)["cli_argv"] == ["sciplot", "task", "resume", state["task_dir"], "--retry", "--json"]
    state.update(status="needs_review", request={"action": "update_source"}, revision_id="c" * 64)
    assert "cli_argv" not in task_next_step(state)
    assert "typed_entries" in task_capabilities()


def test_stress_create_options_reuse_one_doctor_identity(ready, monkeypatch):
    calls, runtime = ready
    identity = {'source_package_root': '/source/src/sciplot_core', 'source_git_head': 'a' * 40,
                'runtime_repo_root': '/source', 'python_executable': '/python',
                'native_execution_verified': False}
    runtime['execution_identity'] = {**identity, 'unbounded_detail': ['not forwarded']}
    requests = []
    monkeypatch.setattr(shortcuts, 'start_task', lambda request, **kwargs: requests.append(request) or {'status': 'needs_input'})
    result = shortcuts.create_task(Path('/original.csv'), rule_id='rheology_stress_relaxation',
                                   xscale='linear', choose_columns=True)
    assert calls == ['doctor']
    assert requests[0]['choose_columns'] is True and requests[0]['xscale'] == 'linear'
    assert result['doctor']['execution_identity'] == identity
    assert result['doctor']['execution_identity']['native_execution_verified'] is False
