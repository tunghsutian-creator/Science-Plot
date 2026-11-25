"""Fork one exact current Managed member into an independent writable Store."""

from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, Any

from sciplot_core.foundation.project_session_lease import external_project_session
from sciplot_core.foundation.source_locations import selected_source_resolver
from sciplot_core.plot_document import seal_document
from sciplot_core.plot_engine.content_store import capture_document_content
from sciplot_core.plot_engine.current import require_current
from sciplot_core.plot_engine.managed_state import source_input_path
from sciplot_core.project_commands import PreparedMutation, PreparedSource, ProjectCommand, ProjectCommands
from sciplot_core.project_store.io import STORE
from sciplot_core.project_store.repository import FileProjectStore
from sciplot_core.project_store.save_as_sources import SAVE_AS_ADAPTER, bind_staged_source_copies

from .attachment_import import entry_for
from .attachment_index import Attachment, INDEX, OWNER, attachment_id, encode, owner_marker, read_index, register_entry
from .attachment_sources import capture_source
from .attached_repository import AttachedProjectRepository
from .context import active, commit, load_head, project_query, publish_content, repository_scope
from .contracts import RevisionToken
from .errors import EngineError
from .managed_creation import bind_managed_member
from .managed_store_target import MANAGED_STORE_CLAIM, open_claimed_store
from .paths import canonical_path
from .repository import digest

if TYPE_CHECKING:
    from .application import ProjectApplication


@dataclass(frozen=True)
class _RawCopy:
    literal: str
    sha256: str
    aliases: tuple[str, ...]
    data: bytes


@dataclass(frozen=True)
class _Captured:
    revision: RevisionToken
    document: dict[str, Any]
    ir_hash: str
    project_id: str | None
    content: dict[str, bytes]
    raw: tuple[_RawCopy, ...]


def _head(owner: "ProjectApplication", plot: Path, plot_id: str, revision: int) -> dict[str, Any]:
    if not owner.repository.has_head(plot):
        raise EngineError("save_as_managed_required",
                          "Choose the exact Managed plot handle from plot describe. For a plain legacy VSZ, explicitly convert a supported copy.")
    head = load_head(plot)
    document = head["document"]
    if document.get("plot_type") != "ManagedPlot":
        raise EngineError("save_as_managed_required", "Save As requires a Managed document, not a legacy VSZ shadow.")
    if (document["plot_id"], document["revision"]) != (plot_id, revision):
        raise EngineError("save_as_stale_revision", "Use the exact current plot ID and revision; the original is unchanged.")
    pending = active(plot)
    if pending and pending["phase"] not in {"complete", "rejected"}:
        raise EngineError("save_as_pending", "Finish or reject the selected plot's pending operation before Save As.")
    if (document["scientific"]["provenance"]["managed"].get("executors")
            or any(item["executor"].get("kind") != "builtin" for item in document["scientific"]["transforms"])):
        raise EngineError("save_as_external_executor",
                          "This revision declares an external executor. Save As does not transfer that executor or its host permissions.")
    require_current(owner.backend, head["binding"])
    return head


def _capture(owner: "ProjectApplication", plot: Path, destination: Path, plot_id: str, revision: int) -> _Captured:
    with repository_scope(owner.repository, capabilities=owner.capabilities):
        with project_query(plot):
            head = _head(owner, plot, plot_id, revision)
            document, binding = head["document"], head["binding"]
            token = RevisionToken.of(document)
            resolver = selected_source_resolver()
            from sciplot_core.project_store.source_resolver import ProjectSourceResolver

            project = resolver.store if isinstance(resolver, ProjectSourceResolver) else None
            project_id = resolver.snapshot["project_id"] if isinstance(resolver, ProjectSourceResolver) else None
            protected = [plot, canonical_path(Path(binding["output"]))]
            if project is not None:
                protected.extend((project.root, *project.locations.values()))
            literals: dict[str, tuple[str, set[str]]] = {}
            for source in document["scientific"]["data_sources"]:
                literal, version = source["path"], source["sha256"]
                prior, aliases = literals.setdefault(literal, (version, set()))
                if prior != version:
                    raise EngineError("save_as_conflicting_source_versions", "One source locator has competing selected versions.")
                aliases.add(source["source_id"])
                protected.append(canonical_path(Path(literal)))
            if not literals:
                raise EngineError("save_as_source_missing", "The selected revision has no original source identities to copy.")
            if any(destination == path or destination.is_relative_to(path) or path.is_relative_to(destination)
                   for path in protected):
                raise EngineError("save_as_output_overlap", "Select a new location outside the original project, its sources and its outputs.")
            raw = []
            for literal, (version, aliases) in sorted(literals.items()):
                actual = source_input_path(document, literal, version)
                data, _ = capture_source(actual)
                if hashlib.sha256(data).hexdigest() != version:
                    raise EngineError("save_as_source_changed", "The selected original source changed during its sealed copy.",
                                      source=literal)
                raw.append(_RawCopy(literal, version, tuple(sorted(aliases)), data))
            content = capture_document_content(plot, document)
        # Do not hold or mutate an original writer lock. A fresh observation
        # linearizes the exact copy before it becomes independent of the origin.
        with project_query(plot):
            current = _head(owner, plot, plot_id, revision)
            if RevisionToken.of(current["document"]) != token or current["binding"]["ir_hash"] != binding["ir_hash"]:
                raise EngineError("save_as_stale_revision", "The original changed during Save As; no new version was selected.")
        return _Captured(token, document, binding["ir_hash"], project_id, content, tuple(raw))


def _attachment(store: FileProjectStore, project_id: str, key: str) -> Attachment:
    identity = attachment_id(project_id, key)
    root = store.root / ".sciplot_semantic" / identity
    output = store.root / STORE / "semantic-derived" / identity / "output"
    plot_id = "plot:" + digest([project_id, key])[:24]
    return Attachment(store, entry_for(store, key=key, figure_id=plot_id, origin=root,
                                       plot_id=plot_id, managed_output=str(output)))


def _prepare(store: FileProjectStore, owner: "ProjectApplication", snapshot: dict[str, Any], key: str,
             captured: _Captured) -> PreparedMutation:
    if (set(snapshot["files"]) != {MANAGED_STORE_CLAIM} or snapshot["sources"] or snapshot["commands"]
            or any(path.name not in {MANAGED_STORE_CLAIM, STORE} for path in store.root.iterdir())):
        raise EngineError("save_as_destination_claimed", "Save As cannot add or replace members in an existing project.")
    attachment = _attachment(store, snapshot["project_id"], key)
    if snapshot["project_id"] == captured.project_id or attachment.entry["plot_id"] == captured.revision.plot_id:
        raise EngineError("save_as_identity_conflict", "The new file must receive a different project and plot identity.")
    document = seal_document({**captured.document, "plot_id": attachment.entry["plot_id"], "revision": 0})
    if any(document[name] != captured.document[name] for name in ("scientific", "presentation", "scientific_hash", "presentation_hash")):
        raise EngineError("save_as_science_changed", "Save As cannot reinterpret the saved scientific or presentation domains.")

    sources = tuple(PreparedSource(digest([snapshot["project_id"], "source", item.literal])[:32],
                                   item.literal, item.sha256, item.data, item.aliases, 0o600)
                    for item in captured.raw)
    # These private source views are only for the first binding admission.
    # Normal later operations resolve the new Store's own sealed source versions.
    with TemporaryDirectory(prefix=".save-as-sources-", dir=store.root / STORE) as temporary:
        pending = []
        for index, source in enumerate(sources):
            path = Path(temporary) / (str(index) + Path(source.locator).suffix)
            with path.open("xb") as stream:
                stream.write(source.data)
            path.chmod(0o400)
            pending.extend({"path": source.locator, "sha256": source.version, "source_id": alias, "actual": str(path)}
                           for alias in source.aliases)
        repository = AttachedProjectRepository(attachment, new_sources=tuple(pending))
        output = attachment.output
        assert output is not None
        with repository.backend_scope(), repository.prepare_new_member(snapshot) as writes, repository_scope(
                repository, capabilities=owner.capabilities):
            for name, data in captured.content.items():
                path = attachment.root / "content" / name
                publish_content(path, data, lambda: None)  # Fresh, validated CAS bytes; never recanonicalize.
            same_science, prepared = bind_managed_member(attachment.root, document, output, already_resolved=True)
            if same_science != document or prepared.binding["ir_hash"] != captured.ir_hash:
                raise EngineError("save_as_render_identity_changed",
                                  "The current runtime does not reproduce the exact saved PlotIR; no replacement figure was committed.")
            commit(attachment.root, document, prepared.binding, SAVE_AS_ADAPTER)

    index = read_index(store, snapshot)
    register_entry(index, attachment)
    writes[INDEX] = encode(index)
    writes[attachment.logical(attachment.root / OWNER)] = owner_marker(attachment, snapshot["project_id"])
    result = {"kind": "sciplot_managed_save_as", "version": 1, "status": "complete",
              "project": str(store.root), "project_id": snapshot["project_id"],
              "plot": str(attachment.root), "plot_id": document["plot_id"], "created_revision": 0,
              "scientific_hash": document["scientific_hash"], "presentation_hash": document["presentation_hash"],
              "ir_hash": captured.ir_hash, "forked_from": {**captured.revision.to_payload(), "project_id": captured.project_id},
              "copy_scope": "selected_current_member_and_bound_sources", "history_copied": False,
              "export_performed": False, "ready_to_use": False,
              "next_step": {"action": "plot.describe", "plot": str(attachment.root), "description": {"scope": "summary"}}}
    return PreparedMutation.from_values(writes, result, prepared_sources=sources)


def _resume(store: FileProjectStore, app: ProjectCommands, prior: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    command = ProjectCommand.from_payload(prior["metadata"])
    if prior["metadata"]["request"].get("save_as") != context:
        raise EngineError("save_as_claim_changed", "This destination no longer owns the exact requested Save As.")
    if prior["phase"] == "complete":
        return dict(prior["result"])
    if prior["phase"] not in {"needs_review", "accepted"}:
        raise EngineError("save_as_incomplete", "This Save As is not yet staged; resume using its exact original revision.")
    bind_staged_source_copies(store, command)
    result = (app.decide(command, decision_id=prior["decision_id"], accept=True) if prior["phase"] == "needs_review"
              else app.resume(command))
    if result["phase"] != "complete":
        raise EngineError("save_as_incomplete", "The exact Store publication is still pending. Retry this same destination.")
    return dict(result["result"])


def save_managed_as(plot: Path, destination: Path, *, plot_id: str, revision: int) -> dict[str, Any]:
    """The destination doubles as the retry key, never as an overwrite option."""
    if (not isinstance(plot_id, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", plot_id) is None
            or type(revision) is not int or revision < 0):
        raise EngineError("save_as_revision_required", "Supply the exact plot ID and nonnegative current revision from plot describe.")
    source = canonical_path(plot)
    root = canonical_path(destination)
    protected = [source, *(parent for parent in source.parents if (parent / STORE / "head.json").is_file())]
    if any(root == path or root.is_relative_to(path) or path.is_relative_to(root) for path in protected):
        raise EngineError("save_as_output_overlap", "Save As must not write in or above the original project.")
    context = {"source_plot": str(source), "plot_id": plot_id, "revision": revision, "destination": str(root)}
    claim = {"kind": "sciplot_managed_save_as_claim", "version": 1, "request_sha256": digest(context)}
    key = "save-as:" + digest(context)
    from sciplot_core.plot_engine.service import PlotService

    owner = PlotService(read_only_legacy=True)
    try:
        captured = _capture(owner, source, root, plot_id, revision) if not root.exists() else None
        store = open_claimed_store(root, claim)
        app = ProjectCommands(store)
        with external_project_session(root):
            prior = app.query(key)
            if prior is not None and prior["phase"] != "reserved":
                return _resume(store, app, prior, context)
            if captured is None:
                captured = _capture(owner, source, root, plot_id, revision)
            snapshot = store.snapshot()
            prepared = _prepare(store, owner, snapshot, key, captured)
            command = ProjectCommand.create("semantic_record", key, project_id=snapshot["project_id"],
                expected_generation=snapshot["generation"], read_set={name: None for name in prepared.writes},
                write_set=sorted(prepared.writes), request={"prepared_digest": prepared.prepared_digest,
                    "adapter": SAVE_AS_ADAPTER, "save_as": context})
            staged = app.stage_prepared(command, prepared)
            return _resume(store, app, staged, context)
    finally:
        owner.close()
