"""Logical terminal identities and active requests survive real Store views."""
from dataclasses import replace
import json
from pathlib import Path
import stat

import pytest

from sciplot_core.figure_plan import CartesianMetricBinding, FigureTask
from sciplot_core.project_commands import InputRead, PreparedSource, ProjectCommand, ProjectCommands, ProjectMutation
from sciplot_core.project_store import FileProjectStore
from sciplot_core.studio_core.figure_source_request import _mechanical_task_source
from sciplot_core.studio_core.preparation_candidate import studio_preparation_candidate
from sciplot_core.studio_core.series_request import _series_from_request
from sciplot_core.terminal_source_binding import MaterializedTerminalSourceBinding, SourceArtifactBinding
from sciplot_core.workflow.rheology_task_sources import RheologyTaskSource
from sciplot_core.workflow.rheology_terminal_validation import validate_temperature_render_payload
from test_mechanical_studio_task_sources import _private_mechanical_source
from test_temperature_terminal_source_binding import _binding_fixture
from test_temperature_workflow_repair import _fake_complete_temperature_render_payload


def inventory(root):
    return {str(path.relative_to(root)): (stat.S_IMODE(path.lstat().st_mode), path.lstat().st_mtime_ns,
        path.read_bytes() if path.is_file() and not path.is_symlink() else None)
        for path in root.rglob("*")}


def test_private_candidate_terminal_uses_logical_identity_and_keeps_exact_source_guards(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    task, plan, original = _private_mechanical_source(project)
    (project / "plot_request.json").write_bytes(b"{}")
    store = FileProjectStore(project)
    store.snapshot(import_legacy=True)
    with studio_preparation_candidate(store) as candidate:
        actual = candidate.project_dir / original.source.relative_to(project)
        bound = replace(original.binding, terminal_source=SourceArtifactBinding.create(actual))
        record = replace(original, source=actual, binding=bound)
        assert bound.terminal_source.path == str(original.source) != str(actual)
        assert _mechanical_task_source({"_mechanical_task_source": record},
            expected_task=task, expected_plan=plan) is record
        record.binding.verify_sources()
        foreign = candidate.project_dir / "foreign.csv"
        foreign.write_bytes(actual.read_bytes())
        with pytest.raises(ValueError, match="studio_figure_task_mismatch"):
            _mechanical_task_source({"_mechanical_task_source": replace(record, source=foreign)},
                expected_task=task, expected_plan=plan)
        actual.write_bytes(actual.read_bytes() + b"changed")
        with pytest.raises(ValueError, match="changed"):
            record.binding.verify_sources()


def rendered_temperature(tmp_path):
    binding, source, _values = _binding_fixture(tmp_path)
    task = FigureTask.with_metric_binding(figure_id=binding.task_key, order=1, title="Loss factor",
        metric_binding=CartesianMetricBinding(x_metric=binding.x_metric, y_metric=binding.y_metric),
        template=binding.template, artifact_stem="temp_loss_factor", document_stem="temp_loss_factor",
        sample_order=binding.sample_order)
    record = RheologyTaskSource("temp_loss_factor", source, {}, binding)
    metric = tmp_path / "metric"
    payload = _fake_complete_temperature_render_payload(source, output_dir=metric,
        _terminal_source_binding=binding, options={"x_metric": binding.x_metric, "y_metric": binding.y_metric},
        request_context={"rule_id": binding.rule_id, "resolved_figure_task": task.to_payload(),
                         "series_order": list(binding.sample_order)})
    return payload, record, task, metric


def test_private_terminal_series_keep_logical_artifacts_and_complete_numeric_values(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    original, source, expected = _binding_fixture(project)
    (project / "plot_request.json").write_bytes(b"{}")
    store = FileProjectStore(project)
    store.snapshot(import_legacy=True)
    with studio_preparation_candidate(store) as candidate:
        actual = candidate.project_dir / source.relative_to(project)
        binding = MaterializedTerminalSourceBinding.create(task_key=original.task_key, rule_id=original.rule_id,
            template=original.template, x_metric=original.x_metric, y_metric=original.y_metric,
            raw_sources=[candidate.project_dir / Path(item.path).relative_to(project) for item in original.raw_sources],
            prepared_source=candidate.project_dir / Path(original.prepared_source.path).relative_to(project),
            terminal_source=actual, sample_order=original.sample_order, point_counts=dict(original.point_counts))
        request = {"input": str(actual), "rule_id": binding.rule_id, "template": binding.template,
            "x_metric": binding.x_metric, "y_metric": binding.y_metric, "series_order": list(binding.sample_order),
            "render_options": {"x_metric": binding.x_metric, "y_metric": binding.y_metric}}
        series, _axes, _steps, _source = _series_from_request(request, base_dir=candidate.project_dir,
            _terminal_source_binding=binding)
        assert [item.label for item in series] == list(binding.sample_order)
        assert [list(item.y_values) for item in series] == [expected[name] for name in binding.sample_order]
        assert all(item.source_artifacts == ((str(source), binding.terminal_source.sha256),) for item in series)
        other = actual.with_name("same-bytes.csv")
        other.write_bytes(actual.read_bytes())
        with pytest.raises(ValueError, match="does not match the bound terminal"):
            _series_from_request({**request, "input": str(other)}, base_dir=candidate.project_dir,
                _terminal_source_binding=binding)


@pytest.mark.parametrize("change", ["sealed-writes", "immutable-input", "source-view", "second-request",
    "rogue-store-request", "new-workbook", "missing", "symlink", "drift", "mode", "missing-head",
    "forged-head", "frozen-drift", "foreign-spec", "semantic-prepare"])
def test_temperature_worker_inventory_uses_verified_roles_and_stays_readonly(tmp_path, change):
    payload, record, task, metric = rendered_temperature(tmp_path)
    document = Path(payload["veusz_documents"][0])
    project = document.parent.parent
    request = project / "plot_request.json"
    if change == "semantic-prepare":
        value = json.loads(request.read_bytes())
        value["transform_ledger"]["steps"].append({"implementation_ref": "sciplot_core.semantic.prepare_semantic_source"})
        request.write_text(json.dumps(value))
    if change == "immutable-input":
        original = project / "source/rheology_temperature_comparison.xlsx"
        original.parent.mkdir()
        original.write_bytes(b"immutable input workbook")
    store = FileProjectStore(project)
    before = store.snapshot(import_legacy=True)
    reads = {"plot_request.json": before["files"]["plot_request.json"]["sha256"]}
    inputs, sources = (), ()
    if change == "immutable-input":
        digest = before["files"]["source/rheology_temperature_comparison.xlsx"]["sha256"]
        reads["source/rheology_temperature_comparison.xlsx"] = digest
        sources = (PreparedSource("e" * 32, str(original), digest, original.read_bytes(), mode=0o644),)
        inputs = (InputRead("source/rheology_temperature_comparison.xlsx", sources[0].source_id, digest),)
    command = ProjectCommand.create("figure_set", "worker-generation", project_id=before["project_id"],
        expected_generation=before["generation"], read_set=reads,
        write_set=["plot_request.json"], request={}, input_reads=inputs)
    if change == "source-view":
        from sciplot_core.foundation.file_hashing import file_sha256

        original = tmp_path / "rheology_temperature_comparison.xlsx"
        original.write_bytes(b"captured immutable source")
        sources = (PreparedSource("f" * 32, str(original), file_sha256(original), original.read_bytes()),)
    receipt = ProjectCommands(store).execute(command,
        lambda: ProjectMutation({"plot_request.json": request.read_bytes()}, {}, prepared_sources=sources))
    assert Path(receipt["staged_paths"]["plot_request.json"]).is_file()
    if sources:
        store.resolve_source(sources[0].source_id, sources[0].version)
    if change in {"second-request", "rogue-store-request", "new-workbook"}:
        extra = ((project / ".sciplot_store/rogue/plot_request.json") if change == "rogue-store-request" else
                 metric / "_veusz/second/plot_request.json" if change == "second-request" else
                 project / "second/rheology_temperature_comparison.xlsx")
        extra.parent.mkdir(parents=True)
        extra.write_bytes(b"{}")
    elif change == "missing":
        request.unlink()
    elif change == "symlink":
        alias = project / "copy.json"
        alias.write_bytes(request.read_bytes())
        request.unlink()
        request.symlink_to(alias)
    elif change == "drift":
        request.write_bytes(request.read_bytes() + b" ")
    elif change == "mode":
        old_mode = stat.S_IMODE(request.stat().st_mode)
        request.chmod(0o644 if old_mode == 0o600 else 0o600)
        assert stat.S_IMODE(request.stat().st_mode) != old_mode
    elif change == "missing-head":
        (project / ".sciplot_store/head.json").unlink()
    elif change == "forged-head":
        (project / ".sciplot_store/head.json").write_bytes(b"{}")
    elif change == "frozen-drift":
        frozen = Path(receipt["staged_paths"]["plot_request.json"])
        frozen.chmod(0o600)
        frozen.write_bytes(frozen.read_bytes() + b" ")
    elif change == "foreign-spec":
        foreign = tmp_path / "foreign.spec.json"
        foreign.write_bytes(Path(payload["veusz_specs"][0]).read_bytes())
        payload["veusz_specs"] = [str(foreign)]
    expected = inventory(tmp_path)
    valid = change in {"sealed-writes", "immutable-input", "source-view"}
    if valid:
        validate_temperature_render_payload(payload, record=record, task=task, metric_dir=metric, export_formats=["pdf"])
    else:
        with pytest.raises(ValueError):
            validate_temperature_render_payload(payload, record=record, task=task, metric_dir=metric, export_formats=["pdf"])
    assert inventory(tmp_path) == expected
