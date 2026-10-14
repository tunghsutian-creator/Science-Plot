"""Discriminating common-intent compilation, CLI and durable recovery coverage."""

from argparse import ArgumentParser
from copy import deepcopy
import json
from pathlib import Path

import pytest
from test_plot_typed_intent import _document
from test_plot_typed_intent_recovery import _engine
from test_plot_engine import SimulatedCrash

from sciplot_core.cli.parsers.common_edits import register_common_edit_command
from sciplot_core.cli.dispatch import common_edits as cli
from sciplot_core.plot_engine.errors import EngineError
from sciplot_core.plot_engine.managed_updates import prepare_update
from sciplot_core.plot_engine.storage import load_head, read
from sciplot_core.plot_ir.figure_document import figure_spec, store_spec
from sciplot_core.task_common_edits import common_edit_capabilities, compile_common_edit, edit_task, normalize_common_edit
from sciplot_core import task_common_edits as edits


def test_closed_chinese_english_and_explicit_flags_normalize_to_identical_intent():
    expected = {"palette": "tol_bright", "font_size": "9pt", "legend_font_size": "7pt"}
    assert normalize_common_edit(intent="换配色 tol_bright；统一字号 9pt；图例字号 7pt") == expected
    assert normalize_common_edit(intent="palette tol_bright; font size 9pt; legend font size 7pt") == expected
    assert normalize_common_edit(**expected) == expected
    assert normalize_common_edit(intent="隐藏图例") == {"legend_visible": False}
    assert normalize_common_edit(intent="legend position 0.8,0.9") == {"legend_position": [.8, .9]}


@pytest.mark.parametrize("options", [
    {}, {"intent": "把图弄好看"}, {"intent": "换配色 蓝色"}, {"intent": "font size 9"},
    {"intent": "font size 9pt; font size 10pt"}, {"intent": "hide legend; show legend"},
    {"intent": "palette tol_bright;"}, {"intent": "font size 9pt", "font_size": "10pt"},
    {"font_size": "0pt"}, {"font_size": "2pt"}, {"font_size": 9}, {"legend_visible": "false"},
    {"legend_position": [True, .5]}, {"legend_position": [float('nan'), .5]},
    {"legend_position": "best"}, {"palette": "PRIVATE"}, {"font_family": "\n"},
    {"scientific": True}, {"palette": ["tol_bright"]},
])
def test_invalid_or_ambiguous_input_has_zero_document_or_task_mutation(monkeypatch, tmp_path, options):
    monkeypatch.setattr(edits, "doctor_payload", lambda: pytest.fail("queried invalid input"))
    monkeypatch.setattr(edits, "PlotService", lambda: pytest.fail("opened invalid input"))
    with pytest.raises(EngineError) as error:
        edit_task(tmp_path / "never-opened", task_dir=tmp_path / "never-reserved", **options)
    assert error.value.repair["request_executed"] is False
    assert not list(tmp_path.iterdir())


def test_batch_changes_only_requested_fields_and_preserves_all_science_and_style(tmp_path):
    document = _document(tmp_path, annotation=True)
    spec = figure_spec(document)
    spec["theme"] = {
        "project": {"line": {"line_style": "dash"}}, "figure": {"axis": {"font_weight": "bold"}}}
    spec["views"][0]["style"] = {"annotation": {"font_size_pt": 5, "color": "#123456"}}
    spec["views"][0]["axes"][0]["style"] = {"font_family": "Arial", "line_width_pt": 1.3, "tick_direction": "out"}
    spec["views"][0]["layers"][0]["marks"][0]["style"] = {"line_width_pt": 2.1, "line_style": "dot"}
    spec["guides"][0]["style"] = {"font_weight": "bold", "frame_visible": True}
    document = store_spec(document, spec)
    before = deepcopy(document)
    request = compile_common_edit(document, normalize_common_edit(palette="tol_bright", font_size="9pt", font_family="Helvetica", legend_font_size="7pt"), "one")
    after, diff, risk, execute = prepare_update(document, request)
    changed = figure_spec(after)
    assert risk == "presentation" and not execute
    assert after["scientific_hash"] == before["scientific_hash"]
    assert after["scientific"] == before["scientific"] and document == before
    assert changed["composition"] == spec["composition"] and changed["layout"] == spec["layout"]
    assert changed["scales"] == spec["scales"]
    expected = deepcopy(spec)
    for kind in ("axis", "legend", "annotation", "text"):
        expected["theme"]["figure"][kind] = {**expected["theme"]["figure"].get(kind, {}), "font_family": "Helvetica", "font_size_pt": 9.}
    expected["views"][0]["style"]["annotation"]["font_size_pt"] = 9.
    for item in [*expected["views"][0]["axes"], *expected["annotations"], *expected["guides"]]:
        item["style"].update(font_family="Helvetica", font_size_pt=9.)
    expected["guides"][0]["style"]["font_size_pt"] = 7.
    for mark in expected["views"][0]["layers"][0]["marks"]:
        mark["style"]["line_color" if mark["type"] == "line" else "marker_color"] = "#4477aa"
    assert changed == expected and diff
    assert (tmp_path / "figure.csv").read_text() == "Frequency,Modulus\nHz,Pa\n0,1\n5,5\n10,15\n"


@pytest.mark.parametrize("change", ["nonmeasurement", "bar", "too_many", "no_legend", "v2_hide", "v2_position"])
def test_current_authority_and_palette_ambiguity_fail_closed(tmp_path, change):
    document = _document(tmp_path)
    spec = figure_spec(document)
    options = {"palette": "tol_bright"}
    layer = spec["views"][0]["layers"][0]
    if change == "nonmeasurement":
        layer["role"] = "prediction"
    elif change == "bar":
        layer["marks"] = [{"id": "mark:bar", "type": "bar", "baseline": 0, "width_data": 1, "style": {}}]
    elif change == "too_many":
        # The compiler checks the complete current target inventory; it never cycles colors.
        spec["views"][0]["layers"] = [deepcopy(layer) for _ in range(8)]
    elif change == "no_legend":
        spec["guides"] = []
        options = {"legend_font_size": "7pt"}
    elif change == "v2_hide":
        options = {"legend_visible": False}
    else:
        options = {"legend_position": [.8, .9]}
    if change == "too_many":
        # Deliberately bypass document revalidation to isolate target-count guard.
        monkey_spec = spec
        from unittest.mock import patch
        with patch.object(edits, "figure_spec", return_value=monkey_spec), pytest.raises(EngineError):
            compile_common_edit(document, options, "bad")
    else:
        document = store_spec(document, spec)
        before = deepcopy(document)
        with pytest.raises(EngineError):
            compile_common_edit(document, options, "bad")
        assert document == before


def test_legacy_uses_only_advertised_shadow_properties_and_retains_other_native_state():
    document = {"plot_type": "LegacyPlot", "plot_id": "old", "revision": 4,
        "presentation": {"objects": {
            "s": {"kind": "series", "properties": {}, "capabilities": {"style.line.color": {"type": "color"}}},
            "a": {"kind": "axis", "properties": {}, "capabilities": {"font.size": {"type": "physical_size"}}},
            "g": {"kind": "legend", "properties": {}, "capabilities": {"font.size": {"type": "physical_size"}, "legend.visible": {"type": "boolean"}, "legend.position": {"type": "number_pair"}}}}}}
    patch = compile_common_edit(document, normalize_common_edit(palette="tol_bright", font_size="9pt", legend_font_size="7pt", legend_visible=False, legend_position=[.8, .9]), "old-key")
    values = {(item["target"][0], item["property"]): item["value"] for item in patch["changes"]}
    assert values == {("s", "style.line.color"): "#4477AA", ("a", "font.size"): "9pt", ("g", "font.size"): "7pt", ("g", "legend.visible"): False, ("g", "legend.position"): [.8, .9]}
    with pytest.raises(EngineError) as error:
        compile_common_edit(document, {"font_family": "Arial"}, "bad")
    assert error.value.reason_code == "common_edit_unavailable"


@pytest.fixture
def ready(monkeypatch):
    monkeypatch.setattr(edits, "doctor_payload", lambda: {"kind": "sciplot_doctor", "status": "ready", "checks": []})


def test_lost_success_reply_and_same_intent_replay_preserve_original_request_and_one_revision(tmp_path, monkeypatch, ready):
    service, root, backend, source, native = _engine(tmp_path)
    monkeypatch.setattr(service, "open", lambda *_a, **_k: {"status": "current", "plot": str(root), "plot_id": "intent-test", "revision": 0})
    entry = tmp_path / "edit-entry"
    original = service.patch
    requests = []
    def lost_reply(plot, request):
        requests.append(deepcopy(request))
        result = original(plot, request)
        assert result["status"] == "complete"
        raise ConnectionError("reply lost after committed export")
    monkeypatch.setattr(service, "patch", lost_reply)
    with pytest.raises(ConnectionError):
        edit_task(root, task_dir=entry, font_size="9pt", service=service)
    assert load_head(root)["document"]["revision"] == 1
    saved = read(entry / "semantic-edit.json")
    monkeypatch.setattr(service, "open", lambda *_a, **_k: pytest.fail("rebound original intent to fresh base"))
    monkeypatch.setattr(service, "patch", original)
    replay = edit_task(root, task_dir=entry, intent="统一字号 9pt", service=service)
    assert replay["replayed"] and replay["revision"] == 1 and backend.native_writes == 1
    assert saved["request"] == requests[0] and saved["request"]["base_revision"] == 0
    with pytest.raises(EngineError) as conflict:
        edit_task(root, task_dir=entry, font_size="10pt", service=service)
    assert conflict.value.reason_code == "document_idempotency_conflict"
    assert backend.native_writes == 1


def test_uncertain_apply_uses_original_engine_journal_and_can_recover_once(tmp_path, monkeypatch, ready):
    service, root, backend, source, native = _engine(tmp_path)
    monkeypatch.setattr(service, "open", lambda *_a, **_k: {"status": "current", "plot": str(root), "plot_id": "intent-test", "revision": 0})
    entry = tmp_path / "uncertain"
    apply = backend.apply
    def interrupted(binding, review):
        apply(binding, review)
        raise SimulatedCrash()
    monkeypatch.setattr(backend, "apply", interrupted)
    with pytest.raises(SimulatedCrash):
        edit_task(root, task_dir=entry, legend_font_size="7pt", service=service)
    monkeypatch.setattr(backend, "apply", apply)
    replay = edit_task(root, task_dir=entry, legend_font_size="7pt", service=service)
    assert replay["status"] == "complete" and load_head(root)["document"]["revision"] == 1
    assert backend.native_writes == 1


def test_cli_registration_and_dispatch_are_directly_runnable_without_request_file(monkeypatch, capsys):
    parser = ArgumentParser()
    register_common_edit_command(parser.add_subparsers(dest="task_action", required=True))
    args = parser.parse_args(["edit", "/saved path", "--palette", "tol_bright", "--font-size", "9pt", "--legend-font-size", "7pt", "--json"])
    calls = []
    monkeypatch.setattr(cli, "edit_task", lambda target, **options: calls.append((target, options)) or {"status": "complete", "revision": 1})
    assert cli.dispatch_common_edit(args) == 0
    assert calls[0][0] == Path("/saved path")
    assert calls[0][1]["font_size"] == "9pt" and calls[0][1]["legend_visible"] is None
    assert json.loads(capsys.readouterr().out) == {"status": "complete", "revision": 1}
    with pytest.raises(SystemExit):
        parser.parse_args(["edit", "/saved", "--hide-legend", "--show-legend"])
    capabilities = common_edit_capabilities()
    assert capabilities["model_required"] is False
    assert "font_family" in capabilities["availability"]["ManagedPlot_FigureSpec_v2"]
    assert "legend_visible" not in capabilities["availability"]["ManagedPlot_FigureSpec_v2"]


def test_export_pending_replays_committed_revision_without_reapplying(tmp_path, monkeypatch, ready):
    service, root, backend, source, native = _engine(tmp_path)
    monkeypatch.setattr(service, "open", lambda *_a, **_k: {"status": "current", "plot": str(root), "plot_id": "intent-test", "revision": 0})
    backend.export_failures = [RuntimeError("export failed after native commit")]
    entry = tmp_path / "pending-export"
    first = edit_task(root, task_dir=entry, font_size="9pt", service=service)
    assert first["status"] == "blocked" and first["export_status"] == "pending" and first["commit_status"] == "committed" and first["revision"] == 1
    assert backend.native_writes == 1
    before = load_head(root)["document"]
    monkeypatch.setattr(service, "open", lambda *_a, **_k: pytest.fail("queried today's base for export retry"))
    retried = edit_task(root, task_dir=entry, font_size="9pt", service=service)
    assert retried["status"] == "complete" and retried["revision"] == 1
    assert load_head(root)["document"] == before and backend.native_writes == 1


@pytest.mark.parametrize("description", [
    {"status": "stale", "changed_inputs": ["native"]},
    {"status": "dirty", "artifact_status": "missing"},
])
def test_currentness_and_pending_continuation_do_not_reserve_a_new_edit(tmp_path, monkeypatch, ready, description):
    class Reader:
        def open(self, *_a, **_k):
            return description
        def patch(self, *_a, **_k):
            pytest.fail("mutated unavailable current state")
    entry = tmp_path / "unallocated"
    result = edit_task(tmp_path / "target", task_dir=entry, font_size="9pt", service=Reader())
    assert result["status"] == "blocked" and result["current_status"] == description["status"]
    assert not entry.exists()


def test_task_entry_cannot_pollute_source_or_revision_storage(tmp_path, monkeypatch, ready):
    service, root, backend, source, native = _engine(tmp_path)
    monkeypatch.setattr(service, "open", lambda *_a, **_k: {"status": "current", "plot": str(root), "plot_id": "intent-test", "revision": 0})
    for entry in (root, root / "revisions" / "malicious", source):
        with pytest.raises(EngineError) as error:
            edit_task(root, task_dir=entry, font_size="9pt", service=service)
        assert error.value.reason_code == "task_path_overlap"
    assert backend.native_writes == 0 and load_head(root)["document"]["revision"] == 0
