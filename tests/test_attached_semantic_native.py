"""Actual owned Veusz figures keep one semantic head through offline project moves."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

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
        assert created["ready_to_use"] and created["revision"] == 0
        styled = service.patch(Path(created["plot"]), patch(created, "native-style", "style.line.width", "1.2pt", "series:A"))
        assert styled["ready_to_use"] and styled["revision"] == 1
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
        assert styled["ready_to_use"] and styled["revision"] == 1
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
    repository = FileProjectRepository()
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
        if isinstance(command, (tuple, list)) and "sciplot_core.veusz_worker" in command:
            workers.append(process)
        return process

    subprocess.Popen = tracked
    try:
        {"managed": managed, "legacy": legacy, "legacy_pending": legacy_pending}[kind](root)
    finally:
        subprocess.Popen = original
    assert workers and all(process.poll() is not None for process in workers)
    (root / "owned-native.json").write_text(json.dumps({"scenario": kind, "pid": os.getpid(),
        "parent_pid": os.getppid(), "workers": [{"pid": process.pid, "exit": process.returncode} for process in workers],
        "checks": ["same_generation_semantic_writer", "raw_units_and_science", "style", "project_offline",
                   "artifact_deletion", "cold_open_export", "unchanged_revision_bytes", "all_owned_workers_exited"]}))


@pytest.mark.parametrize("kind", ["managed", "legacy", "legacy_pending"])
def test_attached_public_native_cold_lifecycle(tmp_path, kind):
    result = subprocess.run([sys.executable, __file__, kind, str(tmp_path)], env=veusz_worker_environment(),
                            capture_output=True, text=True, timeout=180, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads((tmp_path / "owned-native.json").read_text())["checks"]


if __name__ == "__main__":
    scenario(sys.argv[1], Path(sys.argv[2]).resolve())
