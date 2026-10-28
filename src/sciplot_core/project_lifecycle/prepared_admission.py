"""Prepared resource witnesses admit only generation-owned attachment evolution."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sciplot_core.project_commands import MembershipRead, ProjectCommand, SourceTreeRead
from sciplot_core.project_host_factory import project_store
from sciplot_core.project_store import FileProjectStore
from sciplot_core.project_store import commands, preconditions, state
from sciplot_core.project_store.command_records import read_commands
from sciplot_core.project_store.io import StoreIO
from sciplot_core.project_store.source_tree_io import observe
from sciplot_core.project_store.runtime import selected_project_store
from sciplot_core.project_lifecycle.attachment_index import INDEX, validate_index
from .errors import EngineError


@dataclass(frozen=True)
class PreparedReads:
    files: tuple[tuple[str, str], ...]
    memberships: tuple[MembershipRead, ...]
    source: SourceTreeRead
    source_origin: dict[str, Any]


@dataclass(frozen=True)
class _Selection:
    store: FileProjectStore
    checkpoint: dict[str, Any]
    source: SourceTreeRead
    source_origin: dict[str, Any]


_SELECTED: ContextVar[_Selection | None] = ContextVar('sciplot_prepared_adoption', default=None)


@contextmanager
def publication_scope(store: FileProjectStore, checkpoint: dict[str, Any], source: SourceTreeRead) -> Iterator[None]:
    """Carry the prepared intent into every semantic publication, not a writer lease."""
    version, origin = observe(source.locator)
    if version != source.tree_sha256:
        raise EngineError('source_changed', 'The original source changed before prepared adoption.')
    token = _SELECTED.set(_Selection(store, deepcopy(checkpoint), source, origin))
    try:
        yield
    finally:
        _SELECTED.reset(token)


def prepared_batch(store: FileProjectStore) -> tuple[dict[str, Any], PreparedReads] | None:
    selected = _SELECTED.get()
    if selected is None:
        return None
    if store.root != selected.store.root:
        raise EngineError('prepared_project_changed', 'Prepared adoption cannot publish another project.')
    current = require(store, selected.checkpoint)
    version, origin = observe(selected.source.locator)
    if version != selected.source.tree_sha256 or origin != selected.source_origin:
        raise EngineError('source_changed', 'The prepared source changed bytes, members, inode or mode before semantic publication.')
    proof = {**deepcopy(origin), 'actual': selected.source.locator}
    return current, PreparedReads(tuple((name, entry['sha256']) for name, entry in current['files'].items()),
        tuple(MembershipRead.capture(current['files'], prefix)
              for prefix in ('', *('@' + key for key in sorted(store.locations)))), selected.source, proof)


def prepared_store(project: Path, *, create_delivery: bool = False) -> FileProjectStore | None:
    if not (project / '.sciplot_store/head.json').is_file():
        return None
    if create_delivery:
        return project_store(project, create_delivery=True)
    selected = selected_project_store()
    return selected if selected is not None and selected.root == project else project_store(project)


def _physical(store: FileProjectStore, io: StoreIO, current: dict[str, Any]) -> None:
    """Use the same exact bytes/modes, root and whole-membership admission owner."""
    if any(record['command_id'] not in current['commands'] and record['phase'] != 'rejected'
           for record in read_commands(io, expected=current['commands'])):
        raise EngineError('prepared_project_changed',
            'The prepared project has an unresolved command; preserve and explicitly finish or inspect that command before adoption.')
    command = ProjectCommand.create('figure_set', 'prepared-checkpoint-read', project_id=current['project_id'],
        expected_generation=current['generation'],
        read_set={name: entry['sha256'] for name, entry in current['files'].items()}, write_set=[], request={},
        read_memberships=[MembershipRead.capture(current['files'], prefix)
                          for prefix in ('', *('@' + key for key in sorted(store.locations)))])
    record = {'command_id': command.key, 'command_digest': command.command_digest,
              'metadata': command.to_payload(), 'expected_generation': current['generation'],
              'read_set': dict(command.read_set), 'write_set': [], 'projected_reads': []}
    preconditions.require_reads(io, current, record)


def capture(store: FileProjectStore) -> tuple[dict[str, str], dict[str, str]]:
    with store._checked_locked() as (io, current, _checked):
        _physical(store, io, current)
        return ({name: entry['sha256'] for name, entry in current['files'].items()},
                {'project_id': current['project_id'], 'generation': current['generation']})


def require(store: FileProjectStore, checkpoint: dict[str, Any]) -> dict[str, Any]:
    binding = checkpoint.get('store_binding')
    if not isinstance(binding, dict) or set(binding) != {'project_id', 'generation'}:
        raise EngineError('prepared_checkpoint_migration_required',
            'This legacy checkpoint does not bind its registered preparation generation; preserve it and obtain an explicit current preparation.')
    with store._checked_locked() as (io, current, checked):
        baseline = state.reachable(io, current, binding['generation'], checked=checked)
        if (binding['project_id'] != current['project_id'] or baseline['project_id'] != current['project_id']
                or checkpoint['files'] != {name: entry['sha256'] for name, entry in baseline['files'].items()}):
            raise EngineError('prepared_project_changed', 'The checkpoint does not identify its exact prepared generation.')
        before_index = (validate_index(json.loads(io.get(baseline['files'][INDEX])), current['project_id'])
                        if INDEX in baseline['files'] else {'attachments': {}})
        after_index = (validate_index(json.loads(io.get(current['files'][INDEX])), current['project_id'])
                       if INDEX in current['files'] else {'attachments': {}})
        if any(after_index['attachments'].get(key) != value for key, value in before_index['attachments'].items()):
            raise EngineError('prepared_project_changed', 'A prepared semantic attachment was removed or redirected.')
        allowed: set[str] = set()
        for key in set(current['commands']) - set(baseline['commands']):
            outcome = current['commands'][key]
            if not outcome['write_set']:
                continue
            record = state.command(io, key)
            assert record is not None
            commands.public(io, record, checked=checked)
            metadata = record['metadata']
            request = metadata.get('request')
            identity = request.get('attachment_id') if isinstance(request, dict) else None
            attachment = after_index['attachments'].get(identity) if isinstance(identity, str) else None
            if (metadata.get('kind') not in {'semantic_record', 'attachment_import'} or attachment is None
                    or any(name != INDEX and not name.startswith(attachment['namespace'] + '/')
                           for name in record['write_set'])):
                raise EngineError('prepared_project_changed', 'Unrelated publication changed the prepared project before template adoption.')
            allowed.update(record['write_set'])
        for name, entry in baseline['files'].items():
            if name in allowed:
                continue
            if current['files'].get(name) != entry:
                raise EngineError('prepared_project_changed', 'A prepared native, source, specification or artifact changed.')
        if (set(current['files']) - set(baseline['files'])) - allowed:
            raise EngineError('prepared_project_changed', 'The generation added resources outside its admitted semantic attachments.')
        _physical(store, io, current)
        return deepcopy(current)
