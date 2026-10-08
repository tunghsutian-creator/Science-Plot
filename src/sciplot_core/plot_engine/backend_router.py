"""Authority-directed backend calls; both modes share one transaction engine."""

from pathlib import Path
from typing import Any

from .backend import PlotBackend
from .managed_backend import ManagedBackend


class BackendRouter:
    def __init__(self, legacy: PlotBackend) -> None:
        self.legacy = legacy
        self.managed = ManagedBackend()

    def close(self) -> None:
        self.managed.close()
        close = getattr(self.legacy, "close", None)
        if close:
            close()

    def _owner(self, binding: dict[str, Any]) -> Any:
        return self.managed if binding.get("kind") == "sciplot_managed_binding" else self.legacy

    def import_project(self, project: Path, figure_id: str | None = None,
                       plot_id: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
        return self.legacy.import_project(project, figure_id, plot_id)

    def fingerprint(self, binding: dict[str, Any]) -> dict[str, Any]:
        return dict(self._owner(binding).fingerprint(binding))

    def preview(self, document: dict[str, Any], binding: dict[str, Any], new_document: dict[str, Any],
                diff: list[dict[str, Any]], output: Path) -> dict[str, Any]:
        return dict(self._owner(binding).preview(document, binding, new_document, diff, output))

    def apply(self, binding: dict[str, Any], review: dict[str, Any]) -> dict[str, Any]:
        return dict(self._owner(binding).apply(binding, review))

    def refresh_binding(self, binding: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        return dict(self._owner(binding).refresh_binding(binding, result))

    def export(self, binding: dict[str, Any]) -> dict[str, Any]:
        return dict(self._owner(binding).export(binding))

    def render(self, binding: dict[str, Any], output: Path) -> dict[str, Any]:
        return dict(self._owner(binding).render(binding, output))
