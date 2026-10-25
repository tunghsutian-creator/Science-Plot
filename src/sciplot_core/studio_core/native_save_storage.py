"""Bind live native saves to the exact generation observed when editing began."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from sciplot_core.project_store import FileProjectStore, ProjectConflict
from sciplot_core.project_store.adapters import publish_files, store_for_project
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.studio_core.context import _project_context_for_document


def project_save_binding(project: Path, target: Path, *, store: FileProjectStore | None = None) -> dict[str, Any]:
    store = store or store_for_project(project)
    if store.root != project.expanduser().resolve(strict=True):
        raise ProjectConflict("The selected store belongs to a different native project.")
    snapshot = store.snapshot(import_legacy=True)
    name = store.logical_path(target)
    return {"project_id": snapshot["project_id"], "generation": snapshot["generation"],
            "files": {name: snapshot["files"].get(name, {}).get("sha256")}}


def bind_project_document_save(document: Any, project: Path, target: Path, *, save: Callable[..., dict[str, Any]]) -> None:
    root = project.expanduser().resolve(strict=True)
    destination = target.expanduser().absolute()
    if not destination.is_relative_to(root):
        raise ProjectConflict("A native save binding must name its exact trusted project member.")
    if not isinstance(getattr(document, "_sciplot_project_read_set", None), dict):
        raise ProjectConflict("A known native document requires its original editing baseline before save binding.")
    if not hasattr(document, "_sciplot_original_native_save"):
        document._sciplot_original_native_save = document.save
    document._sciplot_project_save_root = root

    def routed(filename: str, mode: str = "vsz") -> dict[str, Any]:
        requested = Path(filename).expanduser().absolute()
        expected_mode = "hdf5" if requested.suffix.casefold() == ".vszh5" else "vsz"
        if mode != expected_mode:
            raise ValueError("The requested native save mode differs from the target format.")
        context = _project_context_for_document(requested)
        if context is not None and Path(context["project_dir"]) != root:
            raise ProjectConflict("A live editing baseline cannot save into a foreign project.")
        return save(document, requested)

    document.save = routed


def publish_native_save(document: Any, target: Path, staged: Path, *, result: dict[str, Any]) -> dict[str, Any] | None:
    context = _project_context_for_document(target)
    root = Path(context["project_dir"]) if context is not None else None
    bound_root = getattr(document, "_sciplot_project_save_root", None)
    if bound_root is not None and target.is_relative_to(bound_root):
        root = Path(bound_root)
    if root is None:
        return None
    binding = getattr(document, "_sciplot_project_read_set", None)
    if binding is None and bound_root is None and not (root / ".sciplot_store/head.json").exists():
        return None
    if not isinstance(binding, dict):
        raise ProjectConflict("Saving an existing project requires the exact baseline captured before editing.")
    store = getattr(document, "_sciplot_project_store", None)
    if store is None:
        store = store_for_project(root)
    if not isinstance(store, FileProjectStore) or store.root != root:
        raise ProjectConflict("The selected native store does not belong to this project.")
    logical = store.logical_path(target)
    outcome = publish_files(store, {logical: staged}, kind="save", baseline=binding, result=result)
    document._sciplot_project_read_set = {**binding, "generation": outcome["generation"],
        "files": {**binding["files"], logical: file_sha256(staged)}}
    return outcome
