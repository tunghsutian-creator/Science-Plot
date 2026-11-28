"""Relocation-safe typed edits publish through the public transports."""

from contextlib import closing
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys

import pytest

from sciplot_core._paths import REPO_ROOT
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.plot_engine.errors import EngineError
from sciplot_core.plot_engine.service import PlotService
from sciplot_core.plot_ir.figure_document import figure_spec
from sciplot_core.plot_protocol.paths import read_owner
from sciplot_core.project_lifecycle import project_file
from sciplot_core.project_lifecycle.attachment_index import INDEX, Attachment, encode, read_index
from sciplot_core.project_lifecycle.context import transaction_path
from sciplot_core.project_lifecycle.project_file_summary import project_file_figure
from sciplot_core.project_lifecycle.project_file import ProjectFileSaveUnconfirmed, create_project_file, open_project_file
from sciplot_core.project_store.repository import FileProjectStore


def _write_fixture_resources(store, name, writes):
    snapshot = store.snapshot()
    read_set = {path: snapshot["files"].get(path, {}).get("sha256") for path in writes}
    store.reserve(name, name, expected_generation=snapshot["generation"], read_set=read_set, write_set=sorted(writes))
    store.publish(name, name, writes=writes, result={})


@pytest.mark.comprehensive
def test_relocated_project_file_axis_edit_is_saved_once_through_cli_and_daily_mcp(tmp_path, monkeypatch):
    import anyio
    from mcp import Client
    from socket_fixture_helpers import socket_directory
    from test_figure_document import request_for_figure
    from test_mcp_stdio import _parameters

    root = tmp_path.resolve()
    original = root / "original"
    original.mkdir()
    project = original / "project"
    project.mkdir()
    store = FileProjectStore(project)
    store.snapshot(import_legacy=True)
    request = request_for_figure(original)
    raw = (original / "figure.csv").read_bytes()
    with closing(PlotService()) as service:
        saved = service.create(request, project=project)
        assert saved["ready_to_use"], saved
    # Model the Store's immutable initial publication, as retained when importing
    # an attached figure. Its still-valid bytes must survive a newer edit.
    index = read_index(store)
    [entry] = index["attachments"].values()
    attachment = Attachment(store, entry)
    original_cache = (attachment.cache / "state" / "export-cache.json").read_bytes()
    archived = attachment.logical(attachment.root / "archive" / "export-cache.json")
    entry["archived_derivatives"]["export-cache.json"] = archived
    _write_fixture_resources(store, "initial-export-fixture", {INDEX: encode(index), archived: original_cache})
    snapshot = store.snapshot()
    archive = original / "模量数据.sciplot"
    initial = create_project_file(archive, store, expected_generation=snapshot["generation"])
    folder = root / "移入 (测试)"
    folder.mkdir()
    moved = archive.rename(folder / "新料.sciplot")
    shutil.rmtree(original)
    scratch = root / "scratch"
    scratch.mkdir()
    env = {**os.environ, "TMPDIR": str(scratch), "SCIPLOT_PYTHON": sys.executable,
           "MPLCONFIGDIR": str(root / "mpl")}
    intent = {"mode": "apply", "plot_id": saved["plot_id"], "base_revision": 0,
              "idempotency_key": "test-axis", "property": "axis.label",
              "target_id": "axis:xb", "value": "Frequency, Hz"}
    request_json = root / "intent.json"

    def cli(operation, *args, code=0):
        run = subprocess.run(
            [str(REPO_ROOT / "skill/scripts/sciplot"), "plot", operation, *map(str, args), "--direct", "--json"],
            env=env, cwd=root, capture_output=True, text=True, timeout=90, check=False,
        )
        assert run.returncode == code, run.stdout + run.stderr
        assert not list(scratch.iterdir())
        assert str(scratch) not in run.stdout
        return json.loads(run.stdout)

    request_json.write_text(json.dumps({**intent, "mode": "plan"}))
    plan = cli("intent", moved.relative_to(root), "--request", request_json)
    assert not plan["saved"] and plan["project_file"] == str(moved) and plan["status"] == "ready"
    assert plan["before"] == "Frequency (Hz)" and plan["after"] == intent["value"]
    assert file_sha256(moved) == initial.sha256

    with socket_directory(prefix="sp-file-edit-", dir="/tmp") as directory:
        socket = Path(directory) / "engine.sock"
        parameters = _parameters(cli=True, profile="daily")
        parameters.env = {**(parameters.env or {}), **env, "SCIPLOT_ENGINE_SOCKET": str(socket)}

        async def check_mcp():
            async with Client(parameters, read_timeout_seconds=90) as client:
                reply = await client.call_tool("sciplot_plot_intent", {"plot": str(moved), "request": intent})
                assert not reply.is_error, reply.content
                assert str(scratch) not in str(reply.structured_content)
                return reply.structured_content

        try:
            result = anyio.run(check_mcp)
        finally:
            if socket.exists():
                os.kill(read_owner(socket)["pid"], signal.SIGTERM)

    assert result == {"kind": "sciplot_project_file_intent", "version": 1, "status": "saved", "saved": True,
                      "project_file": str(moved), "project_id": initial.project_id, "plot_id": saved["plot_id"],
                      "idempotency_key": "test-axis", "revision": 1, "current_revision": 1,
                      "scientific_hash": saved["scientific_hash"], "presentation_hash": result["presentation_hash"]}
    assert result["presentation_hash"] != saved["presentation_hash"]
    published = file_sha256(moved)
    assert published != initial.sha256

    request_json.write_text(json.dumps(intent))
    assert cli("intent", moved, "--request", request_json) == {**result, "status": "already_saved"}
    request_json.write_text(json.dumps({**intent, "value": "Wrong edit"}))
    assert cli("intent", moved, "--request", request_json, code=1)["reason_code"] == "document_idempotency_conflict"
    request_json.write_text(json.dumps({**intent, "idempotency_key": "new-stale-key"}))
    assert cli("intent", moved, "--request", request_json, code=1)["reason_code"] == "document_revision_conflict"
    opened = cli("open", moved, "--figure", saved["plot_id"])
    assert opened["revision"] == 1 and opened["scientific_hash"] == saved["scientific_hash"]
    assert opened["presentation_hash"] == result["presentation_hash"]

    with open_project_file(moved, workspace_parent=scratch) as session:
        [(source_id, versions)] = session.store.snapshot()["sources"].items()
        [version] = versions
        assert session.store.resolve_source(source_id, version).read_bytes() == raw
    with project_file_figure(moved, saved["plot_id"]) as (_session, owner, document):
        attached = owner.attachment.root
        journal = owner.read(transaction_path(attached, intent["idempotency_key"]))
        assert journal["phase"] == "complete" and journal["document"] == document
        assert journal["export_deferred"] is True and "export" not in journal
        assert journal["review"]["scientific_audit"]["status"] == "passed"
        assert not owner.runtime_path(attached / "export-cache.json").exists()
        assert owner.exists(attached / "export-cache.json")
        assert owner.attachment.store.read_bytes(archived) == original_cache
    assert not original.exists() and not list(scratch.iterdir())
    assert list(folder.iterdir()) == [moved] and file_sha256(moved) == published

    no_op = {**intent, "idempotency_key": "same-title", "base_revision": 1}
    request_json.write_text(json.dumps(no_op))
    unchanged = cli("intent", moved, "--request", request_json)
    assert unchanged["revision"] == 1 and unchanged["presentation_hash"] == result["presentation_hash"]
    published = file_sha256(moved)
    assert cli("intent", moved, "--request", request_json) == {**unchanged, "status": "already_saved"}
    assert file_sha256(moved) == published

    output = root / "current handoff"
    delivery = cli("export", moved, "--output-dir", output, "--plot-id", saved["plot_id"],
                   "--revision", "1", "--tiff")
    assert delivery["revision"] == 1 and delivery["scientific_hash"] == saved["scientific_hash"]
    assert delivery["presentation_hash"] == result["presentation_hash"]
    files = {entry["format"]: Path(entry["path"]) for entry in delivery["exports"]}
    assert set(files) == {"pdf", "tiff_300"} and files["pdf"].read_bytes().startswith(b"%PDF-")
    from PIL import Image

    with Image.open(files["tiff_300"]) as raster:
        assert raster.info["dpi"] == pytest.approx((300, 300), abs=.1)
    assert file_sha256(moved) == published

    for bad_cache in ("current", "archived"):
        unready = root / f"unready-{bad_cache}.sciplot"
        with project_file_figure(moved, saved["plot_id"]) as (session, owner, _document):
            attached = owner.attachment.root
            cache = owner.runtime_path(attached / "export-cache.json")
            assert not cache.exists()
            record = json.loads(original_cache)
            record["export"]["publication_qa"]["status"] = "failed"
            if bad_cache == "current":
                record["export"]["ir_hash"] = owner.load_head(attached)["binding"]["ir_hash"]
                cache.write_bytes(encode(record))
            else:
                _write_fixture_resources(session.store, "failed-archive-fixture", {archived: encode(record)})
            generation = session.store.snapshot()["generation"]
            unready_saved = create_project_file(unready, session.store, expected_generation=generation)
        destination = root / f"no retry {bad_cache}"
        with closing(PlotService()) as service, monkeypatch.context() as fault:
            fault.setattr(service, "_export", lambda *_: pytest.fail("An invalid cache must not rebuild."))
            with pytest.raises(EngineError) as failed:
                service.export(unready, handoff={"output_dir": str(destination), "plot_id": saved["plot_id"],
                                                "revision": 1, "formats": ["pdf"]})
            assert failed.value.reason_code == "figure_handoff_publication_unready"
        assert not destination.exists() and file_sha256(unready) == unready_saved.sha256

    next_intent = {**intent, "base_revision": 1, "idempotency_key": "second-axis", "value": "Frequency / Hz"}
    true_publish = project_file._publish

    def refuse_replace(*args):
        raise OSError("publication stopped before replace")

    def lose_ack(path, stage, candidate, baseline):
        true_publish(path, stage, candidate, baseline)
        raise ProjectFileSaveUnconfirmed(candidate.receipt)

    with closing(PlotService()) as service, monkeypatch.context() as fault:
        fault.setattr(project_file, "_publish", refuse_replace)
        with pytest.raises(EngineError) as refused:
            service.intent(moved, next_intent)
        assert refused.value.reason_code == "project_file_save_failed"
        assert file_sha256(moved) == published and cli("open", moved)["revision"] == 1

        fault.setattr(project_file, "_publish", lose_ack)
        with pytest.raises(EngineError) as unconfirmed:
            service.intent(moved, next_intent)
        assert unconfirmed.value.reason_code == "project_file_save_unconfirmed"
        assert unconfirmed.value.repair["idempotency_key"] == next_intent["idempotency_key"]
        assert unconfirmed.value.repair["revision"] == 2
        observed = file_sha256(moved)
        assert observed != published
        request_json.write_text(json.dumps(next_intent))
        retry = cli("intent", moved, "--request", request_json)
        assert retry["status"] == "already_saved" and retry["revision"] == 2
        assert file_sha256(moved) == observed
    assert cli("open", moved)["revision"] == 2
    assert list(folder.iterdir()) == [moved]


@pytest.mark.comprehensive
def test_relocated_semantic_xy_can_save_twice_across_installations(tmp_path):
    import anyio
    from mcp import Client
    from socket_fixture_helpers import socket_directory
    from test_mcp_stdio import _parameters

    original = tmp_path.resolve() / "original analysis"
    original.mkdir()
    source = original / "experiment.csv"
    raw = b"Temperature,Heat Flow\nC,W/g\nSample,Sample\n66,-0.023\n61,0.008\n61,\n53,-0.016\n"
    source.write_bytes(raw)
    reference = original / "reference.csv"
    reference_raw = b"Temperature,Heat Flow\nC,W/g\nReference,Reference\n66,0.026\n60,0.010\n53,-0.013\n"
    reference.write_bytes(reference_raw)
    # Run the producer and first edit from a genuinely distinct, byte-identical
    # source installation. No old paths or user project will exist on the second edit.
    old_install = tmp_path / "prior installation"
    old_source = old_install / "src"
    shutil.copytree(REPO_ROOT / "src/sciplot_core", old_source / "sciplot_core",
                    ignore=shutil.ignore_patterns("__pycache__"))
    # The public startup guard must be owned by the same installation as its package.
    old_wrapper = old_install / "skill/scripts/sciplot"
    old_wrapper.parent.mkdir(parents=True)
    shutil.copy2(REPO_ROOT / "skill/scripts/sciplot", old_wrapper)
    env = {**os.environ, "SCIPLOT_REPO": str(REPO_ROOT), "SCIPLOT_SOURCE_ROOT": str(REPO_ROOT / "src"),
           "SCIPLOT_PYTHON": sys.executable, "MPLCONFIGDIR": str(tmp_path / "mpl")}

    def cli(*args, previous=False, code=0):
        run = subprocess.run(
            [str(old_wrapper if previous else REPO_ROOT / "skill/scripts/sciplot"), *map(str, args), "--json"],
            env={**env, **({"SCIPLOT_REPO": str(old_install), "SCIPLOT_SOURCE_ROOT": str(old_source)}
                          if previous else {})},
            cwd=tmp_path, capture_output=True, text=True, timeout=120, check=False,
        )
        assert run.returncode == code, run.stdout + run.stderr
        return json.loads(run.stdout)

    request = original / "plot.json"
    request.write_text(json.dumps({"version": 1, "action": "create", "sources": [str(source), str(reference)],
                                   "intent": {"x": {"quantity": "temperature"}, "y": {"quantity": "heat_flow"},
                                              "labels": ["Selected", "Reference"]},
                                   "out": str(original / "delivery"), "formats": ["pdf"]}))
    created = cli("task", "start", "--request", request, "--task-dir", original / "task", previous=True)
    assert created["status"] == "complete" and created["scientific_presentation"]["rule_id"] == "ordinary_xy"
    saved = created["result"]
    archive = original / "thermal.sciplot"
    packed = cli("project", "bundle-export", created["project"], "--out", archive, "--single-file", previous=True)
    target = tmp_path / "thermal.sciplot"
    archive.rename(target)
    shutil.rmtree(original)
    request = tmp_path / "edit.json"
    before = saved

    for revision, title in enumerate(("Acquisition temperature (C)", "Cooling temperature (C)"), 1):
        request.write_text(json.dumps({"mode": "apply", "plot_id": saved["plot_id"], "base_revision": revision - 1,
                                       "idempotency_key": f"edit-{revision}", "property": "axis.label",
                                       "target_id": "axis:x", "value": title}))
        applied = cli("plot", "intent", target, "--request", request, "--direct", previous=revision == 1)
        assert applied["status"] == "saved" and applied["revision"] == revision
        assert applied["project_id"] == packed["project_id"] and applied["plot_id"] == saved["plot_id"]
        assert applied["scientific_hash"] == saved["scientific_hash"]
        assert applied["presentation_hash"] != before["presentation_hash"]
        with project_file_figure(target, saved["plot_id"]) as (session, owner, document):
            attached = owner.attachment.root
            previous_head = owner.load_revision(attached, revision - 1)
            assert previous_head["document"]["presentation_hash"] == before["presentation_hash"]
            assert document["revision"] == revision
            pins = owner.read(attached / "revisions" / f"{revision:08d}.json")["binding"]["fingerprint"]["files"]
            assert any(Path(name).is_relative_to(old_source) for name in pins) == (revision == 1)
            assert sorted(session.store.resolve_source(source_id, version).read_bytes()
                          for source_id, versions in session.store.snapshot()["sources"].items()
                          for version in versions) == sorted([raw, reference_raw])
        before = applied
        if revision == 1:
            shutil.rmtree(old_install)
    assert not source.exists() and not old_install.exists()
    current = cli("plot", "open", target, "--direct")
    assert current["revision"] == 2 and current["edit_targets"]["axis:x"]["label"] == title
    assert current["scientific_hash"] == saved["scientific_hash"] and current["plot_id"] == saved["plot_id"]

    targets = {item["label"]: identifier for identifier, item in current["edit_targets"].items()
               if "style.line.color" in item["properties"]}
    assert set(targets) == {"Selected", "Reference"}
    color = "#ab147c"
    intent = {"mode": "apply", "plot_id": current["plot_id"], "base_revision": current["revision"],
              "idempotency_key": "selected-color", "property": "style.line.color",
              "target_id": targets["Selected"], "value": color}
    original_archive = file_sha256(target)
    request.write_text(json.dumps({**intent, "mode": "plan"}))
    plan = cli("plot", "intent", target, "--request", request, "--direct")
    assert plan["status"] == "ready" and not plan["saved"] and file_sha256(target) == original_archive
    assert plan["target"] == {"id": targets["Selected"], "kind": "layer", "label": "Selected"}
    assert plan["before"] != color and plan["after"] == color

    with socket_directory(prefix="sp-file-color-", dir="/tmp") as directory:
        socket = Path(directory) / "engine.sock"
        parameters = _parameters(cli=True, profile="daily")
        parameters.env = {**(parameters.env or {}), **env, "SCIPLOT_ENGINE_SOCKET": str(socket)}

        async def apply_color():
            async with Client(parameters, read_timeout_seconds=90) as client:
                opened = await client.call_tool("sciplot_project_open", {"target": str(target)})
                assert not opened.is_error and opened.structured_content == current
                result = await client.call_tool("sciplot_plot_intent", {"plot": str(target), "request": intent})
                assert not result.is_error, result.content
                return result.structured_content

        try:
            changed = anyio.run(apply_color)
        finally:
            if socket.exists():
                os.kill(read_owner(socket)["pid"], signal.SIGTERM)

    assert changed["status"] == "saved" and changed["revision"] == 3
    assert changed["scientific_hash"] == saved["scientific_hash"]
    assert changed["presentation_hash"] != current["presentation_hash"]
    with project_file_figure(target, current["plot_id"]) as (session, owner, document):
        attached = owner.attachment.root
        old = owner.load_revision(attached, 2)["document"]
        assert old["scientific"] == document["scientific"]
        expected = deepcopy(figure_spec(old))
        line, = [mark for view in expected["views"] for layer in view["layers"]
                 if layer["id"] == targets["Selected"] for mark in layer["marks"] if mark["type"] == "line"]
        assert line["id"] == plan["target_context"]["mark_id"]
        line["style"]["line_color"] = color
        assert figure_spec(document) == expected
        old_audit = owner.read(transaction_path(attached, "edit-2"))["review"]["scientific_audit"]
        new_audit = owner.read(transaction_path(attached, "selected-color"))["review"]["scientific_audit"]
        assert new_audit["status"] == "passed"
        assert {key: new_audit[key] for key in ("datasets", "layers", "scales")} == {
            key: old_audit[key] for key in ("datasets", "layers", "scales")}
        assert sorted(session.store.resolve_source(source_id, version).read_bytes()
                      for source_id, versions in session.store.snapshot()["sources"].items()
                      for version in versions) == sorted([raw, reference_raw])

    published = file_sha256(target)
    assert published != original_archive
    request.write_text(json.dumps(intent))
    assert cli("plot", "intent", target, "--request", request, "--direct") == {**changed, "status": "already_saved"}
    request.write_text(json.dumps({**intent, "idempotency_key": "stale-color", "value": "#112233"}))
    stale = cli("plot", "intent", target, "--request", request, "--direct", code=1)
    assert stale["reason_code"] == "document_revision_conflict"
    assert file_sha256(target) == published

    alias = "Selected (170 °C blend)"
    renamed = {**intent, "base_revision": 3, "idempotency_key": "selected-alias",
               "property": "series.display_label", "value": alias}
    request.write_text(json.dumps({**renamed, "mode": "plan"}))
    plan = cli("plot", "intent", target, "--request", request, "--direct")
    assert plan["before"] == "Selected" and plan["after"] == alias
    assert file_sha256(target) == published
    request.write_text(json.dumps(renamed))
    renamed_result = cli("plot", "intent", target, "--request", request, "--direct")
    assert renamed_result["status"] == "saved" and renamed_result["revision"] == 4
    assert renamed_result["scientific_hash"] == current["scientific_hash"]
    reopened = cli("plot", "open", target, "--direct")
    assert reopened["edit_targets"][targets["Selected"]]["label"] == alias
    assert reopened["edit_targets"][targets["Reference"]]["label"] == "Reference"
    with project_file_figure(target, current["plot_id"]) as (session, owner, after):
        attached = owner.attachment.root
        before = owner.load_revision(attached, 3)["document"]
        assert before["scientific"] == after["scientific"]
        prior_review = owner.read(transaction_path(attached, "selected-color"))["review"]
        after_review = owner.read(transaction_path(attached, "selected-alias"))["review"]
        assert after_review["scientific_audit"]["status"] == "passed"
        assert after_review["scientific_audit"]["datasets"] == prior_review["scientific_audit"]["datasets"]
        assert sorted(session.store.resolve_source(source_id, version).read_bytes()
                      for source_id, versions in session.store.snapshot()["sources"].items()
                      for version in versions) == sorted([raw, reference_raw])


def test_public_resume_confirms_a_moved_archive_key_without_edit_or_export(tmp_path):
    from sciplot_core.plot_protocol.client import call
    from sciplot_core.plot_protocol.rpc import RemoteError
    from sciplot_core.project_lifecycle.capabilities import COMPATIBILITY_CAPABILITIES
    from sciplot_core.project_lifecycle.project_file_append import project_file_create_xy
    from test_project_file_append import _ordinary_request, _save_axis_revision

    original = tmp_path.resolve() / "original work"
    original.mkdir()
    source = original / "sample.csv"
    source.write_text("Temperature,Heat Flow\nC,W/g\nSample,Sample\n66,-0.023\n61,0.008\n53,-0.016\n")
    publication = original / "sample.sciplot"
    project_file_create_xy(publication, _ordinary_request(source), capabilities=COMPATIBILITY_CAPABILITIES)
    def operation(name, **params):
        return call(name, params, direct=True)

    opened = operation("project.open", target=str(publication))
    target, axis = next(iter(opened["edit_targets"].items()))
    lookup = {"plot_id": opened["plot_id"], "base_revision": opened["revision"], "idempotency_key": "saved-unchanged-axis"}
    request = {**lookup, "mode": "apply", "target_id": target, "property": "axis.label", "value": axis["label"]}
    assert operation("plot.intent", plot=str(publication), request=request)["status"] == "saved"
    _save_axis_revision(publication, opened["plot_id"], "Revised temperature axis (C)")
    moved = publication.rename(tmp_path / "moved.sciplot")
    shutil.rmtree(original)
    before = file_sha256(moved)

    assert operation("plot.describe", plot=str(moved)) == operation("project.open", target=str(moved))
    confirmed = operation("plot.resume", plot=str(moved), request=lookup)
    assert confirmed["status"] == "already_saved"
    assert confirmed["project_file"] == str(moved) and confirmed["project_id"] == opened["project_id"]
    assert confirmed["plot_id"] == opened["plot_id"] and confirmed["revision"] == opened["revision"]
    assert confirmed["current_revision"] == opened["revision"] + 1
    lookup_file = tmp_path / "lookup.json"
    lookup_file.write_text(json.dumps(lookup))
    cli = subprocess.run(
        [str(REPO_ROOT / "skill/scripts/sciplot"), "plot", "resume", moved.name,
         "--request", lookup_file.name, "--direct", "--json"], cwd=tmp_path,
        env={**os.environ, "SCIPLOT_PYTHON": sys.executable}, capture_output=True, text=True, timeout=30, check=False,
    )
    assert cli.returncode == 0, cli.stdout + cli.stderr
    assert json.loads(cli.stdout) == confirmed

    for changed, reason in (
        ({"idempotency_key": "unknown"}, "project_file_intent_unconfirmed"),
        ({"base_revision": 45}, "document_revision_conflict"),
        ({"plot_id": "foreign"}, "project_file_figure_not_found"),
    ):
        with pytest.raises(RemoteError) as rejected:
            operation("plot.resume", plot=str(moved), request={**lookup, **changed})
        assert rejected.value.reason_code == reason
    with pytest.raises(RemoteError) as rejected:
        operation("plot.rollback", plot=str(moved),
                  request={"base_revision": 0, "target_revision": 0, "idempotency_key": "no-rollback"})
    assert rejected.value.reason_code == "project_file_operation_unsupported"
    alias = tmp_path / "alias.sciplot"
    alias.symlink_to(moved)
    with pytest.raises(RemoteError) as rejected:
        operation("plot.resume", plot=str(alias), request=lookup)
    assert rejected.value.reason_code == "project_file_invalid"
    assert file_sha256(moved) == before and not original.exists()


def test_archive_open_reports_missing_invalid_and_denied_as_distinct_actions(tmp_path, monkeypatch):
    from sciplot_core.plot_protocol.client import call
    from sciplot_core.plot_protocol.rpc import RemoteError
    from sciplot_core.project_lifecycle import project_file_summary

    target = tmp_path / "sample.sciplot"
    params = {"target": str(target)}
    with pytest.raises(RemoteError) as missing:
        call("project.open", params, direct=True)
    assert missing.value.reason_code == "path_not_found" and missing.value.repair["project_file"] == str(target)
    target.write_text("not a project archive")
    with pytest.raises(RemoteError) as invalid:
        call("project.open", params, direct=True)
    assert invalid.value.reason_code == "project_file_invalid"

    def blocked(_path):
        raise PermissionError("/private/project temporary path")

    monkeypatch.setattr(project_file_summary, "open_project_file", blocked)
    with pytest.raises(RemoteError) as denied:
        call("project.open", params, direct=True)
    assert denied.value.reason_code == "project_file_access_denied"
    assert denied.value.repair == {"action": "check_project_file_access", "project_file": str(target)}
    assert "/private/project temporary path" not in str(denied.value)
