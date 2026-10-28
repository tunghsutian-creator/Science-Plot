"""Freeze only the original input explicitly selected by a private preparation."""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
import stat
import json
import os
from typing import Any

from sciplot_core.data_mapping.execution_inputs import MappingInputReadSet
from sciplot_core.data_mapping.numeric_readset_proof import numeric_input_digest
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.foundation.source_locations import literal_source_path, resolve_source_path, selected_source_resolver
from sciplot_core.project_commands import PreparedSource, SourceTreeRead
from sciplot_core.project_store import ProjectConflict
from sciplot_core.project_store.locators import logical_for_literal
from sciplot_core.project_store.candidate_runtime import ProjectCandidateResolver
from sciplot_core.project_store.io import STORE, directory
from sciplot_core.project_store.runtime import logical_runtime_resource
from sciplot_core.project_store.source_tree_io import observe
from sciplot_core.source_coverage.file_snapshots import _physical_file_snapshot, _require_snapshot_identity


def source_identity_for_locator(snapshot: dict[str, Any], locator: str) -> str:
    known = [identity for identity, versions in snapshot['sources'].items()
             if any(entry.get('locator') == locator for entry in versions.values())]
    if len(known) > 1:
        raise ValueError('The native source literal has ambiguous project identities.')
    return known[0] if known else canonical_json_sha256(
        {'project_id': snapshot['project_id'], 'locator': locator})[:32]


@dataclass(frozen=True)
class OriginalPreparationInput:
    literal: str
    actual: Path
    tree_sha256: str
    proof: dict[str, Any]
    observations: dict[str, dict[str, Any]]
    prepared: tuple[PreparedSource, ...]
    live_tree: SourceTreeRead | None
    allowed_members: frozenset[str] | None = None

    def require_current(self) -> None:
        for literal, previous in self.observations.items():
            current = _physical_file_snapshot(Path(previous['actual']), literal=Path(literal),
                label='Selected preparation original', expected_sha256=previous['sha256'])
            _require_snapshot_identity(previous, current, label='Selected preparation original')
        version, proof = observe(str(self.actual), allowed=set(self.allowed_members) if self.allowed_members is not None else None)
        if version != self.tree_sha256 or proof != self.proof:
            raise ProjectConflict('The selected preparation input changed its complete membership, mode or identity.')


def _require_registered_members(root: int, expected: dict[str, Any]) -> None:
    """Census metadata before content IO; no neighbour becomes an input grant."""
    def visit(fd: int, prefix: str) -> None:
        names = {name[len(prefix):].split('/')[0] for name in expected if name.startswith(prefix)}
        if set(os.listdir(fd)) != names:
            raise ProjectConflict('The registered original directory has unknown or missing members.')
        for name in sorted(names):
            relative = prefix + name
            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            if relative in expected:
                if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                        or stat.S_IMODE(info.st_mode) != expected[relative]['mode']):
                    raise ProjectConflict('The registered original member changed shape or permissions.')
            elif stat.S_ISDIR(info.st_mode):
                with directory(fd, (name,)) as child:
                    visit(child, relative + '/')
            else:
                raise ProjectConflict('A registered original directory cannot traverse an alias or special member.')
    visit(root, '')


def capture_original_input(request: dict[str, Any], *, base_dir: Path,
                           snapshot: dict[str, Any]) -> OriginalPreparationInput | None:
    if request.get('data_mapping_execution'):
        return None  # The confirmed mapping's finite read set already captures its originals.
    value = request.get('input')
    if not isinstance(value, str) or not value.strip():
        return None
    supplied = Path(value).expanduser()
    supplied = supplied if supplied.is_absolute() else base_dir / supplied
    if STORE in supplied.parts:
        raise ProjectConflict('A project store namespace cannot be selected as an original input.')
    selected = selected_source_resolver()
    logical = logical_runtime_resource(supplied)
    allowed = None
    if logical is not None:
        if (not isinstance(selected, ProjectCandidateResolver)
                or {key: value for key, value in snapshot.items() if key not in {'outside_changes', 'outside_metadata', 'projection_status'}} != selected.snapshot):
            raise ProjectConflict('A managed preparation input needs its exact selected candidate generation.')
        prefix = logical + '/'
        members = {name[len(prefix):]: entry for name, entry in snapshot['files'].items() if name.startswith(prefix)}
        produced = {entry.get('produced_resource') for versions in snapshot['sources'].values() for entry in versions.values()}
        if logical in produced or not members and logical not in snapshot['files']:
            return None  # New/produced private inputs retain their existing terminal/output owner.
        if members and any(prefix + name in produced for name in members):
            raise ProjectConflict('An original directory cannot silently include generated output resources.')
        with selected._namespace(logical) as (root, relative):
            parts = () if relative == '.' else Path(relative).parts
            with directory(root, parts[:-1]) as parent:
                info = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False) if parts else os.fstat(parent)
            if stat.S_ISDIR(info.st_mode):
                if logical.startswith('@') and selected.store.location_members[logical[1:].split('/')[0]] is not None:
                    raise ProjectConflict('Finite file capabilities do not authorize an original parent directory.')
                with directory(root, parts) as source:
                    _require_registered_members(source, members)
                allowed = frozenset(members)
            elif (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or logical not in snapshot['files']
                  or stat.S_IMODE(info.st_mode) != snapshot['files'][logical]['mode']):
                raise ProjectConflict('The selected managed original is not a registered ordinary member.')
        literal, actual = selected._literal(logical), selected._private_path(logical)
    else:
        literal = literal_source_path(supplied)
        actual = resolve_source_path(supplied).absolute()
    tree_sha256, proof = observe(str(actual), allowed=set(allowed) if allowed is not None else None)
    is_directory = stat.S_ISDIR(proof['root']['mode'])
    observed_members = [name for name, info in proof['members'].items() if stat.S_ISREG(info['mode'])] if is_directory else ['']
    observations, prepared = {}, []
    for member in observed_members:
        origin = str(Path(literal) / member) if member else literal
        path = actual / member if member else actual
        identity = source_identity_for_locator(snapshot, origin)
        expected = snapshot['files'].get((logical + '/' + member) if member else logical) if logical is not None else None
        captured = _physical_file_snapshot(path, literal=Path(origin), label='Selected preparation original',
            expected_sha256=expected['sha256'] if expected is not None else None)
        captured['actual'] = str(path)
        version = captured['sha256']
        prior = snapshot['sources'].get(identity, {}).get(version)
        observed_mode = stat.S_IMODE(captured['identity']['mode'])
        if (expected is not None and observed_mode != expected['mode']
                or prior is not None and path == Path(origin) and observed_mode != prior['mode']):
            raise ProjectConflict('The selected original input changed its registered permissions.')
        mode = prior['mode'] if prior is not None else observed_mode
        observations[origin] = captured
        prepared.append(PreparedSource(identity, origin, version, captured['bytes'], mode=mode))
    witness = (SourceTreeRead(literal, tree_sha256) if logical is None and actual == Path(literal)
               and logical_for_literal(snapshot, literal) is None else None)
    result = OriginalPreparationInput(literal, actual, tree_sha256, proof, observations, tuple(prepared), witness, allowed)
    result.require_current()
    return result


def verify_original_ledger(request: dict[str, Any], originals: Iterable[OriginalPreparationInput], *,
                           prepared_sources: Iterable[PreparedSource], mapping_inputs: Iterable[MappingInputReadSet] = ()) -> None:
    """Ledger text can assert a relationship, never authorize another file read."""
    captured = tuple(originals)
    allowed = {item.locator: item.version for item in prepared_sources}
    for original in captured:
        original.require_current()
        allowed.update({item.locator: item.version for item in original.prepared})
    mapping_namespaces = set()
    mapping_trees = {}
    for readset in mapping_inputs:
        readset.require_current()
        execution = readset.files.get(readset.execution)
        if execution is None or readset.numeric_inputs_sha256 != numeric_input_digest(readset):
            continue
        payload = json.loads(execution.data)
        ledger = readset.files.get(payload['transform_ledger'])
        if ledger is None or ledger.sha256 != payload['transform_ledger_sha256']:
            raise ProjectConflict('A mapping ledger lost its numerically verified exact input bytes.')
        for prior_step in json.loads(ledger.data)['steps']:
            for artifact in prior_step.get('input_artifacts', []):
                if artifact.get('kind') == 'directory' and artifact.get('path') == payload['source_root']:
                    mapping_namespaces.add((canonical_json_sha256(prior_step), canonical_json_sha256(artifact)))
        for literal, tree in readset.trees.items():
            members = {path: item.sha256 for path, item in readset.files.items() if Path(path).is_relative_to(literal)}
            observed = canonical_json_sha256({'kind': 'directory', 'files': [
                {'path': Path(path).relative_to(literal).as_posix(), 'content_sha256': version}
                for path, version in sorted(members.items(), key=lambda item: Path(item[0]))]})
            if observed == tree.tree_sha256:
                mapping_trees[literal] = members
    steps = request.get('transform_ledger', {}).get('steps', [])
    for step in steps:
        for artifact in step.get('input_artifacts', []):
            literal, expected = artifact.get('path'), artifact.get('sha256')
            if artifact.get('kind') == 'file' and (not isinstance(literal, str) or literal not in allowed or allowed[literal] != expected):
                raise ProjectConflict('A preparation ledger input lacks this invocation\'s exact authorized observation.')
            if artifact.get('kind') == 'directory':
                root = next((item for item in captured if item.literal == literal), None)
                if root is None and (canonical_json_sha256(step), canonical_json_sha256(artifact)) in mapping_namespaces:
                    # This exact verified mapping step retains its historical
                    # namespace metadata. It grants no parent IO or tree seal.
                    continue
                if root is None and literal not in mapping_trees:
                    raise ProjectConflict('A preparation ledger directory was not selected by this invocation.')
                # Publication's directory artifact uses its existing ordered
                # member digest, distinct from the SourceTreeRead composite.
                import hashlib

                digest = hashlib.sha256()
                members = ({path: observation['sha256'] for path, observation in root.observations.items()}
                           if root is not None else mapping_trees[literal])
                for path, version in sorted(members.items(), key=lambda item: Path(item[0])):
                    digest.update(Path(path).relative_to(literal).as_posix().encode())
                    digest.update(version.encode('ascii'))
                if digest.hexdigest() != expected:
                    raise ProjectConflict('The preparation ledger directory differs from its captured original members.')


def original_tree_reads(originals: Iterable[OriginalPreparationInput], existing: Iterable[SourceTreeRead]) -> tuple[SourceTreeRead, ...]:
    values = {item.locator: item for item in existing}
    for original in originals:
        original.require_current()
        item = original.live_tree
        if item is not None:
            if item.locator in values and values[item.locator] != item:
                raise ProjectConflict('The selected input has conflicting complete source-tree witnesses.')
            values[item.locator] = item
    return tuple(values[key] for key in sorted(values))


def checked_original_sources(originals: Iterable[OriginalPreparationInput],
                             sources: Iterable[PreparedSource]) -> tuple[PreparedSource, ...]:
    """Recheck the captured originals after admission and before staging bytes."""
    for original in originals:
        original.require_current()
    return tuple(sources)
