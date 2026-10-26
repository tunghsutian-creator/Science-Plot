"""Default public edit/style checkpoints survive native save, Undo and restart."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from time import monotonic
from uuid import uuid4

import pytest

from sciplot_core.foundation.json_io import atomic_write_json
from sciplot_core.veusz_runtime import veusz_worker_environment

pytestmark = pytest.mark.comprehensive


def lifecycle(root, progress):
    from sciplot_core.plot_engine.service import PlotService
    from sciplot_core.project_store.repository import FileProjectStore
    from sciplot_core.render import render_to_dir
    from sciplot_core.task_common_edits import edit_task
    from sciplot_core.task_shortcuts import style_task

    project = root / "project"
    source = project / "source/values.csv"
    source.parent.mkdir(parents=True)
    source.write_text("Time,Force\ns,N\nA,A\n0,1\n1,3\n2,2\n")
    raw = source.read_bytes()
    progress("initial_render")
    rendered = render_to_dir(source, template="curve", output_dir=root / "rendered",
                             export_formats=(), options={"size": "60x55"})
    studio = project / "studio"
    studio.mkdir()
    shutil.copy2(rendered["veusz_documents"][0], studio / "document.vsz")
    shutil.copy2(rendered["veusz_specs"][0], studio / "spec.json")
    (project / "plot_request.json").write_text(json.dumps({"input": str(source), "template": "curve"}))
    spec = (studio / "spec.json").read_bytes()
    store = FileProjectStore(project)
    store.snapshot(import_legacy=True)
    service = PlotService()
    try:
        progress("open")
        opened = service.open(project, figure_id="primary")
        plot = Path(opened["plot"])
        progress("common_edit")
        common = edit_task(plot, palette="tol_bright", service=service)
        assert common["ready_to_use"] and common["revision"] == 1, common
        common_entry = Path(common["edit_entry"])
        progress("style")
        styled = style_task(project, all_samples=True, width="1.3pt")
        assert styled["ready_to_use"] and styled["revision"] == 2, styled
        entries = [name for name in store.snapshot()["files"] if name.endswith("semantic-style.json")]
        assert len(entries) == 1
        style_entry = (project / entries[0]).parent
        originals = {name: store.read_bytes(name) for name in store.snapshot()["files"]
                     if name.endswith(("semantic-style.json", "semantic-edit.json"))}
        progress("style_replay")
        replay = style_task(project, all_samples=True, width="1.3pt", task_dir=style_entry)
        assert replay["replayed"] and replay["revision"] == 2
        progress("undo")
        undone = service.rollback(plot, {"base_revision": 2, "target_revision": 0, "idempotency_key": "undo-default-edits"})
        if undone["status"] == "needs_review":
            undone = service.decide(plot, undone["next_step"]["request"])
        assert undone["ready_to_use"] and undone["revision"] == 3
        assert undone["presentation_hash"] == opened["presentation_hash"]
        assert undone["scientific_hash"] == opened["scientific_hash"]
        native = (studio / "document.vsz").read_bytes()
    finally:
        progress("close_first_service")
        service.close()
    assert source.read_bytes() == raw and (studio / "spec.json").read_bytes() == spec
    service = PlotService()
    try:
        progress("reopen")
        reopened = service.open(project, figure_id=opened["plot_id"])
        assert reopened["revision"] == 3 and reopened["scientific_hash"] == opened["scientific_hash"]
        def no_apply(*_):
            pytest.fail("Checkpoint replay applied native edits after Undo")
        service.backend.backend.legacy.apply = no_apply
        progress("historical_replay")
        replayed = edit_task(plot, palette="tol_bright", task_dir=common_entry, service=service)
        assert replayed["replayed"] and replayed["historical"] and replayed["revision"] == 1, replayed
        assert replayed["current_revision"] == 3 and replayed["ready_to_use"] is False
        assert (studio / "document.vsz").read_bytes() == native
        assert {name: store.read_bytes(name) for name in originals} == originals
        assert store.snapshot()["projection_status"] == "current"
    finally:
        progress("close_second_service")
        service.close()


def scenario(root):
    root.mkdir(parents=True, exist_ok=True)
    workers = []
    launches = []
    stages = []

    def progress(stage):
        stages.append({"stage": stage, "observed_monotonic": monotonic()})
        atomic_write_json(root / "owned-native-progress.json", {
            "claim": "diagnostic_only_not_exit_or_completion_evidence",
            "pid": os.getpid(), "parent_pid": os.getppid(), "argv": sys.argv,
            "stages": stages, "worker_launches": launches})

    original = subprocess.Popen
    def tracked(command, *args, **kwargs):
        process = original(command, *args, **kwargs)
        if isinstance(command, (tuple, list)) and any(isinstance(item, str) and (
                item == "sciplot_core.veusz_worker" or item.startswith("sciplot_core.veusz_worker.")) for item in command):
            workers.append(process)
            launches.append({"pid": process.pid, "parent_pid": os.getpid(), "requested_argv": list(command),
                "requested_argv_sha256": hashlib.sha256(json.dumps(list(command), separators=(",", ":")).encode()).hexdigest()})
            progress("worker_spawn")
        return process
    subprocess.Popen = tracked
    completed = False
    try:
        progress("scenario_start")
        lifecycle(root, progress)
        completed = True
    finally:
        subprocess.Popen = original
        natural = bool(workers) and all(process.poll() is not None for process in workers)
        forced = []
        for process in workers:
            if process.poll() is None:
                forced.append(process.pid)
                process.terminate()
                process.wait(timeout=10)
        (root / "owned-native.json").write_text(json.dumps({"pid": os.getpid(), "parent_pid": os.getppid(),
            "completed": completed, "natural_worker_exit": natural, "forced_cleanup": forced,
            "workers": [{"pid": process.pid, "exit": process.poll()} for process in workers]}))
    assert natural


def _retain_native_evidence(tmp_path, *, command, stdout, stderr, exit_code, timeout=None):
    evidence = Path(__file__).resolve().parents[1] / ".tmp_verify/entry-checkpoints/native-cases" / uuid4().hex
    evidence.mkdir(parents=True)
    def text(value):
        return value.decode(errors="replace") if isinstance(value, bytes) else value or ""
    (evidence / "child.stdout.log").write_text(text(stdout))
    (evidence / "child.stderr.log").write_text(text(stderr))
    (evidence / "result.json").write_text(json.dumps({"command": command, "exit": exit_code, "timeout_seconds": timeout}))
    for path in tmp_path.rglob("*.json"):
        if path.name in {"owned-native.json", "owned-native-progress.json"} or path.name.startswith("diagnostic-"):
            target = evidence / path.relative_to(tmp_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)


def test_default_attached_native_common_style_save_undo_restart_replay(tmp_path):
    try:
        result = subprocess.run([sys.executable, __file__, str(tmp_path)], env=veusz_worker_environment(),
                                capture_output=True, text=True, timeout=180, check=False)
    except subprocess.TimeoutExpired as error:
        _retain_native_evidence(tmp_path, command=error.cmd, stdout=error.stdout, stderr=error.stderr,
                                exit_code=None, timeout=error.timeout)
        raise
    _retain_native_evidence(tmp_path, command=result.args, stdout=result.stdout, stderr=result.stderr,
                            exit_code=result.returncode)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads((tmp_path / "owned-native.json").read_text())["completed"]


if __name__ == "__main__":
    scenario(Path(sys.argv[1]).resolve())
