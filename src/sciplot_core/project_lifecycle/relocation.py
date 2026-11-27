"""Explicit relocation of a saved Store, not a new project or a paper snapshot."""

from pathlib import Path
from typing import Any

from sciplot_core.foundation.canonical_paths import canonical_path
from sciplot_core.foundation.research_destination import require_data_destination
from sciplot_core.project_store import FileProjectStore, ProjectConflict
from sciplot_core.project_store.io import STORE

from .attached_repository import AttachedProjectRepository
from .attachment_index import read_index
from .errors import EngineError
from .head_observation import observe_plot_head
from .store_composition import existing_store


def _overlaps(target: Path, protected: Path) -> bool:
    return target.is_relative_to(protected) or protected.is_relative_to(target)


def _new_destination(value: Path, origin: Path) -> Path:
    target = canonical_path(value)
    require_data_destination(target)
    if _overlaps(target, origin):
        raise EngineError("project_bundle_path_overlap", "Choose a new destination outside the original project or bundle.")
    if target.exists():
        raise EngineError("project_bundle_destination_exists", "The bundle or relocation destination already exists; nothing was replaced.")
    if not target.parent.is_dir():
        raise EngineError("project_bundle_parent_missing", "Choose a new destination under an existing research directory.")
    return target


def _open_arguments(path: Path) -> dict[str, Any]:
    return {"target": str(path), "description": {"scope": "summary"}}


def _import_step(store: FileProjectStore, head: dict[str, Any]) -> dict[str, Any]:
    arguments = _open_arguments(store.root)
    figures = [{"figure_id": entry["figure_id"], "plot_id": entry["plot_id"],
                "open_arguments": {**arguments, "figure_id": entry["plot_id"]}}
               for entry in read_index(store, head)["attachments"].values()]
    if len(figures) == 1:
        return {"action": "project.open", "arguments": figures[0]["open_arguments"]}
    if figures:
        return {"action": "select_figure", "figures": figures}
    return {"action": "no_registered_figures"}


def _result(operation: str, project: Path, bundle: Path, head: dict[str, Any], *,
            single_file: bool = False, next_step: dict[str, Any] | None = None) -> dict[str, Any]:
    if next_step is not None:
        step = next_step
    elif not single_file:
        step = {"action": "project.bundle-import", "arguments": {"bundle": str(bundle)},
                "required_arguments": ["output_dir"]}
    else:
        step = {"action": "project.open", "arguments": _open_arguments(bundle)}
    return {"kind": "sciplot_project_bundle_result", "version": 1, "status": operation,
            "project": str(project), "bundle": str(bundle), "project_id": head["project_id"],
            "generation": head["generation"], "mode": "same_project_relocation",
            "independent_project": False, "host_grants_included": False, "next_step": step}


def _exact_member(path: Path) -> AttachedProjectRepository | None:
    if path.parent.name != ".sciplot_semantic":
        return None
    from .repository_router import ComposedProjectRepository

    repository = ComposedProjectRepository()
    with repository.invocation_scope():
        selected = repository._discover(path)
        return selected if selected is not None and selected.attachment.root == path else None


def export_project_bundle(project: Path, destination: Path, *, single_file: bool = False,
                          expected_generation: str | None = None) -> dict[str, Any]:
    """Bundle the whole Store at its exact admitted generation, without initializing it."""
    try:
        target = canonical_path(project)
    except ValueError as exc:
        if not single_file:
            raise
        raise EngineError("project_bundle_store_required", "Use the exact versioned Store or saved Managed plot, not a symbolic alias.") from exc
    member = None
    if not canonical_path(target / STORE / "head.json").is_file():
        member = _exact_member(target) if single_file else None
        if member is None:
            detail = ("Choose the exact Store root or saved Managed v2 plot handle." if single_file else
                      "Choose the exact root of an already versioned Store. A VSZ, old unregistered project and paper package cannot be relocated this way.")
            raise EngineError("project_bundle_store_required", detail)
    root = member.attachment.store.root if member is not None else target
    out = _new_destination(destination, root)
    if single_file and out.suffix != ".sciplot":
        raise EngineError("project_file_destination_required", "Choose a new filename ending in .sciplot.")
    store = member.attachment.store if member is not None else existing_store(root)
    for key, location in store.locations.items():
        members = store.location_members[key]
        protected = (location,) if members is None else (location / name for name in members)
        if any(_overlaps(out, path) for path in protected):
            raise EngineError("project_bundle_path_overlap", "The bundle destination overlaps a registered project resource.")

    with store._locked():
        head = store.snapshot()
        if expected_generation is not None and expected_generation != head["generation"]:
            raise EngineError("project_bundle_generation_conflict", "The Store has a different generation. Read its current state before exporting.",
                              action="inspect_project", current_generation=head["generation"])
        if head["projection_status"] != "current":
            raise ProjectConflict("Resolve unadmitted outside changes before bundling the saved project.")
        if member is not None:
            from sciplot_core.plot_ir.figure_document import is_figure

            entry = member.attachment.entry
            if read_index(store, head)["attachments"].get(entry["id"]) != entry:
                raise EngineError("semantic_attachment_owner_conflict", "The saved plot no longer identifies its registered project attachment.")
            selected = observe_plot_head(target, owner=member, optional=True)
            document = selected["document"] if selected is not None else {}
            if document.get("plot_type") != "ManagedPlot" or not is_figure(document):
                raise EngineError("project_file_figure_unsupported", "Use an exact committed Managed v2 plot handle or exact Store root.")
            if document["plot_id"] != entry["plot_id"]:
                raise EngineError("semantic_attachment_owner_conflict", "The saved plot no longer identifies its registered project attachment.")
        if single_file:
            from .project_file import ProjectFileSaveUnconfirmed, create_project_file

            try:
                file = create_project_file(out, store, expected_generation=head["generation"])
            except FileExistsError as exc:
                raise EngineError("project_bundle_destination_exists", "The relocation destination already exists; nothing was replaced.") from exc
            except ProjectFileSaveUnconfirmed as exc:
                raise EngineError("project_file_save_unconfirmed", "The .sciplot file may have been installed. Inspect that exact file before retrying.",
                                  action="project.open", project_file=str(out), project_id=exc.receipt.project_id,
                                  generation=exc.receipt.generation, sha256=exc.receipt.sha256) from exc
            return {**_result("exported", target, out, head, single_file=True), "bundle_format": "single_file", "whole_project": True,
                    "project_file": str(out), "sha256": file.sha256}
        bundle = store.export_bundle(out)
    return _result("exported", root, bundle, head)


def import_project_bundle(bundle: Path, destination: Path) -> dict[str, Any]:
    """Rebind the same authoritative bundle in a new local directory without running it."""
    source = canonical_path(bundle)
    if source.suffix == ".sciplot" and source.is_file():
        raise EngineError("project_bundle_required", "Open the .sciplot file directly; bundle-import is for bundle directories.",
                          action="project.open", arguments=_open_arguments(source))
    if not canonical_path(source / "bundle.json").is_file() or not canonical_path(source / "store").is_dir():
        raise EngineError("project_bundle_required", "Choose an exact Store bundle directory produced by project bundle-export.")
    out = _new_destination(destination, source)
    # The existing importer validates original generation/command bytes and
    # installs only its confined local resource roots. Executor host grants live
    # outside the Store and aren't read or installed by this use case.
    store = FileProjectStore.import_bundle(source, out)
    head = store.snapshot()
    if head["projection_status"] != "current":
        raise ProjectConflict("The installed relocation is not current; preserve its directory and inspect it.")
    return _result("imported", store.root, source, head, next_step=_import_step(store, head))
