"""Native bindings keep file-byte versions distinct from complete tree seals."""
from copy import deepcopy
from contextlib import nullcontext

import pytest

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.source_locations import resolve_source_path, literal_source_path
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
    before = _persistent_tree(store.root)
    require_current(binding)
    assert fingerprint(binding) == binding['fingerprint']
    assert _persistent_tree(store.root) == before
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
        before = _persistent_tree(store.root)
        require_current(binding)
        assert fingerprint(binding) == binding['fingerprint']
        assert _persistent_tree(store.root) == before


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


def _persistent_tree(root):
    return {str(path.relative_to(root)): (path.stat().st_mode, path.stat().st_mtime_ns,
            path.read_bytes() if path.is_file() else None)
            for path in [root, *root.rglob('*')]}


@pytest.mark.parametrize('exception', [False, True])
def test_query_sealed_file_view_is_external_finite_and_cleaned_on_every_exit(tmp_path, exception):
    import stat
    from sciplot_core.project_store.incoming_sources import SourceExpectation
    from sciplot_core.project_store.runtime import sealed_source_runtime
    from sciplot_core.project_store.source_resolver import query_sources

    store, source, _paths, _old, _tree = current_revision(tmp_path)
    literal = str(source)
    version = file_sha256(source)
    snapshot = store.snapshot()
    identities = [identity for identity, versions in snapshot['sources'].items()
                  if version in versions and versions[version]['locator'] == literal]
    assert len(identities) == 1
    expected = source.read_bytes()
    before = _persistent_tree(tmp_path)
    with pytest.raises(RuntimeError, match='backend failure') if exception else nullcontext():
        with sealed_source_runtime(store, [SourceExpectation(literal, identities[0], version)]), query_sources(store):
            target = resolve_source_path(source, expected_sha256=version, source_id=identities[0])
            assert not target.is_relative_to(tmp_path) and target.read_bytes() == expected
            assert stat.S_IMODE(target.stat().st_mode) == 0o400
            assert stat.S_IMODE(target.parent.stat().st_mode) == 0o700
            assert list(target.parent.iterdir()) == [target]
            assert literal_source_path(target) == literal
            assert resolve_source_path(source, expected_sha256=version, source_id=identities[0]) == target
            if exception:
                raise RuntimeError('backend failure')
    assert not target.exists() and not target.parent.exists()
    assert _persistent_tree(tmp_path) == before


def test_query_does_not_expose_unregistered_paths_in_a_selected_project(tmp_path):
    from sciplot_core.project_store.source_resolver import query_sources

    store, _source, _paths, _old, _tree = current_revision(tmp_path)
    unregistered = store.root / 'never-admitted.txt'
    unregistered.write_text('not a registered project input')
    before = _persistent_tree(tmp_path)
    with query_sources(store), pytest.raises(ProjectStoreError, match='no exact preserved locator'):
        resolve_source_path(unregistered)
    assert _persistent_tree(tmp_path) == before


@pytest.mark.parametrize('configuration', [
    'external-cached', 'external-env', 'protected-cached', 'protected-env',
    'protected-alias', 'protected-namespace',
])
def test_query_temp_base_is_checked_without_any_default_directory_probe(tmp_path, monkeypatch, configuration):
    import tempfile
    from sciplot_core.project_store.incoming_sources import SourceExpectation
    from sciplot_core.project_store.runtime import sealed_source_runtime
    from sciplot_core.project_store.source_resolver import query_sources

    store, source, _paths, _old, _tree = current_revision(tmp_path)
    snapshot = store.snapshot()
    version = file_sha256(source)
    identity = next(identity for identity, versions in snapshot['sources'].items()
                    if version in versions and versions[version]['locator'] == str(source))
    expected = source.read_bytes()
    namespace = tmp_path / 'sciplot-query-source-old' / 'namespace'
    namespace.mkdir(parents=True)
    alias = tmp_path / 'protected-alias'
    alias.symlink_to(store.root, target_is_directory=True)
    safe = configuration.startswith('external')
    # The external ancestor is allowed, but all possible generated child names
    # must exclude the preserved namespace descendant before any creation.
    base = tmp_path if safe else namespace if configuration == 'protected-namespace' else alias if configuration == 'protected-alias' else store.root
    before_project = _persistent_tree(store.root)
    before_namespace = _persistent_tree(namespace)
    before_source = (source.read_bytes(), source.stat().st_mode, source.stat().st_mtime_ns)
    calls = []
    original = tempfile.TemporaryDirectory

    def created(*args, **kwargs):
        calls.append(kwargs)
        return original(*args, **kwargs)

    def forbidden_probe():
        pytest.fail('Read-only temp selection invoked a probing tempfile default')

    with monkeypatch.context() as patch:
        patch.setattr(tempfile, 'tempdir', str(base) if configuration.endswith('cached') or configuration == 'protected-namespace' else None)
        patch.setenv('TMPDIR', str(base))
        patch.setattr(tempfile, 'gettempdir', forbidden_probe)
        patch.setattr(tempfile, '_get_default_tempdir', forbidden_probe)
        patch.setattr(tempfile, 'TemporaryDirectory', created)
        with sealed_source_runtime(store, [SourceExpectation(str(source), identity, version)]):
            # The inner scope must inherit the outer namespace protection.
            with query_sources(store, protected_roots=(namespace,)), query_sources(store):
                with nullcontext() if safe else pytest.raises(ProjectStoreError, match='outside protected project and source namespaces'):
                    target = resolve_source_path(source, expected_sha256=version, source_id=identity)
                    assert target.read_bytes() == expected
                    assert not target.is_relative_to(namespace) and not target.is_relative_to(store.root)
                    assert target.parent.name.startswith('sciplot-query-source-private-')
        if safe:
            assert len(calls) == 1 and calls[0]['dir'] == str(base.resolve())
            assert not target.exists() and not target.parent.exists()
        else:
            assert calls == []
    assert _persistent_tree(store.root) == before_project
    assert _persistent_tree(namespace) == before_namespace
    assert (source.read_bytes(), source.stat().st_mode, source.stat().st_mtime_ns) == before_source
