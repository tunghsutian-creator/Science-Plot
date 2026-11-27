"""Independently save every current figure in an admitted standalone project."""

from collections import defaultdict
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from typing import Any

from sciplot_core.foundation.research_destination import require_data_destination
from sciplot_core.plot_backends.figure_plan import capability_profile
from sciplot_core.plot_engine.content_store import capture_document_content
from sciplot_core.plot_ir.figure_document import is_figure
from sciplot_core.project_commands import PreparedMutation, PreparedSource, ProjectCommand, ProjectCommands
from sciplot_core.project_store.repository import FileProjectStore
from sciplot_core.project_store.save_as_sources import FILE_SAVE_AS_ADAPTER, bind_staged_source_copies

from .attached_repository import AttachedProjectRepository
from .attachment_index import Attachment, INDEX, OWNER, encode, owner_marker, read_index, register_entry
from .context import digest, repository_scope
from .contracts import RevisionToken
from .errors import EngineError
from .head_observation import observe_plot_head
from .project_file import ProjectFileSaveUnconfirmed, ProjectFileSession, _path, create_project_file
from .project_file_summary import project_file_read_session
from .save_as import _Captured, prepare_forked_member

_TERMINAL = {"complete", "rejected"}
_BUILTIN_CACHE = re.compile(r"transform-cache/([a-f0-9]{64})\.(result|started)\.json")
_STORE_STATE = re.compile(
    r"commands/[a-f0-9]{64}\.json|generations/[a-f0-9]{32,64}\.json|objects/[a-f0-9]{2}/[a-f0-9]{64}"
    r"|drafts/[a-f0-9]{64}/[a-f0-9]{64}(?:\.json|/writes/\.sciplot_semantic/.+)"
)
_STORE_DESCRIPTORS = {"head.json", "local_locations.json", "local_resource_roots.json", "local_sources.json", "relocation.json"}
_DERIVED_STATE = re.compile(r"state/(?:ir/[a-f0-9]{64}\.json|export-cache\.json)")
_CURRENT_OUTPUTS = {"build.json", "compile-intent.json", "document.vsz", "preview.png",
                    "exports/document.pdf", "exports/document_300dpi.tiff"}
_HISTORY_FILE = re.compile(r"models/([a-f0-9]{64})\.json|revisions/[0-9]{8}\.json|transactions/[a-f0-9]{64}/transaction\.json")


def _unsupported(detail: str) -> EngineError:
    return EngineError("project_file_save_as_unsupported",
                       "This archive cannot be copied in full; the destination was not saved. " + detail,
                       action="inspect_project_file")


def _copy_sources(session: ProjectFileSession, snapshot: dict[str, Any], project_id: str
                  ) -> tuple[tuple[PreparedSource, ...], dict[tuple[str, str, str], PreparedSource]]:
    sources: list[PreparedSource] = []
    use: dict[tuple[str, str, str], PreparedSource] = {}
    for identity, versions in snapshot["sources"].items():
        source_id = digest([project_id, "saved-source", identity])[:32]
        for version, entry in versions.items():
            locator = entry.get("locator")
            if not locator or entry.get("produced_resource") is not None:
                raise _unsupported("A source has no independent sealed original.")
            aliases = tuple(sorted(set(entry.get("aliases", ())) | {identity}))
            sealed = session.store.resolve_source(identity, version, generation=session.opened_generation).read_bytes()
            source = PreparedSource(source_id, locator, version, sealed, aliases, entry["mode"])
            sources.append(source)
            for alias in aliases:
                selected = (locator, version, alias)
                if selected in use:
                    raise _unsupported("One exact source alias identifies different saved inputs.")
                use[selected] = source
    return tuple(sources), use


def _require_known_members(session: ProjectFileSession, entry: dict[str, Any], members: list[str],
                           content: dict[str, bytes], document: dict[str, Any]) -> None:
    prefix = entry["namespace"] + "/"
    cache: dict[str, dict[str, Any]] = defaultdict(dict)
    for name in members:
        if name in {OWNER, "head.json", "active.json"}:
            continue
        if name.startswith("content/") and name.removeprefix("content/") in content:
            continue
        if match := _BUILTIN_CACHE.fullmatch(name):
            key, phase = match.groups()
            cache[key][phase] = json.loads(session.store.read_bytes(prefix + name, generation=session.opened_generation))
            continue
        if name != "managed-creation.json" and not _HISTORY_FILE.fullmatch(name):
            raise _unsupported(f"The archive contains an unhandled figure asset: {name}.")
        record = json.loads(session.store.read_bytes(prefix + name, generation=session.opened_generation))
        value = record if name.startswith("models/") else record.get("document")
        if (not isinstance(value, dict) or value.get("kind") != "sciplot_document"
                or value.get("plot_id") != document["plot_id"]):
            raise _unsupported("An archived member cannot be identified as this figure's state or history.")
        if name == "managed-creation.json" and record.get("phase") != "committed":
            raise _unsupported("Finish the figure's pending creation before copying.")
        if name.startswith("transactions/") and record.get("phase") not in _TERMINAL:
            raise _unsupported("Finish or reject the figure's pending change before copying.")

    # Only the owner's complete builtin cache is disposable: the independent
    # baseline retains the sealed inputs, nodes and current scientific content.
    for key, checkpoint in cache.items():
        started, result = checkpoint.get("started", {}), checkpoint.get("result", {})
        if (set(started) != {"key", "node", "status"} or started["status"] != "started" or started["key"] != key
                or started["node"] not in document["scientific"]["transforms"]
                or set(result) != {"key", "dataset", "sha256", "status"} or result["status"] != "complete"
                or result["key"] != key or result["sha256"] != digest(result["dataset"])):
            raise _unsupported("A transform cache entry is not a known complete builtin result.")


def _check_archive_inventory(session: ProjectFileSession, snapshot: dict[str, Any],
                             members: list[tuple[dict[str, Any], _Captured]]) -> None:
    """Rule out hidden native runs and assets outside the logical generation."""
    current_ir = {entry["id"]: captured.ir_hash for entry, captured in members}
    views = {f"sources/{identity}/{version}/{Path(row['locator']).name}": version
             for identity, versions in snapshot["sources"].items()
             for version, row in versions.items() if row.get("locator")}
    for name, sha in session.opened_member_hashes().items():
        if name in _STORE_DESCRIPTORS or _STORE_STATE.fullmatch(name) or views.get(name) == sha:
            continue
        if name.startswith("semantic-derived/"):
            identity, _, rest = name.removeprefix("semantic-derived/").partition("/")
            if ir := current_ir.get(identity):
                # These are disposable, regenerable products of the unchanged
                # IR, not registered user assets or old export authorizations.
                prefix = f"output/artifacts/{ir}/"
                outputs = _CURRENT_OUTPUTS | {f"plot-ir-{ir}.json"}
                if _DERIVED_STATE.fullmatch(rest) or (rest.startswith(prefix) and rest.removeprefix(prefix) in outputs):
                    continue
        raise _unsupported("The portable Store contains an unhandled native workspace, run asset or derived file.")


def _read_members(session: ProjectFileSession, snapshot: dict[str, Any], index: dict[str, Any]
                  ) -> list[tuple[dict[str, Any], _Captured]]:
    if (not index["attachments"] or session.store.locations or set(snapshot["locators"]) != {""}
            or any(snapshot.get(key) for key in ("history_resources", "input_resources", "retired_namespace_prefixes"))
            or any(record["phase"] not in _TERMINAL or record.get("artifact_paths") or record.get("native_workspace")
                   for record in session.store.commands())):
        raise _unsupported("Use an archive containing committed, internally owned figures only; finish any pending work first.")
    names: dict[str, list[str]] = defaultdict(list)
    for file in snapshot["files"]:
        if file == INDEX:
            continue
        namespace, sep, name = file.removeprefix(".sciplot_semantic/").partition("/")
        if not file.startswith(".sciplot_semantic/") or not sep or namespace not in index["attachments"]:
            raise _unsupported("The archive contains project-level files or assets without a copy binding.")
        names[namespace].append(name)
    result = []
    for key in ("plot_id", "figure_id"):
        if len({entry[key] for entry in index["attachments"].values()}) != len(index["attachments"]):
            raise _unsupported("The archive does not give each figure an unambiguous identity.")
    for identity, entry in index["attachments"].items():
        if any(entry.get(key) for key in ("archived_derivatives", "archived_artifacts", "legacy_prefix",
                                          "transfer_root", "publication_output", "history_root")):
            raise _unsupported("A figure owns imported or published assets that are not supported by this Save As.")
        owner = AttachedProjectRepository(Attachment(session.store, entry))
        root = owner.attachment.root
        head = observe_plot_head(root, owner=owner)
        assert head is not None
        document = head["document"]
        scientific = document["scientific"]
        if (document.get("plot_type") != "ManagedPlot" or not is_figure(document)
                or document["plot_id"] != entry["plot_id"] or not scientific["data_sources"]
                or scientific["provenance"]["managed"].get("executors")
                or any(item["executor"].get("kind") != "builtin" for item in scientific["transforms"])):
            raise _unsupported("Every figure must be a saved Managed v2 figure with sealed sources and builtin transforms.")
        with repository_scope(owner):
            content = capture_document_content(root, document)
            pending = owner.active(root)
        if pending is not None and pending["phase"] not in _TERMINAL:
            raise _unsupported("Finish or reject the figure's pending change before copying.")
        _require_known_members(session, entry, names[identity], content, document)
        result.append((entry, _Captured(RevisionToken.of(document), document, head["binding"]["ir_hash"],
                                       session.project_id, content, ())))
    return result


def _publish_fork(source: ProjectFileSession, path: Path) -> dict[str, Any]:
    old = source.store.snapshot()
    members = _read_members(source, old, read_index(source.store, old))
    _check_archive_inventory(source, old, members)
    with TemporaryDirectory(prefix="sciplot-file-save-as-") as staging:
        store = FileProjectStore(Path(staging).resolve())
        fresh = store.snapshot(import_legacy=True)
        sources, by_alias = _copy_sources(source, old, fresh["project_id"])
        index = read_index(store, fresh)
        writes: dict[str, bytes | None] = {}
        figures = []
        capabilities = capability_profile()
        for entry, captured in members:
            selected = {}
            for declared in captured.document["scientific"]["data_sources"]:
                item = by_alias.get((declared["path"], declared["sha256"], declared["source_id"]))
                if item is None:
                    raise _unsupported("A current figure refers to a source version that is not sealed in the archive.")
                selected[item.source_id, item.version] = item
            attachment, document, files = prepare_forked_member(
                store, fresh, "copy:" + entry["id"], captured, tuple(selected.values()), capabilities=capabilities,
            )
            register_entry(index, attachment)
            if set(files) & writes.keys():
                raise _unsupported("Two figures would occupy the same saved resource.")
            writes.update(files)
            writes[attachment.logical(attachment.root / OWNER)] = owner_marker(attachment, fresh["project_id"])
            figures.append({
                "original": {"figure_id": entry["figure_id"], "plot_id": entry["plot_id"],
                             "revision": captured.revision.revision},
                "figure_id": attachment.entry["figure_id"], "plot_id": document["plot_id"], "revision": 0,
                "open_arguments": {"target": str(path), "figure_id": document["plot_id"], "description": {"scope": "summary"}},
            })
        writes[INDEX] = encode(index)
        mutation = PreparedMutation.from_values(writes, {"figures": figures}, prepared_sources=sources)
        command = ProjectCommand.create("semantic_record", "project-file-save-as", project_id=fresh["project_id"],
            expected_generation=fresh["generation"], read_set=dict.fromkeys(writes), write_set=sorted(writes),
            request={"adapter": FILE_SAVE_AS_ADAPTER, "prepared_digest": mutation.prepared_digest,
                     "save_as": {"destination": str(store.root)}})
        app = ProjectCommands(store)
        draft = app.stage_prepared(command, mutation)
        bind_staged_source_copies(store, command)
        published = app.decide(command, decision_id=draft["decision_id"], accept=True)
        if published["phase"] != "complete":
            raise EngineError("project_file_save_as_incomplete", "The private copy did not publish a complete generation.")
        try:
            saved = create_project_file(path, store, expected_generation=published["generation"])
        except ProjectFileSaveUnconfirmed as exc:
            saved = exc.receipt
            try:
                with project_file_read_session(path) as observed:
                    confirmed = observed.matches_saved(saved)
            except EngineError:
                confirmed = False
            if not confirmed:
                raise EngineError("project_file_save_as_unconfirmed", "The destination does not confirm this exact Save As.",
                                  action="inspect_project_file", project_file=str(path)) from exc
        except FileExistsError as exc:
            raise EngineError("project_file_destination_exists", "Save As never replaces an existing destination.") from exc
    return {"kind": "sciplot_project_file_save_as", "version": 1, "status": "saved",
            "project_file": str(path), "project_id": saved.project_id, "generation": saved.generation,
            "figures": figures, "history_copied": False}


def save_project_file_as(source: Path, destination: Path, *, expected_project_id: str,
                         expected_generation: str) -> dict[str, Any]:
    """Save all admitted current figures and sealed originals with distinct project ownership."""
    path = _path(destination)
    require_data_destination(path)
    if path.exists() or path.is_symlink():
        raise EngineError("project_file_destination_exists", "Save As never replaces an existing destination.")
    with project_file_read_session(source) as opened:
        if (opened.project_id, opened.opened_generation) != (expected_project_id, expected_generation):
            raise EngineError("project_file_save_as_stale", "Open the original and use its current project ID and generation.")
        return _publish_fork(opened, path)
