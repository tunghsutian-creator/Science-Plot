"""Private worker packets pin mapping bytes before source registration."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

import pytest

from test_mapping_execution_portability import confirmed_project
from sciplot_core.data_mapping import load_data_mapping_execution
from sciplot_core.data_mapping.execution_inputs import mapping_input_reads
from sciplot_core.project_store.worker_binding import native_mapping_binding, mapping_binding_payload
from sciplot_core.project_store import ProjectConflict
from sciplot_core.project_store.runtime import project_runtime
from sciplot_core.project_store.worker_binding import native_runtime_binding


@pytest.mark.parametrize("change", ["none", "metadata-drift"], ids=["same-bytes", "after-packet-drift"])
def test_real_child_uses_prepublication_mapping_byte_witness_and_clears_it(tmp_path, monkeypatch, change):
    _origin, _project, store, request, execution = confirmed_project(tmp_path, monkeypatch)
    generation = store.snapshot()["parent"]
    argv = ["observe-mapping-read-only", request["data_mapping_execution"]]
    script = """import json,sys
from sciplot_core.project_store.worker_binding import worker_project_runtime
from sciplot_core.data_mapping import load_data_mapping_execution
from sciplot_core.project_store.worker_binding import native_mapping_binding
from sciplot_core.foundation.source_locations import selected_source_resolver
with worker_project_runtime(json.loads(sys.argv[1]),json.loads(sys.argv[2])):
    result=load_data_mapping_execution(sys.argv[3])
    print(json.dumps({'proposal_id':result['proposal_id'],'rows':[item['rows'] for item in result['outputs']]}))
assert selected_source_resolver() is None and native_mapping_binding() is None
"""
    with project_runtime(store, generation=generation) as resolver, mapping_input_reads(request["data_mapping_execution"]):
        assert resolver.snapshot["sources"] == {}  # Before the introducing source publication.
        load_data_mapping_execution(request["data_mapping_execution"])
        with native_runtime_binding(argv) as reference:
            packet = json.loads(Path(reference["path"]).read_bytes())
            assert packet["project"]["mapping_inputs"] == native_mapping_binding()
            if change != "none":
                seed = Path(execution["request_seed"])
                seed.write_bytes(seed.read_bytes() + b" ")
            result = subprocess.run([sys.executable, "-c", script, json.dumps(reference), json.dumps(argv),
                request["data_mapping_execution"]], capture_output=True, text=True, timeout=30)
            if change == "none":
                assert result.returncode == 0, result.stdout + result.stderr
                assert json.loads(result.stdout) == {"proposal_id": execution["proposal_id"], "rows": [3]}
            else:
                assert result.returncode != 0 and "hash changed" in result.stderr
                seed.write_bytes(seed.read_bytes()[:-1])  # Restore only this fixture's exact preimage.
    assert native_mapping_binding() is None


@pytest.mark.parametrize("mutation", ["extra", "field", "sha", "mode", "relative"])
def test_worker_mapping_descriptor_is_closed_and_byte_typed(tmp_path, monkeypatch, mutation):
    _origin, _project, store, request, _execution = confirmed_project(tmp_path, monkeypatch)
    with project_runtime(store), mapping_input_reads(request["data_mapping_execution"]):
        load_data_mapping_execution(request["data_mapping_execution"])
        packet = deepcopy(native_mapping_binding())
    if mutation == "extra":
        packet["root"] = str(tmp_path)
    elif mutation == "field":
        packet["files"][0]["parent"] = str(tmp_path)
    elif mutation == "sha":
        packet["files"][0]["sha256"] = "not-byte-sha"
    elif mutation == "mode":
        packet["files"][0]["mode"] = True
    else:
        packet["files"][0]["path"] = "execution.json"
    with pytest.raises(ProjectConflict):
        mapping_binding_payload(packet)
