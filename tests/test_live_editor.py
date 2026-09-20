"""Interactive state, save authority and loopback request boundaries."""

import copy
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.live_editor import session as module
from sciplot_core.live_editor.server import EditorHandler

pytestmark = pytest.mark.focused
SETTING = "/page1/graph1/S01/PlotLine/width"
OBJECT = "/page1/graph1/S01"


class Worker:
    def __init__(self, document, spec, output):
        output.mkdir(parents=True, exist_ok=True)
        self.output = output
        self.value = "1pt"
        self.history = [self.value]
        self.cursor = 0
        self.revision = 1
        self.closed = False
        self.calls = []

    @property
    def alive(self):
        return not self.closed

    def request(self, op, **kwargs):
        self.calls.append(op)
        if op == "set":
            change = kwargs["changes"][0]
            assert change["expected_value"] == self.value
            self.value = change["value"]
            self.history = self.history[:self.cursor + 1] + [self.value]
            self.cursor += 1
            self.revision += 1
        elif op in {"undo", "redo"}:
            self.cursor += -1 if op == "undo" else 1
            self.value = self.history[self.cursor]
            self.revision += 1
        path = self.output / f"{self.revision}.png"
        path.write_bytes(self.value.encode())
        state = {"render_revision": self.revision,
                 "preview": {"path": str(path), "sha256": file_sha256(path), "width": 100, "height": 100},
                 "objects": {OBJECT: {"name": "S01", "path": OBJECT, "type": "xy",
                                       "editable_fields": [{"setting_path": SETTING, "current_value": self.value,
                                                            "editor": "distance", "label": "Line width"}]}},
                 "can_undo": self.cursor > 0, "can_redo": self.cursor < len(self.history) - 1}
        return {"state": state, "object_path": OBJECT if op == "hit" else None}

    def close(self):
        self.closed = True


@pytest.fixture
def live(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    document, spec = project / "document.vsz", project / "spec.json"
    document.write_text("original native")
    spec.write_text('{"series": []}')
    figure = {"figure_id": "figure", "document": str(document), "spec": str(spec)}
    evidence = {"source": {"current": True}, "qa": {"current": True}, "delivery": {"current": True}}
    monkeypatch.setattr(module, "resolve_project_path", lambda path: project)
    monkeypatch.setattr(module, "resolve_project_figure", lambda *args: figure)
    monkeypatch.setattr(module, "inspect_project", lambda *args: copy.deepcopy(evidence))
    monkeypatch.setattr(module, "audit_edited_document", lambda *args: {})
    monkeypatch.setattr(module, "edit_state", lambda *args: {
        "project_files": {str(path.relative_to(project)): file_sha256(path)
                          for path in project.rglob("*") if path.is_file()},
        "delivery": str(tmp_path / "delivery"), "delivery_files": None,
    })
    monkeypatch.setattr(module, "new_preview_directory", lambda project, output: output)
    output = tmp_path / "session"
    output.mkdir()
    monkeypatch.setattr(module, "NativeWorker", Worker)
    session = module.LiveSession(project, output=output)
    session.test_evidence = evidence
    yield session
    session.close()


def command(live, action, **values):
    return live.command({"request_id": uuid4().hex, "revision": live.revision,
                         "action": action, **values})


def change(live, value="2pt"):
    return command(live, "set", changes=[{"object_path": OBJECT, "setting_path": SETTING,
                                          "expected_value": live.worker.value, "value": value}])


def test_native_changes_undo_redo_and_frame_identity_do_not_write_document(live):
    before = live.document.read_bytes()
    original_revision = live.revision
    assert not live.state()["dirty"]
    assert change(live)["state"]["dirty"]
    with pytest.raises(ValueError, match="过期"):
        live.preview_path(original_revision)
    assert not command(live, "undo")["state"]["dirty"]
    assert command(live, "redo")["state"]["dirty"]
    assert live.document.read_bytes() == before
    assert live.state()["can_undo"]


def test_same_request_retries_do_not_apply_twice_or_accept_changed_payload(live):
    request = {"request_id": "once", "revision": live.revision, "action": "set",
               "changes": [{"object_path": OBJECT, "setting_path": SETTING,
                            "expected_value": "1pt", "value": "2pt"}]}
    first = live.command(request)
    assert live.command(request) == first
    assert live.worker.calls.count("set") == 1
    with pytest.raises(ValueError, match="同一请求"):
        live.command({**request, "action": "undo"})


def test_stale_request_and_stale_displayed_frame_cannot_hit_or_mutate(live):
    original = live.revision
    change(live)
    with pytest.raises(ValueError, match="过期"):
        live.command({"request_id": "old", "revision": original, "action": "undo"})
    with pytest.raises(ValueError, match="加载完成"):
        command(live, "hit", preview_revision=original, x=20, y=30)
    assert "hit" not in live.worker.calls
    assert command(live, "hit", preview_revision=live.revision, x=20, y=30)["selected_object_path"] == OBJECT


def test_key_drag_binds_displayed_frame_to_native_revision(live, monkeypatch):
    original = live.worker.request
    payloads = []

    def request(op, **kwargs):
        if op == "move_key":
            payloads.append(kwargs)
        return original(op, **kwargs)

    monkeypatch.setattr(live.worker, "request", request)
    with pytest.raises(ValueError, match="加载完成"):
        command(live, "move_key", preview_revision=0, object_path=OBJECT, dx=10, dy=20)
    assert not payloads
    native_revision, revision = live.native["render_revision"], live.revision
    command(live, "move_key", preview_revision=revision, object_path=OBJECT, dx=10, dy=20)
    assert payloads == [{"object_path": OBJECT, "dx": 10, "dy": 20, "render_revision": native_revision}]
    assert live.revision == revision + 1


@pytest.mark.parametrize("kind", ["document", "source"])
def test_changed_canonical_or_original_source_blocks_unsaved_session(live, kind):
    change(live)
    if kind == "document":
        live.document.write_text("external native change")
    else:
        live.test_evidence["source"]["current"] = False
    with pytest.raises(ValueError, match="变化"):
        command(live, "save")
    assert live.state()["stale"] and live.state()["dirty"]


def test_save_requires_native_replay_equal_to_displayed_frame(live, monkeypatch):
    change(live)
    monkeypatch.setattr(module, "preview_document_edit", lambda *a, **k: {"preview": {"sha256": "different"}})
    monkeypatch.setattr(module, "apply_document_edit", lambda *a: pytest.fail("Mismatched preview must never be applied"))
    with pytest.raises(ValueError, match="原生重放"):
        command(live, "save", candidate={"path": "/untrusted.vsz"})
    assert live.document.read_text() == "original native" and live.state()["dirty"]


def test_save_derives_its_own_changes_preserves_native_history_and_rebases_dirty(live, monkeypatch):
    change(live)
    captured = []

    def preview(project, changes, **kwargs):
        captured.extend(changes)
        assert kwargs["expected_document_sha256"] == file_sha256(live.document)
        return {"preview": live.native["preview"]}

    def apply(project, review):
        live.document.write_text("saved 2pt native")
        return {"result_is_current": True, "result_sha256": file_sha256(live.document)}

    monkeypatch.setattr(module, "preview_document_edit", preview)
    monkeypatch.setattr(module, "apply_document_edit", apply)
    saved = command(live, "save", changes=[{"value": "attacker"}])
    assert captured == [{"object_path": OBJECT, "setting_path": SETTING, "expected_value": "1pt", "value": "2pt"}]
    assert not saved["state"]["dirty"] and saved["state"]["can_undo"]
    assert command(live, "undo")["state"]["dirty"]
    assert live._changes()[0] == {"object_path": OBJECT, "setting_path": SETTING, "expected_value": "2pt", "value": "1pt"}


def test_export_never_silently_saves_dirty_changes(live, monkeypatch):
    change(live)
    monkeypatch.setattr(module, "start_task", lambda *a, **k: pytest.fail("Dirty draft cannot export"))
    with pytest.raises(ValueError, match="先保存"):
        command(live, "export")


def test_dead_worker_cached_state_requires_reload_instead_of_false_reconnection(live):
    change(live)
    frame = live.state()["preview"]
    live.worker.close()
    state = live.state()
    assert state["stale"] and state["dirty"]
    assert "原生编辑会话已停止" in state["session_error"]
    assert state["preview"] == frame
    with pytest.raises(ValueError, match="原生编辑会话已停止"):
        command(live, "save")
    restored = command(live, "reload")["state"]
    assert not restored["stale"] and not restored["dirty"]
    assert restored["session_error"] is None and live.worker.alive


@pytest.mark.parametrize("key", ["qa", "delivery"])
@pytest.mark.parametrize("current", [False, None])
def test_complete_export_receipt_cannot_hide_invalid_current_evidence(live, monkeypatch, key, current):
    task = {"status": "complete", "task_dir": "/retained/export-receipt"}

    def export(*args, **kwargs):
        live.test_evidence[key]["current"] = current
        return task

    monkeypatch.setattr(module, "start_task", export)
    with pytest.raises(ValueError, match="当前 QA 或交付"):
        command(live, "export")
    state = live.state()
    assert state["stale"] and state["result"]["task"] == task


@pytest.mark.parametrize("relative", ["spec.json", "plot_request.json", "notes.json", "another.vsz"])
def test_save_does_not_rebase_external_changes_after_apply(live, monkeypatch, relative):
    target = live.project / relative
    target.write_text('{"before": true}')
    live.baseline = module.edit_state(live.project)
    baseline, saved_hash = copy.deepcopy(live.baseline), live.saved_hash
    change(live)
    monkeypatch.setattr(module, "preview_document_edit", lambda *a, **k: {"preview": live.native["preview"]})

    def apply(*args):
        live.document.write_text("saved 2pt native")
        target.write_text('{"foreign": true}')
        return {"operation_id": "committed-save", "result_is_current": True,
                "result_sha256": file_sha256(live.document)}

    monkeypatch.setattr(module, "apply_document_edit", apply)
    with pytest.raises(ValueError, match="保存已执行"):
        command(live, "save")
    assert live.stale and live.baseline == baseline and live.saved_hash == saved_hash
    assert live.state()["dirty"] and live.last_result["operation_id"] == "committed-save"
    assert target.read_text() == '{"foreign": true}'


@pytest.mark.parametrize("relative", ["spec.json", "plot_request.json", "notes.json", "another.vsz"])
def test_export_does_not_rebase_external_input_changes(live, monkeypatch, relative):
    target = live.project / relative
    target.write_text('{"before": true}')
    live.baseline = module.edit_state(live.project)
    baseline = copy.deepcopy(live.baseline)

    def export(*args, **kwargs):
        target.write_text('{"foreign": true}')
        return {"status": "complete", "task_dir": "completed-export"}

    monkeypatch.setattr(module, "start_task", export)
    with pytest.raises(ValueError, match="元数据发生变化"):
        command(live, "export")
    assert live.stale and live.baseline == baseline
    assert live.last_result["task"]["task_dir"] == "completed-export"


@pytest.mark.parametrize("foreign_metadata", [None, "source", "study", "plan"])
def test_export_accepts_publication_records_but_protects_manifest_inputs(live, monkeypatch, foreign_metadata):
    manifest = live.project / "intake_manifest.json"
    registry = live.project / "studio" / "figure_set.json"
    registry.parent.mkdir()
    figure_set = {"figures": [{"figure_id": "figure", "document": "document.vsz",
                               "document_state": {"sha256": "old"}, "document_authority": "generated"}]}
    original = {"source": {"sha256": "original-source"},
                "resolved_figure_plan": {"tasks": [{"figure_id": "figure"}], "outcomes": []},
                "study_model": {"sample_order": ["A", "B"],
                                "figure_queue": [{"id": "figure", "title": "Absorbance", "artifacts": []}]},
                "studio": {
        "spec": "spec.json", "figure_set": figure_set,
        "document_state": {"sha256": "old"}, "manual_edit_hash": "old"}}
    manifest.write_text(json.dumps(original))
    registry.write_text(json.dumps(figure_set))
    live.baseline = module.edit_state(live.project)

    def export(*args, **kwargs):
        updated = copy.deepcopy(original)
        updated["last_run"] = "new-run"
        updated["resolved_figure_plan"].update({"outcomes": [{"figure_id": "figure", "artifacts": ["new.pdf"]}],
                                               "status": "complete", "complete": True})
        updated["study_model"]["run"] = {"output": "new-run", "qa": {"passed": True}}
        updated["study_model"]["figure_queue"][0].update({"status": "rendered", "artifacts": ["new.pdf"]})
        updated["studio"].update({"exports": ["new.pdf"], "last_export_run": "new-run",
                                  "manual_edit_hash": "current", "document_state": {"sha256": "current"}})
        entry = updated["studio"]["figure_set"]["figures"][0]
        entry.update({"document_state": {"sha256": "current"}, "document_authority": "saved"})
        if foreign_metadata == "source":
            updated["source"]["sha256"] = "foreign-source"
        elif foreign_metadata == "study":
            updated["study_model"]["figure_queue"][0]["title"] = "Foreign interpretation"
        elif foreign_metadata == "plan":
            updated["resolved_figure_plan"]["tasks"][0]["figure_id"] = "another-figure"
        manifest.write_text(json.dumps(updated))
        registry.write_text(json.dumps(updated["studio"]["figure_set"]))
        for relative in ("studio/exports/current.pdf", "studio/logs/veusz_export_stderr.log",
                         "Open_in_Veusz.command"):
            target = live.project / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("publication output")
        return {"status": "complete"}

    monkeypatch.setattr(module, "start_task", export)
    if foreign_metadata:
        with pytest.raises(ValueError, match="元数据发生变化"):
            command(live, "export")
        assert live.stale
    else:
        assert command(live, "export")["result"]["task"]["status"] == "complete"
        assert live.baseline == module.edit_state(live.project) and not live.stale


def handler(headers):
    instance = object.__new__(EditorHandler)
    instance.server = SimpleNamespace(origin="http://127.0.0.1:8751", token="session-proof", cookie_name="sciplot_editor_8751")
    instance.headers = headers
    return instance


@pytest.mark.parametrize("headers", [
    {"Host": "attacker.test:8751", "X-SciPlot-Token": "session-proof"},
    {"Host": "127.0.0.1:8751", "Origin": "https://attacker.test", "X-SciPlot-Token": "session-proof"},
    {"Host": "127.0.0.1:8751", "Sec-Fetch-Site": "cross-site", "X-SciPlot-Token": "session-proof"},
    {"Host": "127.0.0.1:8751"},
])
def test_api_rejects_cross_origin_rebinding_and_missing_proof(headers):
    assert not handler(headers)._authorized(api=True)


def test_state_and_images_use_distinct_same_origin_session_proofs():
    headers = {"Host": "127.0.0.1:8751", "X-SciPlot-Token": "session-proof"}
    assert handler(headers)._authorized(api=True)
    assert not handler(headers)._authorized(image=True)
    assert handler({**headers, "Cookie": "sciplot_editor_8751=session-proof; sciplot_editor_8752=another-session"})._authorized(image=True)
    assert not handler({**headers, "Cookie": "sciplot_editor_8752=session-proof"})._authorized(image=True)


def test_static_handler_does_not_serve_files_outside_packaged_assets(tmp_path, monkeypatch):
    from sciplot_core.live_editor import server
    assets = tmp_path / "assets"
    assets.mkdir()
    (tmp_path / "secret.txt").write_text("not an asset")
    monkeypatch.setattr(server, "ASSETS", assets)
    instance = handler({"Host": "127.0.0.1:8751"})
    instance.path = "/%2e%2e/secret.txt"
    response = []
    instance._json = lambda body, status=200: response.append((body, status))
    instance.do_GET()
    assert response[0][1] == 404


def test_edit_cli_selects_existing_project_without_plotting(tmp_path, monkeypatch):
    from sciplot_core.cli.parsers.builder import build_parser
    from sciplot_core.cli.dispatch.interfaces import dispatch_interfaces
    from sciplot_core.live_editor import server
    called = []
    monkeypatch.setattr(server, "serve_editor", lambda target, **kwargs: called.append((target, kwargs)))
    args = build_parser().parse_args(["edit", str(tmp_path), "--figure", "spectra", "--no-open"])
    assert dispatch_interfaces(args, None, serve_intake=lambda **kwargs: pytest.fail("Intake is separate")) == 0
    assert called == [(tmp_path, {"figure_id": "spectra", "port": 0, "output": None, "open_browser": False})]


def test_packaged_editor_injects_one_session_token_before_module_execution():
    from html.parser import HTMLParser

    class Tokens(HTMLParser):
        def __init__(self):
            super().__init__()
            self.values = []

        def handle_starttag(self, tag, attrs):
            data = dict(attrs)
            if tag == "meta" and data.get("name") == "sciplot-token":
                self.values.append(data.get("content"))

    instance = handler({"Host": "127.0.0.1:8751"})
    instance.path = "/"
    responses = []
    instance._send = lambda body, *a, **kwargs: responses.append(body)
    instance.do_GET()
    parsed = Tokens()
    parsed.feed(responses[0].decode())
    assert parsed.values == ["session-proof"]
