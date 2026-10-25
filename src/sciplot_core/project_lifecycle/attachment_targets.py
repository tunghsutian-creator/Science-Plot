"""Closed project/index resolution for explicitly attached semantic aggregates."""
from pathlib import Path
from typing import Any

from sciplot_core.project_store.io import STORE
from sciplot_core.project_store.repository import FileProjectStore
from sciplot_core.project_store.errors import ProjectRecoveryRequired
from .attachment_import import attach_existing, entry_for
from .attachment_index import Attachment, attachment_id, owned_marker, read_index
from .repository import FileProjectRepository, digest, document_root
from .repository_router import ComposedProjectRepository
from .targets import ImportTarget, ManagedCreationLocation, OpenTarget, StoredTarget
from .errors import EngineError


def _store(repository: ComposedProjectRepository, target: Path | None = None) -> FileProjectStore | None:
    selected = repository.selected_store()
    if selected is not None:
        return selected
    if target is not None and (target / STORE / "head.json").is_file():
        return FileProjectStore(target)
    return None


def resolve_attached_open(repository: ComposedProjectRepository, target: Path, figure_id: str | None,
                          resolve_figure: Any) -> OpenTarget | None:
    store = _store(repository, target)
    marker = owned_marker(target)
    if marker is not None:
        owner = marker[1]
        if store is None:
            project = Path(owner["project"])
            if (project / STORE / "head.json").is_file():
                store = FileProjectStore(project)
        try:
            selected = repository._discover(target)
        except (EngineError, ProjectRecoveryRequired) as exc:
            if isinstance(exc, EngineError) and exc.reason_code != "semantic_attachment_import_pending":
                raise
            if (store is None or marker[0] != Path(owner["origin_root"])
                    or figure_id not in {None, owner.get("figure_id")}):
                raise EngineError("semantic_attachment_owner_conflict", "The pending transfer requires its exact original namespace and figure.") from exc
            selected = repository.select(attach_existing(store, marker[0], figure_id=owner["figure_id"]))
        if selected is not None:
            return StoredTarget(selected.attachment.root)
    if store is None:
        return None
    try:
        index = read_index(store)
    except ProjectRecoveryRequired:
        # An explicit selected project may finish only already accepted physical
        # projection; recover never runs/accepts a semantic or native callback.
        store.recover()
        index = read_index(store)
    for entry in index["attachments"].values():
        attachment = Attachment(store, entry)
        if attachment.relative(target) is not None:
            return StoredTarget(repository.select(attachment).attachment.root)
    matches = [item for item in index["attachments"].values()
               if figure_id is not None and figure_id in {item["figure_id"], item["plot_id"]}]
    if figure_id is None and target == store.root and len(index["attachments"]) == 1:
        matches = list(index["attachments"].values())
    if len(matches) == 1:
        selected = repository.select(Attachment(store, matches[0]))
        return StoredTarget(selected.attachment.root)
    if len(matches) > 1 or target == store.root and figure_id is None and len(index["attachments"]) > 1:
        raise EngineError("semantic_attachment_ambiguous", "Choose one exact attached figure or plot ID.",
                          figures=[item["figure_id"] for item in index["attachments"].values()])
    if FileProjectRepository.has_head(repository, target) and target != store.root:
        # The human/host supplied this one exact old namespace; never enumerate
        # its source parent's other .sciplot_documents records.
        raw = FileProjectRepository._head_envelope(repository, target)
        attachment = attach_existing(store, target, figure_id=figure_id or raw["document"]["plot_id"])
        repository.select(attachment)
        return StoredTarget(attachment.root)
    resolve = resolve_figure
    if resolve is None:
        from sciplot_core.studio_core.project_query import resolve_project_figure

        resolve = resolve_project_figure
    selection = resolve(target, figure_id)
    project, selected_id = Path(selection["project"]), selection["figure_id"]
    if project != store.root:
        raise EngineError("semantic_attachment_project_conflict", "The selected figure is outside the explicitly attached project.")
    original = Path(store.snapshot()["locators"][""])
    old = document_root(original, selected_id)
    local = FileProjectRepository()
    if local.has_head(old):
        attachment = attach_existing(store, old, figure_id=selected_id)
        repository.select(attachment)
        return StoredTarget(attachment.root)
    snapshot = store.snapshot()
    identity = attachment_id(snapshot["project_id"], "legacy:" + selected_id)
    root = store.root / ".sciplot_semantic" / identity
    plot_id = "plot:" + digest([snapshot["project_id"], "legacy", selected_id])[:24]
    entry = entry_for(store, key="legacy:" + selected_id, figure_id=selected_id,
                      origin=root, plot_id=plot_id)
    repository.select(Attachment(store, entry))
    return ImportTarget(root, project, selected_id, plot_id)


def attached_managed_creation(repository: ComposedProjectRepository,
                              request: dict[str, Any]) -> ManagedCreationLocation | None:
    store = _store(repository)
    if store is None:
        return None
    snapshot = store.snapshot()
    key = "managed:" + request["idempotency_key"]
    identity = attachment_id(snapshot["project_id"], key)
    index = read_index(store, snapshot)
    existing = index["attachments"].get(identity)
    if existing is None:
        root = store.root / ".sciplot_semantic" / identity
        output = Path(request["out"]).expanduser().absolute() if "out" in request else store.root / STORE / "semantic-derived" / identity / "output"
        if not output.is_relative_to(store.root):
            raise EngineError("managed_output_conflict", "Attached creation requires a project-owned disposable output location.")
        plot_id = "plot:" + digest([snapshot["project_id"], key])[:24]
        existing = entry_for(store, key=key, figure_id=key, origin=root, plot_id=plot_id, managed_output=str(output))
    attachment = Attachment(store, existing)
    from copy import deepcopy
    repository.select(attachment, new_sources=tuple(deepcopy(request["data_binding"]["data_sources"])) if index["attachments"].get(identity) is None else ())
    output = Path(existing["managed_output"])
    if not output.is_relative_to(store.root):
        from .attachment_projection import metadata_view

        output = Path(metadata_view(str(output), attachment))
    return ManagedCreationLocation(attachment.root, output, existing["plot_id"])
