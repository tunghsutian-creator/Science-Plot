"""Versioned plot use cases that don't enter the legacy/source task dispatcher."""
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sciplot_core.plot_engine.backend import PlotBackend
from sciplot_core.plot_engine.current import changed_inputs, dependency_state
from sciplot_core.plot_engine.description_scope import require_selector
from sciplot_core.plot_engine.export_status import current_export
from sciplot_core.plot_engine.object_operations import attach_object_operations

from .admission import usecase
from .context import active, load_head, project_query
from .contracts import RevisionToken
from .errors import EngineError
from .paths import canonical_path
from .ports import ProjectRepository
from .recovery import project_recovery
from .targets import ManagedCreationLocation

if TYPE_CHECKING:
    from .figure_handoff import FigureInstall


class ManagedPlotApplication:
    def __init__(self, backend: PlotBackend, repository: ProjectRepository, *,
                 managed_target: Callable[[dict[str, Any]], ManagedCreationLocation],
                 capabilities: dict[str, Any] | None = None) -> None:
        self.backend, self.repository = backend, repository
        self.capabilities = capabilities
        self._managed_target = managed_target

    def _create_managed(self, request: dict[str, Any]) -> dict[str, Any]:
        from .managed_creation import create_managed

        return create_managed(request, self.backend, location=self._managed_target(request))

    @usecase
    def create(self, request: dict[str, Any]) -> dict[str, Any]:
        from sciplot_core.plot_engine.contracts import validate_create

        request = validate_create(request)
        if "template_definition" not in request or request.get("mode") == "legacy":
            raise EngineError("managed_template_required", "Managed creation requires a template definition and exact data binding.")
        return self._create_managed(request)

    def close(self) -> None:
        close = getattr(self.backend, "close", None)
        if close is not None:
            close()

    @usecase
    def handoff_figure(self, plot: Path, request: dict[str, Any], *,
                       before_install: "Callable[[FigureInstall], None] | None" = None,
                       installed: "FigureInstall | None" = None,
                       rebuild_missing: Callable[[str], bool] | None = None,
                       render_missing_formats: bool = False) -> dict[str, Any]:
        from .figure_handoff import handoff_figure

        return handoff_figure(canonical_path(plot), request, self.backend,
                              before_install=before_install, installed=installed, rebuild_missing=rebuild_missing,
                              render_missing_formats=render_missing_formats)

    @usecase
    def describe(self, plot: Path, *, description: dict[str, Any] | None = None) -> dict[str, Any]:
        description = require_selector(description)
        root = canonical_path(plot)
        with project_query(root):
            return self._describe(root, description=description)

    def _describe(self, root: Path, *, description: dict[str, Any] | None = None) -> dict[str, Any]:
        head = load_head(root)
        document, binding = head["document"], head["binding"]
        changed = changed_inputs(self.backend, binding)
        pending = active(root)
        result = {"kind": "sciplot_plot_description", "version": 1, "status": "stale" if changed else "current",
                "plot_type": document.get("plot_type", "LegacyPlot"),
                "revision_token": RevisionToken.of(document).to_payload(),
                "plot": str(root), "plot_id": document["plot_id"], "revision": document["revision"],
                "scientific_hash": document["scientific_hash"], "presentation_hash": document["presentation_hash"],
                "objects": document["presentation"]["objects"], "coverage": document["coverage"],
                "changed_inputs": changed, "dependencies": ({}
                    if description is not None and document.get("plot_type") == "ManagedPlot"
                    else dependency_state(document, binding, changed)),
                "pending": ({"idempotency_key": pending["request"]["idempotency_key"], "phase": pending["phase"]}
                            if pending and pending["phase"] not in {"complete", "rejected"} else None),
                "document": str(root / "revisions" / f'{document["revision"]:08d}.json')}
        project_recovery(result, root, pending)
        if document.get("plot_type") == "ManagedPlot":
            from sciplot_core.plot_engine.managed_description import describe_managed

            result["export_current"] = current_export(root, head, eligible=not changed and result["pending"] is None)
            return attach_object_operations(describe_managed(root, head, result, self.backend, description=description), document)
        from sciplot_core.plot_engine.external_mutation import authority_status

        if description is not None and description["scope"] == "edit":
            raise EngineError("description_scope_unavailable", "Scoped edit contracts are available for ManagedPlot; use the full LegacyPlot description.",
                              action="plot.describe")
        result["authority"] = authority_status("LegacyPlot")
        if changed and not result["pending"]:
            from sciplot_core.project_lifecycle.reimport import offer

            next_step = offer(self.backend, head, changed)
            if next_step is not None:
                result["next_step"] = next_step
        return attach_object_operations(result, document)

    @usecase
    def deliver(self, request: dict[str, Any]) -> dict[str, Any]:
        """Package exact managed revisions; each export retains its own transaction."""
        from sciplot_core.plot_engine.managed_delivery import deliver

        return deliver(self, request)

    @usecase
    def inspect_delivery(self, request: dict[str, Any], *, paper_dir: Path | None = None) -> dict[str, Any]:
        """Read the Managed delivery owner, or validate its separate paper receipt location."""
        from sciplot_core.plot_engine.managed_delivery import inspect, require_paper_location

        if paper_dir is not None:
            require_paper_location(request, paper_dir)
            return {}
        return inspect(self, request)


def managed_task_application() -> ManagedPlotApplication:
    """Compose the local owner for independent Python task/Studio calls."""
    from sciplot_core.plot_backends.figure_plan import capability_profile
    from sciplot_core.plot_engine.managed_backend import ManagedBackend

    from .backend_paths import compose_project_repository
    from .managed_creation_targets import managed_creation_target

    capabilities = capability_profile()
    backend, repository = compose_project_repository(ManagedBackend(), None, capabilities)
    return ManagedPlotApplication(backend, repository, capabilities=capabilities,
        managed_target=partial(managed_creation_target, repository, publish_fresh_managed_output=True))
