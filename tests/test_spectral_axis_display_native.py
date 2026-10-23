"""Generated public lifecycles for persisted qualitative XRD axis display."""

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

import pytest


def _capture(document, destination, *, native_show=False, axis_paths=None):
    """Read real saved native settings, datasets and synchronously painted text."""
    from sciplot_core.foundation.file_hashing import file_sha256

    original = file_sha256(document)
    paths = axis_paths or {name: "/page1/graph1/" + name for name in ("x", "y")}
    code = """
import json
from importlib import import_module
from pathlib import Path
import sys
from rendering_profiles_native import _painted_text, normalized, settings
from sciplot_core.veusz_worker.document_edit import loaded_native_document
with loaded_native_document(Path(sys.argv[1])) as document:
    if sys.argv[3] == 'show':
        from veusz.document import CommandInterface
        from veusz.document.operations import OperationSettingSet
        for suffix in ('MajorTicks/hide', 'MinorTicks/hide', 'TickLabels/hide'):
            document.applyOperation(OperationSettingSet('/page1/graph1/y/' + suffix, False))
        document.applyOperation(OperationSettingSet('/page1/graph1/Background/color', '#fafafa'))
        CommandInterface(document).Save(sys.argv[1])
    axes = {name: settings(document.resolveWidgetPath(None, path), document)
            for name, path in json.loads(sys.argv[4]).items()}
    text, _ = _painted_text(document, import_module('veusz.document'))
    data = {name: normalized(value.data.tolist()) for name, value in document.data.items()}
    Path(sys.argv[2]).write_text(json.dumps({'axes': axes, 'text': text, 'data': data}, allow_nan=False))
"""
    result = subprocess.run(
        [sys.executable, "-c", code, str(document), str(destination),
         "show" if native_show else "read", json.dumps(paths)],
        capture_output=True, text=True, timeout=90, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    if not native_show:
        assert file_sha256(document) == original
    return json.loads(destination.read_text())


def _assert_axis(captured, *, show_y, log_y=False, axis_paths=None):
    paths = axis_paths or {name: "/page1/graph1/" + name for name in ("x", "y")}
    x, y = (captured["axes"][name] for name in ("x", "y"))
    for axis in (x, y):
        assert axis["Line/hide"] is False and axis["Label/hide"] is False
        assert axis["label"]
    assert x["TickLabels/hide"] is False and x["MajorTicks/hide"] is False
    assert y["TickLabels/hide"] is not show_y
    assert y["MajorTicks/hide"] is not show_y
    if not show_y:
        assert y["MinorTicks/hide"] is True
    assert y["log"] is log_y
    for name, axis in (("x", x), ("y", y)):
        painted = [row["text"] for row in captured["text"]
                   if row["widget_path"] == paths[name]]
        assert axis["label"] in painted, (name, painted)
        readout = [text for text in painted if text != axis["label"]]
        if name == "y" and not show_y:
            # This also rejects a leftover exponent/offset rendered by the axis.
            assert readout == [], painted
        else:
            assert readout and any(any(char.isdigit() for char in text) for text in readout)


def _assert_source_data(document, captured, source, points, rule, *, lineage=None, input_binding=None, native_presentation=False):
    from sciplot_core.foundation.file_hashing import file_sha256
    from sciplot_core.publication.artifacts import artifact_record
    from sciplot_core.semantic_sources.registered_paired_curve_transform import _comparable_unit
    from sciplot_core.studio_core.annotation_axes import axis_unit
    from sciplot_core.studio_core.document_edit_state import run_document_worker
    from sciplot_core.studio_core.registry_state import _veusz_spec_path

    spec_path = _veusz_spec_path(document)
    document_hash, spec_hash = file_sha256(document), file_sha256(spec_path)
    spec = json.loads(spec_path.read_text())
    assert [item["label"] for item in spec["series"]] == ["Generated Cedar", "Generated Birch"]
    assert len(spec["series"]) == len(points) == 2
    for item, expected in zip(spec["series"], points, strict=True):
        for axis, index in (("x", 0), ("y", 1)):
            values = [float(point[index]).hex() for point in expected]
            assert [float(value).hex() for value in item[axis + "_values"]] == values
            assert [float(value).hex() for value in captured["data"][item[axis + "_name"]]] == values
        assert item["source_artifacts"]
        for artifact in item["source_artifacts"]:
            assert file_sha256(Path(artifact["path"])) == artifact["sha256"]
    expected_units = {"xrd_pattern": ("degree", "a.u."),
                      "uvvis_spectrum": ("nm", "a.u."),
                      "saxs_profile": ("nm^-1", "a.u.")}
    assert tuple(_comparable_unit(axis_unit(spec, name)) for name in ("x", "y")) == tuple(
        _comparable_unit(unit) for unit in expected_units[rule])
    ledger = lineage if lineage is not None else spec["source_request"]["transform_ledger"]
    canonical_input, selected_source = (source, source) if input_binding is None else input_binding
    if lineage is None:
        assert spec["source_request"]["input"] == str(canonical_input)
    assert file_sha256(selected_source) == file_sha256(source)
    raw = [artifact for step in ledger["steps"] for artifact in step["input_artifacts"]
           if artifact["path"] == str(canonical_input)]
    assert len(raw) == 1 and raw[0] == artifact_record(canonical_input, artifact_id=raw[0]["id"], role=raw[0]["role"])
    contracts = [step["parameters"]["scientific_transform"] for step in ledger["steps"]
                 if "scientific_transform" in step["parameters"]]
    assert len(contracts) == 1
    contract = contracts[0]
    assert contract["semantic_family"] == rule
    assert tuple(contract["output"][name + "_unit"] for name in ("x", "y")) == expected_units[rule]
    assert contract["normalizer"]["scope"] == contract["normalizer"]["operation"] == "none"
    assert contract["selected_sources"] == [str(selected_source)]
    assert [(row["x"]["column_index_zero_based"], row["response"]["column_index_zero_based"])
            for row in contract["source_columns"]] == [(0, 1), (2, 3)]
    assert [row["point_count"] for row in contract["output"]["series"]] == [3, 2]
    arguments = ["audit-spec-data", document, spec_path]
    if native_presentation:
        arguments.append("--allow-presentation-edits")
    audit = run_document_worker(*arguments)
    assert audit["status"] == "passed", audit
    assert audit["audit_scope"] == ("current_scientific_data" if native_presentation else "generated_contract")
    assert audit["document"] == {"path": str(document.resolve()), "sha256": document_hash}
    assert audit["spec"] == {"path": str(spec_path.resolve()), "sha256": spec_hash}
    assert (file_sha256(document), file_sha256(spec_path)) == (document_hash, spec_hash)
    return spec


def _intake_binding(source, project, task_dir):
    from sciplot_core.foundation.file_hashing import file_sha256
    from sciplot_core.foundation.source_tree import source_tree_sha256

    task = json.loads((task_dir / "task.json").read_text())
    assert task["request"]["source"] == str(source) and task["project"] == str(project)
    assert task["source_sha256"] == source_tree_sha256(source)
    manifest = json.loads((project / "intake_manifest.json").read_text())
    assert manifest["kind"] == "sciplot_intake_project" and len(manifest["groups"]) == 1
    group = manifest["groups"][0]
    assert group["sample"] == source.stem and len(group["files"]) == 1
    item = group["files"][0]
    raw = project / "raw" / source.stem / source.name
    staged = project / "source" / (source.stem + "__" + source.name)
    assert item["original_name"] == source.name
    assert item["raw_path"] == str(raw) and item["source_path"] == str(staged)
    assert manifest["source_dir"] == str(staged.parent)
    assert item["size_bytes"] == source.stat().st_size
    assert item["sha256"] == file_sha256(source) == file_sha256(raw) == file_sha256(staged)
    assert source.read_bytes() == raw.read_bytes() == staged.read_bytes()
    assert list(staged.parent.iterdir()) == [staged]
    return staged.parent, staged


def _create(tmp_path, rule):
    from public_curve_inputs import paired_source
    from test_task_control_native import _cli

    source, points = paired_source(tmp_path / "raw", rule)
    before = source.read_bytes()
    # An ordinary task intentionally omits the optional template.
    created = _cli("task", "create", source, "--rule", rule,
                   "--task-dir", tmp_path / "create")
    assert created["status"] == "complete", created
    assert source.read_bytes() == before
    project = Path(created["project"])
    document = Path(created["current_project"]["figures"][0]["document"])
    binding = _intake_binding(source, project, tmp_path / "create")
    return source, points, before, project, document, binding


def _presentation_round_trip(project):
    from sciplot_core.plot_engine.service import PlotService
    from sciplot_core.plot_engine.storage import load_head

    service = PlotService()
    try:
        opened = service.open(project)
        root = Path(opened["plot"])
        before = load_head(root)["document"]
        science = deepcopy(before["scientific"])
        series = next(key for key, value in before["presentation"]["objects"].items()
                      if value["kind"] == "series")
        result = service.patch(root, {
            "plot_id": before["plot_id"], "base_revision": before["revision"],
            "idempotency_key": "axis-display-style", "intent_class": "presentation",
            "changes": [{"op": "set", "target": [series],
                         "property": "style.line.width", "value": "1.5pt"}],
        })
        if result["status"] == "needs_review":
            assert result["scientific_audit"]["status"] == "passed"
            result = service.decide(root, result["next_step"]["request"])
        assert result["status"] == "complete" and result["ready_to_use"], result
        after = load_head(root)["document"]
        assert after["scientific"] == science
        assert after["scientific_hash"] == before["scientific_hash"]
        assert after["presentation_hash"] != before["presentation_hash"]
        assert service.export(root)["ready_to_use"]
        assert load_head(root)["document"] == after
    finally:
        service.close()


def _managed_hidden_append(tmp_path):
    from test_current_view import current, fixed
    from test_figure_document import request_for_figure
    from test_managed_source_append import append_request
    from sciplot_core.foundation.file_hashing import file_sha256
    from sciplot_core.plot_backends.figure_marks import graph_path
    from sciplot_core.plot_backends.native_primitives import dataset_name, native_name
    from sciplot_core.plot_engine.service import PlotService
    from sciplot_core.plot_engine.storage import load_head, read
    from sciplot_core.plot_ir.figure_document import figure_spec

    tmp_path.mkdir()
    request = request_for_figure(tmp_path)
    spec, _ = current()
    fixed(spec, [0, 10], [0, 20])
    for tick_axis in spec["views"][0]["axes"]:
        tick_axis["ticks_mode"] = "fixed"
    request["template_definition"]["figure_spec"] = spec
    axis = spec["views"][0]["axes"][1]
    axis.update(ticks=[], ticks_mode="fixed", style={**axis["style"], "minor_ticks_visible": False})
    paths = {name: graph_path("view:A") + "/" + native_name("axis", identifier)
             for name, identifier in (("x", "axis:xb"), ("y", "axis:yl"))}
    service = PlotService()
    try:
        made = service.create(request)
        assert made["ready_to_use"], made
        root = Path(made["plot"])
        before = load_head(root)
        old_ir = read(Path(before["binding"]["ir_path"]))
        source_a = Path(before["document"]["scientific"]["data_sources"][0]["path"])
        raw_a = source_a.read_bytes()
        initial = _capture(Path(before["binding"]["document"]), tmp_path / "before.json", axis_paths=paths)
        _assert_axis(initial, show_y=False, axis_paths=paths)
        patch = append_request(before["document"], tmp_path)
        source_b = Path(patch["changes"][0]["value"]["source"]["path"])
        raw_b = source_b.read_bytes()
        pending = service.patch(root, patch)
        assert pending["status"] == "needs_review" and load_head(root) == before, pending
        review = read(Path(pending["evidence"]))["review"]
        assert review["scientific_audit"]["status"] == review["source_append"]["before_scientific_audit"]["status"] == "passed"
        accepted = service.decide(root, pending["next_step"]["request"])
        assert accepted["ready_to_use"] and accepted["revision"] == 1, accepted
        after = load_head(root)
        ir = read(Path(after["binding"]["ir_path"]))
        assert figure_spec(after["document"])["views"][0]["axes"] == figure_spec(before["document"])["views"][0]["axes"]
        assert after["document"]["scientific"]["data_sources"][:-1] == before["document"]["scientific"]["data_sources"]
        assert all(ir["datasets"][name] == value for name, value in old_ir["datasets"].items())
        assert ir["datasets"]["raw:B"]["columns"]["column:0"]["values"] == [8, 5, 5, 2]
        assert ir["datasets"]["raw:B"]["columns"]["column:1"]["values"] == [7, None, 3, 9]
        assert ir["datasets"]["raw:B"]["provenance"]["sources"][0]["rows"] == [3, 4, 5, 6]
        current = _capture(Path(after["binding"]["document"]), tmp_path / "appended.json", axis_paths=paths)
        _assert_axis(current, show_y=False, axis_paths=paths)
        assert all(current["data"][name] == value for name, value in initial["data"].items())
        assert current["data"][dataset_name("raw:B", "column:0")] == [8, 5, 5, 2]
        assert current["data"][dataset_name("raw:B", "column:1")] == [7, {"nonfinite": "nan"}, 3, 9]
        service.close()
        service = PlotService()
        assert service.open(root)["revision"] == 1
        assert service.export(root)["ready_to_use"] and load_head(root) == after
        assert _capture(Path(after["binding"]["document"]), tmp_path / "reopened.json", axis_paths=paths) == current
        assert source_a.read_bytes() == raw_a and source_b.read_bytes() == raw_b
        assert all(file_sha256(Path(item["path"])) == item["sha256"] for item in after["document"]["scientific"]["data_sources"])
    finally:
        service.close()


@pytest.mark.comprehensive
def test_ordinary_xrd_default_native_lifecycle_preserves_frozen_display(tmp_path):
    from sciplot_core.foundation.file_hashing import file_sha256
    from sciplot_core.studio import prepare_studio_document
    from sciplot_core.studio_core.project_creation import export_project
    from sciplot_core.workflow import run_one_step

    source, points, original, project, document, binding = _create(tmp_path, "xrd_pattern")
    request_path = project / "plot_request.json"
    request = json.loads(request_path.read_text())
    assert request["render_options"]["show_y_ticks"] is False
    assert "show_y_ticks" not in request["explicit_render_option_keys"]
    initial = _capture(document, tmp_path / "initial.json")
    _assert_axis(initial, show_y=False)
    _assert_source_data(document, initial, source, points, "xrd_pattern", input_binding=binding)

    # Equal effective presentation remains equal with omitted/explicit syntax.
    for index, template in enumerate((None, "curve")):
        prepare_studio_document(project, rule_id="xrd_pattern", template=template,
                                regenerate_generated=True)
        saved = json.loads(request_path.read_text())
        assert saved["render_options"]["show_y_ticks"] is False
        assert "show_y_ticks" not in saved["explicit_render_option_keys"]
        captured = _capture(document, tmp_path / f"regenerated-{index}.json")
        _assert_axis(captured, show_y=False)
        _assert_source_data(document, captured, source, points, "xrd_pattern", input_binding=binding)

    # Autoplot resolves the first auto request, then redraws the same XRD rule.
    for index, selection in enumerate(({}, {"rule_id": "xrd_pattern", "template": "curve"})):
        run = run_one_step(source, output_root=tmp_path / "autoplot", **selection)
        assert run["manifest"]["semantic"]["rule_id"] == "xrd_pattern", run
        saved = json.loads(Path(run["request_path"]).read_text())
        assert saved["input"] == str(source)
        assert saved["render_options"]["show_y_ticks"] is False
        assert "show_y_ticks" not in saved["explicit_render_option_keys"]
        native = run["manifest"]["veusz_documents"]
        assert len(native) == 1
        auto_document = Path(native[0])
        captured = _capture(auto_document, tmp_path / f"autoplot-{index}.json")
        _assert_axis(captured, show_y=False)
        _assert_source_data(auto_document, captured, source, points, "xrd_pattern",
                            lineage=run["manifest"]["transform_ledger"])

    # Only the same saved canonical document's presentation edit is seal-neutral.
    _presentation_round_trip(project)
    captured = _capture(document, tmp_path / "styled.json")
    _assert_axis(captured, show_y=False)
    _assert_source_data(document, captured, source, points, "xrd_pattern", input_binding=binding)
    # Actual external native Save is authoritative on ordinary reopen/export.
    captured = _capture(document, tmp_path / "external-save.json", native_show=True)
    _assert_axis(captured, show_y=True)
    native_hash = file_sha256(document)
    prepare_studio_document(project)
    exported = export_project(project)
    assert exported["status"] == "exported" and exported["studio_run"]["ready_to_use"]
    assert file_sha256(document) == native_hash
    current = _capture(document, tmp_path / "reopened.json")
    assert current == captured
    with pytest.raises(ValueError, match="Exact-current Veusz x/y axis.*differ"):
        _assert_source_data(document, current, source, points, "xrd_pattern", input_binding=binding)
    _assert_source_data(document, current, source, points, "xrd_pattern",
                        input_binding=binding, native_presentation=True)
    assert source.read_bytes() == original
    # Explicit Managed hiding is inherited by a scientific append; it is not
    # a new Managed default or an unsupported append to this Legacy XRD plot.
    _managed_hidden_append(tmp_path / "managed-append")


@pytest.mark.comprehensive
@pytest.mark.parametrize("control", ["show_true", "readout_domain", "log"])
def test_explicit_xrd_native_controls_remain_quantitative(tmp_path, control):
    from public_curve_inputs import paired_source
    from sciplot_core.foundation.file_hashing import file_sha256
    from sciplot_core.studio import prepare_studio_document
    from sciplot_core.studio_core.project_export import export_project_document

    source, points = paired_source(tmp_path / "raw", "xrd_pattern")
    original = source.read_bytes()
    options = {"show_true": {"show_y_ticks": True},
               "readout_domain": {"y_min": 0, "y_max": 10, "y_ticks": [0, 5, 10]},
               "log": {"yscale": "log"}}[control]
    project = tmp_path / "canonical"
    project.mkdir()
    request = project / "plot_request.json"
    # These controls use the real canonical request schema, not task-only fields.
    request.write_text(json.dumps({
        "input": str(source), "rule_id": "xrd_pattern", "template": "curve",
        "output": str(project / "runs" / "run_001"),
        "render_options": options, "explicit_render_option_keys": list(options),
    }))
    # This is a known fresh factory context, not a replay of a historical JSON.
    # The internal context flag is not a field in the public request schema.
    prepared = prepare_studio_document(request, _new_creation=True)
    saved = json.loads(request.read_text())
    assert saved["render_options"]["show_y_ticks"] is True
    assert set(saved["explicit_render_option_keys"]) == set(options)
    assert ("show_y_ticks" in saved["explicit_render_option_keys"]) is (control == "show_true")
    document = Path(prepared["document"])
    captured = _capture(document, tmp_path / "quantitative.json")
    _assert_axis(captured, show_y=True, log_y=control == "log")
    spec = _assert_source_data(document, captured, source, points, "xrd_pattern")
    if control == "readout_domain":
        assert [captured["axes"]["y"][key] for key in ("min", "max")] == [0, 10]
        assert captured["axes"]["y"]["MajorTicks/manualTicks"] == [0, 5, 10]
    for key, value in options.items():
        assert spec["render_options"][key] == value
    native_hash = file_sha256(document)
    prepare_studio_document(project)
    exported = export_project_document(project_dir=project, formats=["pdf", "tiff_300"])
    assert exported.ready_to_use, exported.run_payload
    assert file_sha256(document) == native_hash
    assert json.loads(request.read_text()) == saved
    assert source.read_bytes() == original


@pytest.mark.comprehensive
@pytest.mark.parametrize("rule", ["uvvis_spectrum", "saxs_profile"],
                         ids=["uvvis_absorbance", "saxs_log"])
def test_other_spectral_rules_keep_quantitative_native_axes(tmp_path, rule):
    source, points, original, project, document, binding = _create(tmp_path, rule)
    request = json.loads((project / "plot_request.json").read_text())
    assert "show_y_ticks" not in request.get("render_options", {})
    captured = _capture(document, tmp_path / "other-rule.json")
    _assert_axis(captured, show_y=True, log_y=rule == "saxs_profile")
    spec = _assert_source_data(document, captured, source, points, rule, input_binding=binding)
    assert spec["axes"]["y"]["label"] == (
        "Absorbance (a.u.)" if rule == "uvvis_spectrum" else "Log intensity (a.u.)"
    )
    assert source.read_bytes() == original
