"""Keep native/render derivatives in their explicit attached disposable owner."""
from pathlib import Path
import shutil
import tempfile
from typing import Any
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.canonical_paths import canonical_path
from .errors import EngineError


def _retain_preview(result: dict[str, Any], workspace: Path, destination: Path) -> None:
    original = canonical_path(Path(result["preview"]["path"]))
    if not original.is_relative_to(workspace):
        raise EngineError("native_preview_owner_invalid", "The native render did not return its exact private preview artifact.")
    if file_sha256(original) != result["preview"].get("sha256"):
        raise EngineError("native_preview_owner_invalid", "The native preview differs from its returned byte seal.")
    destination.mkdir(parents=True, exist_ok=False)
    preview = destination / "preview.png"
    shutil.copy2(original, preview)
    if file_sha256(preview) != result["preview"].get("sha256"):
        raise EngineError("native_preview_owner_invalid", "The copied native preview differs from its returned byte seal.")
    result["preview"] = {**result["preview"], "path": str(preview)}


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
            destination = self.repository.runtime_path(output)
            if binding.get("kind") == "sciplot_veusz_binding" and binding.get("_semantic_attachment_id"):
                # Native v3 owns the immutable review artifacts. Its producer
                # workspace must stay outside active project/source/delivery.
                with tempfile.TemporaryDirectory(prefix="sciplot-semantic-preview-") as temporary:
                    workspace = Path(temporary).resolve() / "preview"
                    result: dict[str, Any] = self.backend.preview(document, binding, new_document, diff, workspace)
                    result.pop("review_path", None)
                    if result.get("document_only") is True:
                        _retain_preview(result, workspace, destination)
                    elif result.get("kind") != "sciplot_document_edit_preview" or result.get("version") != 3:
                        raise EngineError("native_preview_owner_invalid", "An attached native edit requires a sealed version-3 review.")
                    elif any(Path(result[key]["path"]).is_relative_to(workspace.parent)
                             for key in ("candidate", "preview", "candidate_spec") if key in result):
                        raise EngineError("native_preview_owner_invalid", "The native review still depends on its disposable producer workspace.")
                    return result
            result = self.backend.preview(document, binding, new_document, diff, destination)
            return result

    def render(self, binding: dict[str, Any], output: Path) -> dict[str, Any]:
        with self.repository.binding_scope(binding):
            destination = self.repository.runtime_path(output)
            if binding.get("kind") == "sciplot_veusz_binding" and (
                binding.get("_semantic_attachment_id") or destination != output
            ):
                with tempfile.TemporaryDirectory(prefix="sciplot-semantic-preview-") as temporary:
                    workspace = Path(temporary).resolve() / "preview"
                    result: dict[str, Any] = self.backend.render(binding, workspace)
                    _retain_preview(result, workspace, destination)
                    return result
            result = self.backend.render(binding, destination)
            return result

    def export(self, binding: dict[str, Any]) -> dict[str, Any]:
        with self.repository.binding_scope(binding):
            result: dict[str, Any] = self.backend.export(binding)
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
