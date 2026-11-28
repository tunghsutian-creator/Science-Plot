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
from sciplot_core.workflow.frequency_managed_requests import prepare_frequency_requests
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
    requests = prepare_frequency_requests(resolved.domain, plan, task_root=tmp_path / "candidate-tasks").requests
    try:
        for task, request in zip(tasks, requests, strict=True):
            expected = (("Anonymous material · 210 °C", 2), ("Anonymous material · 150 °C", 1), ("Anonymous material · 170 °C", 1))
            assert task.replicate_counts == expected
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
        assert primary["export_current"]["current"] and primary["export_current"]["byte_inventory_verified"]
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
    [identity] = provenance["Anonymous material"]
    assert (identity["source_id"], identity["table_id"], identity["block_id"]) == ("source:0", "table:0", "block:0")
    assert (identity["path"], identity["result"]) == (str(first), "FS 210 °C")
    only = spec["data_binding"]["data_sources"][0]
    assert only["path"] == str(first)
    assert (only["table_selection"]["header_rows"], only["table_selection"]["data_start_row"],
            only["table_selection"]["data_end_row"]) == ([7], 10, 26)


def test_frequency_group_binds_exact_files_and_metrics_even_if_local_ids_are_reordered(tmp_path):
    from sciplot_core.plot_engine.managed_sources import load_sources
    from sciplot_core.plot_transforms import resolve_transforms
    from sciplot_core.semantic_sources.scientific_source import resolve_scientific_source

    raw, originals = _mean_input(tmp_path)
    rule = "rheology_frequency_sweep"
    resolved = resolve_scientific_source(raw, rule_id=rule, template="point_line", request={})
    assert resolved is not None and resolved.figure_plan is not None
    task = resolved.figure_plan.tasks[0]
    value = {**intent(), "y": {"quantity": task.y_metric, "unit": "Pa"}}
    local = prepare_plan(originals, value)
    blocks = resolve_mean_group_blocks(resolved.domain, resolved.figure_plan, local["sources"])

    def request_for(intent_value, paths):
        return build_managed_request({"request": {"intent": intent_value}, "semantic_plan": prepare_plan(paths, intent_value),
            "semantic_choices": {}, "intent_revision": 1, "task_dir": str(tmp_path / "task")})

    wrong = {**value, "y": {"quantity": "loss_modulus", "unit": "Pa"}}
    with pytest.raises(ValueError, match="match the selected FigureTask metrics"):
        group_frequency_request(request_for(wrong, originals), task, blocks)
    hertz = {**value, "x": {"quantity": "angular_frequency", "unit": "Hz"}}
    with pytest.raises(ValueError, match="coordinate units must match"):
        group_frequency_request(request_for(hertz, originals), task, blocks)
    swapped = group_frequency_request(request_for(value, list(reversed(originals))), task, blocks)
    document = create_managed_document(swapped["template_definition"], swapped["data_binding"], plot_id="physical-order")
    datasets = resolve_transforms(document, load_sources(document, rule))["datasets"]
    layers = swapped["template_definition"]["figure_spec"]["views"][0]["layers"]
    observed = {}
    for layer in layers:
        columns = datasets[layer["dataset_id"]]["columns"]
        observed[layer["label"]] = min(zip(columns["x"]["values"], columns["y"]["values"], strict=True), key=lambda pair: pair[0])[1]
    assert observed == {
        "Anonymous material · 210 °C": 565.,
        "Anonymous material · 150 °C": 171.,
        "Anonymous material · 170 °C": 515.,
    }


def test_new_frequency_mean_rejects_duplicate_x_within_one_replicate(tmp_path, capsys):
    import json

    from sciplot_core.cli import main
    from sciplot_core.semantic_sources.rheology_sweep_sources import _read_rheology_frequency_comparison_samples

    raw, (first, _second) = _mean_input(tmp_path)
    lines = first.read_text(encoding="utf-16").splitlines()
    initial = lines[10].split("\t")
    repeated = lines[11].split("\t")
    assert (initial[1], repeated[1]) == ("1", "2")
    repeated[3] = initial[3]
    lines[11] = "\t".join(repeated)
    first.write_text("\n".join(lines), encoding="utf-16")
    originals = first.read_bytes()

    sample = _read_rheology_frequency_comparison_samples(first)[0]
    assert [row["x"] for row in sample.rows[:2]] == [100, 100]
    assert sample.source_rows[:2] == (10, 11)

    status = main(["plan", str(raw), "--rule", "rheology_frequency_sweep", "--json"])
    result = json.loads(capsys.readouterr().out)
    assert status != 0 and result["status"] == "blocked"
    assert result["blocker"]["reason_code"] == "frequency_mean_duplicate_acquisition_frequency"
    message = result["blocker"]["message"]
    assert "A.csv" in message and "original rows 11 and 12" in message
    assert first.read_bytes() == originals


def _prepare_in_process(root, *, interrupt):
    """Exercise the production coordinator in each independent process."""
    import os

    from sciplot_core.semantic import classify_source
    from sciplot_core.study_model import study_model_from_request
    from sciplot_core.workflow import frequency_managed_suite as owner
    from sciplot_core.workflow.scientific_source_resolution import resolve_workflow_scientific_source

    raw_data, workspace = root / "raw", root / "cold-workspace"
    rule = "rheology_frequency_sweep"
    request = {"rule_id": rule}
    semantic = classify_source(raw_data, requested_rule_id=rule)
    study = study_model_from_request(request=request, semantic=semantic, input_path=raw_data)
    resolved, _ = resolve_workflow_scientific_source(
        input_path=raw_data, rule_id=rule, template="point_line", study_model=study, request=request)
    assert resolved is not None and resolved.figure_plan is not None
    plan = resolved.figure_plan
    real = owner._figure
    computed = []
    interrupt_next_export = False
    compiler = ManagedVeuszCompiler(warm=False)
    export = compiler.export_ir

    def interrupt_after_compile(*args):
        if interrupt_next_export:
            assert Path(args[1]).is_file()
            os._exit(43)
        return export(*args)

    def prepare(store, snapshot, key, figure_id, request, compiler, private):
        nonlocal interrupt_next_export
        interrupt_next_export = interrupt and figure_id == plan.tasks[-1].figure_id
        computed.append(figure_id)
        with (root / "native-invocations").open("a", encoding="utf-8") as stream:
            stream.write(figure_id + "\n")
        return real(store, snapshot, key, figure_id, request, compiler, private)

    owner._figure = prepare
    compiler.export_ir = interrupt_after_compile
    try:
        result = owner.publish_frequency_managed_suite(FileProjectStore(workspace),
            key="cold-frequency-mean-suite", resolved=resolved, compiler=compiler, task_root=root / "cold-tasks")
        assert result["phase"] == "complete" and computed == [plan.tasks[-1].figure_id]
        repeated = owner.publish_frequency_managed_suite(FileProjectStore(workspace),
            key="cold-frequency-mean-suite", resolved=resolved, compiler=compiler, task_root=root / "cold-tasks")
        assert repeated["generation"] == result["generation"] and computed == [plan.tasks[-1].figure_id]
    finally:
        compiler.close()


@pytest.mark.comprehensive
def test_frequency_suite_preaccept_retry_cold_resumes_only_the_unfinished_figure(tmp_path):
    import subprocess
    import sys

    _mean_input(tmp_path)
    workspace = tmp_path / "cold-workspace"
    workspace.mkdir()
    store = FileProjectStore(workspace)
    before = store.snapshot(import_legacy=True)
    command = [sys.executable, "-c",
               "import sys; from pathlib import Path; from test_rheology_mean_suite_publication import _prepare_in_process; "
               "_prepare_in_process(Path(sys.argv[1]), interrupt=sys.argv[2] == 'interrupt')", str(tmp_path)]
    failed = subprocess.run([*command, "interrupt"], capture_output=True, text=True, timeout=120)
    assert failed.returncode == 43, failed.stderr
    before_retry = FileProjectStore(workspace).snapshot()
    assert before_retry["generation"] == before["generation"] and before_retry["files"] == before["files"]
    assert not (workspace / "figures").exists()
    from sciplot_core.project_lifecycle.attachment_group_prepare import prepare_attachment_group

    key = "cold-frequency-mean-suite"
    saved = ProjectCommands(store).query(key + ":prepare")
    assert saved is not None and saved["phase"] == "reserved"
    original = saved["metadata"]["request"]
    source_tree = SourceTreeRead(**original["original"])
    with pytest.raises(ValueError, match="exact saved plan"):
        with prepare_attachment_group(store, key=key, plan=original["plan"],
                figures=dict(original["figures"]), source_tree=source_tree, runtime="different renderer"):
            pytest.fail("A different renderer must not reuse the cold candidates")
    completed = subprocess.run([*command, "continue"], capture_output=True, text=True, timeout=120)
    assert completed.returncode == 0, completed.stderr
    actual = FileProjectStore(workspace).snapshot()
    assert actual["sequence"] == before["sequence"] + 1
    names = (tmp_path / "native-invocations").read_text().splitlines()
    assert names == ["storage_modulus_vs_frequency", "loss_modulus_vs_frequency",
                     "loss_factor_vs_frequency", "complex_viscosity_vs_frequency", "complex_viscosity_vs_frequency"]
    _assert_legacy_auto_delivery_parity(tmp_path, workspace)
    import pymupdf

    path = workspace / "figures" / "loss_modulus_vs_frequency" / "document.pdf"
    with pymupdf.open(path) as pdf:
        page = pdf[0]
        # MuPDF joins the base and superscript in each scientific tick.
        # Restrict to the y-side before the graph so X ticks cannot pass this.
        ticks = {word[4] for word in page.get_text("words") if word[2] < 40}
        assert {"101", "102"} <= ticks, page.get_text("words")


def _assert_legacy_auto_delivery_parity(root, workspace):
    import json

    import pymupdf

    from sciplot_core.workflow.request_run import run_request

    request = root / "legacy-request.json"
    request.write_text(json.dumps({"input": str(root / "raw"), "output": str(root / "legacy-output"),
                                  "rule_id": "rheology_frequency_sweep"}), encoding="utf-8")
    (root / "legacy-output").mkdir()
    old = run_request(request)
    assert old["route"] == "auto" and old["ready_to_use"] is True
    current_plan = json.loads((workspace / "figure-plan.json").read_bytes())
    old_plan = old["resolved_figure_plan"]
    assert current_plan["complete"] is old_plan["complete"] is True
    for key in ("tasks", "primary_figure_id", "selected_figure_ids", "source_sha256"):
        assert current_plan[key] == old_plan[key], key
    assert (workspace / "analysis/analysis_metrics.csv").read_bytes() == (
        root / "legacy-output/tables/analysis_metrics.csv").read_bytes()
    store = FileProjectStore(workspace)
    attachments = {entry["figure_id"]: Attachment(store, entry) for entry in read_index(store)["attachments"].values()}
    for figure in current_plan["selected_figure_ids"]:
        paired = {row["format"]: Path(row["path"]) for row in old["result"]["exports"] if row["figure_id"] == figure}
        assert set(paired) == {"pdf", "tiff_300"}
        directory = workspace / "figures" / figure
        tiff = next(directory.glob("*.tiff"))
        assert tiff.stat().st_size > 0
        with pymupdf.open(paired["pdf"]) as legacy, pymupdf.open(directory / "document.pdf") as managed:
            assert len(managed) == len(legacy) == 1
            # Legacy sizing and the managed first-fitting house layout can
            # choose different widths for the same science. Check the managed
            # PDF against its saved figure, not the legacy renderer's width.
            attachment = attachments[figure]
            repo = AttachedProjectRepository(attachment)
            head = repo.load_head(attachment.root)
            layout = repo.read(Path(head["binding"]["ir_path"]))["layout"]
            assert managed[0].rect.height == pytest.approx(legacy[0].rect.height, abs=1.2)
            size_mm = [managed[0].rect.width * 25.4 / 72, managed[0].rect.height * 25.4 / 72]
            assert size_mm == pytest.approx([layout["width_mm"], layout["height_mm"]], abs=.4)


def test_frequency_readable_narrow_log_keeps_fixed_endpoints_and_unmarked_specs():
    from sciplot_core.plot_grammar.domain_values import numeric_axis

    source = [29., 34., 41.]
    args = {"quantity": "loss_modulus", "transform": "log", "dimension": "y"}
    assert numeric_axis(source, **args) == ([20., 50.], [])
    assert numeric_axis(source, **args, extend_empty_log_ticks=True) == ([10., 100.], [10., 100.])
    assert numeric_axis(source, **args, minimum=20., maximum=50., extend_empty_log_ticks=True) == ([20., 50.], [])
    assert numeric_axis(source, **args, minimum=20., extend_empty_log_ticks=True) == ([20., 100.], [100.])
    assert source == [29., 34., 41.]


@pytest.mark.comprehensive
def test_default_frequency_cli_publishes_and_retries_same_managed_editable_group(tmp_path, monkeypatch, capsys):
    import json

    from sciplot_core.cli import main
    from sciplot_core.plot_engine.service import PlotService

    raw, originals = _mean_input(tmp_path)
    request, output = tmp_path / "request.json", tmp_path / "run"
    payload = {"input": str(raw), "output": str(output), "rule_id": "rheology_frequency_sweep"}
    request.write_text(json.dumps(payload), encoding="utf-8")
    before = {path: path.read_bytes() for path in originals}
    assert main(["run", str(request)]) == 0
    first = json.loads(capsys.readouterr().out)
    managed = first["result"]["managed_frequency"]
    assert first["ready_to_use"] is True and first["delivery_package"]["complete"] is True
    assert first["publication_qa"]["coverage_complete"] is True and first["publication_qa"]["status"] == "passed"
    assert managed["primary_figure_id"] == "storage_modulus_vs_frequency"
    assert [item["figure_id"] for item in managed["figures"]] == first["resolved_figure_plan"]["selected_figure_ids"]
    assert [item["format"] for item in first["result"]["exports"]] == ["pdf", "tiff_300"] * 4
    assert [item["value"] for item in first["result"]["analysis_metrics"]] == [565., 171., 515.]
    assert all(item["scientific_audit"]["status"] == item["publication_qa"]["status"] == "passed"
               for item in first["qa"]["managed_native"])
    assert len(first["delivery_package"]["figures"]) == 8
    assert all(Path(item["path"]).is_file() for item in first["delivery_package"]["figures"])
    store = FileProjectStore(Path(managed["project"]))
    snapshot = store.snapshot()

    def no_native(*args, **kwargs):
        pytest.fail("the exact retry must reuse all sealed native figures")

    monkeypatch.setattr(ManagedVeuszCompiler, "compile_ir", no_native)
    monkeypatch.setattr(ManagedVeuszCompiler, "export_ir", no_native)
    assert main(["run", str(request)]) == 0
    second = json.loads(capsys.readouterr().out)
    assert second["result"]["managed_frequency"] == managed
    assert store.snapshot() == snapshot
    assert before == {path: path.read_bytes() for path in originals}
    service = PlotService()
    try:
        for item in managed["figures"]:
            reopened = service.open(Path(item["plot"]))
            assert reopened["plot_type"] == "ManagedPlot" and reopened["revision"] == 0
            assert reopened["export_current"]["byte_inventory_verified"] is True
    finally:
        service.close()

    request.write_text(json.dumps({**payload, "replicate_mode": "overlay"}), encoding="utf-8")
    assert main(["run", str(request)]) != 0
    capsys.readouterr()
    assert store.snapshot() == snapshot
    assert json.loads((output / "manifest.json").read_bytes())["ready_to_use"] is True

    request.write_text(json.dumps(payload), encoding="utf-8")
    visible = Path(first["veusz_documents"][0])
    original = visible.read_bytes()
    visible.write_bytes(original + b"\n# visible edit\n")
    assert main(["run", str(request)]) != 0
    assert "Saved Veusz copy has local edits" in capsys.readouterr().err
    assert visible.read_bytes() == original + b"\n# visible edit\n"
    visible.write_bytes(original)

    native = next(Path(managed["project"]).glob("figures/*/**/*.vsz"))
    native.write_bytes(native.read_bytes() + b"\n# external edit\n")
    assert main(["run", str(request)]) != 0
    assert "saved Managed frequency project has changed" in capsys.readouterr().err
    assert native.read_bytes().endswith(b"# external edit\n")



def test_frequency_cli_does_not_fall_back_after_managed_science_replay_mismatch(tmp_path, monkeypatch, capsys):
    import json

    from sciplot_core.cli import main
    from sciplot_core.workflow import frequency_managed_requests as owner

    raw, _ = _mean_input(tmp_path)
    request, output = tmp_path / "request.json", tmp_path / "run"
    request.write_text(json.dumps({"input": str(raw), "output": str(output), "rule_id": "rheology_frequency_sweep"}),
                       encoding="utf-8")
    real = owner.execute_node

    def corrupt(node, values):
        dataset, proof = real(node, values)
        if node["kind"] == "rheology_mean_exact_x":
            dataset["columns"]["storage_modulus"]["values"][0] += 250.0
        return dataset, proof

    monkeypatch.setattr(owner, "execute_node", corrupt)
    assert main(["run", str(request)]) != 0
    assert "does not replay the selected original frequency arrays exactly" in capsys.readouterr().err
    assert not (output / ".sciplot-frequency").exists()
    assert not (output / "figures").exists()
