"""Prepared resource witnesses admit only generation-owned attachment evolution."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sciplot_core.project_commands import MembershipRead, ProjectCommand
from sciplot_core.project_host_factory import project_store
from sciplot_core.project_store import FileProjectStore
from sciplot_core.project_store import commands, preconditions, state
from sciplot_core.project_store.command_records import read_commands
from sciplot_core.project_store.io import StoreIO
from sciplot_core.project_store.runtime import selected_project_store
from sciplot_core.project_lifecycle.attachment_index import INDEX, validate_index
from sciplot_core.task_contract import TaskControlError


def prepared_store(project: Path) -> FileProjectStore | None:
    if not (project / '.sciplot_store/head.json').is_file():
        return None
    selected = selected_project_store()
    return selected if selected is not None and selected.root == project else project_store(project)


def _physical(store: FileProjectStore, io: StoreIO, current: dict[str, Any]) -> None:
    """Use the same exact bytes/modes, root and whole-membership admission owner."""
    if any(record['command_id'] not in current['commands'] and record['phase'] != 'rejected'
           for record in read_commands(io, expected=current['commands'])):
        raise TaskControlError('prepared_project_changed',
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


def require(store: FileProjectStore, checkpoint: dict[str, Any]) -> None:
    binding = checkpoint.get('store_binding')
    if not isinstance(binding, dict) or set(binding) != {'project_id', 'generation'}:
        raise TaskControlError('prepared_checkpoint_migration_required',
            'This legacy checkpoint does not bind its registered preparation generation; preserve it and obtain an explicit current preparation.')
    with store._checked_locked() as (io, current, checked):
        baseline = state.reachable(io, current, binding['generation'], checked=checked)
        if (binding['project_id'] != current['project_id'] or baseline['project_id'] != current['project_id']
                or checkpoint['files'] != {name: entry['sha256'] for name, entry in baseline['files'].items()}):
            raise TaskControlError('prepared_project_changed', 'The checkpoint does not identify its exact prepared generation.')
        before_index = (validate_index(json.loads(io.get(baseline['files'][INDEX])), current['project_id'])
                        if INDEX in baseline['files'] else {'attachments': {}})
        after_index = (validate_index(json.loads(io.get(current['files'][INDEX])), current['project_id'])
                       if INDEX in current['files'] else {'attachments': {}})
        if any(after_index['attachments'].get(key) != value for key, value in before_index['attachments'].items()):
            raise TaskControlError('prepared_project_changed', 'A prepared semantic attachment was removed or redirected.')
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
                raise TaskControlError('prepared_project_changed', 'Unrelated publication changed the prepared project before template adoption.')
            allowed.update(record['write_set'])
        for name, entry in baseline['files'].items():
            if name in allowed:
                continue
            if current['files'].get(name) != entry:
                raise TaskControlError('prepared_project_changed', 'A prepared native, source, specification or artifact changed.')
        if (set(current['files']) - set(baseline['files'])) - allowed:
            raise TaskControlError('prepared_project_changed', 'The generation added resources outside its admitted semantic attachments.')
        _physical(store, io, current)

