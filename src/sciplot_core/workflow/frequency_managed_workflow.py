"""Project a sealed Managed frequency generation into the existing run package."""
from contextlib import AbstractContextManager, nullcontext
import hashlib
import json
from typing import Any
from pathlib import Path

from sciplot_core.figure_plan import FigureOutcome, merge_figure_outcomes, resolved_figure_plan_from_payload
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.foundation.project_session_lease import external_project_session
from sciplot_core.foundation.source_tree import source_tree_sha256
from sciplot_core.plot_backends.managed import ManagedVeuszCompiler
from sciplot_core.policy.render_options import DELIVERY_DIR, DELIVERY_PROJECT_DIR
from sciplot_core.project_commands import ProjectCommands
from sciplot_core.project_lifecycle.attachment_index import Attachment, read_index
from sciplot_core.project_store import FileProjectStore
from sciplot_core.semantic_sources.rheology_sweep_domain import ResolvedRheologySweepDomain
from sciplot_core.semantic_sources.scientific_source import ResolvedScientificSource
from sciplot_core.task_errors import TaskControlError
from sciplot_core.studio_core.managed_frequency_query import AUTHORITY

from .frequency_managed_requests import PreparedFrequencyRequests, prepare_frequency_requests
from .frequency_managed_suite import publish_frequency_managed_suite


_STANDARD_REQUEST_KEYS = {"input", "output", "rule_id", "recipe", "replicate_mode"}
_COMMAND = "workflow-frequency"
_COMPATIBILITY_REFUSALS = {
    "frequency_managed_candidates_unavailable",
    "frequency_managed_group_origin_unavailable",
    "frequency_managed_metric_origin_unavailable",
    "frequency_managed_metric_unit_unavailable",
    "frequency_managed_derivation_unavailable",
    "frequency_managed_metric_unavailable",
}


def managed_frequency_session(output: Path, request: dict[str, Any], *,
                              new_creation: bool) -> tuple[AbstractContextManager[None], Path | None]:
    authority = output / AUTHORITY
    standard = (not new_creation and not (set(request) - _STANDARD_REQUEST_KEYS)
                and request.get("rule_id") in (None, "rheology_frequency_sweep")
                and request.get("recipe") in (None, "auto")
                and request.get("replicate_mode") in (None, "mean"))
    if authority.is_symlink() or (authority.exists() and (not authority.is_dir() or not standard)):
        raise ValueError("This output belongs to its original Managed frequency request; choose a new output for a different request.")
    if standard and (authority.is_dir() or not output.exists()):
        return external_project_session(output), authority
    return nullcontext(), None


def _visible_document(output: Path, stem: str) -> Path:
    return output / "figures" / "_veusz" / stem / "single/studio/document.vsz"


def check_visible_frequency_documents(authority: Path, request: dict[str, Any], output: Path, *,
                                      delivery: Path | None = None) -> None:
    """Do not move users' edited VSZ projections into the old run backup."""
    identity = canonical_json_sha256(request)
    workspace = authority / identity
    if not (workspace / ".sciplot_store/head.json").is_file():
        return
    store = FileProjectStore(workspace)
    receipt = ProjectCommands(store).query(_COMMAND + ":" + identity)
    if receipt is None or receipt["phase"] != "complete":
        return
    package = delivery if delivery is not None else output / DELIVERY_DIR
    generation = receipt["generation"]
    plan = resolved_figure_plan_from_payload(json.loads(store.read_bytes("figure-plan.json", generation=generation)))
    assert plan is not None
    for task, outcome in zip(plan.tasks, plan.outcomes, strict=True):
        native = next(Path(path) for path in outcome.artifacts if Path(path).suffix == ".vsz")
        expected = receipt["result"]["artifacts"][store.logical_path(native)]
        for path in (_visible_document(output, task.artifact_stem), package / DELIVERY_PROJECT_DIR / (task.artifact_stem + ".vsz")):
            if path.exists() and (not path.is_file() or file_sha256(path) != expected):
                raise ValueError(f"Saved Veusz copy has local edits; its bytes were kept: {path}")


def frequency_candidates(resolved: ResolvedScientificSource, *, authority: Path) -> PreparedFrequencyRequests | None:
    domain, plan = resolved.domain, resolved.figure_plan
    if (not isinstance(domain, ResolvedRheologySweepDomain) or plan is None
            or domain.rule_id != "rheology_frequency_sweep" or domain.replicate_mode != "mean"):
        return None
    try:
        return prepare_frequency_requests(domain, plan, task_root=authority)
    except TaskControlError as exc:
        if (not authority.exists() and exc.reason_code in _COMPATIBILITY_REFUSALS
                and source_tree_sha256(domain.source) == domain.source_sha256):
            return None
        raise


def render_managed_frequency(resolved: ResolvedScientificSource, *, authority: Path, output: Path,
                             source_request: dict[str, Any], prepared: PreparedFrequencyRequests | None = None) -> dict[str, Any] | None:
    """Return a projection only for the complete, original-source mean suite."""
    claimed = authority.exists()
    domain, plan = resolved.domain, resolved.figure_plan
    if (not isinstance(domain, ResolvedRheologySweepDomain) or plan is None
            or domain.rule_id != "rheology_frequency_sweep" or domain.replicate_mode != "mean"):
        if claimed:
            raise ValueError("The output belongs to the original Managed frequency run.")
        return None
    identity = canonical_json_sha256(source_request)
    key = _COMMAND + ":" + identity
    workspace = authority / identity
    if claimed and (authority.is_symlink() or workspace.is_symlink()
                    or any(entry != workspace and entry.name != ".sciplot_session_locks"
                           for entry in authority.iterdir())):
        raise ValueError("The Managed frequency output is reserved for its exact original request.")
    if not workspace.exists():
        prepared = prepared or frequency_candidates(resolved, authority=authority)
        if prepared is None:
            return None
        workspace.mkdir(mode=0o700, parents=True)
    store = FileProjectStore(workspace)
    if not (workspace / ".sciplot_store/head.json").exists():
        store.snapshot(import_legacy=True)
    compiler = ManagedVeuszCompiler()
    try:
        receipt = publish_frequency_managed_suite(store, key=key, resolved=resolved, compiler=compiler,
                                                  task_root=authority, prepared=prepared)
    finally:
        compiler.close()
    return _project(store, output=output, receipt=receipt)


def _project(store: FileProjectStore, *, output: Path, receipt: dict[str, Any]) -> dict[str, Any]:
    generation = receipt["generation"]
    result = receipt["result"]
    plan = resolved_figure_plan_from_payload(json.loads(store.read_bytes("figure-plan.json", generation=generation)))
    if plan is None or not plan.complete or list(plan.selected_figure_ids) != result["figure_ids"]:
        raise ValueError("Managed frequency publication has no complete figure plan.")
    current = store.snapshot()
    if current["generation"] != generation or current["projection_status"] != "current":
        raise ValueError("The saved Managed frequency project has changed. Open its figures or choose a new run output.")
    attachments = {entry["figure_id"]: Attachment(store, entry)
                   for entry in read_index(store, current)["attachments"].values()}
    exports, documents, outcomes, edits = [], [], [], []
    for task, outcome in zip(plan.tasks, plan.outcomes, strict=True):
        attachment = attachments[task.figure_id]
        cache = json.loads(store.read_bytes(attachment.entry["archived_derivatives"]["export-cache.json"],
                                            generation=generation))
        artifact = cache["export"]
        edits.append({"figure_id": task.figure_id, "plot": str(attachment.root),
                      "scientific_audit": artifact["scientific_audit"], "publication_qa": artifact["publication_qa"]})
        delivered = []
        for value in outcome.artifacts:
            source = Path(value)
            logical = store.logical_path(source)
            blob = store.read_bytes(logical, generation=generation)
            if hashlib.sha256(blob).hexdigest() != result["artifacts"].get(logical):
                raise ValueError("Managed frequency publication does not match its sealed artifact receipt.")
            if source.suffix == ".vsz":
                target = _visible_document(output, task.artifact_stem)
                documents.append(str(target))
            else:
                suffix = {"pdf": ".pdf", "tiff": "_300dpi.tiff"}[source.suffix.lstrip(".")]
                target = output / "figures" / (task.artifact_stem + suffix)
                exports.append({"format": "pdf" if suffix == ".pdf" else "tiff_300", "path": str(target),
                                "source": str(target), "figure_id": task.figure_id, "exists": True,
                                "size_bytes": len(blob), "dpi": None if suffix == ".pdf" else 300})
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(blob)
            delivered.append(str(target))
        outcomes.append(FigureOutcome(task.figure_id, "ready", tuple(delivered)))
    metrics = store.read_bytes("analysis/analysis_metrics.csv", generation=generation)
    table = output / "tables" / "analysis_metrics.csv"
    table.parent.mkdir(parents=True, exist_ok=True)
    table.write_bytes(metrics)
    return {"kind": "sciplot_render_result", "template": "point_line", "sheet": 0,
            "render_engine": "veusz", "qa_target": "veusz_export", "export_formats": ["pdf", "tiff_300"],
            "outputs": [item["path"] for item in exports], "exports": exports, "veusz_documents": documents, "veusz_specs": [],
            "analysis_metrics": json.loads(store.read_bytes("analysis/analysis_metrics.json", generation=generation)), "qa_reports": [],
            "multi_metric_bundle": {"kind": "rheology_sweep_metric_bundle",
                                    "metric_ids": [task.artifact_stem for task in plan.tasks],
                                    "figure_ids": list(plan.selected_figure_ids)},
            "managed_frequency": {"project": str(store.root), "generation": generation,
                                  "primary_figure_id": plan.primary_figure_id, "figures": edits},
            "resolved_figure_plan": merge_figure_outcomes(plan, outcomes).to_payload()}
