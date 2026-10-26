"""Same-object native continuation is source-bound, selective and recoverable."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.plot_engine.errors import EngineError
from sciplot_core.workflow.native_suite_operations import (
    decide_native_object, describe_native_object, export_native_object, patch_native_object,
    resolve_native_object, resume_native_object,
)
from sciplot_core.workflow.rheology_tts_prepared import plot_prepared_suite
from sciplot_core.workflow.rheology_tts_style_storage import snapshot
from sciplot_core.workflow.rheology_tts_style_update import preview_suite_style
from sciplot_core.workflow.rheology_tts_tables import write_json
from test_rheology_tts_render import _native_settings


def _saved_command(workspace, delivery, request):
    from sciplot_core.project_store import FileProjectStore

    record, = [item for item in FileProjectStore(workspace, locations={"delivery": delivery}).commands()
               if item["metadata"]["request"].get("adapter") == "native_display"
               and item["metadata"]["request"].get("request") == request]
    return record


@pytest.fixture
def suite(tmp_path, monkeypatch):
    from sciplot_core.semantic_sources import rheology_tts

    def forbidden(*_args, **_kwargs):
        pytest.fail("Display continuation must not perform scientific analysis.")

    monkeypatch.setattr(rheology_tts, "analyze_tts_request", forbidden)
    source = tmp_path / "raw.csv"
    source.write_text("x,y\n3,10\n1,7\n1,9\n", encoding="utf-8")
    figure = {"id": "Main", "panels": [{"id": "graph1", "x_label": "ω (rad/s)", "y_label": "G′ (Pa)",
        "notes": [{"text": "Existing scientific note", "x": .03, "y": .94}],
        "series": [{"role": "measured_curve", "label": "220 °C", "x": [3, 1, 1], "y": [10, 7, 9]}]}]}
    optional = deepcopy(figure)
    optional["id"] = "SI_Optional"
    plan = {"version": 1, "figure_layout": "prepared",
        "source_binding": {"sources": [{"path": str(source), "sha256": file_sha256(source)}]},
        "transform_ledger": {"processing": "Caller supplied; no fitting", "units": {"x": "rad/s", "y": "Pa"}},
        "figures": [figure, optional]}
    prepared, request = tmp_path / "plan.json", tmp_path / "request.json"
    write_json(prepared, plan)
    write_json(request, {"version": 1, "prepared_plan": str(prepared), "out": str(tmp_path / "Figures")})
    created = plot_prepared_suite(request)
    workspace, delivery = Path(created["workspace"]), Path(created["delivery"])
    manifest = json.loads((workspace / "suite.json").read_text())
    return workspace, delivery, source, prepared, manifest


def _request(description, *, key="move-legend", changes=None):
    return {"plot_id": description["plot_id"], "base_revision": description["revision"],
        "idempotency_key": key, "intent_class": "presentation", "changes": changes or [{
            "op": "set", "target": ["legend:graph1"], "property": "legend.location", "value": "top-right"}]}


def _accept(result):
    return result["next_step"]["request"]


def _add_opaque_label(path):
    import subprocess
    import sys
    from sciplot_core.veusz_runtime import veusz_worker_environment

    script = """
import sys
from sciplot_core.studio_core.runtime import _ensure_veusz_on_path
_ensure_veusz_on_path()
from sciplot_core.studio_core.qt_compat import ensure_veusz_loader_compat, ensure_veusz_qsettings_compat
ensure_veusz_loader_compat(); ensure_veusz_qsettings_compat()
from PyQt6 import QtWidgets
from veusz import document, dataimport, widgets
from veusz.document import CommandInterface
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
doc = document.Document(); doc.load(sys.argv[1]); doc._sciplot_write_full_precision = True
interface = CommandInterface(doc); interface.To('/page1/graph1')
interface.Add('label', name='human_note', autoadd=False); interface.To('human_note')
interface.Set('label', 'Opaque human note'); interface.Set('Text/color', '#884400')
interface.Set('xPos', [.45]); interface.Set('yPos', [.25]); interface.Save(sys.argv[1])
"""
    subprocess.run([sys.executable, "-c", script, str(path)], env=veusz_worker_environment(),
                   capture_output=True, text=True, check=True)


@pytest.mark.comprehensive
def test_prepared_same_object_display_delta_preserves_science_native_and_optional(suite, monkeypatch):
    from sciplot_core import rheology_tts_render
    from sciplot_core.foundation.json_hashing import canonical_json_sha256
    from sciplot_core.project_store import FileProjectStore

    workspace, delivery, source, prepared, manifest = suite
    native, optional = [Path(item["path"]) for item in manifest["documents"]]
    _native_settings(native, edits=[("/page1/graph1/x/label", "Manual native axis"),
        ("/page1/graph1/key1/Text/size", "9pt"), ("/page1/graph1/key1/horzPosn", "centre")])
    _add_opaque_label(native)
    protected = snapshot([source, prepared, workspace / "figure_plan.json", delivery / "data/figure_plan.json",
        *(Path(item["spec_path"]) for item in manifest["native_result"]["figures"]), optional,
        *(Path(path) for path in manifest["documents"][1]["exports"])])
    optional_description = describe_native_object(optional, description={"scope": "summary"})
    description = describe_native_object(native, description={"scope": "summary"})
    assert description["plot_type"] == "LegacyPlot"
    assert set(description["edit_targets"]) == {"legend:graph1", "annotation:graph1:note_0"}
    assert describe_native_object(native, description={"scope": "edit", "target": "legend:graph1",
        "property": "legend.location"})["current_value"] is None  # manual native position
    assert resolve_native_object(workspace, "Main")["plot"] == str(native)
    with pytest.raises(ValueError, match="separated layout"):
        preview_suite_style(workspace)  # explicit template restoration retains its guard
    calls, dispatch = [], rheology_tts_render._dispatch

    def record(request):
        calls.append((request["action"], request.get("figure", {}).get("id")))
        return dispatch(request)

    monkeypatch.setattr(rheology_tts_render, "_dispatch", record)
    request = _request(description, changes=[
        {"op": "set", "target": ["legend:graph1"], "property": "legend.location", "value": "top-right"},
        {"op": "set", "target": ["annotation:graph1:note_0"], "property": "annotation.y", "value": .82},
        {"op": "set", "target": ["annotation:graph1:note_0"], "property": "annotation.text", "value": "Repositioned note"}])
    before = file_sha256(native)
    preview = patch_native_object(native, request)
    assert preview["status"] == "needs_review" and file_sha256(native) == before
    assert patch_native_object(native, request)["decision_id"] == preview["decision_id"]
    result = decide_native_object(native, _accept(preview))
    assert result["status"] == "complete" and result["scientific_hash_changed"] is False
    assert result["transform_execution"]["executed"] == []
    assert len(result["exports"]) == 3
    assert patch_native_object(native, request)["replayed"] is True  # original base after commit
    assert decide_native_object(native, _accept(preview))["replayed"] is True
    assert calls == [("audit", "Main"), ("display_state", "Main"), ("display_patch", "Main"), ("export", "Main")]
    store = FileProjectStore(workspace, locations={"delivery": delivery})
    records = store.commands()
    audited, = [item for item in records if item["metadata"]["request"].get("adapter") == "native_saved_audit"]
    imported, = [item for item in records if item["metadata"]["request"].get("adapter") == "native_saved_import"]
    assert audited["phase"] == imported["phase"] == "complete"
    audit = audited["result"]["audit"]
    assert audit["status"] == "passed" and audit["document_sha256"] == before
    assert imported["metadata"]["native_adoptions"] == [{"resource": store.logical_path(native),
        "before_sha256": audited["metadata"]["request"]["before"], "observed_sha256": before,
        "audit_sha256": canonical_json_sha256(audit)}]
    assert _saved_command(workspace, delivery, request)["read_set"][store.logical_path(native)] == before
    assert snapshot([Path(path) for path in protected]) == protected
    values = _native_settings(native, reads=["/page1/graph1/x/label", "/page1/graph1/key1/Text/size",
        "/page1/graph1/key1/horzPosn", "/page1/graph1/note_0/yPos", "/page1/graph1/note_0/label"])
    assert list(values.values()) == ["Manual native axis", "9pt", "right", [.82], "Repositioned note"]
    assert _native_settings(native, reads=["/page1/graph1/human_note/label", "/page1/graph1/human_note/Text/color",
        "/page1/graph1/human_note/xPos", "/page1/graph1/human_note/yPos"]) == {
        "/page1/graph1/human_note/label": "Opaque human note", "/page1/graph1/human_note/Text/color": "#884400",
        "/page1/graph1/human_note/xPos": [.45], "/page1/graph1/human_note/yPos": [.25]}
    assert describe_native_object(optional, description={"scope": "summary"})["revision"] == optional_description["revision"]
    assert describe_native_object(native, description={"scope": "summary"})["scientific_hash"] == description["scientific_hash"]
    assert not (workspace / "analysis.json").exists()
    calls_before = len(calls)
    source.write_text("controlled stale-source fault\n", encoding="utf-8")
    historical = patch_native_object(native, request)
    assert historical["status"] == "complete" and historical["replayed"] is True
    assert historical["ready_to_use"] is False and historical["current_state_matches"] is False
    assert historical["export_status"] == "unknown"
    assert historical["exports"] == []
    assert len(calls) == calls_before


@pytest.mark.comprehensive
def test_selected_export_and_edit_ignore_missing_optional_native_and_spec(suite, monkeypatch):
    from sciplot_core import rheology_tts_render

    workspace, _delivery, _source, _prepared, manifest = suite
    native, optional = [Path(item["path"]) for item in manifest["documents"]]
    from sciplot_core.workflow.native_suite_storage import operation_path

    optional_context = resolve_native_object(optional)
    broken = operation_path(optional_context, "broken-optional-transaction")
    broken.parent.mkdir(parents=True)
    broken.write_text("{broken unrelated optional transaction", encoding="utf-8")
    optional.unlink()
    Path(manifest["native_result"]["figures"][1]["spec_path"]).unlink()
    original_optional = snapshot([Path(path) for path in manifest["documents"][1]["exports"]])
    description = describe_native_object(native, description={"scope": "summary"})
    request = _request(description)
    preview = patch_native_object(native, request)
    decided = decide_native_object(native, _accept(preview))
    assert decided["status"] == "complete"
    calls, dispatch = [], rheology_tts_render._dispatch

    def record(request):
        calls.append(request)
        return dispatch(request)

    monkeypatch.setattr(rheology_tts_render, "_dispatch", record)
    result = export_native_object(native)
    assert result["selected_figures"] == ["Main"] and result["scope"] == "single_figure"
    assert len(calls) == 1 and calls[0]["action"] == "export_batch"
    assert [item["figure"]["id"] for item in calls[0]["documents"]] == ["Main"]
    resumed = resume_native_object(native, {key: request[key] for key in (
        "plot_id", "base_revision", "idempotency_key")})
    assert resumed["replayed"] is True and resumed["ready_to_use"] is True
    assert resumed["exports"] == result["exports"]
    for exported in resumed["exports"]:
        assert exported["sha256"] == file_sha256(Path(exported["path"]))
    assert len(calls) == 1  # replay checks current receipts, never executes the native worker
    assert snapshot([Path(path) for path in original_optional]) == original_optional
    assert not optional.exists()
    Path(manifest["documents"][0]["exports"][0]).unlink()
    current = describe_native_object(native, description={"scope": "summary"})
    unchanged = patch_native_object(native, _request(current, key="no-op-missing-export"))
    assert unchanged["changed"] is False and unchanged["ready_to_use"] is False
    assert unchanged["export_status"] == "pending" and unchanged["next_step"]["action"] == "plot.export"
    assert unchanged["exports"] == []


@pytest.mark.comprehensive
def test_export_failure_resume_and_publication_retry_do_not_apply_twice(suite, monkeypatch):
    from sciplot_core import rheology_tts_render
    from sciplot_core.project_store import state

    workspace, _delivery, _source, _prepared, manifest = suite
    native = Path(manifest["documents"][0]["path"])
    description = describe_native_object(native, description={"scope": "summary"})
    request = _request(description)
    counts, dispatch = {}, rheology_tts_render._dispatch

    def fail_export_once(payload):
        action = payload["action"]
        counts[action] = counts.get(action, 0) + 1
        if action == "export" and counts[action] == 1:
            raise RuntimeError("transient native export failure")
        return dispatch(payload)

    monkeypatch.setattr(rheology_tts_render, "_dispatch", fail_export_once)
    before = snapshot([native, *(Path(path) for path in manifest["documents"][0]["exports"])])
    failure = patch_native_object(native, request)
    assert failure["status"] == "blocked" and "transient" in failure["error"]["message"]
    assert snapshot([Path(path) for path in before]) == before
    preview = resume_native_object(native, failure["next_step"]["request"])
    assert preview["status"] == "needs_review" and counts["display_patch"] == 1 and counts["export"] == 2
    boundary = state.boundary

    def fail_publication(name):
        if name == "before_head":
            raise OSError("transient publication failure")
        return boundary(name)

    monkeypatch.setattr(state, "boundary", fail_publication)
    with pytest.raises(OSError, match="publication failure"):
        decide_native_object(native, _accept(preview))
    assert snapshot([Path(path) for path in before]) == before
    monkeypatch.setattr(state, "boundary", boundary)
    result = decide_native_object(native, _accept(preview))
    assert result["status"] == "complete" and counts["display_patch"] == 1 and counts["export"] == 2
    assert patch_native_object(native, request)["replayed"] is True
    altered = deepcopy(request)
    altered["changes"][0]["value"] = "bottom-right"
    with pytest.raises(EngineError, match="exact original identity") as conflict:
        patch_native_object(native, altered)
    assert conflict.value.reason_code == "document_idempotency_conflict"


@pytest.mark.comprehensive
def test_stale_unknown_and_rejected_changes_preserve_native(suite):
    _workspace, _delivery, _source, _prepared, manifest = suite
    native = Path(manifest["documents"][0]["path"])
    description = describe_native_object(native, description={"scope": "summary"})
    request = _request(description)
    before = file_sha256(native)
    invalid = deepcopy(request)
    invalid["changes"][0]["target"] = ["legend:missing"]
    with pytest.raises(EngineError, match="advertised target"):
        patch_native_object(native, invalid)
    _native_settings(native, edits=[("/page1/graph1/key1/Text/size", "9pt")])
    with pytest.raises(EngineError, match="current object revision"):
        patch_native_object(native, request)
    current = describe_native_object(native, description={"scope": "summary"})
    request = _request(current)
    changed = file_sha256(native)
    preview = patch_native_object(native, request)
    decision = {**_accept(preview), "accept": False}
    assert decide_native_object(native, decision)["status"] == "rejected"
    assert patch_native_object(native, request)["status"] == "rejected"
    assert file_sha256(native) == changed != before


@pytest.mark.comprehensive
def test_publication_reply_loss_recovers_exact_installed_candidate_without_reapplication(suite, monkeypatch):
    from sciplot_core import rheology_tts_render
    from sciplot_core.project_store import state

    workspace, delivery, _source, _prepared, manifest = suite
    native = Path(manifest["documents"][0]["path"])
    description = describe_native_object(native, description={"scope": "summary"})
    request = _request(description)
    preview = patch_native_object(native, request)
    save, fail = state.save_command, True

    def lose_completion(io, record):
        nonlocal fail
        if record["phase"] == "complete" and fail:
            fail = False
            raise OSError("lost completion after successful native publication")
        return save(io, record)

    monkeypatch.setattr(state, "save_command", lose_completion)
    before = file_sha256(native)
    with pytest.raises(OSError, match="after successful"):
        decide_native_object(native, _accept(preview))
    assert file_sha256(native) != before
    installed = snapshot([native, *(Path(name) for name in manifest["documents"][0]["exports"])])
    pending = _saved_command(workspace, delivery, request)
    assert pending["accepted"] is True and pending["phase"] == "accepted"
    assert pending["projection_pending"] is True

    def forbid_native(_request):
        pytest.fail("Exact-installed recovery must not execute native work again.")

    monkeypatch.setattr(rheology_tts_render, "_dispatch", forbid_native)
    recovered = decide_native_object(native, _accept(preview))
    assert recovered["status"] == "complete"
    evidence = _saved_command(workspace, delivery, request)
    assert evidence["phase"] == "complete" and evidence["generation"] == pending["install_generation"]
    assert evidence["decision_id"] == pending["decision_id"]
    assert evidence["draft"] == pending["draft"]
    assert snapshot([Path(name) for name in installed]) == installed
    assert patch_native_object(native, request)["replayed"] is True


@pytest.mark.comprehensive
@pytest.mark.parametrize("stage", ["apply", "export"])
def test_native_save_after_successful_owner_cannot_mint_a_verified_revision(suite, monkeypatch, stage):
    from sciplot_core.project_store import state
    from sciplot_core.workflow import rheology_tts_suite as suite_owner

    workspace, delivery, source, prepared, manifest = suite
    native = Path(manifest["documents"][0]["path"])
    description = describe_native_object(native, description={"scope": "summary"})
    request = _request(description)
    preview = patch_native_object(native, request)
    scientific = snapshot([source, prepared])

    def native_save():
        _native_settings(native, edits=[("/page1/graph1/x/label", "Concurrent native save")])

    if stage == "apply":
        boundary = state.boundary

        def save_after_apply(name):
            if name == "before_reply":
                native_save()
            return boundary(name)

        monkeypatch.setattr(state, "boundary", save_after_apply)
        decided = decide_native_object(native, _accept(preview))
        # The committed revision remains historical; a later foreign native
        # save must never acquire its current/ready authority.
        assert decided["ready_to_use"] is False and decided["current_state_matches"] is False
        assert decided["exports"] == [] and decided["export_status"] == "unknown"
    else:
        decided = decide_native_object(native, _accept(preview))
        assert decided["ready_to_use"] is True
        export = suite_owner._export_saved_suite

        def save_after_export(*args, **kwargs):
            result = export(*args, **kwargs)
            native_save()
            return result

        monkeypatch.setattr(suite_owner, "_export_saved_suite", save_after_export)
        with pytest.raises(EngineError, match="changed after verified"):
            export_native_object(native)
    updated = json.loads((workspace / "suite.json").read_text())
    receipt = next(item for item in updated["last_export"] if Path(item["document"]) == native)
    assert file_sha256(native) != receipt["document_sha256"]
    record = _saved_command(workspace, delivery, request)
    assert record["phase"] == "complete" and record["accepted"] is True
    assert record["result"]["revision"] == decided["revision"]
    assert record["result"]["presentation_hash"] == receipt["document_sha256"]
    assert _native_settings(native, reads=["/page1/graph1/x/label"])["/page1/graph1/x/label"] == "Concurrent native save"
    assert snapshot([Path(name) for name in scientific]) == scientific


@pytest.mark.comprehensive
def test_backend_owns_foreground_role_order_without_reordering_science_or_legend(tmp_path):
    from sciplot_core.rheology_tts_render import inspect_tts_display, render_tts_figures
    from sciplot_core.rheology_tts_style import prepare_tts_presentation
    from test_rheology_tts_style import _processed

    plan = _processed(("context_curve", "context_curve", "fitting_region_points", "fitting_region_points"))
    source = tmp_path / "source.csv"
    source.write_text("Synthetic role-order evidence\n", encoding="utf-8")
    plan["source_binding"]["sources"] = [{"path": str(source), "sha256": file_sha256(source)}]
    rows = plan["figures"][0]["panels"][0]["series"]
    for index, row in enumerate(rows):
        row.pop("color")
        row["color_index"] = index % 2
        row["label"] = f"Context {index}" if index < 2 else ""
    rows[2].update(x=[10, .1], y=[30, 10])
    rows[3].update(x=[1], y=[20])
    supplied = deepcopy(plan)
    result = render_tts_figures(prepare_tts_presentation(plan), tmp_path / "native")["figures"][0]
    figure = json.loads(Path(result["spec_path"]).read_text())["figure"]
    assert plan == supplied
    assert [(item["x_values"], item["y_values"]) for item in figure["panels"][0]["series"]] == [
        (row["x"], row["y"]) for row in rows]
    native = Path(result["document"])
    state = inspect_tts_display(native, figure)
    plotted_order = [name for name in state["panel_widget_order"]["graph1"] if name.startswith("series_")]
    assert plotted_order == ["series_3", "series_4", "series_1", "series_2"]
    assert _native_settings(native, reads=["/page1/graph1/key1/order"])["/page1/graph1/key1/order"] == (
        "series_1,series_2,series_3,series_4")
    assert [item["legend_key"] for item in figure["panels"][0]["series"]] == ["Context 0", "Context 1", "", ""]
