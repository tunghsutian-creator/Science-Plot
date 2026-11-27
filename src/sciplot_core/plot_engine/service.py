"""Public compatibility facade; semantic orchestration belongs to ProjectApplication.

Native prepared suites have their own complete-native authority and transaction
owner. The composition adapter routes those objects before entering the semantic
aggregate application; no native draft is silently promoted to Managed authority.
"""
from pathlib import Path
from typing import Any
from sciplot_core.plot_document.requests import RequestInput, admit_patch

from sciplot_core.project_lifecycle.admission import usecase
from sciplot_core.project_lifecycle.application import ProjectApplication
from sciplot_core.project_lifecycle.composition import components
from sciplot_core.project_lifecycle.paths import canonical_path
from sciplot_core.project_lifecycle.ports import ProjectRepository, ProjectTargets
from sciplot_core.project_lifecycle.target_adapter import FilesystemProjectTargets, PublicFilesystemProjectTargets

from .backend import PlotBackend
from .description_scope import require_selector
from .errors import EngineError
from .prepared_routing import native_dispatch


def _standalone_archive(path: Path) -> bool:
    return path.suffix == ".sciplot" and (path.is_symlink() or not path.is_dir())


def _require_directory_plot(path: Path, operation: str, *, next_action: str = "project.open") -> None:
    path = path.expanduser()
    if _standalone_archive(path):
        message = {
            "patch": "Use plot.intent for an advertised edit on a standalone project file.",
            "rollback": "Standalone project files do not yet support rollback.",
            "decide": "Standalone project files have no generic change-review decision to accept.",
            "render": "Use plot.export with a plot ID, current revision and output directory.",
            "export": "Provide a plot ID, current revision and output directory for a standalone project export.",
        }[operation]
        raise EngineError("project_file_operation_unsupported", message, action=next_action,
                          project_file=str(path.absolute()), operation=operation)


class PlotService(ProjectApplication):
    def __init__(self, backend: PlotBackend | None = None, *, repository: ProjectRepository | None = None,
                 capabilities: dict[str, Any] | None = None, resolve_figure: Any = None, targets: ProjectTargets | None = None,
                 read_only_legacy: bool = False) -> None:
        self.read_only_legacy = read_only_legacy
        backend, repository, capabilities, resolve_figure = components(backend, repository, capabilities, resolve_figure)
        default_targets = PublicFilesystemProjectTargets if read_only_legacy else FilesystemProjectTargets
        super().__init__(backend, repository, capabilities=capabilities,
                         targets=targets if targets is not None else default_targets(repository, resolve_figure=resolve_figure))

    def create(self, request: dict[str, Any], *, project: Path | None = None) -> dict[str, Any]:
        from .selected_project import selected_project_creation

        with selected_project_creation(project, request):
            return super().create(request)

    def _allow_new_legacy_template(self) -> bool:
        return not self.read_only_legacy

    def _template_creation_owner(self) -> ProjectApplication:
        # Apply a frozen template only inside its existing creation lifecycle.
        # Share the real backend and repository, without public saved-plot dispatch.
        if not self.read_only_legacy:
            return self
        return ProjectApplication(self.backend, self.repository, targets=self.targets, capabilities=self.capabilities)

    def open(self, target: Path, figure_id: str | None = None, *,
             description: dict[str, Any] | None = None) -> dict[str, Any]:
        description = require_selector(description)
        target = target.expanduser()
        if _standalone_archive(target):
            from sciplot_core.project_lifecycle.project_file_summary import project_file_summary

            if description is not None and description["scope"] != "summary":
                raise EngineError("project_file_summary_only", ".sciplot files currently support read-only open summaries.",
                                  action="project.open", target=str(target.absolute()), description={"scope": "summary"})
            return project_file_summary(target, figure_id)
        target = canonical_path(target)
        native = native_dispatch("describe", target, figure_id=figure_id, description=description)
        if native is not None:
            return native
        if self.read_only_legacy:
            saved = self._read_legacy_saved(target, figure_id)
            if saved is not None:
                from sciplot_core.studio_core.legacy_saved_plot import open_legacy_document

                return open_legacy_document(*saved)
        return super().open(target, figure_id, description=description)

    @usecase
    def _read_legacy_saved(self, target: Path, figure_id: str | None) -> tuple[Path, Path] | None:
        return self.targets.read_legacy_saved(target, figure_id) if isinstance(self.targets, FilesystemProjectTargets) else None

    def require_editable(self, plot: Path, *, figure_id: str | None = None) -> None:
        if self.read_only_legacy:
            saved = self._read_legacy_saved(canonical_path(plot), figure_id)
            if saved is not None:
                from sciplot_core.studio_core.legacy_saved_plot import conversion_required

                raise conversion_required(saved[1])

    @usecase
    def _require_saved_continuation(self, plot: Path, request: dict[str, Any], *, decision: bool) -> None:
        if not self.read_only_legacy or not isinstance(self.targets, FilesystemProjectTargets):
            return
        root = canonical_path(plot)
        saved = self.targets.read_legacy_saved(root, None)
        if saved is None:
            return
        if request.get("reimport") is True:
            from sciplot_core.studio_core.legacy_saved_plot import conversion_required

            raise conversion_required(saved[1])
        from sciplot_core.project_lifecycle.context import active, exists, read, transaction_path

        with self.repository.query_scope(root):
            if decision:
                transaction = active(root)
                if (transaction is not None and transaction["id"] == request["decision_id"]
                        and transaction["request"]["base_revision"] == request["base_revision"]):
                    return
            else:
                path = transaction_path(root, request["idempotency_key"])
                if exists(path):
                    transaction = read(path)
                    if (transaction["request"]["base_revision"] == request["base_revision"]
                            and transaction["document"]["plot_id"] == request["plot_id"]):
                        return
        raise EngineError("legacy_transaction_unknown",
                          "A read-only legacy plot can only continue an already saved transaction.")

    def describe(self, plot: Path, *, description: dict[str, Any] | None = None) -> dict[str, Any]:
        description = require_selector(description)
        if _standalone_archive(plot.expanduser()):
            return self.open(plot, description=description)
        target = canonical_path(plot)
        native = native_dispatch("describe", target, description=description)
        if native is not None:
            return native
        if self.read_only_legacy:
            saved = self._read_legacy_saved(target, None)
            if saved is not None:
                from sciplot_core.studio_core.legacy_saved_plot import open_legacy_document

                return open_legacy_document(*saved)
        return super().describe(plot, description=description)

    def patch(self, plot: Path, request: RequestInput) -> dict[str, Any]:
        _require_directory_plot(plot, "patch", next_action="plot.intent")
        request = admit_patch(request)
        native = native_dispatch("patch", canonical_path(plot), request=request)
        if native is not None:
            return native
        self.require_editable(plot)
        return super().patch(plot, request)

    def decide(self, plot: Path, request: dict[str, Any]) -> dict[str, Any]:
        from .contracts import validate_decide

        _require_directory_plot(plot, "decide")
        request = validate_decide(request)
        native = native_dispatch("decide", canonical_path(plot), request=request)
        if native is not None:
            return native
        self._require_saved_continuation(plot, request, decision=True)
        return super().decide(plot, request)

    def resume(self, plot: Path, request: dict[str, Any]) -> dict[str, Any]:
        plot = plot.expanduser()
        if _standalone_archive(plot):
            from sciplot_core.project_lifecycle.project_file_intent import resume_project_file_intent

            return resume_project_file_intent(plot, request)
        native = native_dispatch("resume", canonical_path(plot), request=request)
        if native is not None:
            return native
        if self.read_only_legacy:
            from .contracts import validate_resume

            self._require_saved_continuation(plot, validate_resume(request), decision=False)
        return super().resume(plot, request)

    def export(self, plot: Path, *, handoff: dict[str, Any] | None = None) -> dict[str, Any]:
        if handoff is not None:
            plot = plot.expanduser()
            if _standalone_archive(plot):
                from sciplot_core.project_lifecycle.project_file_handoff import project_file_handoff

                return project_file_handoff(self, plot, handoff)
            return super().export(plot, handoff=handoff)
        _require_directory_plot(plot, "export", next_action="plot.export")
        native = native_dispatch("export", canonical_path(plot))
        if native is not None:
            return native
        self.require_editable(plot)
        return super().export(plot)

    def intent(self, plot: Path, request: dict[str, Any]) -> dict[str, Any]:
        plot = plot.expanduser()
        if _standalone_archive(plot):
            from sciplot_core.project_lifecycle.project_file_intent import project_file_intent

            return project_file_intent(self, plot, request)
        self.require_editable(plot)
        from .typed_intent import LINE_COLOR

        if isinstance(request, dict) and request.get("property") == LINE_COLOR:
            raise EngineError("plot_intent_invalid", "Line color via plot intent requires a standalone .sciplot file.",
                              action="inspect_project_file")
        return super().intent(plot, request)

    def rollback(self, plot: Path, request: dict[str, Any]) -> dict[str, Any]:
        _require_directory_plot(plot, "rollback")
        self.require_editable(plot)
        return super().rollback(plot, request)

    def render(self, plot: Path) -> dict[str, Any]:
        _require_directory_plot(plot, "render", next_action="plot.export")
        self.require_editable(plot)
        return super().render(plot)


def public_plot_service() -> PlotService:
    """All public hosts use the same policy for saved legacy documents."""
    return PlotService(read_only_legacy=True)
