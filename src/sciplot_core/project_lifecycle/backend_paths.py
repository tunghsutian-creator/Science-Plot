"""Keep native/render derivatives in their explicit attached disposable owner."""
from pathlib import Path
from typing import Any


class RepositoryBackendPaths:
    def __init__(self, backend: Any, repository: Any) -> None:
        self.backend, self.repository = backend, repository

    def __getattr__(self, name: str) -> Any:
        return getattr(self.backend, name)

    def fingerprint(self, binding: dict[str, Any]) -> dict[str, Any]:
        with self.repository.binding_scope(binding):
            result: dict[str, Any] = self.backend.fingerprint(binding)
            return result

    def preview(self, document: dict[str, Any], binding: dict[str, Any], new_document: dict[str, Any],
                diff: list[dict[str, Any]], output: Path) -> dict[str, Any]:
        with self.repository.binding_scope(binding):
            result: dict[str, Any] = self.backend.preview(document, binding, new_document, diff, self.repository.runtime_path(output))
            return result

    def render(self, binding: dict[str, Any], output: Path) -> dict[str, Any]:
        with self.repository.binding_scope(binding):
            result: dict[str, Any] = self.backend.render(binding, self.repository.runtime_path(output))
            return result

    def apply(self, binding: dict[str, Any], review: dict[str, Any]) -> dict[str, Any]:
        with self.repository.binding_scope(binding):
            if (binding.get("kind") != "sciplot_managed_binding" and review.get("kind") == "sciplot_document_edit_preview"
                    and review.get("version") == 3):
                from sciplot_core.studio_core.document_edit_commands import rebind_document_edit_review

                fields = {key: value for key, value in review.items() if key.startswith("_backend_")}
                original = {key: value for key, value in review.items() if not key.startswith("_backend_")}
                review = {**rebind_document_edit_review(Path(binding["project"]), original), **fields}
            result: dict[str, Any] = self.backend.apply(binding, review)
            return result
