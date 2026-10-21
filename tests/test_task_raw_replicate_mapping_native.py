"""Generated native acceptance target; not part of bounded pure development runs."""
import json
from pathlib import Path

import pytest

from sciplot_core import task_control as control
from sciplot_core.data_mapping import load_data_mapping_execution
from sciplot_core.foundation.file_hashing import file_sha256
from test_task_raw_replicate_mapping import original
from test_task_raw_replicate_source_update import expanded


@pytest.mark.comprehensive
def test_raw_subset_then_same_project_group_expansion_keeps_native_science_and_style(tmp_path):
    from sciplot_core.studio_core.registry_state import _veusz_spec_path
    from sciplot_core.studio_core.document_edit_state import run_document_worker
    from sciplot_core.veusz_worker.document_edit import loaded_native_document

    source, request, mapping = original(tmp_path)
    digest = file_sha256(source)
    created = control.start_task({**request, "mapping": mapping}, task_dir=tmp_path / "create")
    assert created["status"] == "complete", created
    assert all(created["current_project"][key]["current"] for key in ("source", "qa", "delivery"))
    project = Path(created["project"])
    figure = created["current_project"]["figures"][0]
    identity, document = figure["figure_id"], Path(figure["document"])
    spec_path = _veusz_spec_path(document)
    before = json.loads(spec_path.read_text())
    expected = {"Amber": [1., 1., 3., 5.], "Blue": [7., 8., 9.], "Coral": [11., 12., 13., 14., 15.]}
    assert [group["raw_values"] for group in before["categorical"]["groups"]] == [expected["Amber"], expected["Blue"]]
    with loaded_native_document(document) as native:
        from veusz.document import CommandInterface
        interface = CommandInterface(native)
        interface.To("/page1/graph1/x")
        interface.Set("Label/size", "9pt")
        for series in before["series"]:
            interface.To("/page1/graph1/" + series["name"])
            interface.Set("MarkerFill/color", "#7B61A8")
            interface.Set("MarkerLine/color", "#7B61A8")
        interface.Save(str(document))
    edited = document.read_bytes()

    task = tmp_path / "update"
    question = control.start_task({"version": 1, "action": "update_source", "project": str(project), "source": str(source)}, task_dir=task)
    assert question["status"] == "needs_input" and question["question"]["mapping_shape"] == "replicates"
    pending = control.resume_task(task, {"expected_question_id": question["question"]["question_id"], "mapping": expanded(mapping)})
    assert pending["status"] == "needs_review", pending
    assert document.read_bytes() == edited
    assert all(Path(item["preview"]["path"]).is_file() for item in pending["previews"])
    assert {item["scope"] for item in pending["previews"]} == {"before", "candidate"}
    change = pending["preview"]["changes"]["changes"]["figures"][0]
    assert change["figure_id"] == identity and change["samples_added"] == ["Coral"]
    assert change["samples_removed"] == [] and change["numerical_differences"] == []
    completed = control.resume_task(task, {"accept_source_update": True, "expected_revision_id": pending["revision_id"]})
    assert completed["status"] == "complete" and Path(completed["project"]) == project, completed
    assert all(completed["current_project"][key]["current"] for key in ("source", "qa", "delivery"))
    assert completed["current_project"]["figures"][0]["figure_id"] == identity
    current = json.loads(spec_path.read_text())
    assert current["categorical"]["summary_calculation"] == "none"
    assert [group["label"] for group in current["categorical"]["groups"]] == list(expected)
    assert [group["raw_values"] for group in current["categorical"]["groups"]] == list(expected.values())
    assert all("descriptive_statistics" not in group for group in current["categorical"]["groups"])
    with loaded_native_document(document) as native:
        from veusz.document import CommandInterface
        interface = CommandInterface(native)
        interface.To("/page1/graph1/x")
        assert interface.Get("Label/size") == "9pt"
        for series in current["series"]:
            assert [float(value).hex() for value in native.data[series["y_name"]].data] == [value.hex() for value in expected[series["label"]]]
            if series["label"] in {"Amber", "Blue"}:
                interface.To("/page1/graph1/" + series["name"])
                assert interface.Get("MarkerFill/color") == "#7B61A8"
    assert run_document_worker("audit-spec-data", document, spec_path)["status"] == "passed"
    stored = json.loads((project / "plot_request.json").read_text())
    mapped = load_data_mapping_execution(stored["data_mapping_execution"])
    assert [item["rows"] for item in mapped["outputs"]] == [7, 7, 5]
    from sciplot_core.task_storage import load_task
    archive = Path(load_task(task)["source_update_outcome"]["archive"])
    assert (archive / "studio/document.vsz").read_bytes() == edited
    installed = document.read_bytes()
    assert control.resume_task(task, {"retry": True})["status"] == "complete"
    assert document.read_bytes() == installed and file_sha256(source) == digest
