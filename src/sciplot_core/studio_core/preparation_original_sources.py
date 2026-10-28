"""Freeze only the original input explicitly selected by a private preparation."""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
import stat
from typing import Any

from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.foundation.source_locations import literal_source_path, resolve_source_path
from sciplot_core.project_commands import PreparedSource, SourceTreeRead
from sciplot_core.project_store import ProjectConflict
from sciplot_core.project_store.locators import logical_for_literal
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

    def require_current(self) -> None:
        for literal, previous in self.observations.items():
            current = _physical_file_snapshot(Path(previous['actual']), literal=Path(literal),
                label='Selected preparation original', expected_sha256=previous['sha256'])
            _require_snapshot_identity(previous, current, label='Selected preparation original')
        version, proof = observe(str(self.actual))
        if version != self.tree_sha256 or proof != self.proof:
            raise ProjectConflict('The selected preparation input changed its complete membership, mode or identity.')


def capture_original_input(request: dict[str, Any], *, base_dir: Path,
                           snapshot: dict[str, Any]) -> OriginalPreparationInput | None:
    if request.get('data_mapping_execution'):
        return None  # The confirmed mapping's finite read set already captures its originals.
    value = request.get('input')
    if not isinstance(value, str) or not value.strip():
        return None
    supplied = Path(value).expanduser()
    supplied = supplied if supplied.is_absolute() else base_dir / supplied
    literal = literal_source_path(supplied)
    actual = resolve_source_path(supplied).absolute()
    logical = logical_runtime_resource(actual, private_only=True)
    if logical is not None and (logical not in snapshot['files'] or any(
            entry.get('produced_resource') == logical for versions in snapshot['sources'].values() for entry in versions.values())):
        return None  # A new private terminal/mapping output is not another original input.
    tree_sha256, proof = observe(str(actual))
    directory = stat.S_ISDIR(proof['root']['mode'])
    members = [name for name, info in proof['members'].items() if stat.S_ISREG(info['mode'])] if directory else ['']
    observations, prepared = {}, []
    for member in members:
        origin = str(Path(literal) / member) if member else literal
        path = actual / member if member else actual
        identity = source_identity_for_locator(snapshot, origin)
        captured = _physical_file_snapshot(path, literal=Path(origin), label='Selected preparation original')
        captured['actual'] = str(path)
        version = captured['sha256']
        prior = snapshot['sources'].get(identity, {}).get(version)
        observed_mode = stat.S_IMODE(captured['identity']['mode'])
        if prior is not None and path == Path(origin) and observed_mode != prior['mode']:
            raise ProjectConflict('The selected original input changed its registered permissions.')
        mode = prior['mode'] if prior is not None else observed_mode
        observations[origin] = captured
        prepared.append(PreparedSource(identity, origin, version, captured['bytes'], mode=mode))
    witness = (SourceTreeRead(literal, tree_sha256) if actual == Path(literal)
               and logical_for_literal(snapshot, literal) is None else None)
    result = OriginalPreparationInput(literal, actual, tree_sha256, proof, observations, tuple(prepared), witness)
    result.require_current()
    return result


def verify_original_ledger(request: dict[str, Any], originals: Iterable[OriginalPreparationInput], *,
                           prepared_sources: Iterable[PreparedSource]) -> None:
    """Ledger text can assert a relationship, never authorize another file read."""
    captured = tuple(originals)
    allowed = {item.locator: item.version for item in prepared_sources}
    for original in captured:
        original.require_current()
        allowed.update({item.locator: item.version for item in original.prepared})
    steps = request.get('transform_ledger', {}).get('steps', [])
    for step in steps:
        for artifact in step.get('input_artifacts', []):
            literal, expected = artifact.get('path'), artifact.get('sha256')
            if artifact.get('kind') == 'file' and (not isinstance(literal, str) or literal not in allowed or allowed[literal] != expected):
                raise ProjectConflict('A preparation ledger input lacks this invocation\'s exact authorized observation.')
            if artifact.get('kind') == 'directory':
                root = next((item for item in captured if item.literal == literal), None)
                if root is None:
                    raise ProjectConflict('A preparation ledger directory was not selected by this invocation.')
                # Publication's directory artifact uses its existing ordered
                # member digest, distinct from the SourceTreeRead composite.
                import hashlib

                digest = hashlib.sha256()
                for path, observation in sorted(root.observations.items(), key=lambda item: Path(item[0])):
                    digest.update(Path(path).relative_to(root.literal).as_posix().encode())
                    digest.update(observation['sha256'].encode('ascii'))
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
