"""Explicit production candidate orchestration, before an automatic cutover."""
from pathlib import Path
from typing import Any

from sciplot_core.figure_plan import FigureOutcome, merge_figure_outcomes
from sciplot_core.materials_rules.analysis import frequency_terminal_analysis
from sciplot_core.plot_backends.managed import ManagedVeuszCompiler, compiler_identity
from sciplot_core.plot_engine.managed_backend import native_build_record
from sciplot_core.project_commands import ProjectCommands, SourceTreeRead
from sciplot_core.project_lifecycle.attached_repository import AttachedProjectRepository
from sciplot_core.project_lifecycle.attachment_group import PreparedFigure, publish_attachment_group, resume_attachment_group
from sciplot_core.project_lifecycle.attachment_group_prepare import prepare_attachment_group
from sciplot_core.project_lifecycle.attachment_import import entry_for
from sciplot_core.project_lifecycle.attachment_index import Attachment, encode
from sciplot_core.project_lifecycle.capabilities import COMPATIBILITY_CAPABILITIES
from sciplot_core.project_lifecycle.context import repository_scope
from sciplot_core.project_lifecycle.managed_creation import bind_managed_member, new_managed_member
from sciplot_core.project_lifecycle.repository import digest
from sciplot_core.project_store import FileProjectStore
from sciplot_core.semantic_sources.scientific_source import ResolvedScientificSource
from sciplot_core.semantic_sources.rheology_sweep_domain import ResolvedRheologySweepDomain
from sciplot_core.task_errors import TaskControlError

from .frequency_managed_requests import PreparedFrequencyRequests, prepare_frequency_requests


def _figure(
    store: FileProjectStore, snapshot: dict[str, Any], key: str, figure_id: str,
    request: dict[str, Any], compiler: ManagedVeuszCompiler, private: Path,
) -> PreparedFigure:
    owner_key = "frequency-mean:" + digest([key, figure_id])
    output = store.root / "figures" / figure_id
    entry = entry_for(store, key=owner_key, figure_id=figure_id, origin=store.root,
                      plot_id="plot:" + digest([snapshot["project_id"], owner_key])[:24], managed_output=str(output))
    entry["origin_root"] = entry["namespace_origin"]
    attachment = Attachment(store, entry)
    repo = AttachedProjectRepository(attachment)
    with repo.prepare_new_member(snapshot) as members, repository_scope(repo, capabilities=COMPATIBILITY_CAPABILITIES):
        document = new_managed_member(request, entry["plot_id"])
        document, prepared = bind_managed_member(attachment.root, document, output)
        binding, ir = prepared
        repo.commit(attachment.root, document, binding, "frequency_mean_suite")
    native = Path(binding["document"])
    built = compiler.compile_ir(ir, private)
    exports = compiler.export_ir(ir, Path(built["document"]), private / "exports")
    assets = {store.logical_path(native): Path(built["document"]).read_bytes(),
              store.logical_path(native.parent / "build.json"): encode(native_build_record(ir["ir_hash"], built, ir["ir_hash"]))}
    for export in exports["exports"]:
        path = Path(export["path"])
        assets[store.logical_path(output / path.name)] = path.read_bytes()
    return PreparedFigure(attachment, members, assets, exports)


def publish_frequency_managed_suite(
    store: FileProjectStore, *, key: str, resolved: ResolvedScientificSource, compiler: ManagedVeuszCompiler,
    task_root: Path, prepared: PreparedFrequencyRequests | None = None,
) -> dict[str, Any]:
    """Prepare or resume all figures of an exact source-bound FigurePlan."""
    plan = resolved.figure_plan
    domain = resolved.require_domain(ResolvedRheologySweepDomain)
    if plan is None or domain.replicate_mode != "mean":
        raise TaskControlError("frequency_managed_candidates_unavailable", "Select an exact mean-frequency FigurePlan.")
    source_tree = SourceTreeRead(str(domain.source), domain.source_sha256)
    plan_data = plan.to_payload()
    app = ProjectCommands(store)
    prior = app.query(key)
    if prior is not None and prior["phase"] in {"accepted", "complete"}:
        prepare = app.query(key + ":prepare")
        recorded = prepare["metadata"]["request"] if prepare is not None else {}
        if recorded.get("plan") != plan_data or recorded.get("original") != source_tree.to_payload():
            raise TaskControlError("frequency_managed_request_changed", "Use the exact saved frequency group plan and original input identity.")
        return resume_attachment_group(store, key)
    if prepared is None:
        prepared = prepare_frequency_requests(domain, plan, task_root=task_root)
    by_figure = dict(zip(plan.selected_figure_ids, prepared.requests, strict=True))
    identity = {figure_id: digest(request) for figure_id, request in by_figure.items()}
    snapshot = store.snapshot()
    with prepare_attachment_group(store, key=key, plan=plan_data, figures=identity,
                                  source_tree=source_tree, runtime=compiler_identity()) as pending:
        figures = tuple(pending.figure(figure_id, lambda private, figure_id=figure_id: _figure(
            store, snapshot, key, figure_id, by_figure[figure_id], compiler, private))
            for figure_id in plan.selected_figure_ids)
        analysis = pending.workspace / "analysis_metrics.csv"
        metrics = frequency_terminal_analysis(prepared.terminal_pairs,
            semantic={"axis_plan": {"y": {"canonical_unit": "Pa"}}}, output=analysis)
        completed = merge_figure_outcomes(plan, [
            FigureOutcome(figure.attachment.entry["figure_id"], "ready",
                          artifacts=tuple(str(store.root / name) for name in figure.assets
                                          if Path(name).suffix in {".vsz", ".pdf", ".tiff"}))
            for figure in figures
        ])
        outputs = {"analysis/analysis_metrics.csv": analysis.read_bytes(), "analysis/analysis_metrics.json": encode(metrics),
                   "figure-plan.json": encode(completed.to_payload())}
        return publish_attachment_group(store, snapshot, key=key, selected_figures=plan.selected_figure_ids,
            figures=figures, required_outputs=tuple(outputs), outputs=outputs, source_tree=source_tree)
