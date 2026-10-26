"""Read-only native inspection cannot acquire export replacement authority."""

from pathlib import Path

import pytest

from sciplot_core.project_store import FileProjectStore, ProjectConflict
from sciplot_core.project_commands import ProjectCommands, ProjectCommandUnknown
from sciplot_core.foundation.source_locations import selected_source_resolver
from sciplot_core.workflow import native_suite_transactions as native
from sciplot_core.workflow.native_suite_generation import open_store
from sciplot_core.workflow.rheology_tts_style_storage import snapshot

from test_native_suite_project_commands import bound as bound, request


@pytest.mark.parametrize("drift", ["missing", "changed", "mode"])
def test_noop_with_unavailable_export_records_no_writes_and_replays_without_native(bound, monkeypatch, drift):
    workspace, delivery, source, documents, capture, calls, _export = bound
    plot = Path(documents[0]["path"])
    req = request(bound)
    req["changes"][0]["value"] = "top-left"
    store = open_store(workspace, delivery)
    artifact = Path(documents[0]["exports"][0])
    if drift == "missing":
        artifact.unlink()
    elif drift == "changed":
        artifact.write_bytes(b"foreign visible export")
    else:
        artifact.chmod((artifact.stat().st_mode & 0o777) ^ 0o200)
    drifted = snapshot([artifact]) if artifact.exists() else {}
    protected = snapshot([source, plot, Path(documents[1]["path"]),
                          *(Path(name) for name in documents[1]["exports"])])
    inspections = []

    def inspect(context):
        inspections.append(context["figure_id"])
        return capture(context)

    monkeypatch.setattr(native, "capture_object", inspect)
    result = native.patch_native(plot, req)
    assert result["changed"] is False and result["status"] == "complete"
    assert result["exports"] == [] and result["export_status"] == "pending" and result["ready_to_use"] is False
    assert result["next_step"]["action"] == "plot.export"
    records = store.commands()
    assert len(records) == 1 and records[0]["write_set"] == [] and records[0]["phase"] == "complete"
    assert records[0]["metadata"]["request"]["request"] == req
    assert calls == [] and inspections == ["A"]

    def forbidden(_context):
        pytest.fail("Saved no-op must not inspect or execute native work again")

    monkeypatch.setattr(native, "capture_object", forbidden)
    assert native.patch_native(plot, req)["replayed"] is True
    assert native.resume_native(plot, {key: req[key] for key in ("plot_id", "base_revision", "idempotency_key")})["replayed"] is True
    assert snapshot([Path(name) for name in protected]) == protected
    assert snapshot([artifact]) == drifted if artifact.exists() else drift == "missing"


def test_lost_completed_inspection_reply_resumes_without_another_inspection(bound, monkeypatch):
    plot = Path(bound[3][0]["path"])
    req = request(bound)
    execute = ProjectCommands.execute
    fail = True

    def reply_loss(app, command, callback):
        nonlocal fail
        result = execute(app, command, callback)
        if fail and command.to_payload()["request"].get("adapter") == "native_display_inspection":
            fail = False
            raise OSError("reply lost after completed inspection")
        return result

    monkeypatch.setattr(ProjectCommands, "execute", reply_loss)
    with pytest.raises(OSError, match="completed inspection"):
        native.patch_native(plot, req)
    assert not bound[5]

    def forbidden(_context):
        pytest.fail("A completed inspection cannot run again")

    monkeypatch.setattr(native, "capture_object", forbidden)
    preview = native.resume_native(plot, {key: req[key] for key in ("plot_id", "base_revision", "idempotency_key")})
    assert preview["status"] == "needs_review" and bound[5] == ["patch", "export"]
    assert native.decide_native(plot, preview["next_step"]["request"])["status"] == "complete"
    assert bound[5] == ["patch", "export"]


@pytest.mark.parametrize("phase", ["inspection", "candidate"])
def test_unknown_parent_or_child_never_repeats_inspection_or_effects(bound, monkeypatch, phase):
    plot = Path(bound[3][0]["path"])
    req = request(bound)
    entered = FileProjectStore.mark_applying
    transitions = []

    def fail_after_entering(store, key, digest):
        result = entered(store, key, digest)
        adapter = store.query(key)["metadata"]["request"]["adapter"]
        transitions.append(adapter)
        if adapter == ("native_display_inspection" if phase == "inspection" else "native_display"):
            raise OSError("controlled loss after applying transition")
        return result

    monkeypatch.setattr(FileProjectStore, "mark_applying", fail_after_entering)
    with pytest.raises(OSError, match="applying transition"):
        native.patch_native(plot, req)
    assert bound[5] == []
    with pytest.raises(ProjectCommandUnknown):
        native.patch_native(plot, req)
    with pytest.raises(ProjectCommandUnknown):
        native.resume_native(plot, {key: req[key] for key in ("plot_id", "base_revision", "idempotency_key")})
    assert transitions == (["native_display_inspection"] if phase == "inspection" else ["native_display_inspection", "native_display"])
    assert bound[5] == []


def test_candidate_reenters_current_runtime_without_rejecting_unrelated_figure(bound, monkeypatch):
    a, b = [Path(item["path"]) for item in bound[3]]
    req_a, req_b = request(bound, "A", "A"), request(bound, "B", "B")
    execute, prepare = ProjectCommands.execute, native._prepare
    changed_b = []
    observed = []

    def complete_other_figure(app, command, callback):
        result = execute(app, command, callback)
        wire = command.to_payload()["request"]
        if wire.get("adapter") == "native_display_inspection" and wire["figure_id"] == "A" and not changed_b:
            changed_b.append(True)
            b_preview = native.patch_native(b, req_b)
            native.decide_native(b, b_preview["next_step"]["request"])
            changed_b.append(b.read_bytes())
        return result

    def current_runtime(context, captured, request, diff, changes, store):
        selected = selected_source_resolver()
        assert selected.store.root == store.root and selected.generation == store.snapshot()["generation"]
        observed.append(context["figure_id"])
        return prepare(context, captured, request, diff, changes, store)

    monkeypatch.setattr(ProjectCommands, "execute", complete_other_figure)
    monkeypatch.setattr(native, "_prepare", current_runtime)
    a_preview = native.patch_native(a, req_a)
    native.decide_native(a, a_preview["next_step"]["request"])
    assert observed == ["B", "A"] and b.read_bytes() == changed_b[1]
    assert bound[5] == ["patch", "export", "patch", "export"]


def test_real_delta_keeps_foreign_export_closed_then_resumes_frozen_inspection(bound, monkeypatch):
    workspace, delivery, _source, documents, capture, calls, _export = bound
    plot = Path(documents[0]["path"])
    req = request(bound)
    store = open_store(workspace, delivery)
    artifact = Path(documents[0]["exports"][0])
    original = artifact.read_bytes()
    artifact.write_bytes(b"foreign export not authorized for replacement")
    inspections = []

    def inspect(context):
        inspections.append(context["figure_id"])
        return capture(context)

    monkeypatch.setattr(native, "capture_object", inspect)
    with pytest.raises(ProjectConflict, match="Outside bytes changed a declared project read"):
        native.patch_native(plot, req)
    assert calls == [] and inspections == ["A"]
    assert all(record["phase"] == "complete" for record in store.commands())
    artifact.write_bytes(original)
    preview = native.patch_native(plot, req)
    assert preview["status"] == "needs_review" and inspections == ["A"] and calls == ["patch", "export"]
    result = native.decide_native(plot, preview["next_step"]["request"])
    assert result["status"] == "complete" and calls == ["patch", "export"]
    assert native.patch_native(plot, req)["replayed"] is True
