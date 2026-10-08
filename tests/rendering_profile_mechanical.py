"""Mechanical real-data profile: replay preserved outputs through production APIs.

This module has no renderer, statistic, or golden-update implementation. Summary
values come from the historical scientific owner; all source bytes stay pinned.
"""

from copy import deepcopy
import json
from pathlib import Path

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.plot_engine.contracts import validate_create
from sciplot_core.plot_engine.managed_sources import load_sources
from sciplot_core.plot_ir import create_managed_document
from sciplot_core.plot_transforms import resolve_transforms


def mechanical_request(profile_dir: Path) -> dict:
    """Resolve pinned fixture-relative file paths without changing any values."""
    root = Path(profile_dir).resolve()
    manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
    for role, entry in manifest['files'].items():
        path = (root / entry['path']).resolve()
        if not path.is_relative_to(root) or file_sha256(path) != entry['sha256']:
            raise AssertionError(f'Immutable mechanical fixture changed: {role}')
    request = deepcopy(json.loads((root / 'mapped_request.json').read_text(encoding='utf-8')))
    for source in request['data_binding']['data_sources']:
        path = (root / source['path']).resolve()
        if not path.is_relative_to(root) or file_sha256(path) != source['sha256']:
            raise AssertionError(f'Mechanical source changed: {source["source_id"]}')
        source['path'] = str(path)
    return validate_create(request)


def mechanical_document(profile_dir: Path) -> dict:
    """Resolve source-bound FigureTemplate using the existing Managed owners."""
    request = mechanical_request(profile_dir)
    document = create_managed_document(request['template_definition'], request['data_binding'],
                                       plot_id='mechanical-v1')
    return resolve_transforms(document, load_sources(document, request['rule_id']))['document']


def replay_legacy(profile_dir: Path, output_dir: Path) -> Path:
    """Re-run the old production native compiler on the exact historical spec."""
    from sciplot_core.studio_core.veusz_save import save_veusz_document_from_spec

    root, output = Path(profile_dir).resolve(), Path(output_dir).resolve()
    if output.is_relative_to(root):
        raise AssertionError('Replay output cannot replace immutable fixture files')
    mechanical_request(root)  # Verify all immutable inputs before a native call.
    spec_path = root / 'legacy/spec.json'
    document = output / 'document.vsz'
    save_veusz_document_from_spec(document, json.loads(spec_path.read_text(encoding='utf-8')),
                                 spec_path=spec_path)
    return document
