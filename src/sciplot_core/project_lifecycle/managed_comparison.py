"""Read and prepare detached Managed candidates; apply only through the patch owner."""

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sciplot_core.foundation.writer_lease import exclusive_directory_lease
from sciplot_core.plot_backends.managed import ManagedVeuszCompiler, compiler_identity
from sciplot_core.plot_document import seal_document
from sciplot_core.plot_document.requests import admit_patch
from sciplot_core.plot_engine.current import require_current
from sciplot_core.plot_engine.current_unit_admission import prepare_current_update
from sciplot_core.plot_engine.managed_state import resolved_ir

from .admission import admitted
from .context import active, exists, external_project_session, load_head, project_query, repository_scope, scientific_source_scope, transaction_path
from .contracts import RevisionToken
from .errors import EngineError
from .exports import export_head, export_key
from .patch_execution import execute_patch

if TYPE_CHECKING:
    from .application import ProjectApplication


def _head(owner: "ProjectApplication", plot: Path, *,
          baseline: dict[str, Any] | None = None,
          continue_baseline_export: bool = False) -> tuple[dict[str, Any], dict[str, Any]]:
    head = load_head(plot)
    if head["document"].get("plot_type") != "ManagedPlot":
        raise EngineError("comparison_managed_required", "Convert a separate supported copy of the saved VSZ for a new comparison.",
                          action="use_legacy_conversion")
    token = RevisionToken.of(head["document"]).to_payload()
    if baseline is not None and token != baseline:
        raise EngineError("comparison_baseline_stale", "The saved figure changed; start a new comparison from its current revision.")
    pending = active(plot)
    if pending and pending["phase"] not in {"complete", "rejected"}:
        own_export = (continue_baseline_export and pending["request"].get("action") == "export"
                      and pending["request"]["idempotency_key"] == export_key(head)
                      and pending["document"] == head["document"]
                      and pending["phase"] in {"committed", "exporting", "export_pending"})
        if not own_export:
            raise EngineError("comparison_plot_pending", "Finish or reject the current plot transaction before continuing this comparison.")
    require_current(owner.backend, head["binding"])
    return head, token


def observe_baseline(owner: "ProjectApplication", plot: Path, *,
                     location: Path | None = None) -> dict[str, Any]:
    """Exact saved handle only. A query never imports, repairs or renders a plot."""
    with repository_scope(owner.repository, capabilities=owner.capabilities), project_query(plot):
        head, token = _head(owner, plot)
        if location is not None:
            from sciplot_core.project_store.io import STORE

            protected = [plot, Path(head["binding"]["output"])]
            protected.extend(Path(source["path"]) for source in head["document"]["scientific"]["data_sources"])
            protected.extend(parent for parent in plot.parents if (parent / STORE / "head.json").is_file())
            if any(location == path or location.is_relative_to(path) or path.is_relative_to(location)
                   for path in (path.resolve() for path in protected)):
                raise EngineError("comparison_output_overlap",
                                  "Use a separate comparison directory outside the project, sources and publication.")
        return token


def prepare_preview(owner: "ProjectApplication", compiler: ManagedVeuszCompiler, plot: Path, baseline: dict[str, Any],
                    output: Path, patch: dict[str, Any] | None) -> dict[str, Any]:
    """Only sealed datasets and the same patch admission are used; no transactional preview."""
    with repository_scope(owner.repository, capabilities=owner.capabilities):
        with project_query(plot):
            head, _ = _head(owner, plot, baseline=baseline)
            saved = head["document"]
            candidate, diff = saved, []
            if patch is not None:
                from sciplot_core.plot_engine.managed_updates import SPECIAL

                if any(item["property"] in SPECIAL - {"theme"} or item["property"] == "scale.domain"
                       for item in patch["changes"]):
                    raise EngineError("comparison_presentation_only", "Scientific source, executor, transform or scale edits cannot be compared.")
                candidate, diff, risk, scientific = prepare_current_update(plot, saved, admit_patch(patch))
                if scientific or risk == "scientific" or candidate["scientific_hash"] != saved["scientific_hash"]:
                    raise EngineError("comparison_presentation_only", "A candidate must preserve the complete scientific hash.")
                if diff:
                    # Compute the exact eventual compilation without creating a revision or journal.
                    candidate = seal_document({**candidate, "revision": saved["revision"] + 1})
            ir = resolved_ir(plot, candidate)
            if not diff and ir["ir_hash"] != head["binding"]["ir_hash"]:
                raise EngineError("comparison_baseline_changed", "The saved binding no longer reproduces its original PlotIR.")
        # The real Veusz worker writes only under this owned attempt directory.
        with exclusive_directory_lease(output) as lease:
            evidence = compiler.compile_ir(ir, output)
            lease.verify()
        with project_query(plot):
            _head(owner, plot, baseline=baseline)
        if evidence["scientific_audit"].get("status") != "passed":
            raise EngineError("comparison_audit_failed", "The detached native candidate lacks a passed scientific audit.")
        return {**evidence, "changes": diff, "presentation_hash": candidate["presentation_hash"]}


def finish_selection(owner: "ProjectApplication", plot: Path, baseline: dict[str, Any], *,
                     patch: dict[str, Any] | None, export: bool,
                     verify_choice: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    """Recheck the sealed choice under the existing owner lease; resume its one command."""
    # Keeping the baseline without publication is a record-only action.
    # Do not enter a lease that could attach a historical namespace for writing.
    with repository_scope(owner.repository, capabilities=owner.capabilities):
        scope = project_query(plot) if patch is None and not export else external_project_session(plot)
        with scope:
            return _finish(owner, plot, baseline, patch=patch, export=export, proof=verify_choice())


def _finish(owner: "ProjectApplication", plot: Path, baseline: dict[str, Any], *,
            patch: dict[str, Any] | None, export: bool, proof: dict[str, Any]) -> dict[str, Any]:
    if patch is None:
        head, _ = _head(owner, plot, baseline=baseline, continue_baseline_export=export)
        if export:
            return {**export_head(plot, head, owner.backend), "outcome": "kept_baseline", "changed": False}
        return {"status": "complete", "outcome": "kept_baseline", "plot": str(plot),
                "plot_id": baseline["plot_id"], "revision": baseline["revision"],
                "changed": False, "export_status": "not_requested", "ready_to_use": False}
    owned = admit_patch(patch)
    if not exists(transaction_path(plot, owned.to_payload()["idempotency_key"])):
        _head(owner, plot, baseline=baseline)
        if compiler_identity() != proof["compiler_identity"]:
            raise EngineError("comparison_compiler_changed", "The renderer changed; start a new comparison before editing the plot.")
    with admitted(plot, "patch", owned), scientific_source_scope(plot, owned.to_payload()):
        return execute_patch(plot, owned, owner.backend, owner._cached_export, comparison={
            "baseline": baseline, "export": export, "operation_id": proof["operation_id"],
            "ir_hash": proof["ir_hash"], "native_state_hash": proof["native_state_hash"],
            "compiler_identity": proof["compiler_identity"], "presentation_hash": proof["presentation_hash"],
            "changed": bool(proof["changes"]),
        })
