"""NativeSuite adapters for the single project command and generation owner.

Only candidate files enter this boundary. Old preview/operation/checkpoint files
are imported history; no adapter writes them as another active transaction log.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
import json
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.project_commands import ProjectCommand, ProjectCommands, ProjectMutation, ProjectionRead, MembershipRead, PreparedFile
from sciplot_core.project_commands.read_projections import projection_digest
from sciplot_core.project_store import FileProjectStore


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n").encode()


def open_store(workspace: Path, delivery: Path) -> FileProjectStore:
    from sciplot_core.workflow.native_suite_runtime import current_store
    active = current_store()
    store = active if active is not None and active.root == workspace else FileProjectStore(workspace, locations={"delivery": delivery})
    if (workspace / ".sciplot_store/head.json").is_file():
        store.recover()
    store.snapshot(import_legacy=True)
    return store


def source_versions(store: FileProjectStore, sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    current = store.snapshot()
    result = []
    for item in sources:
        identities = [identity for identity, versions in current["sources"].items()
                      if versions.get(item["sha256"], {}).get("locator") == item["path"]]
        if len(identities) > 1 and not item.get("source_id"):
            raise ValueError("An original source must resolve to one exact stable identity.")
        identity = item.get("source_id") or (identities[0] if identities else
                   uuid5(NAMESPACE_URL, current["project_id"] + ":" + item["path"]).hex)
        result.append({"source_id": identity, "path": item["path"], "version": item["sha256"]})
    return result


def saved_command(app: ProjectCommands, key: str, request: dict[str, Any]) -> ProjectCommand | None:
    record = app.query(key)
    if record is None:
        return None
    command = ProjectCommand.from_payload(record["metadata"])
    if command.to_payload()["request"] != request:
        from sciplot_core.plot_engine.errors import EngineError
        raise EngineError("document_idempotency_conflict", "This key belongs to a different immutable request.")
    return command


def command_for(store: FileProjectStore, kind: str, key: str, *, request: dict[str, Any],
                reads: Iterable[Path], writes: Iterable[Path], figure_id: str | None = None,
                expected_revision: int | None = None, whole: bool = False,
                figure_ids: tuple[str, ...] | None = None, generation: str | None = None) -> ProjectCommand:
    with store._locked() as (io, head):
        from sciplot_core.project_store.state import reachable
        current = reachable(io, head, generation) if generation is not None else head
    read_set = {}
    write_set = [store.logical_path(path) for path in writes]
    selectors = figure_ids or ((figure_id,) if figure_id else ())
    manifest_names = {"suite.json", "@delivery/data/delivery_manifest.json"} if selectors else set()
    for path in [*reads, *writes]:
        logical = store.logical_path(path)
        if logical not in manifest_names:
            read_set[logical] = current["files"].get(logical, {}).get("sha256")
    selected = [ProjectionRead(name, "native_suite_figure_v1", identifier,
                projection_digest(store.read_bytes(name, generation=current["generation"]), kind="native_suite_figure_v1", key=identifier))
                for name in sorted(manifest_names) for identifier in selectors]
    return ProjectCommand.create(kind, key, project_id=current["project_id"],
        expected_generation=current["generation"], read_set=read_set, write_set=write_set,
        projected_reads=selected, projected_writes=[item for item in selected if item.resource in write_set],
        expected_revision=expected_revision, request=request,
        read_memberships=[MembershipRead.capture(current["files"], prefix) for prefix in ("", "@delivery")] if whole else ())


def mutation(store: FileProjectStore, updates: Mapping[Path, bytes | Path | PreparedFile | None], result: dict[str, Any], *,
             sources: list[dict[str, Any]], review: dict[str, Any] | None = None,
             artifacts: Mapping[str, bytes | Path | PreparedFile] | None = None) -> ProjectMutation:
    current = store.snapshot()
    writes = {}
    for path, value in updates.items():
        logical = store.logical_path(path)
        writes[logical] = (PreparedFile(value, current["files"].get(logical, {}).get("mode", 0o600))
                           if isinstance(value, bytes) else value)
    return ProjectMutation(writes, result,
        sources=source_versions(store, sources), review=review, artifacts=artifacts or {})


def command_key(adapter: str, request: Any) -> str:
    return adapter + ":" + canonical_json_sha256(request)


def suite_paths(workspace: Path, manifest: dict[str, Any], identifiers: tuple[str, ...] | None = None,
                *, native_writes: bool = False) -> tuple[list[Path], list[Path]]:
    from sciplot_core.workflow.rheology_tts_saved_state import _active_receipts, _figure_folder, _selected_documents
    from sciplot_core.workflow.native_suite_runtime import delivery_path, native_path
    from sciplot_core.project_store.runtime import resolve_runtime_path
    delivery = delivery_path(manifest)
    manifests = [workspace / "suite.json", delivery / "data/delivery_manifest.json"]
    reads, writes = list(manifests), list(manifests)
    selected = _selected_documents(manifest, identifiers)
    receipts = {item["id"]: item for item in _active_receipts(manifest)}
    for document in selected:
        native = native_path(manifest, document)
        reads.extend([native, resolve_runtime_path(receipts[document["id"]]["spec_path"], expected_sha256=receipts[document["id"]]["spec_sha256"])])
        writes.extend([*(delivery / Path(name).relative_to(Path(manifest["delivery"])) for name in document["exports"]),
                       _figure_folder(delivery, document["id"]) / f"{document['id']}.native-audit.json"])
        if native_writes:
            writes.append(native)
    return reads, writes


def verified_bytes(store: FileProjectStore, paths: Iterable[Path]) -> None:
    # Hash-verify projections immediately before passing any active path to a
    # read-only native inspection/export adapter. Native edits use new paths.
    for path in paths:
        name = store.logical_path(path)
        if store.projection_path(name) != path or file_sha256(path) != canonical_sha(store.read_bytes(name)):
            raise ValueError("Native input differs from its pinned generation.")


def canonical_sha(data: bytes) -> str:
    import hashlib
    return hashlib.sha256(data).hexdigest()


def adopt_saved_native(store: FileProjectStore, manifest: dict[str, Any],
                       identifiers: tuple[str, ...] | None = None) -> None:
    """Explicitly audit and import exact user-saved VSZ before native operations.

    The narrow typed admission permits only this observed VSZ's outside bytes.
    Original spec/source/other resources still require their ordinary guards.
    """
    from sciplot_core.project_commands import NativeAdoption
    from sciplot_core.rheology_tts_render import audit_tts_document
    from sciplot_core.workflow.rheology_tts_saved_state import _check_sources, _compiled_figures, _selected_documents

    current = store.snapshot()
    documents = _selected_documents(manifest, identifiers)
    figures = _compiled_figures(manifest, figure_ids=identifiers)
    app = ProjectCommands(store)
    for document in documents:
        from sciplot_core.workflow.native_suite_runtime import native_path
        path = native_path(manifest, document)
        logical = store.logical_path(path)
        before = current['files'].get(logical, {}).get('sha256')
        observed = file_sha256(path)
        if before == observed:
            continue
        if before is None:
            raise ValueError('A saved native import must belong to the existing project generation.')
        _check_sources(manifest['sources'])
        audit_request = {'adapter': 'native_saved_audit', 'figure_id': document['id'],
                         'before': before, 'observed': observed}
        audit_key = command_key('native_audit', audit_request)
        audit_command = saved_command(app, audit_key, audit_request)
        if audit_command is None:
            audit_reads, _unused = suite_paths(store.root, manifest, (document['id'],))
            audit_reads = [item for item in audit_reads if item != path]
            audit_command = command_for(store, 'native_export', audit_key, request=audit_request,
                                       reads=audit_reads, writes=[], figure_id=document['id'])
        else:
            app.resume(audit_command)
        def prepare_audit(path: Path = path, observed: str = observed,
                          figure: dict[str, Any] = figures[document['id']]) -> ProjectMutation:
            if file_sha256(path) != observed:
                raise ValueError('Saved native bytes changed before their admitted audit.')
            audit = audit_tts_document(path, figure)
            if (audit.get('status') != 'passed' or audit.get('document_sha256') != observed
                    or Path(audit.get('document', '')) != path or file_sha256(path) != observed):
                raise ValueError('Explicit native adoption requires exact domain-audited saved bytes.')
            return mutation(store, {}, {'audit': audit}, sources=manifest['sources'],
                            artifacts={'native-audit.json': json_bytes(audit)})
        audited = app.execute(audit_command, prepare_audit)
        audit = audited['result']['audit']
        audit_sha = canonical_json_sha256(audit)
        request = {'adapter': 'native_saved_import', 'figure_id': document['id'],
                   'before': before, 'observed': observed, 'audit': audit_sha}
        key = command_key('native_import', request)
        command = saved_command(app, key, request)
        if command is not None:
            app.resume(command)
        if command is None:
            reads, _writes = suite_paths(store.root, manifest, (document['id'],))
            base = command_for(store, 'native_export', key, request=request, reads=reads,
                               writes=[path], figure_id=document['id'])
            command = ProjectCommand.create('native_import', key, project_id=base.project_id,
                expected_generation=base.expected_generation, read_set=dict(base.read_set), write_set=base.write_set,
                projected_reads=base.projected_reads, request=request,
                native_adoptions=[NativeAdoption(logical, before, observed, audit_sha)])
        candidate = mutation(store, {path: candidate_file(path, observed)},
            {'status': 'native_imported', 'native_sha256': observed, 'audit_artifact': 'native-audit.json'},
            sources=manifest['sources'], artifacts={'native-audit.json': json_bytes(audit)})
        def frozen_candidate(value: ProjectMutation = candidate) -> ProjectMutation:
            return value
        app.execute(command, frozen_candidate)
        current = store.snapshot()



def candidate_file(path: Path, expected_sha256: str, *, unaliased: bool = True) -> PreparedFile:
    """Capture audited bytes and ordinary mode from one stable descriptor."""
    import os
    import stat
    from sciplot_core.studio_core.source_update_commit import reject_symlink_path
    reject_symlink_path(path)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or unaliased and info.st_nlink != 1
                or info.st_mode & 0o7000):
            raise ValueError('A candidate must have ordinary mode and its declared alias policy.')
        data = stream.read()
        after = os.fstat(stream.fileno())
        fields = ('st_dev', 'st_ino', 'st_mode', 'st_nlink', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
        if any(getattr(info, field) != getattr(after, field) for field in fields):
            raise ValueError('Candidate bytes or mode changed while being captured.')
    if canonical_sha(data) != expected_sha256:
        raise ValueError('Candidate changed after its native/scientific audit; no active output published.')
    return PreparedFile(data, info.st_mode & 0o777)


def candidate_bytes(path: Path, expected_sha256: str) -> bytes:
    return candidate_file(path, expected_sha256).data
