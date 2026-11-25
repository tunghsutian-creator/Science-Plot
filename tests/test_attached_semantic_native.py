"""Actual owned Veusz figures keep one semantic head through offline project moves."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from uuid import uuid4

import pytest

from sciplot_core.veusz_runtime import veusz_worker_environment

pytestmark = pytest.mark.comprehensive


def managed(root):
    from managed_plot_helpers import patch, request_for_source
    from sciplot_core.plot_engine.service import PlotService
    from sciplot_core.project_store.repository import FileProjectStore

    project, sources = root / "managed-project", root / "original-inputs"
    project.mkdir()
    sources.mkdir()
    request = request_for_source(sources)
    raw_path = Path(request["data_binding"]["data_sources"][0]["path"])
    raw = raw_path.read_bytes()
    store = FileProjectStore(project)
    identity = store.snapshot(import_legacy=True)["project_id"]
    service = PlotService()
    try:
        created = service.create(request, project=project)
        assert created["ready_to_use"] and created["revision"] == 0, created
        styled = service.patch(Path(created["plot"]), patch(created, "native-style", "style.line.width", "1.2pt", "series:A"))
        assert styled["ready_to_use"] and styled["revision"] == 1, styled
        assert styled["scientific_hash"] == created["scientific_hash"]
        snapshot = store.snapshot()
        history = {name: store.read_bytes(name) for name in snapshot["files"] if "/revisions/" in name}
        assert len(history) == 2
        bundle = store.export_bundle(root / "managed-bundle")
    finally:
        service.close()
    assert raw_path.read_bytes() == raw
    project.rename(root / "managed-offline")
    sources.rename(root / "inputs-offline")
    cold = FileProjectStore.import_bundle(bundle, root / "managed-cold")
    shutil.rmtree(cold.root / ".sciplot_store/semantic-derived", ignore_errors=True)
    service = PlotService()
    try:
        opened = service.open(cold.root, figure_id=created["plot_id"])
        exported = service.export(Path(opened["plot"]))
        assert opened["plot_id"] == created["plot_id"] and opened["revision"] == 1
        assert exported["ready_to_use"] and exported["scientific_hash"] == created["scientific_hash"]
        assert all(Path(item["path"]).is_relative_to(cold.root) for item in exported["exports"])
        assert {name: cold.read_bytes(name) for name in history} == history
        assert cold.snapshot()["project_id"] == identity and cold.snapshot()["projection_status"] == "current"
    finally:
        service.close()


def legacy(root):
    from managed_plot_helpers import patch
    from sciplot_core.plot_engine.service import PlotService
    from sciplot_core.project_store.repository import FileProjectStore
    from sciplot_core.render import render_to_dir

    project = root / "legacy-project"
    source = project / "source/values.csv"
    source.parent.mkdir(parents=True)
    source.write_text("Time,Force\ns,N\nA,A\n0,1\n1,3\n2,2\n")
    raw = source.read_bytes()
    rendered = render_to_dir(source, template="curve", output_dir=root / "rendered",
                             export_formats=(), options={"size": "60x55"})
    studio = project / "studio"
    studio.mkdir()
    shutil.copy2(rendered["veusz_documents"][0], studio / "document.vsz")
    shutil.copy2(rendered["veusz_specs"][0], studio / "spec.json")
    (project / "plot_request.json").write_text(json.dumps({"input": str(source), "template": "curve"}))
    spec = (studio / "spec.json").read_bytes()
    store = FileProjectStore(project)
    identity = store.snapshot(import_legacy=True)["project_id"]
    service = PlotService()
    try:
        opened = service.open(project, figure_id="primary")
        assert opened["plot_type"] == "LegacyPlot" and Path(opened["plot"]).parent == project / ".sciplot_semantic"
        styled = service.patch(Path(opened["plot"]), patch(opened, "native-legacy-style", "style.line.width", "1.3pt", "series:A"))
        assert styled["ready_to_use"] and styled["revision"] == 1, styled
        assert styled["scientific_hash"] == opened["scientific_hash"]
        native = (studio / "document.vsz").read_bytes()
        history = {name: store.read_bytes(name) for name in store.snapshot()["files"] if "/revisions/" in name}
        bundle = store.export_bundle(root / "legacy-bundle")
    finally:
        service.close()
    assert source.read_bytes() == raw and (studio / "spec.json").read_bytes() == spec
    project.rename(root / "legacy-offline")
    cold = FileProjectStore.import_bundle(bundle, root / "legacy-cold")
    shutil.rmtree(cold.root / ".sciplot_store/semantic-derived", ignore_errors=True)
    service = PlotService()
    try:
        reopened = service.open(cold.root, figure_id=opened["plot_id"])
        result = service.export(Path(reopened["plot"]))
        assert result["ready_to_use"] and result["scientific_hash"] == opened["scientific_hash"]
        assert result["plot_id"] == opened["plot_id"] and reopened["revision"] == 1
        assert (cold.root / "studio/document.vsz").read_bytes() == native
        assert (cold.root / "studio/spec.json").read_bytes() == spec
        assert (cold.root / "source/values.csv").read_bytes() == raw
        assert {name: cold.read_bytes(name) for name in history} == history
        assert cold.snapshot()["project_id"] == identity and cold.snapshot()["projection_status"] == "current"
    finally:
        service.close()


def legacy_pending(root):
    from managed_plot_helpers import patch
    from sciplot_core.foundation.project_session_lease import external_project_session
    from sciplot_core.plot_engine.service import PlotService
    from sciplot_core.project_lifecycle.repository import FileProjectRepository, transaction_path
    from sciplot_core.project_store.repository import FileProjectStore
    from sciplot_core.project_store.runtime import project_runtime
    from sciplot_core.render import render_to_dir

    class LostReply(BaseException):
        pass

    project = root / "pending-project"
    source = project / "source/values.csv"
    source.parent.mkdir(parents=True)
    source.write_text("Time,Force\ns,N\nA,A\n0,1\n1,3\n2,2\n")
    rendered = render_to_dir(source, template="curve", output_dir=root / "rendered",
                             export_formats=(), options={"size": "60x55"})
    studio = project / "studio"
    studio.mkdir()
    shutil.copy2(rendered["veusz_documents"][0], studio / "document.vsz")
    shutil.copy2(rendered["veusz_specs"][0], studio / "spec.json")
    (project / "plot_request.json").write_text(json.dumps({"input": str(source), "template": "curve"}))
    repository = FileProjectRepository(lease=external_project_session)
    original = PlotService(repository=repository)
    try:
        opened = original.open(project, figure_id="primary")
        old = Path(opened["plot"])
        request = patch(opened, "lost-native-reply", "style.line.width", "1.3pt", "series:A")
        apply = original.backend.apply
        calls = []

        def interrupted(*args):
            calls.append("apply")
            apply(*args)
            raise LostReply()

        original.backend.apply = interrupted
        with pytest.raises(LostReply):
            original.patch(old, request)
        transaction = repository.active(old)
        assert transaction["phase"] == "applying" and repository.load_head(old)["document"]["revision"] == 0
        assert calls == ["apply"]
    finally:
        original.close()
    native = (studio / "document.vsz").read_bytes()
    head_bytes = (old / "revisions/00000000.json").read_bytes()
    store = FileProjectStore(project)
    service = PlotService()
    try:
        def no_repeat(*_args):
            pytest.fail("Ownership transfer must consume the saved native receipt without applying again")

        service.backend.backend.apply = no_repeat
        journal = transaction_path(old, request["idempotency_key"])
        saved = journal.read_bytes()
        forged = json.loads(saved)
        forged["review"]["decision_id"] = "unrelated-native-decision"
        journal.write_text(json.dumps(forged))
        with project_runtime(store), pytest.raises(ValueError):
            service.open(old)
        assert not (old / ".sciplot_semantic_owner.json").exists()
        assert repository.load_head(old)["document"]["revision"] == 0
        assert (studio / "document.vsz").read_bytes() == native
        journal.write_bytes(saved)
        with project_runtime(store):
            attached = service.open(old)
        assert attached["pending"]["phase"] == "applying"
        root = Path(attached["plot"])
        assert (studio / "document.vsz").read_bytes() == native
        assert (root / "revisions/00000000.json").read_bytes() == head_bytes
        # Restoring the method permits the native owner to return its existing
        # completed receipt; it must not execute a second edit or native worker.
        del service.backend.backend.apply
        before = native
        resumed = service.patch(root, request)
        assert resumed["ready_to_use"] and resumed["revision"] == 1, resumed
        assert (studio / "document.vsz").read_bytes() == before
        assert resumed["scientific_hash"] == opened["scientific_hash"]
        assert store.snapshot()["projection_status"] == "current"
    finally:
        service.close()


def scenario(kind, root):
    root.mkdir(parents=True, exist_ok=True)
    workers = []
    original = subprocess.Popen

    def tracked(command, *args, **kwargs):
        process = original(command, *args, **kwargs)
        if isinstance(command, (tuple, list)) and any(isinstance(item, str) and (
                item == "sciplot_core.veusz_worker" or item.startswith("sciplot_core.veusz_worker.")) for item in command):
            workers.append(process)
        return process

    subprocess.Popen = tracked
    completed = False
    try:
        {"managed": managed, "legacy": legacy, "legacy_pending": legacy_pending}[kind](root)
        completed = True
    except subprocess.CalledProcessError as exc:
        def stream(value):
            return value.decode(errors="replace") if isinstance(value, bytes) else value

        (root / "failed-native-process.json").write_text(json.dumps({"cmd": exc.cmd, "exit": exc.returncode,
            "stdout": stream(exc.stdout), "stderr": stream(exc.stderr)}))
        raise
    finally:
        subprocess.Popen = original
        natural = bool(workers) and all(process.poll() is not None for process in workers)
        forced = []
        for process in workers:
            if process.poll() is None:
                forced.append(process.pid)
                process.terminate()
                process.wait(timeout=10)
        (root / "owned-native.json").write_text(json.dumps({"scenario": kind, "pid": os.getpid(),
            "parent_pid": os.getppid(), "completed": completed, "natural_worker_exit": natural, "forced_cleanup": forced,
            "workers": [{"pid": process.pid, "exit": process.poll()} for process in workers],
            "checks": (["same_generation_semantic_writer", "unchanged_scientific_seal", "style",
                        "unchanged_revision_bytes", "all_owned_workers_exited"] + (
                        ["native_complete_reply_loss", "forged_decision_refused_before_fence", "readonly_receipt_handoff", "same_key_recovery"]
                        if kind == "legacy_pending" else ["raw_units_and_science", "project_offline", "artifact_deletion", "cold_open_export"]))
                       if completed else []}))
    assert natural


@pytest.mark.parametrize("kind", ["managed", "legacy", "legacy_pending"])
def test_attached_public_native_cold_lifecycle(tmp_path, kind):
    result = subprocess.run([sys.executable, __file__, kind, str(tmp_path)], env=veusz_worker_environment(),
                            capture_output=True, text=True, timeout=180, check=False)
    evidence = Path(__file__).resolve().parents[1] / ".tmp_verify/attached-semantic/native-cases" / (uuid4().hex + "-" + kind)
    evidence.mkdir(parents=True)
    (evidence / "child.stdout.log").write_text(result.stdout)
    (evidence / "child.stderr.log").write_text(result.stderr)
    (evidence / "result.json").write_text(json.dumps({"command": result.args, "exit": result.returncode, "scenario": kind}))
    for path in tmp_path.rglob("*.json"):
        if path.name in {"owned-native.json", "failed-native-process.json"} or path.name.startswith("diagnostic-"):
            target = evidence / path.relative_to(tmp_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads((tmp_path / "owned-native.json").read_text())["checks"]


if __name__ == "__main__":
    scenario(sys.argv[1], Path(sys.argv[2]).resolve())


def test_cold_expert_bundle_does_not_write_to_its_historical_publication(tmp_path):
    import anyio
    from mcp import Client
    from managed_plot_helpers import patch, request_for_source
    from test_mcp_stdio import _call, _parameters

    from sciplot_core.plot_engine.service import PlotService
    from sciplot_core.project_store.repository import FileProjectStore
    from sciplot_core.studio_core.project_query import inspect_project

    sources = tmp_path / "original-input"
    sources.mkdir()
    request = request_for_source(sources)
    raw = Path(request["data_binding"]["data_sources"][0]["path"])
    raw_bytes = raw.read_bytes()
    output = tmp_path / "historical-exports"
    request["out"] = str(output)
    with_service = PlotService(read_only_legacy=True)
    try:
        created = with_service.create(request)
        assert created["ready_to_use"] and created["revision"] == 0, created
        assert all(Path(item["path"]).is_relative_to(output) for item in created["exports"])
        plot = Path(created["plot"])
        store = plot.parent.parent
        snapshot = {path.relative_to(output): path.read_bytes() for path in output.rglob("*") if path.is_file()}
    finally:
        with_service.close()
    original_store = FileProjectStore(store)
    history = {name: original_store.read_bytes(name) for name in original_store.snapshot()["files"] if "/revisions/" in name}
    assert history

    async def scenario():
        async with Client(_parameters(cli=True, profile="daily"), read_timeout_seconds=180) as client:
            rejected_target = await client.call_tool("sciplot_project_bundle_export", {
                "project": str(plot), "output_dir": str(tmp_path / "not-a-bundle")})
            assert rejected_target.is_error and rejected_target.structured_content["error"]["code"] == "project_bundle_store_required"
            assert not (tmp_path / "not-a-bundle").exists()
            result = await _call(client, "sciplot_project_bundle_export", {
                "project": str(store), "output_dir": str(tmp_path / "bundle")})
            assert result["project"] == str(store) and result["status"] == "exported"
            offline = tmp_path / "offline"
            # The expert creation's Store is inside the source tree.
            sources.rename(offline)
            assert not raw.exists() and not store.exists()
            moved = tmp_path / "new-location"
            relocation = {"bundle": result["bundle"], "output_dir": str(moved)}
            relocated = await _call(client, "sciplot_project_bundle_import", relocation)
            assert relocated["project"] == str(moved) and relocated["status"] == "imported"
            assert (relocated["project_id"], relocated["generation"]) == (result["project_id"], result["generation"])
            assert relocated["host_grants_included"] is False
            duplicate = await client.call_tool("sciplot_project_bundle_import", relocation)
            assert duplicate.is_error and duplicate.structured_content["error"]["code"] == "project_bundle_destination_exists"
            cold_store = FileProjectStore(moved)
            assert cold_store.snapshot()["generation"] == result["generation"]
            assert {name: cold_store.read_bytes(name) for name in history} == history

            cold = PlotService(read_only_legacy=True)
            try:
                opened = cold.open(moved, figure_id=created["plot_id"], description={"scope": "summary"})
                assert opened["plot_id"] == created["plot_id"] and opened["revision"] == 0
                latest = cold.patch(Path(opened["plot"]), patch(opened, "cold-style", "style.line.width", "1.3pt", "series:A"))
                assert latest["ready_to_use"] and latest["revision"] == 1, latest
                assert latest["scientific_hash"] == created["scientific_hash"]
                assert all(Path(item["path"]).is_relative_to(moved) for item in latest["exports"])
                inspected = inspect_project(Path(opened["plot"]), figure_id=created["plot_id"])
                assert inspected["selected_figure"]["revision"] == 1 and inspected["ready_to_use"] is True
                assert inspected["delivery"]["current"] and inspected["qa"]["current"] is False
                assert {name: cold_store.read_bytes(name) for name in history} == history
                original_generation = cold_store.snapshot()["generation"]

                independent = tmp_path / "independent-project"
                save_as = {"plot": opened["plot"], "plot_id": opened["plot_id"], "revision": latest["revision"],
                           "output_dir": str(independent)}
                fork = await _call(client, "sciplot_project_save_as", save_as)
                assert fork["project"] == str(independent) and fork["project_id"] != relocated["project_id"]
                assert fork["plot_id"] != opened["plot_id"] and fork["created_revision"] == 0
                assert not fork["history_copied"] and fork["scientific_hash"] == latest["scientific_hash"]
                assert (await _call(client, "sciplot_project_save_as", save_as)) == fork
                forked = cold.open(Path(fork["plot"]), description={"scope": "summary"})
                changed = cold.patch(Path(fork["plot"]), patch(forked, "fork-style", "style.line.width", "1.8pt", "series:A"))
                assert changed["ready_to_use"] and changed["revision"] == 1
                assert changed["scientific_hash"] == latest["scientific_hash"]
                assert all(Path(item["path"]).is_relative_to(independent) for item in changed["exports"])
                assert cold_store.snapshot()["generation"] == original_generation
            finally:
                cold.close()
            assert {path.relative_to(output): path.read_bytes() for path in output.rglob("*") if path.is_file()} == snapshot
            assert (offline / raw.relative_to(sources)).read_bytes() == raw_bytes

    anyio.run(scenario)
