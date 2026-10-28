"""Actual figure-set adapter hard exits never expose an unmarked mixed set."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import pytest

from sciplot_core.project_commands import ProjectCommand, ProjectCommands
from sciplot_core.project_store import FileProjectStore
from sciplot_core.project_store import ProjectRecoveryRequired

pytestmark = pytest.mark.comprehensive


def _install(root_string, point):
    from sciplot_core.project_store import state
    from sciplot_core.studio_core.figure_set_storage import _commit_studio_figure_set_transaction

    root = Path(root_string)
    tempfile.tempdir = str(root.parent / "private-temporaries")
    Path(tempfile.tempdir).mkdir(exist_ok=True)
    replacements = []
    for name, data, kind in (("document.vsz", b"new native", "document"), ("spec.json", b'{"new":true}', "spec")):
        source = root / "studio" / (".candidate-" + name)
        source.write_bytes(data)
        replacements.append({"target": root / "studio" / name, "staged": source,
            "expected_hash": __import__("hashlib").sha256(data).hexdigest(), "kind": kind})

    def boundary(name):
        if name == point:
            os._exit(73)

    state.boundary = boundary
    calls = []

    def replace(source, destination):
        source.replace(destination)
        calls.append(destination)
        if point == "second_private_install" and len(calls) == 2:
            os._exit(73)

    _commit_studio_figure_set_transaction(project_dir=root, replacements=replacements, manual_archive_requests=[],
        registry={"kind": "sciplot_studio_figure_set", "version": 1, "figures": [], "generation": "new"},
        path_replacer=replace)


@pytest.mark.parametrize("point", ["second_private_install", "before_storage", "after_generation", "before_head", "after_head", "after_projection", "before_reply"])
def test_actual_figure_adapter_hard_exit_recovers_one_complete_generation(tmp_path, point):
    root = tmp_path / "project"
    studio = root / "studio"
    studio.mkdir(parents=True)
    (studio / "document.vsz").write_bytes(b"old native")
    (studio / "spec.json").write_bytes(b'{"old":true}')
    (studio / "figure_set.json").write_text(json.dumps({"kind": "sciplot_studio_figure_set", "version": 1,
        "figures": [], "generation": "old"}))
    FileProjectStore(root).snapshot(import_legacy=True)
    program = "import runpy,sys;runpy.run_path(sys.argv[1])['_install'](*sys.argv[2:])"
    process = subprocess.run([sys.executable, "-c", program, str(Path(__file__).resolve()), str(root), point],
                             capture_output=True, text=True, check=False, timeout=10)
    assert process.returncode == 73, (process.stdout, process.stderr)
    observed = [(studio / name).read_bytes() for name in ("document.vsz", "spec.json")]
    if point == "after_projection":
        assert observed == [b"new native", b'{"old":true}']
    else:
        assert observed in ([b"old native", b'{"old":true}'], [b"new native", b'{"new":true}'])
    store = FileProjectStore(root)
    if point in {"after_head", "after_projection"}:
        with pytest.raises(ProjectRecoveryRequired):
            store.snapshot()
    records = store.commands()
    for record in records:
        command = ProjectCommand.from_payload(record["metadata"])
        ProjectCommands(store).resume(command)
    store.recover()
    snapshot = store.snapshot()
    if point == "second_private_install":
        assert not records
        assert snapshot["files"]["studio/document.vsz"]["sha256"] == __import__("hashlib").sha256(b"old native").hexdigest()
        assert [(studio / name).read_bytes() for name in ("document.vsz", "spec.json")] == [b"old native", b'{"old":true}']
    else:
        assert [(studio / name).read_bytes() for name in ("document.vsz", "spec.json")] == [b"new native", b'{"new":true}']
        assert json.loads((studio / "figure_set.json").read_bytes())["generation"] == "new"
        assert all(record["phase"] == "complete" for record in store.commands())
