"""Compatibility entries bind once; PlotService remains the mutation authority."""

from copy import deepcopy
from contextlib import contextmanager
from pathlib import Path

import pytest
from test_plot_typed_intent_recovery import _engine

from sciplot_core import task_common_edits as edits
from sciplot_core.plot_engine import compat
from sciplot_core.plot_engine.errors import EngineError
from sciplot_core.plot_engine.storage import digest, load_head, read, write


@pytest.fixture
def semantic(tmp_path, monkeypatch):
    service, root, backend, source, native = _engine(tmp_path)
    calls = {"close": 0, "patch": []}

    class Owner:
        def patch(self, plot, request):
            calls["patch"].append((plot, deepcopy(request)))
            return service.patch(plot, request)

        def close(self):
            calls["close"] += 1

    monkeypatch.setattr(compat, "PlotService", Owner)
    return service, root, backend, source, native, calls


def style(root, entry, **changes):
    return compat.migrated_style(root, **{
        "samples": ["layer:modulus"], "all_samples": False,
        "style": {"color": "#123456"}, "figure_id": None,
        "task_dir": entry, **changes,
    })


def test_style_replay_uses_original_binding_before_resolving_entrypoint(semantic, tmp_path, monkeypatch):
    _, root, backend, source, native, calls = semantic
    target, entry = tmp_path / "delivery", tmp_path / "style"
    target.mkdir()
    monkeypatch.setattr(compat, "resolve_project_figure", lambda *_a: {"project": str(tmp_path), "figure_id": "primary"})
    monkeypatch.setattr(compat, "document_root", lambda *_a: root)
    before = source.read_bytes(), native.read_bytes()
    assert style(target, entry)["status"] == "complete"
    saved = (entry / "semantic-style.json").read_bytes()
    monkeypatch.setattr(compat, "resolve_project_figure", lambda *_a: pytest.fail("rebound original request to today's entrypoint"))
    replay = style(target, entry)
    assert replay["replayed"] is True and replay["revision"] == 1
    assert calls["close"] == 2 and backend.native_writes == 1
    assert calls["patch"][0] == calls["patch"][1]
    assert (entry / "semantic-style.json").read_bytes() == saved
    assert (source.read_bytes(), native.read_bytes()) == before


@pytest.mark.parametrize("where", ["root", "revision", "source", "native", "ancestor"])
def test_style_entry_admission_precedes_persistence_and_native_work(semantic, where):
    _, root, backend, source, native, calls = semantic
    entry = {"root": root, "revision": root / "revisions" / "intruder",
             "source": source, "native": native, "ancestor": root.parent}[where]
    before = load_head(root), source.read_bytes(), native.read_bytes()
    with pytest.raises(EngineError) as failed:
        style(root, entry)
    assert failed.value.reason_code == "task_path_overlap"
    assert not calls["patch"] and backend.native_writes == 0
    assert not (entry / "semantic-style.json").is_file()
    assert (load_head(root), source.read_bytes(), native.read_bytes()) == before


@pytest.mark.parametrize("record", ["notes.txt", "semantic-edit.json"])
def test_style_does_not_allocate_inside_another_occupied_entry(semantic, tmp_path, record):
    _, root, backend, _, _, calls = semantic
    entry = tmp_path / "occupied"
    entry.mkdir()
    (entry / record).write_text("{}")
    before = {p.name: p.read_bytes() for p in entry.iterdir()}
    with pytest.raises(EngineError) as failed:
        style(root, entry)
    assert failed.value.reason_code == "document_idempotency_conflict"
    assert {p.name: p.read_bytes() for p in entry.iterdir()} == before
    assert not calls["patch"] and backend.native_writes == 0


def test_style_owner_is_closed_when_execution_loses_reply(semantic, tmp_path, monkeypatch):
    service, root, backend, _, _, calls = semantic
    actual = service.patch

    def lost_reply(plot, request):
        actual(plot, request)
        raise ConnectionError("lost successful reply")

    monkeypatch.setattr(service, "patch", lost_reply)
    entry = tmp_path / "lost"
    with pytest.raises(ConnectionError):
        style(root, entry)
    assert calls["close"] == 1 and backend.native_writes == 1
    saved = read(entry / "semantic-style.json")
    monkeypatch.setattr(service, "patch", actual)
    assert style(root, entry)["replayed"] is True
    assert calls["close"] == 2 and backend.native_writes == 1
    assert read(entry / "semantic-style.json") == saved


def test_old_style_record_replays_literal_request_without_inventing_new_intent(tmp_path, monkeypatch):
    root, entry = tmp_path / "original-plot", tmp_path / "old-style"
    intent = {"plot": str(root), "samples": None, "all_samples": True, "style": {"width": "0.7pt"}}
    request = {"plot_id": "original", "base_revision": 7, "idempotency_key": "style:" + digest("old-location"),
               "intent_class": "presentation", "changes": [{"literal": "original-request"}]}
    write(entry / "semantic-style.json", {"intent": intent, "request": request})
    before, calls = (entry / "semantic-style.json").read_bytes(), []

    class Owner:
        def patch(self, plot, value):
            calls.append((plot, value))
            return {"status": "blocked", "next_step": {"action": "recover_original"}}

        def close(self):
            calls.append("closed")

    monkeypatch.setattr(compat, "PlotService", Owner)
    monkeypatch.setattr(compat, "resolve_project_figure", lambda *_a: pytest.fail("queried current target for original root"))
    result = style(root, entry, samples=None, all_samples=True, style={"width": "0.7pt"})
    assert result["next_step"] == {"action": "recover_original"}
    assert calls == [(root, request), "closed"]
    assert (entry / "semantic-style.json").read_bytes() == before


def test_common_and_style_entries_cannot_claim_each_others_checkpoint(semantic, tmp_path, monkeypatch):
    service, root, backend, _, _, _ = semantic
    entry = tmp_path / "style-entry"
    style(root, entry)
    original = (entry / "semantic-style.json").read_bytes()
    monkeypatch.setattr(edits, "doctor_payload", lambda: pytest.fail("discovered current state for occupied entry"))
    with pytest.raises(EngineError) as failed:
        edits.edit_task(root, task_dir=entry, service=service, font_size="9pt")
    assert failed.value.reason_code == "document_idempotency_conflict"
    assert (entry / "semantic-style.json").read_bytes() == original
    assert not (entry / "semantic-edit.json").exists() and backend.native_writes == 1


@pytest.mark.parametrize("change", ["target", "figure_id", "samples", "style"])
def test_new_style_checkpoint_retains_original_caller_and_rejects_rebinding(semantic, tmp_path, monkeypatch, change):
    _, root, backend, _, _, calls = semantic
    entry = tmp_path / "stable-entry"
    style(root, entry)
    original = (entry / "semantic-style.json").read_bytes()
    monkeypatch.setattr(compat, "resolve_project_figure", lambda *_a: pytest.fail("resolved changed caller before checkpoint comparison"))
    target = tmp_path / "other" if change == "target" else root
    changes = {"figure_id": "secondary"} if change == "figure_id" else (
        {"samples": ["Modulus"]} if change == "samples" else (
            {"style": {"color": "#654321"}} if change == "style" else {}))
    with pytest.raises(EngineError) as failed:
        style(target, entry, **changes)
    assert failed.value.reason_code == "document_idempotency_conflict"
    assert (entry / "semantic-style.json").read_bytes() == original
    assert backend.native_writes == 1 and len(calls["patch"]) == calls["close"] == 1


def test_relocated_checkpoint_keeps_original_key_and_does_not_repeat_apply(semantic, tmp_path):
    _, root, backend, _, _, calls = semantic
    entry = tmp_path / "original-entry"
    style(root, entry)
    original = (entry / "semantic-style.json").read_bytes()
    relocated = tmp_path / "relocated-entry"
    entry.rename(relocated)
    assert style(root, relocated)["replayed"] is True
    assert (relocated / "semantic-style.json").read_bytes() == original
    assert calls["patch"][0] == calls["patch"][1] and backend.native_writes == 1


def test_concurrent_binding_wins_before_compile_without_reinterpreting_completed_revision(semantic, tmp_path, monkeypatch):
    service, root, backend, _, _, calls = semantic
    entry = tmp_path / "competing-entry"
    actual_session = compat.edit_entry_session
    original = compat.compile_series_style
    request = {"plot_id": "intent-test", "base_revision": 0, "idempotency_key": "style:original-concurrent-key",
               "intent_class": "presentation", "changes": original(load_head(root)["document"],
                   samples=["layer:modulus"], all_samples=False, style={"color": "#123456"})}
    caller = {"target": str(root), "figure_id": None, "samples": ["layer:modulus"],
              "all_samples": False, "style": {"color": "#123456"}}
    state = {"entry_intent": caller, "intent": {"plot": str(root), **{k: caller[k] for k in ("samples", "all_samples", "style")}},
             "request": request}

    @contextmanager
    def concurrent_session(path):
        write(entry / "semantic-style.json", state)
        assert service.patch(root, request)["status"] == "complete"
        with actual_session(path):
            yield

    monkeypatch.setattr(compat, "edit_entry_session", concurrent_session)
    monkeypatch.setattr(compat, "compile_series_style", lambda *_a, **_k: pytest.fail("recompiled a competing original"))
    result = style(root, entry)
    assert result["replayed"] is True and result["revision"] == 1
    assert read(entry / "semantic-style.json") == state
    assert calls["patch"] == [(root, request)] and backend.native_writes == 1


@pytest.mark.parametrize("command", ["style", "common"])
@pytest.mark.parametrize("failure", [None, RuntimeError("primary failed"), KeyboardInterrupt("cancelled")])
def test_edit_cleanup_preserves_primary_failure_and_surfaces_standalone_failure(tmp_path, monkeypatch, command, failure):
    root, entry = tmp_path / "plot", tmp_path / "entry"
    request = {"base_revision": 3, "idempotency_key": "original-key"}
    calls = []
    cleanup = RuntimeError("cleanup failed")

    class Owner:
        def patch(self, *_a):
            if failure is not None:
                raise failure
            return {"status": "complete"}

        def close(self):
            calls.append("close")
            raise cleanup

    if command == "style":
        write(entry / "semantic-style.json", {"intent": {"plot": str(root), "samples": ["layer:modulus"],
            "all_samples": False, "style": {"color": "#123456"}}, "request": request})
        monkeypatch.setattr(compat, "PlotService", Owner)
        def invoke():
            return style(root, entry)
    else:
        normalized = {"kind": "sciplot_common_edit_intent", "version": 1, "target": str(root),
                      "figure_id": None, "edits": edits.normalize_common_edit(font_size="9pt")}
        write(entry / "semantic-edit.json", {"intent": normalized, "plot": str(root), "request": request})
        monkeypatch.setattr(edits, "PlotService", Owner)
        def invoke():
            return edits.edit_task(root, task_dir=entry, font_size="9pt")
    expected = failure or cleanup
    with pytest.raises(type(expected)) as failed:
        invoke()
    assert failed.value is expected and calls == ["close"]


@pytest.mark.parametrize("managed_fails,legacy_fails", [(True, False), (False, True), (True, True), (False, False)])
def test_backend_router_closes_both_owners_and_retains_first_failure(monkeypatch, managed_fails, legacy_fails):
    from sciplot_core.plot_engine import backend_router

    calls = []
    managed_error, legacy_error = RuntimeError("managed"), RuntimeError("legacy")

    class Managed:
        def close(self):
            calls.append("managed")
            if managed_fails:
                raise managed_error

    class Legacy:
        def close(self):
            calls.append("legacy")
            if legacy_fails:
                raise legacy_error

    monkeypatch.setattr(backend_router, "ManagedBackend", Managed)
    router = backend_router.BackendRouter(Legacy())
    if managed_fails or legacy_fails:
        with pytest.raises(RuntimeError) as failed:
            router.close()
        assert failed.value is (managed_error if managed_fails else legacy_error)
    else:
        router.close()
    assert calls == ["managed", "legacy"]


@pytest.mark.parametrize("command", ["style", "common"])
def test_malformed_checkpoint_retains_its_owner_and_cannot_be_rebound(tmp_path, monkeypatch, command):
    entry = tmp_path / "entry"
    name = "semantic-style.json" if command == "style" else "semantic-edit.json"
    write(entry / name, {"intent": [], "request": None})
    before = (entry / name).read_bytes()
    monkeypatch.setattr(compat, "resolve_project_figure", lambda *_a: pytest.fail("resolved corrupted checkpoint as new edit"))
    monkeypatch.setattr(edits, "doctor_payload", lambda: pytest.fail("rebound corrupted checkpoint"))
    with pytest.raises(EngineError) as failed:
        if command == "style":
            style(tmp_path / "target", entry)
        else:
            edits.edit_task(tmp_path / "target", task_dir=entry, font_size="9pt", service=object())
    assert failed.value.reason_code == "document_state_invalid"
    assert (entry / name).read_bytes() == before


@pytest.mark.parametrize("drift", ["source", "native"])
def test_style_replay_does_not_bypass_original_engine_currentness(semantic, tmp_path, drift):
    _, root, backend, source, _, calls = semantic
    entry = tmp_path / "current-entry"
    style(root, entry)
    head = load_head(root)
    original = (entry / "semantic-style.json").read_bytes()
    changed = source if drift == "source" else Path(head["binding"]["document"])
    changed.write_bytes(changed.read_bytes() + b"changed")
    with pytest.raises(EngineError) as failed:
        style(root, entry)
    assert failed.value.reason_code == "document_inputs_changed"
    assert calls["patch"][0] == calls["patch"][1] and calls["close"] == 2
    assert backend.native_writes == 1 and (entry / "semantic-style.json").read_bytes() == original


def test_legacy_task_route_remains_its_own_authority_but_mixed_bindings_reject(tmp_path, monkeypatch):
    entry = tmp_path / "legacy-task"
    write(entry / "task.json", {"literal": "old-task-owner"})
    original = (entry / "task.json").read_bytes()
    monkeypatch.setattr(compat, "resolve_project_figure", lambda *_a: pytest.fail("rediscovered a legacy task"))
    assert style(tmp_path / "target", entry) is None
    write(entry / "semantic-style.json", {"literal": "second-owner"})
    with pytest.raises(EngineError) as failed:
        style(tmp_path / "target", entry)
    assert failed.value.reason_code == "document_idempotency_conflict"
    assert (entry / "task.json").read_bytes() == original
