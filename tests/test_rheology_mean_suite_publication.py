"""An isolated, real generation publishes a whole Managed frequency candidate."""
from copy import deepcopy
import csv
from io import StringIO
import json
from pathlib import Path
import shutil

import pytest

from sciplot_core.plot_backends.managed import ManagedVeuszCompiler
from sciplot_core.plot_engine.managed_resolution import resolve_science, resolved_metadata
from sciplot_core.plot_engine.managed_state import prepare_binding
from sciplot_core.plot_ir import create_managed_document
from sciplot_core.plot_transforms import builtin_executor
from sciplot_core.project_commands import PreparedMutation, ProjectCommand, ProjectCommands, SourceTreeRead
from sciplot_core.project_lifecycle.attached_repository import AttachedProjectRepository, _Batch
from sciplot_core.project_lifecycle.attachment_import import entry_for
from sciplot_core.project_lifecycle.attachment_index import Attachment, INDEX, encode, read_index
from sciplot_core.project_lifecycle.attachment_sources import prepared_sources
from sciplot_core.project_lifecycle.capabilities import COMPATIBILITY_CAPABILITIES
from sciplot_core.project_lifecycle.context import repository_scope
from sciplot_core.project_store import FileProjectStore, state
from sciplot_core.task_semantic_creation import build_managed_request
from sciplot_core.task_semantic_plan import prepare_plan
from test_frequency_interval_binding import instrument_source, intent


def _grouped_request(paths, task, units, task_root):
    value = {**intent(), "y": {"quantity": task.y_metric, "unit": units[task.y_metric]}}
    scientific_plan = prepare_plan(paths, value)
    request = build_managed_request({"request": {"intent": value}, "semantic_plan": scientific_plan,
        "semantic_choices": {}, "intent_revision": 1, "task_dir": str(task_root)})
    binding = request["data_binding"]
    view = request["template_definition"]["figure_spec"]["views"][0]
    original = view["layers"]
    retained, slots = [], {}
    for index, (condition, count) in enumerate(task.replicate_counts):
        members = [layer for layer in original if layer["label"] == condition]
        assert len(members) == count
        layer = deepcopy(members[0])
        mapped = [(name, slot) for name, slot in binding["slots"].items() if slot["series_id"] == layer["id"]]
        (name, slot), = mapped
        slot = deepcopy(slot)
        if count > 1:
            kind = "rheology_mean_exact_x"
            output = "group:" + str(index)
            binding["transforms"].append({"id": "mean:" + str(index), "kind": kind,
                "inputs": [item["dataset_id"] for item in members], "output": output,
                "parameters": {"x_column": "x"}, "executor": builtin_executor(kind), "determinism": "deterministic"})
            layer["dataset_id"] = output
            slot["x"]["source_id"] = slot["y"]["source_id"] = output
        retained.append(layer)
        slots[name] = slot
    view["layers"] = retained
    binding["slots"] = slots
    binding["provenance"]["figure_task"] = task.to_payload()
    return request


def _mean_input(tmp_path):
    root = tmp_path / "raw"
    root.mkdir()
    one = instrument_source(root / "A.csv", temperatures=(210, 150))
    two = instrument_source(root / "B.csv", temperatures=(210, 170))
    # A second original 210°C sweep changes every storage observation by 100
    # Pa. The 150°C condition appears only once and must stay in source order.
    lines = two.read_text(encoding="utf-16").splitlines()
    for index, line in enumerate(lines):
        cells = line.split("\t")
        if len(cells) > 11 and cells[1].isdigit():
            cells[4] = str(float(cells[4]) + 100)
            lines[index] = "\t".join(cells)
    two.write_text("\n".join(lines), encoding="utf-16")
    return root, [one, two]


def _candidate_head(compiler, store, before, task, request, staging):
    output = store.root / "figures" / task.figure_id
    entry = entry_for(store, key="frequency-mean:" + task.figure_id, figure_id=task.figure_id,
        origin=store.root / ".sciplot_semantic" / task.figure_id, plot_id=task.figure_id, managed_output=str(output))
    entry["origin_root"] = entry["namespace_origin"]
    attachment = Attachment(store, entry)
    repo = AttachedProjectRepository(attachment)
    # Capture the exact existing Managed repository writes, not its individual
    # _flush. The real group outer owner is the one PreparedMutation below.
    batch = _Batch(before)
    token = repo._batch.set(batch)
    try:
        with repository_scope(repo, capabilities=COMPATIBILITY_CAPABILITIES):
            document = create_managed_document(request["template_definition"], request["data_binding"], plot_id=task.figure_id)
            document = resolved_metadata(document, rule_id=request["rule_id"], executors={})
            document, _ = resolve_science(attachment.root, document)
            binding, ir = prepare_binding(attachment.root, document, output=output)
            repo.commit(attachment.root, document, binding, "frequency_mean_suite")
    finally:
        repo._batch.reset(token)
    worker = staging / task.figure_id
    built = compiler.compile_ir(ir, worker)
    assert built["scientific_audit"]["status"] == built["publication_qa"]["status"] == "passed"
    exports = compiler.export_ir(ir, Path(built["document"]), worker / "exports")
    assert exports["ready_to_use"]
    files = dict(batch.writes)
    files[store.logical_path(Path(binding["document"]))] = Path(built["document"]).read_bytes()
    for export in exports["exports"]:
        path = Path(export["path"])
        files[store.logical_path(output / path.name)] = path.read_bytes()
    return attachment, files, ir, binding


@pytest.mark.comprehensive
def test_frequency_mean_suite_publishes_real_managed_heads_and_analysis_as_one_generation(tmp_path, monkeypatch):
    from sciplot_core.materials_rules.analysis import compute_analysis_metrics
    from sciplot_core.semantic import prepare_semantic_source
    from sciplot_core.semantic_sources.scientific_source import resolve_scientific_source

    raw, originals = _mean_input(tmp_path)
    source_bytes = {path: path.read_bytes() for path in originals}
    rule = "rheology_frequency_sweep"
    resolved = resolve_scientific_source(raw, rule_id=rule, template="point_line", request={})
    assert resolved is not None and resolved.figure_plan is not None
    plan = resolved.figure_plan
    tasks = plan.tasks
    assert len(tasks) == 4
    old_samples = resolved.domain.prepared_samples
    units = old_samples[0].metric_units
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    store = FileProjectStore(workspace)
    before = store.snapshot(import_legacy=True)
    index = read_index(store, before)
    writes = {}
    evidence = {}
    terminal = []
    compile_order = []

    class Interrupted(Exception):
        pass

    compiler = ManagedVeuszCompiler(warm=False)
    real_compile = compiler.compile_ir

    def compile_once(ir, output):
        compile_order.append(output.name)
        return real_compile(ir, output)

    monkeypatch.setattr(compiler, "compile_ir", compile_once)
    try:
        for task in tasks:
            expected = (("Anonymous material · 210 °C", 2), ("Anonymous material · 150 °C", 1), ("Anonymous material · 170 °C", 1))
            assert task.replicate_counts == expected
            request = _grouped_request(originals, task, units, tmp_path / ("task-" + task.figure_id))
            if task is tasks[-1]:
                def missing_final_figure(*_args):
                    raise Interrupted()
                # Preparation is not a commit. A last-figure failure cannot
                # expose the other three; retry this still-private candidate.
                with monkeypatch.context() as fault:
                    fault.setattr(compiler, "compile_ir", missing_final_figure)
                    with pytest.raises(Interrupted):
                        _candidate_head(compiler, store, before, task, request, tmp_path / "staging")
                assert store.snapshot()["files"] == before["files"]
                assert not (workspace / "figures").exists()
                assert compile_order == list(plan.selected_figure_ids[:-1])
            attachment, files, ir, binding = _candidate_head(compiler, store, before, task, request, tmp_path / "staging")
            evidence[task.figure_id] = attachment, binding
            assert len(evidence) <= len(tasks) and store.snapshot()["generation"] == before["generation"]
            assert store.snapshot()["files"] == before["files"]
            index["attachments"][attachment.entry["id"]] = attachment.entry
            writes.update(files)
            candidates = ir["views"][0]["layers"]
            for layer, old in zip(candidates, old_samples, strict=True):
                values = ir["datasets"][layer["dataset_id"]]["columns"]
                assert values["x"]["unit"] == "rad/s" and values["y"]["unit"] == units[task.y_metric]
                points = [(row["x"], row[task.y_metric]) for row in old.rows if task.y_metric in row]
                actual_x, actual_y = values["x"]["values"], values["y"]["values"]
                assert actual_x == [x for x, _ in points]
                assert actual_y == pytest.approx([y for _, y in points], rel=2e-15, abs=0.)
                if task.y_metric == "storage_modulus":
                    terminal.append(min(zip(actual_x, actual_y, strict=True))[1])
    finally:
        compiler.close()

    semantic = {"rule_id": rule, "semantic_family": "rheology_frequency", "axis_plan": {"y": {"canonical_unit": "Pa"}}}
    prepared = prepare_semantic_source(raw, output_dir=tmp_path / "prepared", semantic=semantic,
                                       resolved_scientific_source=resolved)
    rows = compute_analysis_metrics(source_path=raw, processed_source=Path(prepared["processed_source"]),
                                    semantic=semantic, output_dir=tmp_path / "old-analysis")
    assert [row["value"] for row in rows] == terminal == [565., 415., 515.]
    analysis = StringIO(newline="")
    writer = csv.DictWriter(analysis, fieldnames=["metric", "value", "unit", "status", "reason"])
    writer.writeheader()
    writer.writerows({**row, "value": value} for row, value in zip(rows, terminal, strict=True))

    writes["analysis/frequency.csv"] = analysis.getvalue().encode()
    writes["figure-plan.json"] = encode(plan.to_payload())
    writes[INDEX] = encode(index)
    inventory = [source for attachment, _ in evidence.values()
                 for name, data in writes.items()
                 if data and name.startswith(attachment.entry["namespace"] + "/revisions/")
                 for source in json.loads(data)["document"]["scientific"]["data_sources"]]
    captured = prepared_sources(store, inventory, snapshot=before)
    assert {Path(item.locator): item.data for item in captured} == source_bytes
    mutation = PreparedMutation.from_values(writes, {"figure_ids": list(plan.selected_figure_ids),
        "analysis": "analysis/frequency.csv"}, prepared_sources=captured)
    command = ProjectCommand.create("semantic_record", "frequency-mean-suite", project_id=before["project_id"],
        expected_generation=before["generation"], read_set=dict.fromkeys(writes), write_set=sorted(writes),
        request={"prepared_digest": mutation.prepared_digest, "plan": plan.to_payload()},
        source_trees=(SourceTreeRead(str(raw), resolved.source_sha256),))

    def interrupt(point):
        if point == "before_head":
            raise Interrupted()

    with monkeypatch.context() as fault:
        fault.setattr(state, "boundary", interrupt)
        with pytest.raises(Interrupted):
            ProjectCommands(store).publish_prepared(command, mutation)
    assert store.snapshot()["generation"] == before["generation"]
    assert store.snapshot()["files"] == before["files"]
    assert not (workspace / "analysis/frequency.csv").exists()
    # Recover only from the saved accepted command, with fresh Store objects.
    # The publication must not require caller candidate bytes or native staging.
    shutil.rmtree(tmp_path / "staging")
    restarted = FileProjectStore(workspace)
    recovery = ProjectCommands(restarted)
    prior = recovery.query(command.key)
    assert prior is not None and prior["phase"] == "accepted"
    completed = recovery.resume(ProjectCommand.from_payload(prior["metadata"]))
    current = restarted.snapshot()
    assert completed["phase"] == "complete"
    assert current["sequence"] == before["sequence"] + 1
    assert set(current["files"]) - set(before["files"]) == set(writes)
    assert restarted.read_bytes("analysis/frequency.csv") == writes["analysis/frequency.csv"]
    assert compile_order == list(plan.selected_figure_ids)
    assert len([member for member in writes if member.endswith(".pdf")]) == len(tasks)
    assert len([member for member in writes if member.endswith(".tiff")]) == len(tasks)
    assert len([member for member in writes if member.endswith(".vsz")]) == len(tasks)
    for figure, (old_attachment, binding) in evidence.items():
        entry = read_index(restarted, current)["attachments"][old_attachment.entry["id"]]
        attached = Attachment(restarted, entry)
        saved = AttachedProjectRepository(attached).load_head(attached.root)
        assert saved["document"]["plot_type"] == "ManagedPlot" and saved["document"]["plot_id"] == figure
        assert saved["binding"]["ir_hash"] == binding["ir_hash"]
    assert {path: path.read_bytes() for path in originals} == source_bytes
