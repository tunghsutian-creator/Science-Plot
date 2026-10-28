"""Native bindings keep file-byte versions distinct from complete tree seals."""
from copy import deepcopy

import pytest

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.source_locations import resolve_source_path
from sciplot_core.plot_backends.veusz_identity import fingerprint, require_current
from sciplot_core.plot_document import DocumentError
from sciplot_core.project_store import FileProjectStore, ProjectStoreError
from sciplot_core.project_store.runtime import project_runtime
from sciplot_core.studio_core.preparation_source_runtime import current_preparation_runtime

from test_current_preparation_sources import current_revision


def binding_for(store, source, paths, tree):
    files = {str(path): file_sha256(path) for path in paths}
    # This projection exercises scientific reads; no native file is selected.
    return {'project': str(store.root), 'document': str(store.root / 'studio/document.vsz'),
            'files': files, 'source_trees': {str(source): tree},
            'fingerprint': {'files': deepcopy(files), 'source_trees': {str(source): tree}, 'projections': {}}}


@pytest.mark.parametrize('cold', [False, True])
def test_registered_file_tree_uses_its_byte_version_and_preserves_composite(tmp_path, cold):
    store, source, paths, _old, tree = current_revision(tmp_path)
    binding = binding_for(store, source, paths, tree)
    assert binding['files'][str(source)] != tree
    if cold:
        store = FileProjectStore.import_bundle(store.export_bundle(tmp_path / 'bundle'), tmp_path / 'cold')
        source.rename(tmp_path / 'original-offline')
        binding['project'] = str(store.root)
    require_current(binding)
    assert fingerprint(binding) == binding['fingerprint']
    with project_runtime(store), pytest.raises(ProjectStoreError, match='exact registered version'):
        resolve_source_path(source)


@pytest.mark.parametrize('cold', [False, True])
def test_complete_directory_witness_keeps_all_members_live_or_imported(tmp_path, cold):
    store, source, paths, _old, tree = current_revision(tmp_path, directory=True)
    assert any(path.name == 'notes.txt' for path in paths)
    binding = binding_for(store, source, paths, tree)
    if cold:
        store = FileProjectStore.import_bundle(store.export_bundle(tmp_path / 'bundle'), tmp_path / 'cold')
        source.rename(tmp_path / 'original-offline')
        binding['project'] = str(store.root)
    with current_preparation_runtime(store, store.snapshot()):
        require_current(binding)
        assert fingerprint(binding) == binding['fingerprint']


@pytest.mark.parametrize('changed', ['bytes', 'composite_as_file_sha', 'missing_byte_proof'])
def test_file_drift_and_incomplete_or_conflated_proofs_are_not_current(tmp_path, changed):
    store, source, paths, _old, tree = current_revision(tmp_path)
    binding = binding_for(store, source, paths, tree)
    if changed == 'bytes':
        source.write_bytes(b'foreign source revision')
    elif changed == 'composite_as_file_sha':
        binding['files'][str(source)] = tree
    else:
        binding['files'].pop(str(source))
    with pytest.raises((DocumentError, ProjectStoreError)):
        require_current(binding)


@pytest.mark.parametrize('changed', ['new_member', 'bytes', 'mode', 'alias'])
def test_complete_directory_drift_is_not_hidden_by_registered_versions(tmp_path, changed):
    store, source, paths, _old, tree = current_revision(tmp_path, directory=True)
    binding = binding_for(store, source, paths, tree)
    if changed == 'new_member':
        (source / 'late.txt').write_bytes(b'foreign member')
    elif changed == 'bytes':
        paths[0].write_bytes(b'foreign bytes')
    elif changed == 'mode':
        paths[0].chmod(0o600 if paths[0].stat().st_mode & 0o777 != 0o600 else 0o644)
    else:
        (source / 'alias').symlink_to(paths[0])
    with pytest.raises(ValueError):
        with current_preparation_runtime(store, store.snapshot()):
            require_current(binding)


def test_unbound_cold_directory_cannot_be_reconstructed_from_used_files(tmp_path):
    store, source, paths, _old, tree = current_revision(tmp_path, directory=True)
    binding = binding_for(store, source, paths, tree)
    cold = FileProjectStore.import_bundle(store.export_bundle(tmp_path / 'bundle'), tmp_path / 'cold')
    source.rename(tmp_path / 'original-offline')
    binding['project'] = str(cold.root)
    with pytest.raises((DocumentError, ProjectStoreError)):
        require_current(binding)
