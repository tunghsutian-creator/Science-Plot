"""A single read supplies current edit bindings without another task lifecycle."""

from copy import deepcopy
import json

from jsonschema import Draft202012Validator
import pytest

from sciplot_core import task_edit_context as context
from sciplot_core.cli.dispatch.tasks import dispatch_task
from sciplot_core.cli.parsers import build_parser
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.studio_core import project_query as query
from sciplot_core.task_capabilities import task_capabilities
from sciplot_core.task_contract import TaskControlError
from sciplot_core.task_next_step import task_next_step
from sciplot_core.task_storage import save_task


def inventory(root):
    return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}


@pytest.fixture
def saved(tmp_path, monkeypatch):
    root = tmp_path / "project"
    (root / "studio").mkdir(parents=True)
    source = tmp_path / "original.csv"
    source.write_text("x,y\n400,1\n450,3\n500,1\n")
    (root / "plot_request.json").write_text(json.dumps({"input": str(source)}))
    (root / "studio/document.vsz").write_text("saved native document")
    spec = {"template": "curve", "axes": {
        "x": {"label": "Wavelength (nm)", "min": 400, "max": 500, "scale": "linear"},
        "y": {"label": "Absorbance (a.u.)", "min": 0, "max": 5, "scale": "linear"}},
        "series": [{"name": "series_1", "label": "Exact A", "presentation_kind": "curve",
                    "x_name": "x", "y_name": "y", "x_values": [400, 450, 500],
                    "y_values": [1, 3, 1], "source_artifacts": []}],
        "native_annotations": {"version": 1, "items": [{
            "op": "add_annotation", "id": "spectrum_title", "parent_path": "/page1/graph1",
            "text": "Original title", "position": {"mode": "relative", "x": 0.03, "y": 0.96}}]}}
    (root / "studio/spec.json").write_text(json.dumps(spec))
    doctor_calls = []
    monkeypatch.setattr(context, "doctor_payload", lambda: doctor_calls.append(True) or {
        "kind": "sciplot_doctor", "status": "ready",
        "checks": [{"id": "runtime", "status": "passed", "detail": "large healthy details"}],
        "next_actions": [], "unneeded": "large catalog"})
    monkeypatch.setattr(query, "_inspect_document", lambda _: pytest.fail("context unexpectedly started native inspection"))
    return root, spec, doctor_calls


@pytest.mark.parametrize("operation", ["set_sample_style", "remove_annotation", "update_annotation", "set_axis_range"])
def test_context_reads_once_preserves_uncertainty_and_never_writes(saved, monkeypatch, operation):
    root, spec, doctor_calls = saved
    before = inventory(root.parent)
    calls = []
    def inspect(*args, **kwargs):
        calls.append((args, kwargs))
        return query.inspect_project(*args, **kwargs)
    monkeypatch.setattr(context, "inspect_project", inspect)
    result = context.edit_context(root, operations=[operation])
    assert len(calls) == len(doctor_calls) == 1
    assert calls[0][1]["native"] is False
    assert result["doctor"] == {"kind": "sciplot_doctor", "status": "ready", "failed_checks": []}
    assert result["status"] == "ok"
    current, selected = result["current_project"], result["selected_figure"]
    assert current["ready_to_use"] is None and current["readiness_evaluated"] is False
    assert current["source"]["current"] is None
    assert current["qa"]["current"] is None
    assert current["delivery"]["current"] is None
    assert "objects" not in selected
    assert selected["sample_styles"] == [{"sample": "Exact A", "unique": True,
                                           "object_paths": ["/page1/graph1/series_1"]}]
    assert result["request_template"] == {
        "version": 1, "action": "edit", "project": str(root), "figure_id": "primary",
        "expected_document_sha256": file_sha256(root / "studio/document.vsz"), "operations": []}
    if operation in {"remove_annotation", "update_annotation"}:
        assert selected["annotations"] == spec["native_annotations"]["items"]
    else:
        assert "annotations" not in selected
    if operation in {"update_annotation", "set_axis_range"}:
        assert selected["axes"]["x"] == {"unit": "nm", **spec["axes"]["x"]}
    else:
        assert "axes" not in selected
    assert inventory(root.parent) == before


@pytest.mark.parametrize("changed", ["document.vsz", "spec.json"])
def test_context_rejects_document_or_spec_changed_during_read(saved, monkeypatch, changed):
    root, _, _ = saved
    original = query.sample_style_targets
    def mutate(spec):
        path = root / "studio" / changed
        path.write_text(path.read_text() + "\n")
        return original(spec)
    monkeypatch.setattr(query, "sample_style_targets", mutate)
    with pytest.raises(ValueError, match="changed during inspection"):
        context.edit_context(root, operations=["remove_annotation"])


def test_context_native_style_reuses_exact_current_fields_and_compaction(saved, monkeypatch):
    root, _, _ = saved
    calls = []
    fields = [{"setting_path": "/page1/graph1/title/hide", "current_value": False}]
    def native(document):
        calls.append(document)
        return {"document": {"path": str(document), "sha256": file_sha256(document)},
                "widgets": {"/page1/graph1/title": {"type": "label", "editable_fields": fields,
                    "settings": {"label": "Native title", "hide": False, "unused": list(range(50))}}}}
    monkeypatch.setattr(query, "_inspect_document", native)
    monkeypatch.setattr(query, "filter_editable_fields", lambda widgets, spec: widgets)
    before = inventory(root)
    result = context.edit_context(root, operations=["set_style"])
    assert calls == [root / "studio/document.vsz"]
    objects = result["selected_figure"]["objects"]
    assert objects["/page1/graph1/title"]["editable_fields"] == fields
    assert objects["/page1/graph1/title"]["display_context"] == {"label": "Native title", "hide": False}
    assert "settings" not in objects["/page1/graph1/title"]
    assert objects["/page1/graph1/title"]["target"]["document_sha256"] == result["request_template"]["expected_document_sha256"]
    assert inventory(root) == before


@pytest.mark.parametrize("explicit_figure", [False, True])
def test_context_selects_secondary_saved_identity_without_native_inspection(saved, explicit_figure):
    root, spec, _ = saved
    secondary = root / "studio/figures/secondary.vsz"
    secondary.parent.mkdir()
    secondary.write_text("distinct secondary native document")
    second_spec = deepcopy(spec)
    second_spec["series"][0]["label"] = "Exact B"
    secondary.with_suffix(".spec.json").write_text(json.dumps(second_spec))
    (root / "studio/figure_set.json").write_text(json.dumps({
        "kind": "sciplot_studio_figure_set", "version": 1, "primary_figure_id": "primary",
        "figures": [{"figure_id": identity, "status": "ready"} for identity in ("primary", "secondary")]}))
    before = inventory(root)
    result = context.edit_context(root if explicit_figure else secondary, operations=["set_sample_style"],
                                  figure_id="secondary" if explicit_figure else None)
    assert result["request_template"]["figure_id"] == "secondary"
    assert result["request_template"]["expected_document_sha256"] == file_sha256(secondary)
    assert result["selected_figure"]["sample_styles"][0]["sample"] == "Exact B"
    assert inventory(root) == before


def test_annotation_context_retains_complete_bound_peak_record(saved):
    from sciplot_core.studio_core.annotation_contracts import normalize_annotation
    from sciplot_core.studio_core.peak_evidence import peak_candidates_for_spec

    root, spec, _ = saved
    peak = peak_candidates_for_spec(spec, object_path="/page1/graph1/series_1",
                                   window={"min": 400, "max": 500, "unit": "nm"}, polarity="maximum")[0]
    annotation = normalize_annotation(spec, {"op": "add_peak_label", "id": "peak", "candidate": peak})
    spec["native_annotations"]["items"].append(annotation)
    (root / "studio/spec.json").write_text(json.dumps(spec))
    before = inventory(root)
    result = context.edit_context(root, operations=["remove_annotation"])
    assert result["selected_figure"]["annotations"][-1] == annotation
    assert result["selected_figure"]["annotations"][-1]["peak_anchor"] == peak
    assert inventory(root) == before


def test_selected_capabilities_share_contract_and_exclude_unrequested_operations(saved):
    root, spec, _ = saved
    result = context.edit_context(root, operations=["remove_annotation", "remove_annotation"])
    capabilities = result["capabilities"]
    assert capabilities["operation_names"] == ["remove_annotation"]
    assert capabilities["contract_sha256"] == task_capabilities()["contract_sha256"]
    assert "edit-context" in task_capabilities()["saved_edit_context"]["cli"]
    schema = capabilities["request_schema"]
    Draft202012Validator.check_schema(schema)
    request = {**result["request_template"], "operations": [{"op": "remove_annotation", "id": "spectrum_title",
        "expected_annotation": spec["native_annotations"]["items"][0]}]}
    assert Draft202012Validator(schema).is_valid(request)
    assert not Draft202012Validator(schema).is_valid({**request, "operations": [
        {"op": "set_sample_style", "samples": ["Exact A"], "style": {"width": "0.7pt"}}]})
    assert Draft202012Validator(capabilities["response_schema"]).is_valid(
        {"accept_preview": True, "expected_operation_id": "a" * 64})
    assert "sections" not in capabilities


@pytest.mark.parametrize("operations", [[], ["unknown"], [None]])
def test_unknown_operation_is_rejected_before_runtime_or_project_read(saved, monkeypatch, operations):
    root, _, doctor_calls = saved
    monkeypatch.setattr(context, "inspect_project", lambda *a, **kw: pytest.fail("invalid schema reached project"))
    with pytest.raises(TaskControlError, match="advertised"):
        context.edit_context(root, operations=operations)
    assert not doctor_calls


def test_doctor_failure_blocks_without_promoting_readiness_or_emitting_request(saved, monkeypatch):
    root, _, _ = saved
    failure = {"id": "veusz", "status": "failed", "required": True, "detail": "missing runtime"}
    monkeypatch.setattr(context, "doctor_payload", lambda: {
        "kind": "sciplot_doctor", "status": "blocked", "checks": [failure], "next_actions": ["repair runtime"]})
    monkeypatch.setattr(context, "inspect_project", lambda *a, **kw: pytest.fail("failed runtime should stop early"))
    result = context.edit_context(root, operations=["set_sample_style"])
    assert result["status"] == "blocked" and result["doctor"]["failed_checks"] == [failure]
    assert "request_template" not in result
    assert result["next_step"] == {"action": "repair_runtime", "next_actions": ["repair runtime"]}


def write_task(tmp_path, project, *, pending=False):
    root = tmp_path / "task"
    root.mkdir()
    state = {"kind": "sciplot_task", "version": 1, "task_dir": str(root),
             "status": "needs_review" if pending else "complete", "phase": "previewing" if pending else "finished",
             "project": str(project), "request": {"version": 1, "action": "edit", "project": str(project),
                 "figure_id": "primary", "expected_document_sha256": "a" * 64,
                 "operations": [{"op": "set_sample_style", "samples": ["Exact A"], "style": {"width": "1pt"}}]},
             "operation_id": "b" * 64, "preview": {"image": {"path": "/already-reviewed/candidate.png"},
                 "scientific_audit": {"status": "passed"}}}
    save_task(root, state)
    return root


@pytest.mark.parametrize("file_target", [False, True])
def test_completed_task_resolves_current_project_once(saved, file_target):
    root, _, _ = saved
    task = write_task(root.parent, root)
    before = inventory(root.parent)
    result = context.edit_context(task / "task.json" if file_target else task, operations=["set_sample_style"])
    assert result["request_template"]["project"] == str(root)
    assert result["request_template"]["expected_document_sha256"] == file_sha256(root / "studio/document.vsz")
    assert inventory(root.parent) == before


def test_pending_task_returns_its_existing_review_without_discovery_or_new_request(saved):
    root, _, doctor_calls = saved
    task = write_task(root.parent, root, pending=True)
    before = inventory(root.parent)
    result = context.edit_context(task, operations=["remove_annotation"])
    assert result["status"] == "blocked" and result["reason_code"] == "unfinished_task"
    assert result["current_task"]["preview"]["scientific_audit"]["status"] == "passed"
    assert result["next_step"]["response_template"] == {"accept_preview": True, "expected_operation_id": "b" * 64}
    assert "request_template" not in result and not doctor_calls
    assert inventory(root.parent) == before


@pytest.mark.parametrize("source_update", [False, True])
def test_review_guidance_supplies_only_current_acceptance_bindings(source_update):
    state = {"status": "needs_review", "phase": "previewing", "task_dir": "/task",
             "request": {"action": "update_source" if source_update else "edit"},
             "revision_id": "a" * 64, "operation_id": "b" * 64}
    before = deepcopy(state)
    result = task_next_step(state)
    assert result["response_template"] == ({"accept_source_update": True, "expected_revision_id": "a" * 64}
        if source_update else {"accept_preview": True, "expected_operation_id": "b" * 64})
    assert state == before and result["action"] == "view_preview_then_decide"


def test_cli_context_accepts_repeated_operations_and_figure_without_full_discovery(saved, monkeypatch, capsys):
    root, _, _ = saved
    calls = []
    def fake(target, **kwargs):
        calls.append((target, kwargs))
        return {"kind": "sciplot_task_edit_context", "status": "ok", "request_template": {"operations": []}}
    monkeypatch.setattr(context, "edit_context", fake)
    args = build_parser().parse_args(["task", "edit-context", str(root), "--operation", "remove_annotation",
        "--operation", "set_sample_style", "--figure", "primary", "--json"])
    assert dispatch_task(args) == 0
    assert calls == [(root, {"operations": ["remove_annotation", "set_sample_style"], "figure_id": "primary"})]
    assert json.loads(capsys.readouterr().out)["kind"] == "sciplot_task_edit_context"
    with pytest.raises(SystemExit):
        build_parser().parse_args(["task", "edit-context", str(root), "--json"])
