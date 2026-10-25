"""Explicit host selection around semantic creation, outside the scientific wire."""
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sciplot_core.project_lifecycle.errors import EngineError
from sciplot_core.project_lifecycle.paths import canonical_path
from sciplot_core.project_store import FileProjectStore
from sciplot_core.project_store.io import STORE
from sciplot_core.project_store.runtime import project_runtime, selected_project_store


def _owned_output(request: dict[str, Any], store: FileProjectStore) -> None:
    value = request.get("out")
    if not isinstance(value, str):
        return  # Scientific request validation retains its existing ownership.
    output = canonical_path(Path(value))
    if not output.is_relative_to(store.root):
        raise EngineError("managed_output_conflict", "The explicitly selected project must own its disposable output.")
    for parent in (output, *output.parents):
        if parent == store.root:
            break
        if (parent / STORE / "head.json").is_file():
            raise EngineError("semantic_project_target_conflict", "The output belongs to another nested project.")


@contextmanager
def selected_project_creation(project: Path | None, request: dict[str, Any]) -> Iterator[None]:
    """Validate an exact existing project; never infer, initialize or repair it."""
    existing = selected_project_store()
    if (project is not None or existing is not None) and (
            "template_definition" not in request or request.get("mode") == "legacy"):
        raise EngineError("semantic_project_creation_unsupported", "Attached creation requires an expert Managed Template/Binding request; source-only creation starts its own project.")
    if project is None:
        if existing is not None:
            _owned_output(request, existing)
        yield
        return
    if not project.is_absolute():
        raise EngineError("semantic_project_invalid", "Select one exact absolute existing project root.")
    root = canonical_path(project)
    if not root.is_dir() or not (root / STORE / "head.json").is_file():
        raise EngineError("semantic_project_unregistered", "The selected root has no existing project generation; initialize it explicitly first.")
    store = existing if existing is not None and existing.root == root else FileProjectStore(root)
    store.snapshot()  # Validates identity and refuses a pending projection; no import or repair.
    _owned_output(request, store)
    with project_runtime(store):
        yield
