"""Read current source evidence without materializing scientific source views."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any
from collections.abc import Callable

from sciplot_core.foundation.canonical_paths import canonical_path
from sciplot_core.project_host_factory import project_store
from sciplot_core.project_store import FileProjectStore, ProjectConflict, ProjectStoreError
from sciplot_core.project_store import directories, locators
from sciplot_core.project_store.io import STORE, StoreIO, directory, parts, read_file, sha
from sciplot_core.project_store.root_bindings import require as require_roots
from sciplot_core.project_store.source_resolver import ProjectSourceResolver
from sciplot_core.project_store.source_inspection import inspect_file
from sciplot_core.project_store.physical_projection import projected_directory
from sciplot_core.project_store.source_tree_io import _files, _stamp
from sciplot_core.data_mapping.execution_inputs import MappingInputReadSet, mapping_input_reads, mapping_input_scope
from sciplot_core.data_mapping.numeric_readset_proof import numeric_input_digest
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.project_manifest_locations import admitted_project_generation



class CurrentMappingObservationUnavailable(ValueError):
    """A stored mapping version has no current physical readonly observation."""


def _require_revision(current: dict[str, Any], entry: dict[str, Any], expected: dict[str, Any] | None) -> None:
    if expected is not None and any(expected.get(key) != value for key, value in {
            'project_id': current['project_id'], 'generation': current['generation'], 'request_sha256': entry['sha256']}.items()):
        raise ProjectConflict('The project status canonical revision changed during this observation.')


def _record(fd: int, components: tuple[str, ...], expected: dict[str, Any], *, audit: bool,
            directory_members: bool = False, allowed: set[str] | None = None,
            expected_modes: dict[str, int] | None = None) -> dict[str, Any]:
    with directory(fd, components[:-1]) as parent:
        info = os.stat(components[-1], dir_fd=parent, follow_symlinks=False)
        if directory_members:
            if not stat.S_ISDIR(info.st_mode):
                raise ProjectConflict('A current source directory cannot become an alias or special member.')
            if expected_modes is not None and stat.S_IMODE(info.st_mode) != expected_modes['']:
                raise ProjectConflict('The selected original directory changed its admitted permissions.')
            result: dict[str, Any] = {'kind': 'directory'}
            if audit:
                with directory(parent, (components[-1],)) as source:
                    rows, observations = _files(source, allowed=allowed or set(expected))
                if expected_modes is not None and (set(observations) != set(expected_modes) - {''}
                        or any(stat.S_IMODE(item['mode']) != expected_modes[name] for name, item in observations.items())):
                    raise ProjectConflict('The complete original directory changed its declared shape or permissions.')
                if {row['path'] for row in rows} != set(expected):
                    raise ProjectConflict('The current source directory lost an admitted member.')
                for name, entry in expected.items():
                    if stat.S_IMODE(observations[name]['mode']) != entry['mode']:
                        raise ProjectConflict('A current source member changed its admitted permissions.')
                digest = hashlib.sha256()
                for row in sorted(rows, key=lambda item: Path(item['path'])):
                    digest.update(row['path'].encode('utf-8'))
                    digest.update(row['content_sha256'].encode('ascii'))
                result.update(member_count=len(rows), size_bytes=sum(observations[row['path']]['_stamp'][4] for row in rows), sha256=digest.hexdigest())
        else:
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                    or stat.S_IMODE(info.st_mode) != expected['mode']):
                raise ProjectConflict('The current source file changed shape or permissions.')
            result = {'kind': 'file'}
            if audit:
                data, _mode = read_file(parent, components[-1], owned=True)
                result.update(size_bytes=len(data), sha256=sha(data))
    # Reopen from the bound root so replacing an ancestor cannot make a
    # previously observed directory descriptor certify another current path.
    with directory(fd, components[:-1]) as parent:
        if _stamp(info) != _stamp(os.stat(components[-1], dir_fd=parent, follow_symlinks=False)):
            raise ProjectConflict('The current source locator changed during its observation.')
    return result


def _selected_input(request: dict[str, Any], current: dict[str, Any], identity: str) -> None:
    configured = request.get('input')
    if not isinstance(configured, str):
        raise ProjectConflict('The current canonical request has no selected original input.')
    selected = Path(configured) if Path(configured).is_absolute() else Path(current['locators']['']) / configured
    if not (Path(identity) == selected or Path(identity).is_relative_to(selected)):
        raise ProjectConflict('The source status locator is not this canonical request input.')


def observe_studio_source_content(path: Path | None, *, project_dir: Path,
                                  request_path: Path, audit_source: bool,
                                  expected_revision: dict[str, Any] | None = None,
                                  mapping_inputs: MappingInputReadSet | None = None) -> dict[str, Any] | None:
    """None explicitly means a legacy project; known-store failures never retry legacy IO."""
    project = canonical_path(project_dir)
    if canonical_path(request_path) != project / 'plot_request.json':
        raise ProjectConflict('Source status requires this project canonical request.')
    if not (project / STORE).exists():
        return None
    if not (project / STORE / 'head.json').is_file():
        raise ProjectConflict('An existing managed project has no admitted current generation.')
    if path is None:
        # Validate before GUI mapping inspection, without selecting external caps
        # or holding a store lease across GUI/service callbacks.
        with admitted_project_generation(project) as (_primary, io, current):
            entry = locators.checked_member(io, current, 'plot_request.json', None)
            _require_revision(current, entry, expected_revision)
            return {'project_id': current['project_id'], 'generation': current['generation'], 'request_sha256': entry['sha256'],
                    'path': None, 'identity_path': None, 'exists': False, 'status': 'not_established'}
    store = project_store(project)
    with store._checked_locked() as (io, current, checked):
        require_roots(io, current)
        request_entry = locators.checked_member(io, current, 'plot_request.json', None)
        _require_revision(current, request_entry, expected_revision)
        request = json.loads(io.get(request_entry))
        supplied = path.expanduser().absolute()
        if request.get('data_mapping_execution'):
            if not audit_source or mapping_inputs is None:
                return {'path': None, 'identity_path': str(supplied), 'exists': False, 'status': 'not_observed',
                        'scope': 'mapping_selected_files',
                        'audit_status': 'not_computed' if not audit_source else 'not_currently_observed'}
            return _mapped_source(store, io, current, request, supplied, mapping_inputs)
        if STORE in supplied.parts or any(part in {'.', '..'} for part in supplied.parts):
            raise ProjectStoreError('Source status cannot observe a source cache or ambiguous locator.')
        logical = locators.logical_for_literal(current, str(supplied))
        if logical is None:
            try:
                local = store.logical_path(supplied)
            except ProjectStoreError:
                local = None
            if local in current['files']:
                logical = local
        if logical is not None:
            components = parts(logical)
            key = components[0][1:] if components[0].startswith('@') else ''
            relative = components[1:] if key else components
            physical = (io.locations[key] if key else io.root).joinpath(*relative)
            identity = locators.original_for_logical(current, logical)
            expected = current['files'][logical]
            _selected_input(request, current, identity)
            with directory(io.root_fds[key], ()) as descriptor:
                record = _record(descriptor, relative, expected, audit=audit_source)
        else:
            selected = directories._prefix(current, supplied, {'': io.root, **io.locations})
            if selected is None:
                _selected_input(request, current, str(supplied))
                return _external(store, io, current, supplied, request, audit_source)
            prefix, identity = selected
            components = tuple(prefix.rstrip('/').split('/')) if prefix else ()
            key = components[0][1:] if components and components[0].startswith('@') else ''
            relative = components[1:] if key else components
            if not relative or io.location_members.get(key) is not None:
                raise ProjectStoreError('Source status needs an admitted whole source directory, never a finite-cap parent.')
            expected = {name[len(prefix):]: entry for name, entry in current['files'].items() if name.startswith(prefix)}
            physical = (io.locations[key] if key else io.root).joinpath(*relative)
            _selected_input(request, current, identity)
            record = _record(io.root_fds[key], relative, expected, audit=audit_source, directory_members=True)
        io.verify_roots()
        return {'path': str(physical), 'identity_path': identity, 'exists': True, 'status': 'present', 'content': record}


def _external(store: FileProjectStore, io: StoreIO, current: dict[str, Any], source: Path,
              request: dict[str, Any], audit: bool) -> dict[str, Any]:
    # Domain-selected exact versions, not arbitrary ledger locators, own external IO.
    from sciplot_core.project_store.runtime import project_runtime
    from sciplot_core.studio_core.project_query_sources import current_source_files

    if not any(entry.get('locator') == str(source) for versions in current['sources'].values() for entry in versions.values()):
        return _external_tree(store, io, current, source, request, audit)
    figures = [{'status': 'ready', 'spec': str(store.root / 'studio/spec.json')}] if 'studio/spec.json' in current['files'] else []
    with project_runtime(store, generation=current['generation']):
        files, identities = current_source_files(store.root, source, figures)
    if str(source) not in files:
        return _external_tree(store, io, current, source, request, audit)
    if str(source) not in identities or len(files) != 1:
        raise ProjectStoreError('External source status requires one exact current source identity/version.')
    identity, version = identities[str(source)], files[str(source)]
    entry = current['sources'][identity][version]
    local = io.read('local_sources.json') or {'versions': {}}
    if local['versions'].get(identity, {}).get(version) == version:
        io.get(entry)
        io.verify_roots()
        return {'path': None, 'identity_path': str(source), 'exists': False, 'status': 'not_observed', 'sealed': True}
    descriptor = os.open(source.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        record = _record(descriptor, source.parts[1:], entry, audit=audit)
    finally:
        os.close(descriptor)
    io.verify_roots()
    return {'path': str(source), 'identity_path': str(source), 'exists': True, 'status': 'present', 'content': record}


def _external_tree(store: FileProjectStore, io: StoreIO, current: dict[str, Any], source: Path,
                   request: dict[str, Any], audit: bool) -> dict[str, Any]:
    from sciplot_core.project_commands import SourceTreeRead
    from sciplot_core.studio_core.project_query_sources import current_tree_record
    from sciplot_core.foundation.json_hashing import canonical_json_sha256

    version = (request.get('resolved_figure_plan') or {}).get('source_sha256')
    if 'source_update.json' in current['files']:
        review = json.loads(io.get(current['files']['source_update.json']))
        if review.get('source') == str(source):
            version = review.get('source_tree_sha256')
    if not isinstance(version, str):
        raise ProjectStoreError('An external source directory requires its complete current tree author.')
    tree = SourceTreeRead(str(source), version)
    record = current_tree_record(store, current, tree)
    proof = record.get('source_tree_origins', {}).get(str(source))
    if not isinstance(proof, dict) or not stat.S_ISDIR(proof['root']['mode']):
        raise ProjectConflict('The current tree author has no complete ordinary directory proof.')
    captured = [entry for versions in record['draft']['sources'].values() for entry in versions.values()]
    expected = {}
    local = io.read('local_sources.json') or {'versions': {}}
    sealed = []
    for name, member in proof['members'].items():
        if not stat.S_ISREG(member['mode']):
            continue
        entries = [entry for entry in captured if entry['locator'] == str(source / name)]
        if (len(entries) != 1 or entries[0]['mode'] != stat.S_IMODE(member['mode'])
                or current['sources'].get(entries[0]['source_id'], {}).get(entries[0]['version']) != entries[0]):
            raise ProjectConflict('The complete source directory lacks one exact captured version per member.')
        expected[name] = entries[0]
        sealed.append(local['versions'].get(entries[0]['source_id'], {}).get(entries[0]['version']) == entries[0]['version'])
    composite = canonical_json_sha256({'kind': 'directory', 'files': [
        {'path': name, 'content_sha256': entry['sha256']} for name, entry in sorted(expected.items())]}, allow_nan=False)
    if composite != version:
        raise ProjectConflict('The complete source directory differs from its current author seal.')
    if sealed and all(sealed):
        io.verify_roots()
        return {'path': None, 'identity_path': str(source), 'exists': False, 'status': 'not_observed', 'sealed': True}
    fd = os.open(source.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        result = _record(fd, source.parts[1:], expected, audit=audit, directory_members=True, allowed=set(proof['members']),
            expected_modes={'': stat.S_IMODE(proof['root']['mode']),
                **{name: stat.S_IMODE(member['mode']) for name, member in proof['members'].items()}})
    finally:
        os.close(fd)
    io.verify_roots()
    return {'path': str(source), 'identity_path': str(source), 'exists': True, 'status': 'present', 'content': result}


class _CurrentMappingResolver(ProjectSourceResolver):
    """Only readonly physical locations can feed current GUI mapping replay."""
    def resolve_path(self, original: str | Path, *, expected_sha256: str | None = None,
                     source_id: str | None = None) -> Path:
        literal = Path(original).expanduser().absolute()
        known = directories._prefix(self.snapshot, literal, {'': self.store.root, **self.store.locations})
        if known is not None and locators.logical_for_literal(self.snapshot, str(literal)) is None:
            return projected_directory(self.store, literal, generation=self.generation)
        fact = inspect_file(self.store, literal, expected_sha256=expected_sha256,
                            source_id=source_id, generation=self.generation)
        if fact.physical is None:
            raise CurrentMappingObservationUnavailable('A sealed mapping version is historical evidence, not current physical input.')
        return fact.physical


def resolve_studio_mapping_application(request: dict[str, Any], *, project_dir: Path,
                                       request_path: Path,
                                       expected_revision: dict[str, Any] | None = None,
                                       on_verified_mapping: Callable[[MappingInputReadSet], None] | None = None) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Revalidate a current mapping without reading the old clone origin or creating views."""
    from sciplot_core.data_mapping import resolve_data_mapping_request
    from sciplot_core.foundation.source_locations import source_location_scope

    project = canonical_path(project_dir)
    if canonical_path(request_path) != project / 'plot_request.json':
        raise ProjectConflict('Mapping status requires this project canonical request.')
    if not (project / STORE).exists():
        return resolve_data_mapping_request(request, base_dir=project)
    store = project_store(project)
    with store._checked_locked() as (io, current, _checked):
        entry = locators.checked_member(io, current, 'plot_request.json', None)
        _require_revision(current, entry, expected_revision)
        if request != json.loads(io.get(entry)):
            raise ProjectConflict('The mapping status request is not this current canonical generation.')
        resolver = _CurrentMappingResolver(store, current['generation'])
        with source_location_scope(resolver), mapping_input_reads(request.get('data_mapping_execution')) as observed:
            result = resolve_data_mapping_request(request, base_dir=project)
            if observed is not None and on_verified_mapping is not None:
                observed.require_current()
                on_verified_mapping(observed)
            return result


def _mapped_source(store: FileProjectStore, io: StoreIO, current: dict[str, Any], request: dict[str, Any],
                   selected: Path, observed: MappingInputReadSet) -> dict[str, Any]:
    """A verified finite source set never grants its namespace directory."""
    from sciplot_core.foundation.source_locations import source_location_scope
    from sciplot_core.data_mapping.execution_inputs import mapping_execution_path

    with source_location_scope(_CurrentMappingResolver(store, current['generation'])):
        if (not isinstance(observed, MappingInputReadSet) or not observed.sealed
                or observed.execution != str(mapping_execution_path(request['data_mapping_execution']))
                or observed.numeric_inputs_sha256 is None or observed.numeric_inputs_sha256 != numeric_input_digest(observed)):
            raise ProjectConflict('Source status lacks this canonical mapping numeric read witness.')
        execution = json.loads(observed.files[observed.execution].data)
        raw = {str(Path(execution['source_root']) / name): version for name, version in execution['source_hashes'].items()}
        if str(selected) not in {*raw, execution['source_root'], str(request['input'])}:
            raise ProjectConflict('Source status cannot widen the confirmed mapping source set.')
        with mapping_input_scope(observed):
            observed.require_current()
            rows = []
            for literal, version in sorted(raw.items()):
                item = observed.files.get(literal)
                owners = [(identity, entry) for identity, versions in current['sources'].items()
                    for digest, entry in versions.items() if digest == version and entry.get('locator') == literal]
                if item is None or item.sha256 != version or len(owners) != 1 or owners[0][1]['mode'] != item.mode:
                    raise ProjectConflict('A confirmed mapping source lacks its exact registered identity and bytes.')
                rows.append({'identity_path': literal, 'path': str(item.actual), 'source_id': owners[0][0],
                             'sha256': version, 'size_bytes': len(item.data)})
    io.verify_roots()
    revision = {key: current[key] for key in ('project_id', 'generation')}
    revision['request_sha256'] = current['files']['plot_request.json']['sha256']
    binding = {'observation_revision': revision, 'mapping_execution': observed.execution,
               'confirmation_id': execution['confirmation_id'], 'proposal_sha256': execution['proposal_sha256']}
    if len(rows) == 1 and str(selected) == rows[0]['identity_path']:
        row = rows[0]
        return {**binding, 'path': row['path'], 'identity_path': row['identity_path'], 'exists': True, 'status': 'present',
                'scope': 'mapping_source_file', 'content': {key: row[key] for key in ('sha256', 'size_bytes')} | {'kind': 'file'}}
    return {**binding, 'path': None, 'identity_path': str(selected), 'exists': True, 'status': 'present',
            'scope': 'mapping_selected_files', 'selected_files_current': True,
            'audit_status': 'matches_confirmed_mapping_sources', 'selected_files': rows,
            'content': {'kind': 'selected_files', 'member_count': len(rows), 'size_bytes': sum(row['size_bytes'] for row in rows),
                        'selected_files_sha256': canonical_json_sha256(rows)}}
