"""An isolated, real generation publishes a whole Managed frequency candidate."""
from dataclasses import replace
from pathlib import Path
import shutil

import pytest

from sciplot_core.plot_backends.managed import ManagedVeuszCompiler
from sciplot_core.plot_engine.managed_backend import native_build_record
from sciplot_core.plot_engine.managed_resolution import resolve_science, resolved_metadata
from sciplot_core.plot_engine.managed_state import prepare_binding
from sciplot_core.plot_ir import create_managed_document
from sciplot_core.project_commands import ProjectCommands, SourceTreeRead
from sciplot_core.project_lifecycle.attached_repository import AttachedProjectRepository
from sciplot_core.project_lifecycle.attachment_group import PreparedFigure, publish_attachment_group, resume_attachment_group
from sciplot_core.project_lifecycle.attachment_import import entry_for
from sciplot_core.project_lifecycle.attachment_index import Attachment, encode, read_index
from sciplot_core.project_lifecycle.capabilities import COMPATIBILITY_CAPABILITIES
from sciplot_core.project_lifecycle.context import repository_scope
from sciplot_core.project_store import FileProjectStore, state
from sciplot_core.task_semantic_creation import build_managed_request
from sciplot_core.task_semantic_plan import prepare_plan
from sciplot_core.workflow.frequency_managed_grouping import group_frequency_request, resolve_mean_group_blocks
from test_frequency_interval_binding import instrument_source, intent


def _grouped_request(paths, domain, plan, task, units, task_root):
    value = {**intent(), "y": {"quantity": task.y_metric, "unit": units[task.y_metric]}}
    scientific_plan = prepare_plan(paths, value)
    request = build_managed_request({"request": {"intent": value}, "semantic_plan": scientific_plan,
        "semantic_choices": {}, "intent_revision": 1, "task_dir": str(task_root)})
    return group_frequency_request(request, task, resolve_mean_group_blocks(domain, plan, scientific_plan["sources"]))


def _mean_input(tmp_path):
    root = tmp_path / "raw"
    root.mkdir()
    one = instrument_source(root / "A.csv", temperatures=(210, 150))
    two = instrument_source(root / "B.csv", temperatures=(210, 170))
    lines = one.read_text(encoding="utf-16").splitlines()
    singleton = False
    for index, line in enumerate(lines):
        if line.startswith("Result:"):
            singleton = "150 °C" in line
        cells = line.split("\t")
        if singleton and len(cells) > 11 and cells[1] in {"15", "16"}:
            cells[3], cells[4] = "6.25", "171" if cells[1] == "15" else "169"
            lines[index] = "\t".join(cells)
    one.write_text("\n".join(lines), encoding="utf-16")
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
    with repo.prepare_new_member(before) as members:
        with repository_scope(repo, capabilities=COMPATIBILITY_CAPABILITIES):
            document = create_managed_document(request["template_definition"], request["data_binding"], plot_id=task.figure_id)
            document = resolved_metadata(document, rule_id=request["rule_id"], executors={})
            document, _ = resolve_science(attachment.root, document)
            binding, ir = prepare_binding(attachment.root, document, output=output)
            repo.commit(attachment.root, document, binding, "frequency_mean_suite")
    worker = staging / task.figure_id
    built = compiler.compile_ir(ir, worker)
    assert built["scientific_audit"]["status"] == built["publication_qa"]["status"] == "passed"
    exports = compiler.export_ir(ir, Path(built["document"]), worker / "exports")
    assert exports["ready_to_use"]
    published_native = Path(binding["document"])
    assets = {store.logical_path(published_native): Path(built["document"]).read_bytes(),
              store.logical_path(published_native.parent / "build.json"):
                  encode(native_build_record(ir["ir_hash"], built, ir["ir_hash"]))}
    for export in exports["exports"]:
        path = Path(export["path"])
        assets[store.logical_path(output / path.name)] = path.read_bytes()
    return PreparedFigure(attachment, members, assets, exports), ir, binding


@pytest.mark.comprehensive
def test_frequency_mean_suite_publishes_real_managed_heads_and_analysis_as_one_generation(tmp_path, monkeypatch):
    from sciplot_core.materials_rules.analysis import compute_analysis_metrics, frequency_terminal_analysis
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
    candidates = []
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
            request = _grouped_request(originals, resolved.domain, plan, task, units, tmp_path / ("task-" + task.figure_id))
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
            candidate, ir, binding = _candidate_head(compiler, store, before, task, request, tmp_path / "staging")
            candidates.append(candidate)
            evidence[task.figure_id] = candidate.attachment, binding
            assert len(evidence) <= len(tasks) and store.snapshot()["generation"] == before["generation"]
            assert store.snapshot()["files"] == before["files"]
            layers = ir["views"][0]["layers"]
            for layer, old in zip(layers, old_samples, strict=True):
                values = ir["datasets"][layer["dataset_id"]]["columns"]
                assert values["x"]["unit"] == "rad/s" and values["y"]["unit"] == units[task.y_metric]
                points = [(row["x"], row[task.y_metric]) for row in old.rows if task.y_metric in row]
                actual_x, actual_y = values["x"]["values"], values["y"]["values"]
                assert actual_x == [x for x, _ in points]
                assert actual_y == pytest.approx([y for _, y in points], rel=2e-15, abs=0.)
                if task.y_metric == "storage_modulus":
                    terminal.append((old.sample, actual_x, actual_y))
    finally:
        compiler.close()

    semantic = {"rule_id": rule, "semantic_family": "rheology_frequency", "axis_plan": {"y": {"canonical_unit": "Pa"}}}
    prepared = prepare_semantic_source(raw, output_dir=tmp_path / "prepared", semantic=semantic,
                                       resolved_scientific_source=resolved)
    rows = compute_analysis_metrics(source_path=raw, processed_source=Path(prepared["processed_source"]),
                                    semantic=semantic, output_dir=tmp_path / "old-analysis")
    analysis = tmp_path / "candidate-analysis" / "frequency.csv"
    managed_rows = frequency_terminal_analysis(terminal, semantic=semantic, output=analysis)
    assert managed_rows == rows
    assert [row["value"] for row in rows] == [565., 171., 515.]
    assert analysis.read_bytes() == (tmp_path / "old-analysis" / "tables" / "analysis_metrics.csv").read_bytes()

    outputs = {"analysis/frequency.csv": analysis.read_bytes(), "figure-plan.json": encode(plan.to_payload())}
    key = "frequency-mean-suite"
    args = {"key": key, "selected_figures": plan.selected_figure_ids, "outputs": outputs,
            "source_tree": SourceTreeRead(str(raw), resolved.source_sha256), "required_outputs": tuple(outputs)}
    with pytest.raises(ValueError, match="Prepare every selected figure"):
        publish_attachment_group(store, before, figures=tuple(candidates[:-1]), **args)
    assert ProjectCommands(store).query(key) is None

    first, second, *others = candidates
    a_pdf = next(path for path in first.assets if path.endswith(".pdf"))
    b_pdf = next(path for path in second.assets if path.endswith(".pdf"))
    a_tiff = next(path for path in first.assets if path.endswith(".tiff"))
    assert first.assets[a_pdf] != second.assets[b_pdf]
    swapped = (replace(first, assets={**first.assets, a_pdf: second.assets[b_pdf]}),
               replace(second, assets={**second.assets, b_pdf: first.assets[a_pdf]}), *others)
    modified = (replace(first, assets={**first.assets, a_tiff: first.assets[a_tiff] + b"changed"}), second, *others)
    missing = (replace(first, assets={name: data for name, data in first.assets.items() if name != a_pdf}), second, *others)
    for altered, message in ((swapped, "audited export"), (modified, "audited export"), (missing, "complete native and export set")):
        with pytest.raises(ValueError, match=message):
            publish_attachment_group(store, before, figures=altered, **args)
        assert ProjectCommands(store).query(key) is None

    def interrupt(point):
        if point == "before_head":
            raise Interrupted()

    with monkeypatch.context() as fault:
        fault.setattr(state, "boundary", interrupt)
        with pytest.raises(Interrupted):
            publish_attachment_group(store, before, figures=tuple(candidates), **args)
    assert store.snapshot()["generation"] == before["generation"]
    assert store.snapshot()["files"] == before["files"]
    assert not (workspace / "analysis/frequency.csv").exists()
    # Recover only from the saved accepted command, with fresh Store objects.
    # The publication must not require caller candidate bytes or native staging.
    shutil.rmtree(tmp_path / "staging")
    restarted = FileProjectStore(workspace)
    prior = ProjectCommands(restarted).query(key)
    assert prior is not None and prior["phase"] == "accepted"
    completed = resume_attachment_group(restarted, key)
    current = restarted.snapshot()
    assert completed["phase"] == "complete"
    assert len(completed["result"]["artifacts"]) == len(tasks) * 4
    assert current["sequence"] == before["sequence"] + 1
    published = set(current["files"]) - set(before["files"])
    assert set(outputs) <= published
    assert restarted.read_bytes("analysis/frequency.csv") == outputs["analysis/frequency.csv"]
    assert compile_order == list(plan.selected_figure_ids)
    for suffix in (".vsz", ".pdf", ".tiff"):
        assert len([member for member in published if member.endswith(suffix)]) == len(tasks)
    for figure, (old_attachment, binding) in evidence.items():
        entry = read_index(restarted, current)["attachments"][old_attachment.entry["id"]]
        attached = Attachment(restarted, entry)
        saved = AttachedProjectRepository(attached).load_head(attached.root)
        assert saved["document"]["plot_type"] == "ManagedPlot" and saved["document"]["plot_id"] == figure
        assert saved["binding"]["ir_hash"] == binding["ir_hash"]
    # Reopen and edit a real published aggregate through the same public
    # semantic service used by other Managed plots, not a suite-specific editor.
    from sciplot_core.plot_engine.service import PlotService

    service = PlotService()
    try:
        primary = service.open(workspace, figure_id=plan.primary_figure_id)
        assert primary["plot_type"] == "ManagedPlot" and primary["revision"] == 0
        updated = service.patch(Path(primary["plot"]), {
            "plot_id": primary["plot_id"], "base_revision": 0, "idempotency_key": "frequency-axis-label",
            "intent_class": "presentation",
            "changes": [{"op": "set", "target": ["axis:x"], "property": "axis.label", "value": "Angular frequency (rad/s)"}],
        })
        assert updated["revision"] == 1 and updated["ready_to_use"]
        assert updated["scientific_hash"] == primary["scientific_hash"]
        other = service.open(workspace, figure_id=tasks[1].figure_id)
        assert other["revision"] == 0
    finally:
        service.close()
    assert {path: path.read_bytes() for path in originals} == source_bytes


def test_automatic_frequency_groups_bind_original_regions_not_condition_display_labels(tmp_path):
    from sciplot_core.semantic_sources.scientific_source import resolve_scientific_source

    raw = tmp_path / "raw"
    raw.mkdir()
    first = instrument_source(raw / "one.csv", temperatures=(210,))
    second = instrument_source(raw / "two.csv", temperatures=(170, 150))
    rule = "rheology_frequency_sweep"
    resolved = resolve_scientific_source(raw, rule_id=rule, template="point_line", request={})
    assert resolved is not None and resolved.figure_plan is not None
    plan = resolved.figure_plan
    spec = _grouped_request([first, second], resolved.domain, plan, plan.tasks[0],
                            resolved.domain.prepared_samples[0].metric_units, tmp_path / "task")
    layers = spec["template_definition"]["figure_spec"]["views"][0]["layers"]
    # The existing explicit semantic display would suffix the single 210°C
    # Result. Native automatic identity intentionally retains the short name.
    assert [layer["label"] for layer in layers] == ["Anonymous material",
        "Anonymous material · 170 °C", "Anonymous material · 150 °C"]
    assert not any(item["kind"] == "rheology_mean_exact_x" for item in spec["data_binding"]["transforms"])
    provenance = spec["data_binding"]["provenance"]["frequency_mean_original_blocks"]
    assert provenance["Anonymous material"] == (
        {"source_id": "source:0", "table_id": "table:0", "block_id": "block:0"},)
    only = spec["data_binding"]["data_sources"][0]
    assert only["path"] == str(first)
    assert (only["table_selection"]["header_rows"], only["table_selection"]["data_start_row"],
            only["table_selection"]["data_end_row"]) == ([7], 10, 26)
