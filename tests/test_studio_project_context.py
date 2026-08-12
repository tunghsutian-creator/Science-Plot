from __future__ import annotations

from pathlib import Path
from typing import Any

from sciplot_gui.studio_project import context as context_module
from sciplot_gui.studio_project.context import ContextMixin


class _StatusView:
    def setPlainText(self, _text: str) -> None:
        pass


class _Context(ContextMixin):
    def __init__(self, document_path: Path) -> None:
        self.document_path = document_path
        self.project_dir = document_path.parent
        self.window = object()
        self.status_view = _StatusView()
        self.status_snapshot: dict[str, Any] = {
            "scientific_transform_review": {
                "status": "available",
                "semantic_family": "rheology_stress_relaxation",
            }
        }
        self.published_status: dict[str, Any] | None = None

    def _publish_status(self, status: dict[str, Any]) -> None:
        self.published_status = status


def test_document_context_change_clears_scientific_transform_review(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    bound_document = tmp_path / "bound.vsz"
    changed_document = tmp_path / "changed.vsz"
    context = _Context(bound_document)
    monkeypatch.setattr(
        context_module,
        "resolved_window_document_path",
        lambda _window: changed_document,
    )
    monkeypatch.setattr(context_module, "_status_text", lambda _status: "blocked")

    status = context.handle_document_context_changed()

    assert status is not None
    assert status["state"] == "document_context_changed"
    assert status["scientific_transform_review"] is None
    assert context.published_status is status
