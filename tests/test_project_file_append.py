"""Explicit ordinary XY append keeps existing archive members and history."""

from contextlib import closing
from copy import deepcopy
import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from sciplot_core.plot_document import seal_document
from sciplot_core.plot_engine.content_store import resolve_document_content
from sciplot_core.plot_engine.current_unit_admission import prepare_current_update
from sciplot_core.plot_engine.service import PlotService
from sciplot_core.plot_engine.typed_intent import compile_intent
from sciplot_core.plot_ir.figure_document import figure_spec
from sciplot_core.project_lifecycle import managed_creation, project_file
from sciplot_core.project_lifecycle.attachment_index import INDEX, read_index
from sciplot_core.project_lifecycle.capabilities import COMPATIBILITY_CAPABILITIES
from sciplot_core.project_lifecycle.context import repository_scope
from sciplot_core.project_lifecycle.errors import EngineError
from sciplot_core.project_lifecycle.project_file_summary import project_file_figure
from sciplot_core.project_store.errors import ProjectStoreError
from sciplot_core.project_store.repository import FileProjectStore
from sciplot_core.task_semantic_contract import validate_intent
from sciplot_core.task_semantic_creation import build_managed_request, prepare_plan


def _ordinary_request(source):
    intent = validate_intent({"x": {"quantity": "temperature"}, "y": {"quantity": "heat_flow"}})
    plan = prepare_plan([source], intent)
    assert plan["decisions"] == []
    return build_managed_request({"request": {"intent": intent}, "semantic_plan": plan,
                                  "semantic_choices": {}, "task_dir": str(source.with_suffix("")), "intent_revision": 1})


def _coordinates(owner, document):
    with repository_scope(owner), owner.query_scope(owner.attachment.root):
        expanded = resolve_document_content(owner.attachment.root, document)
    layer = figure_spec(expanded)["views"][0]["layers"][0]
    columns = expanded["scientific"]["provenance"]["datasets"][layer["dataset_id"]]["columns"]
    return {role: columns[layer["mappings"][role]]["values"] for role in ("x", "y")}


def _save_axis_revision(archive, plot_id, label):
    with project_file_figure(archive, plot_id) as (session, owner, before):
        root = owner.attachment.root
        axis = figure_spec(before)["views"][0]["axes"][0]["id"]
        patch, _ = compile_intent(before, {"mode": "apply", "plot_id": plot_id, "base_revision": before["revision"],
            "idempotency_key": "fixture-axis-revision", "property": "axis.label", "target_id": axis, "value": label})
        with repository_scope(owner, capabilities=COMPATIBILITY_CAPABILITIES), owner.lease(root), owner.storage_batch(root):
            document, diff, _, _ = prepare_current_update(root, before, patch)
            assert diff
            document = seal_document({**document, "revision": before["revision"] + 1})
            _, prepared = managed_creation.bind_managed_member(root, document, owner.attachment.cache / "output", already_resolved=True)
            owner.commit(root, document, prepared.binding, "fixture-axis-revision")
        session.save(expected_generation=session.store.snapshot()["generation"])


@pytest.fixture
def ordinary_archive(tmp_path, monkeypatch):
    folder = tmp_path.resolve()
    source = folder / "original.csv"
    source.write_text("Temperature,Heat Flow\nC,W/g\nSample Z,Sample Z\n66,-0.023\n61,0.008\n61,\n53,-0.016\n")
    incoming = folder / "incoming.csv"
    incoming.write_text("Temperature,Heat Flow\nC,W/g\nSample N,Sample N\n40,0.4\n46,-0.1\n55,0.2\n")
    request = _ordinary_request(incoming)
    root = folder / "working project"
    root.mkdir()
    store = FileProjectStore(root)
    store.snapshot(import_legacy=True)
    archive = folder / "研究项目.sciplot"

    # Create through the regular application route. The fixture only needs
    # semantic publication, so native dispatch can stay outside this test.
    with monkeypatch.context() as setup:
        setup.setattr(managed_creation, "export_head", lambda root, head, _backend: {**head["document"], "plot": str(root)})
        with closing(PlotService()) as service:
            first = service.create(_ordinary_request(source), project=root)
    snapshot = store.snapshot()
    project_file.create_project_file(archive, store, expected_generation=snapshot["generation"])
    _save_axis_revision(archive, first["plot_id"], "Cooling temperature (C)")
    source.unlink()
    return archive, first["plot_id"], incoming, request


def test_append_keeps_original_points_and_history_and_reopens_each_exact_plot(ordinary_archive, monkeypatch):
    archive, first_id, incoming, request = ordinary_archive
    with project_file_figure(archive, first_id) as (session, owner, current):
        before = session.store.snapshot()
        prior_revision = owner.load_revision(owner.attachment.root, 0)["document"]
        original_points = {"x": [66., 61., 61., 53.], "y": [-.023, .008, None, -.016]}
        assert _coordinates(owner, current) == original_points
    monkeypatch.setattr(managed_creation, "export_head", lambda *_args: pytest.fail("append rendered a native derivative"))
    before_bytes = archive.read_bytes()
    with closing(PlotService()) as service:
        result = service.append_project_file_xy(archive, request, expected_generation=before["generation"])
        assert result["status"] == "saved" and result["revision"] == 0
        assert result["generation"] != before["generation"] and result["project_id"] == before["project_id"]
        assert result["plot_id"] != first_id and result["scientific_hash"] != current["scientific_hash"]
        assert archive.read_bytes() != before_bytes
        with pytest.raises(EngineError) as ambiguous:
            service.open(archive)
        assert ambiguous.value.reason_code == "project_file_figure_ambiguous"
        assert {choice["plot_id"] for choice in ambiguous.value.repair["figures"]} == {first_id, result["plot_id"]}
        arguments = result["next_step"]["arguments"]
        opened = service.open(**{**arguments, "target": Path(arguments["target"])})
        assert all(opened[key] == result[key] for key in ("plot_id", "revision", "scientific_hash", "presentation_hash"))
        assert service.open(archive, first_id)["scientific_hash"] == current["scientific_hash"]

        incoming_bytes = incoming.read_bytes()
        incoming.unlink()
        appended_bytes = archive.read_bytes()
        replay = service.append_project_file_xy(archive, request, expected_generation=before["generation"])
        assert replay == {**result, "status": "already_saved"}
        assert archive.read_bytes() == appended_bytes
        changed = deepcopy(request)
        changed["data_binding"]["provenance"]["note"] = "different request, same key"
        with pytest.raises(EngineError) as conflict:
            service.append_project_file_xy(archive, changed, expected_generation=result["generation"])
        assert conflict.value.reason_code == "document_idempotency_conflict"
        assert archive.read_bytes() == appended_bytes

    with project_file_figure(archive, first_id) as (session, owner, still_current):
        after = session.store.snapshot()
        assert read_index(session.store, after)["attachments"][owner.attachment.entry["id"]] == owner.attachment.entry
        assert after["sequence"] == before["sequence"] + 1
        assert all(after["files"][name] == entry for name, entry in before["files"].items() if name != INDEX)
        assert still_current == current and _coordinates(owner, still_current) == original_points
        assert owner.load_revision(owner.attachment.root, 0)["document"] == prior_revision
        assert session.store.observe_members((), generation=before["generation"], projection=False).selected["generation"] == before["generation"]
    with project_file_figure(archive, result["plot_id"]) as (session, owner, document):
        assert _coordinates(owner, document) == {"x": [40., 46., 55.], "y": [.4, -.1, .2]}
        [(source_id, version)] = [(source_id, version) for source_id, versions in session.store.snapshot()["sources"].items()
                                  for version, entry in versions.items() if entry["locator"] == str(incoming)]
        assert session.store.resolve_source(source_id, version).read_bytes() == incoming_bytes


def test_append_rejects_stale_generation_source_failure_and_old_format(ordinary_archive, tmp_path):
    archive, first_id, incoming, request = ordinary_archive
    original = archive.read_bytes()
    with project_file.open_project_file(archive) as session:
        generation = session.store.snapshot()["generation"]
    with closing(PlotService()) as service:
        with pytest.raises(EngineError) as stale:
            service.append_project_file_xy(archive, request, expected_generation="obsolete")
        assert stale.value.reason_code == "project_file_generation_conflict"
        assert archive.read_bytes() == original

        old = tmp_path / "old.sciplot"
        with ZipFile(archive) as current, ZipFile(old, "w") as legacy:
            for name in current.namelist():
                payload = current.read(name)
                if name == "bundle.json":
                    payload = json.dumps({**json.loads(payload), "version": 0}).encode()
                legacy.writestr(name, payload)
        old_bytes = old.read_bytes()
        with pytest.raises(ProjectStoreError, match="bundle manifest"):
            service.append_project_file_xy(old, request, expected_generation=generation)
        assert old.read_bytes() == old_bytes

        incoming.write_bytes(incoming.read_bytes() + b"60,0.6\n")
        with pytest.raises(EngineError) as changed:
            service.append_project_file_xy(archive, request, expected_generation=generation)
        assert changed.value.reason_code == "semantic_attachment_source_unavailable"
        assert archive.read_bytes() == original
        assert service.open(archive)["plot_id"] == first_id


def test_append_does_not_overwrite_an_archive_saved_after_it_opened(ordinary_archive, monkeypatch):
    archive, first_id, _incoming, request = ordinary_archive
    with project_file.open_project_file(archive) as session:
        generation = session.store.snapshot()["generation"]
    publish = project_file.ProjectFileSession.save
    latest = None

    def save_after_competing_edit(session, *, expected_generation):
        nonlocal latest
        with monkeypatch.context() as writer:
            writer.setattr(project_file.ProjectFileSession, "save", publish)
            _save_axis_revision(archive, first_id, "Another temperature label (C)")
        latest = archive.read_bytes()
        return publish(session, expected_generation=expected_generation)

    monkeypatch.setattr(project_file.ProjectFileSession, "save", save_after_competing_edit)
    with closing(PlotService()) as service:
        with pytest.raises(EngineError) as conflict:
            service.append_project_file_xy(archive, request, expected_generation=generation)
        assert conflict.value.reason_code == "project_file_save_conflict"
        assert archive.read_bytes() == latest
        current = service.open(archive)
        assert current["plot_id"] == first_id and current["revision"] == 2


@pytest.mark.comprehensive
@pytest.mark.parametrize("writer", ["cli", "daily"])
def test_public_append_uses_observed_generation_and_opens_new_plot(ordinary_archive, writer):
    import os
    import signal
    import subprocess
    import sys

    import anyio
    from mcp import Client
    from socket_fixture_helpers import socket_directory
    from test_mcp_stdio import _call, _parameters

    from sciplot_core._paths import REPO_ROOT
    from sciplot_core.plot_protocol.paths import read_owner

    archive, first_id, incoming, request = ordinary_archive
    request_file = archive.parent / "append.json"

    with socket_directory(prefix="sp-append-", dir="/tmp") as directory:
        socket = Path(directory) / "engine.sock"
        env = {**os.environ, "SCIPLOT_PYTHON": sys.executable, "SCIPLOT_ENGINE_SOCKET": str(socket)}

        def cli(*arguments, fails=False):
            run = subprocess.run([str(REPO_ROOT / "skill/scripts/sciplot"), "plot", *map(str, arguments), "--json"],
                                 env=env, cwd=archive.parent, capture_output=True, text=True, timeout=60, check=False)
            assert run.returncode == int(fails), run.stdout + run.stderr
            return json.loads(run.stdout)

        def cli_append(payload, generation, *, fails=False):
            request_file.write_text(json.dumps(payload), encoding="utf-8")
            return cli("append", archive.name, "--request", request_file, "--expected-generation", generation, fails=fails)

        parameters = _parameters(cli=True, profile="daily")
        parameters.env = {**(parameters.env or {}), **env}

        async def scenario():
            async with Client(parameters, read_timeout_seconds=60) as client:
                original = cli("open", archive.name, "--scope", "summary")
                target = {"target": str(archive), "description": {"scope": "summary"}}
                assert original == await _call(client, "sciplot_project_open", target)
                generation = original["generation"]
                call = {"target": str(archive), "expected_generation": generation, "request": request}
                unchanged = archive.read_bytes()
                unresolved = {"idempotency_key": "unresolved", "source": str(incoming)}
                if writer == "cli":
                    rejected = cli_append(unresolved, generation, fails=True)
                    assert rejected["reason_code"] == "project_file_append_unsupported"
                else:
                    rejected = await client.call_tool("sciplot_project_file_append", {**call, "request": unresolved})
                    assert rejected.is_error and rejected.structured_content["error"]["code"] == "project_file_append_unsupported"
                assert archive.read_bytes() == unchanged

                saved = (cli_append(request, generation) if writer == "cli"
                         else await _call(client, "sciplot_project_file_append", call))
                assert saved["status"] == "saved" and saved["generation"] != generation
                assert saved["plot_id"] != first_id and saved["project_id"] == original["project_id"]
                assert saved["next_step"]["action"] == "project.open"
                new_figure = await _call(client, "sciplot_project_open", saved["next_step"]["arguments"])
                assert all(new_figure[key] == saved[key] for key in ("plot_id", "revision", "scientific_hash", "generation"))
                assert cli("open", archive.name, "--figure", saved["plot_id"]) == new_figure
                assert cli("open", archive.name, "--figure", first_id) == {**original, "generation": saved["generation"]}
                selection = await client.call_tool("sciplot_project_open", target)
                assert selection.is_error and selection.structured_content["repair"]["generation"] == saved["generation"]

                published = archive.read_bytes()
                stale = cli_append({**request, "idempotency_key": "new-stale-key"}, generation, fails=True)
                assert stale["reason_code"] == "project_file_generation_conflict"
                incoming.unlink()
                replay = (await _call(client, "sciplot_project_file_append", call) if writer == "cli"
                          else cli_append(request, generation))
                assert replay == {**saved, "status": "already_saved"}
                assert archive.read_bytes() == published

        try:
            anyio.run(scenario)
        finally:
            if socket.exists():
                os.kill(read_owner(socket)["pid"], signal.SIGTERM)
