"""Serialized terminal requests retain identities after their IO view is gone."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

from sciplot_core.foundation.source_locations import resolve_source_path
from sciplot_core.project_commands import ProjectCommand, ProjectCommands, ProjectMutation
from sciplot_core.project_store import FileProjectStore
from sciplot_core.project_store.runtime import project_runtime
from sciplot_core.studio_core import veusz_document
from sciplot_core.studio_core.figure_requests import _impact_condition_figure_queue, _impact_condition_figure_request
from sciplot_core.studio_core.figure_source_request import figure_source_request
from sciplot_core.studio_core.preparation_candidate import studio_preparation_candidate
from sciplot_core.studio_core.series_request import _series_from_request
from sciplot_core.studio_render.models import IMPACT_POINT_LINE_RAW_KIND
from sciplot_core.terminal_source_binding import MaterializedTerminalSourceBinding
from test_impact_condition_figure_set import _write_two_condition_impact_source
from test_mechanical_studio_task_sources import _private_mechanical_source


@pytest.mark.parametrize("family", ["mechanical", "impact", "impact-point-line"])
def test_terminal_request_spec_and_artifacts_survive_private_cleanup_and_official_move(tmp_path, monkeypatch, family):
    project = tmp_path / "project"
    project.mkdir()
    task, plan, original = _private_mechanical_source(project)
    table = b"Strain,Stress,Strain,Stress\nE0,E0,E2,E2\n%,MPa,%,MPa\n0,1,0,2\n1,3,1,4\n"
    original.source.write_bytes(table)
    workbook = project / "impact.xlsx"
    _write_two_condition_impact_source(workbook)
    (project / "plot_request.json").write_bytes(b"{}")
    store = FileProjectStore(project)
    before = store.snapshot(import_legacy=True)

    def native_boundary(path, _spec, **_kwargs):
        path.write_bytes(b"only native serialization is excluded from this pure IO/spec counter")

    monkeypatch.setattr(veusz_document, "_save_veusz_document_from_spec", native_boundary)
    with studio_preparation_candidate(store) as candidate:
        if family == "mechanical":
            actual = candidate.project_dir / original.source.relative_to(project)
            binding = MaterializedTerminalSourceBinding.create(task_key=task.figure_id, rule_id=plan.rule_id,
                template=task.template, x_metric="strain", y_metric="stress",
                raw_sources=[candidate.project_dir / "raw.csv"], prepared_source=candidate.project_dir / "prepared.csv",
                terminal_source=actual, sample_order=task.sample_order, point_counts={"E0": 2, "E2": 2})
            record = replace(original, source=actual, binding=binding)
            request, selected = figure_source_request({"rule_id": plan.rule_id, "template": "curve"},
                figure={"_mechanical_task_source": record}, task=task, figure_plan=plan, queue_override=None)
            expected = str(project / "terminal.csv")
            foreign = candidate.project_dir / "foreign" / actual.name
            foreign.parent.mkdir()
            foreign.write_bytes(actual.read_bytes())
            with pytest.raises(ValueError, match="studio_figure_task_mismatch"):
                figure_source_request({}, figure={"_mechanical_task_source": replace(record, source=foreign)},
                    task=task, figure_plan=plan, queue_override=None)
        else:
            base = {"rule_id": "impact_metric", "template": "point_line" if family == "impact-point-line" else "box_strip",
                    "input": str(workbook)}
            queue = _impact_condition_figure_queue(base, base_dir=candidate.project_dir, project_dir=candidate.project_dir)
            actual = Path(queue[0]["condition_source"])
            request = _impact_condition_figure_request(base, queue[0])
            selected = None
            expected = str(project / actual.relative_to(candidate.project_dir))
            assert Path(queue[0]["condition_source"]) == actual and actual.is_file()
        assert str(actual) != expected and request["input"] == expected
        series, axes, _steps, _source = _series_from_request(request, base_dir=candidate.project_dir,
            _terminal_source_binding=selected)
        if family == "impact-point-line":
            assert sorted(tuple(item.y_values) for item in series if item.presentation_kind == IMPACT_POINT_LINE_RAW_KIND) == [
                (1., 1.1), (2., 2.1), (11., 11.1), (12., 12.1)]
        else:
            assert [item.label for item in series] == ["E0", "E2"]
            assert [list(item.y_values) for item in series] == ([[1., 3.], [2., 4.]] if family == "mechanical"
                                                            else [[1., 1.1], [2., 2.1]])
        spec_path = veusz_document._write_veusz_document(candidate.project_dir / "studio/document.vsz",
            request=request, series=series, axis_info=axes)
        spec_bytes = spec_path.read_bytes()
        spec = json.loads(spec_bytes)
        assert spec["source_request"]["input"] == expected
        expected_bytes = actual.read_bytes()
        captured = {expected: expected_bytes}
        for item in spec["series"]:
            for artifact in item["source_artifacts"]:
                assert Path(artifact["path"]).is_relative_to(project)
                if family == "mechanical":
                    assert artifact["path"] == expected
                # Impact intentionally derives a canonical plotting table from
                # its condition CSV; retain that real second artifact identity.
                physical = resolve_source_path(artifact["path"], expected_sha256=artifact["sha256"])
                assert physical.is_relative_to(candidate.project_dir)
                data = physical.read_bytes()
                assert hashlib.sha256(data).hexdigest() == artifact["sha256"]
                assert captured.setdefault(artifact["path"], data) == data
        writes = candidate.capture()
    assert not actual.exists()
    reads = {name: item["sha256"] for name, item in before["files"].items()}
    reads.update({name: reads.get(name) for name in writes})
    command = ProjectCommand.create("figure_set", "serialize-terminal-" + family, project_id=before["project_id"],
        expected_generation=before["generation"], read_set=reads, write_set=list(writes), request={})
    ProjectCommands(store).execute(command, lambda: ProjectMutation(writes, {}))
    cold = FileProjectStore.import_bundle(store.export_bundle(tmp_path / "bundle"), tmp_path / "cold")
    project.rename(tmp_path / "original-offline")
    with project_runtime(cold):
        persisted = json.loads(cold.read_bytes("studio/spec.json"))
        path = persisted["source_request"]["input"]
        for literal, data in captured.items():
            digest = hashlib.sha256(data).hexdigest()
            resolved = resolve_source_path(literal, expected_sha256=digest)
            assert resolved.is_relative_to(cold.root) and resolved.read_bytes() == data
        assert path == expected and not Path(path).exists()
    foreign = tmp_path / "foreign" / Path(expected).name
    foreign.parent.mkdir()
    foreign.write_bytes(expected_bytes)
    with pytest.raises(ValueError):
        cold.resolve_path(foreign, expected_sha256=hashlib.sha256(expected_bytes).hexdigest())
    assert cold.read_bytes("studio/spec.json") == spec_bytes
