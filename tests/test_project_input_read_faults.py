"""Real process exits retain typed dynamic input admission through recovery."""
import subprocess
import sys

import pytest

from sciplot_core.project_commands import InputRead, PreparedSource, ProjectCommand, ProjectCommands, ProjectMutation
from sciplot_core.project_store import FileProjectStore, ProjectConflict
from sciplot_core.project_store.io import sha
from test_project_observed_inputs import input_store

pytestmark = pytest.mark.comprehensive


def candidate(store, source_id):
    before = store.snapshot()
    resource = "confirmed/execution.json"
    path = store.root / resource
    data = path.read_bytes()
    source = PreparedSource(source_id, str(path), sha(data), data, mode=0o600)
    mutation = ProjectMutation({"result.json": b'{"complete":"prepared"}'}, {}, prepared_sources=(source,),
                               input_reads=(InputRead(resource, source_id, source.version),))
    command = ProjectCommand.create("semantic_record", "fault-input", project_id=before["project_id"],
        expected_generation=before["generation"], read_set={resource: source.version, "result.json": None},
        write_set=["result.json"], request={"prepared_digest": mutation.prepared_digest})
    return command, mutation


@pytest.mark.parametrize("point", ["after_generation", "after_head", "before_reply"])
def test_owned_hardexit_recovers_exact_input_marker_without_source_install(tmp_path, point):
    store, before, resource, target, source = input_store(tmp_path)
    original = target.stat()
    command, mutation = candidate(store, source.source_id)
    program = """
import os, sys
from sciplot_core.project_store import FileProjectStore, state
from sciplot_core.project_commands import ProjectCommands
from test_project_input_read_faults import candidate
def boundary(name):
    if name == sys.argv[2]:
        os._exit(67)
state.boundary = boundary
store = FileProjectStore(sys.argv[1])
command, mutation = candidate(store, sys.argv[3])
ProjectCommands(store).publish_prepared(command, mutation)
"""
    child = subprocess.run([sys.executable, "-c", program, str(store.root), point, source.source_id],
                           capture_output=True, text=True, check=False, timeout=20)
    assert child.returncode == 67, (child.stdout, child.stderr)
    observed = FileProjectStore(store.root)
    if point == "after_generation":
        assert observed.snapshot()["generation"] == before["generation"]
    receipt = ProjectCommands(observed).resume(command)
    assert receipt["phase"] == "complete"
    assert observed.snapshot()["input_resources"] == [resource]
    assert observed.read_bytes("result.json") == mutation.writes["result.json"]
    assert target.read_bytes() == source.data
    assert (target.stat().st_ino, target.stat().st_mode, target.stat().st_mtime_ns) == (
        original.st_ino, original.st_mode, original.st_mtime_ns)
    assert ProjectCommands(observed).execute(command, lambda: pytest.fail("hardexit replay ran preparation"))["replayed"]
    current = observed.snapshot()
    with pytest.raises(ProjectConflict):
        observed.reserve("bad-write", "bad-write-digest", expected_generation=current["generation"],
                         read_set={resource: source.version}, write_set=[resource], metadata={"kind": "synthetic"})
