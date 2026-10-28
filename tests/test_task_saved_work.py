"""Saved-work discovery never promotes hashes, copies or stale records to authority."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from sciplot_core import task_saved_work as work
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.source_tree import source_tree_sha256
from sciplot_core.launchers import write_delivery_launcher
from sciplot_core.launchers.delivery_binding import DeliveryBinding
from sciplot_core.plot_engine.storage import commit
from sciplot_core.task_contract import TaskControlError
from sciplot_core.task_storage import save_task
from test_managed_external_mutation import _canonical


def inventory(root):
    return {str(path): (path.read_bytes(), path.stat().st_mtime_ns)
            for path in root.rglob("*") if path.is_file() and not path.is_symlink()}


@pytest.fixture
def managed(tmp_path):
    root, document, binding = _canonical(tmp_path)
    commit(root, document, binding, "managed_creation")
    return root, Path(document["scientific"]["data_sources"][0]["path"]), binding


def legacy(root, source):
    (root / "studio").mkdir(parents=True)
    (root / "plot_request.json").write_text(json.dumps({"input": str(source)}))
    (root / "studio/document.vsz").write_text("saved native")
    (root / "studio/spec.json").write_text(json.dumps({"series": [{
        "source_artifacts": [{"path": str(source), "sha256": file_sha256(source)}]}]}))
    return root


def receipt(root, source, project=None, **values):
    root.mkdir(parents=True)
    save_task(root, {"kind": "sciplot_task", "version": 1, "task_dir": str(root),
                     "request": {"version": 1, "action": "create", "source": str(source)},
                     "source_sha256": source_tree_sha256(source), "status": "complete", "phase": "finished",
                     "project": str(project) if project else None, **values})
    return root


def delivery(root, source, owner=None):
    (root / "project").mkdir(parents=True)
    native = root / "project/figure.vsz"
    native.write_text("portable native")
    binding = DeliveryBinding(root=str(root), source=str(source),
        request=str(owner / "plot_request.json") if owner else str(root.parent / "gone/plot_request.json"),
        primary=native.name, documents=((native.name, file_sha256(native)),))
    write_delivery_launcher(root, binding=binding)
    return root


def test_managed_discovery_and_continuation_use_existing_seals_without_native_or_writes(managed, tmp_path, monkeypatch):
    root, source, _ = managed
    before = inventory(tmp_path)
    monkeypatch.setattr(subprocess, "run", lambda *_a, **_k: pytest.fail("read started native worker"))
    found = work.find_saved_work(source, search_roots=[tmp_path])
    assert found["scan_complete"] and found["match_count"] == 1
    assert found["matches"][0]["target"] == str(root)
    assert found["matches"][0]["authority"] == "sciplot_document"
    continued = work.continue_saved_work(source, search_roots=[tmp_path])
    assert continued["status"] == "current"
    assert continued["next_step"]["arguments"] == {"target": str(root)}
    assert continued["ready_to_use"] is None and not continued["readiness_evaluated"]
    assert inventory(tmp_path) == before
    from sciplot_core.plot_engine.service import PlotService
    service = PlotService()
    try:
        # The returned arguments enter the actual existing open owner. Missing
        # disposable native artifacts stay dirty, while semantic IDs are current.
        opened = service.open(Path(continued["next_step"]["arguments"]["target"]))
        assert opened["plot_id"] == continued["current"]["plot_id"]
        assert opened["scientific_hash"] == continued["current"]["scientific_hash"]
    finally:
        service.close()


def test_renamed_or_copied_source_is_candidate_evidence_without_rebinding(managed, tmp_path):
    root, source, _ = managed
    renamed = tmp_path / "renamed.csv"
    shutil.copy2(source, renamed)
    before = inventory(tmp_path)
    found = work.find_saved_work(renamed, search_roots=[root])
    assert found["matches"][0]["source_relation"] == "same_content_other_path"
    assert work.continue_saved_work(renamed, search_roots=[root])["status"] == "current"
    source.unlink()
    stale = work.continue_saved_work(renamed, search_roots=[root])
    assert stale["status"] == "blocked" and stale["reason_code"] == "document_conflict"
    assert inventory(tmp_path) == {path: value for path, value in before.items() if path != str(source)}


@pytest.mark.parametrize("change", ["bytes", "missing", "symlink"])
def test_managed_search_source_race_after_final_document_read_fails_closed(managed, tmp_path, monkeypatch, change):
    root, source, _ = managed
    copied = tmp_path / "renamed-source.csv"
    shutil.copy2(source, copied)
    original_hash, authority_before = file_sha256(source), inventory(root)
    read_document = work.document_evidence
    reads = []

    def change_after_owner_read(target):
        current = read_document(target)
        assert current["current"]
        reads.append(target)
        if change == "bytes":
            copied.write_bytes(copied.read_bytes().replace(b"2", b"9"))
        else:
            copied.unlink()
            if change == "symlink":
                copied.symlink_to(source)
        return current

    # Only the final continuation owner is patched. Discovery reads the real
    # managed document through its own owner, before the external mutation.
    monkeypatch.setattr(work, "document_evidence", change_after_owner_read)
    result = work.continue_saved_work(copied, search_roots=[root], target=root)
    assert reads == [root]
    assert result["status"] == "blocked", result
    assert result["reason_code"] == "source_changed_during_continuation"
    assert result["next_step"]["action"] == "find_saved_work_again"
    assert "current" not in result
    assert file_sha256(source) == original_hash and inventory(root) == authority_before


def test_same_name_different_bytes_never_match(managed, tmp_path):
    root, source, _ = managed
    other = tmp_path / "elsewhere" / source.name
    other.parent.mkdir()
    other.write_text("different content")
    assert work.find_saved_work(other, search_roots=[root])["match_count"] == 0


def test_exact_path_changed_bytes_reports_conflict_not_a_fresh_authority(managed):
    root, source, _ = managed
    source.write_text("different content")
    continued = work.continue_saved_work(source, search_roots=[root])
    assert continued["status"] == "blocked"
    assert str(source) in continued["selected"]["document"]["changed_inputs"]


def test_copied_managed_root_cannot_operate_original_absolute_binding(managed, tmp_path):
    root, source, _ = managed
    copied = tmp_path / "copied"
    shutil.copytree(root, copied)
    before = inventory(tmp_path)
    found = work.find_saved_work(source, search_roots=[copied])
    assert found["match_count"] == 0 and not found["scan_complete"]
    assert "another authority root" in found["issues"][0]["message"]
    assert work.continue_saved_work(source, search_roots=[copied], target=copied)["status"] == "blocked"
    assert inventory(tmp_path) == before


@pytest.mark.parametrize("mutation", ["untracked", "external"])
def test_managed_native_external_save_is_a_conflict(managed, mutation):
    root, source, binding = managed
    native = Path(binding["document"])
    native.parent.mkdir(parents=True)
    native.write_text("native bytes")
    if mutation == "external":
        (native.parent / "build.json").write_text(json.dumps({"ir_hash": binding["ir_hash"],
            "document_sha256": "a" * 64}))
    found = work.find_saved_work(source, search_roots=[root])
    assert found["matches"][0]["state"] == "document_conflict"
    assert not found["matches"][0]["continuation_available"]


def test_tampered_managed_canonical_model_is_not_a_continuable_head(managed, tmp_path):
    root, source, binding = managed
    Path(binding["canonical_document"]).write_text("{}")
    before = inventory(tmp_path)
    found = work.find_saved_work(source, search_roots=[root])
    assert not found["matches"] and not found["scan_complete"]
    assert inventory(tmp_path) == before


def test_pending_managed_transaction_requires_its_existing_owner(managed):
    from sciplot_core.plot_engine.storage import transaction_path

    root, source, _ = managed
    # This is an existing minimal historical journal, not a new admission.
    # New reserve calls require complete command input and its base snapshot.
    transaction = transaction_path(root, "unfinished")
    transaction.parent.mkdir(parents=True)
    transaction.write_text(json.dumps({"id": "pending-edit", "phase": "applying",
                                       "request": {"idempotency_key": "unfinished"}}))
    (root / "active.json").write_text(json.dumps({"key": "unfinished"}))
    before = inventory(root)
    continued = work.continue_saved_work(source, search_roots=[root])
    assert continued["status"] == "blocked" and continued["reason_code"] == "document_conflict"
    assert continued["selected"]["document"]["pending"]["phase"] == "applying"
    assert inventory(root) == before


def test_multiple_same_source_projects_are_not_deduplicated_or_auto_selected(tmp_path):
    source = tmp_path / "raw.csv"
    source.write_text("x,y\n1,2\n")
    first = legacy(tmp_path / "first", source)
    second = tmp_path / "second"
    shutil.copytree(first, second)
    found = work.find_saved_work(source, search_roots=[tmp_path], limit=1)
    assert found["match_count"] == 2 and found["selection_required"] and found["has_more_matches"]
    assert work.continue_saved_work(source, search_roots=[tmp_path])["status"] == "needs_selection"
    selected = work.continue_saved_work(source, search_roots=[tmp_path], target=second)
    assert selected["reason_code"] == "source_evidence_missing"  # No full raw-tree creation evidence.


@pytest.mark.parametrize("current", [True, False, None], ids=['current', 'stale', 'unknown'])
def test_known_foreign_delivery_owner_stays_the_explicit_copy_conflict(tmp_path, monkeypatch, current):
    from sciplot_core import task_saved_work_evidence as evidence

    source = tmp_path / "raw.csv"
    source.write_text("x,y\n1,2\n")
    owner = legacy(tmp_path / "owner", source)
    copied = tmp_path / "copied"
    shutil.copytree(owner, copied)
    package = delivery(tmp_path / "visible", source, owner)
    before = inventory(tmp_path)
    monkeypatch.setattr(evidence, "inspect_project", lambda *_a, **_k: {
        "figures": [], "source": {"current": current}, "delivery": {"path": str(package)},
        "request_sha256": file_sha256(copied / "plot_request.json"), "primary_figure_id": "curve"})
    def known_owner(root):
        assert root == package
        return owner
    monkeypatch.setattr(evidence, "bound_delivery_project", known_owner)
    result = evidence.project_evidence(copied, source, source_tree_sha256(source))
    assert result["state"] == "project_output_conflict" and not result["continuation_available"]
    assert result["delivery_owner"] == str(owner)
    assert inventory(tmp_path) == before


@pytest.mark.parametrize("state", ["current", "pending", "missing-revision", "foreign-plot", "generation-race", "source-drift", "unindexed"])
def test_saved_work_reads_the_current_attachment_without_materializing_or_adopting_history(tmp_path, monkeypatch, state):
    from test_attached_semantic_repository import application
    from managed_plot_helpers import patch, request_for_source
    from sciplot_core.project_store import FileProjectStore
    from sciplot_core.project_store.runtime import project_runtime
    from sciplot_core.project_lifecycle.attachment_index import Attachment, read_index
    from sciplot_core.project_lifecycle.attached_repository import AttachedProjectRepository
    from sciplot_core.project_lifecycle.errors import EngineError
    from sciplot_core.project_commands import ProjectCommand, ProjectCommands, ProjectMutation
    from sciplot_core import task_saved_work_evidence as evidence

    project = tmp_path / 'project'
    project.mkdir()
    store = FileProjectStore(project)
    store.snapshot(import_legacy=True)
    app = application()
    with project_runtime(store):
        created = app.create(request_for_source(project))
    root = Path(created['plot'])
    if state == 'pending':
        app.patch(root, patch(created, 'first', 'style.line.width', '1.2pt', 'series:A'))
        app.rollback(root, {'base_revision': 1, 'target_revision': 0, 'idempotency_key': 'pending-undo'})
    snapshot = store.snapshot()
    entry = next(iter(read_index(store, snapshot)['attachments'].values()))
    # The pure creation adapter writes synthetic native bytes without a real
    # compiler marker. This control selects the documented missing-disposable
    # case; untracked/mutated existing bytes are tested separately below.
    output = Attachment(store, entry).output
    assert output is not None
    for product in output.glob('artifacts/*/document.vsz'):
        product.unlink()
    if state == 'missing-revision':
        name = entry['namespace'] + '/revisions/00000000.json'
        mutation = ProjectMutation({name: None}, {})
        command = ProjectCommand.create('semantic_record', 'missing-control', project_id=snapshot['project_id'],
            expected_generation=snapshot['generation'], read_set={name: snapshot['files'][name]['sha256']},
            write_set=[name], request={'prepared_digest': mutation.prepared_digest})
        ProjectCommands(store).publish_prepared(command, mutation)
        snapshot = store.snapshot()
    if state == 'unindexed':
        from sciplot_core.project_lifecycle.attachment_index import INDEX
        mutation = ProjectMutation({INDEX: None}, {})
        command = ProjectCommand.create('semantic_record', 'unindexed-control', project_id=snapshot['project_id'],
            expected_generation=snapshot['generation'], read_set={INDEX: snapshot['files'][INDEX]['sha256']},
            write_set=[INDEX], request={'prepared_digest': mutation.prepared_digest})
        ProjectCommands(store).publish_prepared(command, mutation)
        snapshot = store.snapshot()
    if state == 'foreign-plot':
        entry = {**entry, 'plot_id': 'foreign-plot'}
    if state == 'source-drift':
        (project / 'A.csv').write_text('Time,Signal\ns,V\n0,99\n1,88\n')
    # Even a physical refusal shell cannot replace missing Core members.
    from sciplot_core.plot_engine.storage import document_root
    shell = document_root(project, entry['figure_id'])
    shell.mkdir(parents=True, exist_ok=True)
    (shell / 'head.json').write_text('{"read_only_history":true}')
    before = inventory(tmp_path)
    monkeypatch.setattr(AttachedProjectRepository, '_materialize_history', lambda *_a: pytest.fail('Discovery materialized history.'))
    monkeypatch.setattr(subprocess, 'run', lambda *_a, **_k: pytest.fail('Discovery launched a native worker.'))
    if state == 'generation-race':
        monkeypatch.setattr(store, 'snapshot', lambda: {**snapshot, 'generation': 'later-generation'})
    if state in {'missing-revision', 'foreign-plot', 'generation-race', 'unindexed'}:
        with pytest.raises((OSError, ValueError, EngineError)):
            if state == 'unindexed':
                evidence.document_evidence(root)
            else:
                evidence.document_evidence(root, attachment=Attachment(store, entry), snapshot=snapshot)
    else:
        result = evidence.document_evidence(root)  # Direct Managed discovery uses the same Core reader.
        assert result['plot_id'] == created['plot_id']
        assert (result['pending'] is not None) == (state == 'pending')
        assert result['current'] is (state == 'current')
    assert inventory(tmp_path) == before


@pytest.mark.parametrize('ownership', ['unattached', 'retired', 'unindexed'])
def test_core_project_discovery_distinguishes_unattached_history_from_retired_or_unindexed_state(tmp_path, monkeypatch, ownership):
    from sciplot_core import task_saved_work_evidence as evidence
    from sciplot_core.project_store import FileProjectStore
    from sciplot_core.project_lifecycle.attachment_index import OWNER
    from sciplot_core.plot_engine.storage import document_root
    from test_plot_engine import FakeBackend

    source = tmp_path / 'original.csv'
    source.write_text('x,y\n1,2\n')
    project = legacy(tmp_path / 'project', source)
    if ownership == 'unindexed':
        orphan = project / '.sciplot_semantic' / ('a' * 32)
        orphan.mkdir(parents=True)
        (orphan / 'head.json').write_text('{"unindexed":true}')
    FileProjectStore(project).snapshot(import_legacy=True)
    root = document_root(project, 'curve')
    class ReadBackend(FakeBackend):
        def close(self):
            pass
    backend = ReadBackend(tmp_path / 'fake-native')
    document, binding = backend.initial()
    binding.update(project=str(project), figure_id='curve')
    commit(root, document, binding, 'unattached-history')
    if ownership == 'retired':
        (root / OWNER).write_text(json.dumps({'kind': 'sciplot_semantic_owner', 'version': 1,
            'origin_root': str(root), 'project': str(project), 'project_id': 'owned-project', 'attachment_id': 'b' * 32}))
    monkeypatch.setattr(evidence, 'BackendRouter', lambda *_a: backend)
    figure = {'figure_id': 'curve', 'title': 'Curve', 'document': str(project / 'studio/document.vsz'),
              'document_sha256': file_sha256(project / 'studio/document.vsz'),
              'spec': str(project / 'studio/spec.json'), 'spec_sha256': file_sha256(project / 'studio/spec.json')}
    monkeypatch.setattr(evidence, 'inspect_project', lambda *_a, **_k: {'figures': [figure],
        'source': {'current': True}, 'request_sha256': file_sha256(project / 'plot_request.json'), 'primary_figure_id': 'curve'})
    before = inventory(tmp_path)
    if ownership == 'unattached':
        result = evidence.project_evidence(project, source, source_tree_sha256(source))
        assert result['state'] == 'saved_project' and len(result['documents']) == 1
    else:
        with pytest.raises(ValueError):
            evidence.project_evidence(project, source, source_tree_sha256(source))
    assert inventory(tmp_path) == before


@pytest.mark.parametrize('projection', ['valid', 'unsupported-kind', 'mismatched-digest', 'duplicate'])
def test_saved_native_projection_id_is_a_typed_read_witness_not_a_file_path(tmp_path, monkeypatch, projection):
    from sciplot_core import task_saved_work_evidence as evidence
    from sciplot_core.project_commands.read_projections import projection_digest
    from test_plot_engine import FakeBackend

    project = tmp_path / 'native'
    project.mkdir()
    registry = project / 'studio/figure_set.json'
    registry.parent.mkdir()
    registry.write_text(json.dumps({'kind': 'sciplot_studio_figure_set', 'version': 1,
        'primary_figure_id': 'curve', 'figures': [{'figure_id': 'curve', 'status': 'ready'}]}))
    key = 'studio/figure_set.json:studio_figure_v1:curve'
    digest = projection_digest(registry.read_bytes(), kind='studio_figure_v1', key='curve')
    class ReadBackend(FakeBackend):
        def close(self):
            pass
        def fingerprint(self, binding):
            return {**super().fingerprint(binding), 'projections': {key:
                projection_digest(registry.read_bytes(), kind='studio_figure_v1', key='curve')}}
    backend = ReadBackend(project)
    document, binding = backend.initial()
    binding['projected_reads'] = [{'resource': 'studio/figure_set.json', 'kind': 'studio_figure_v1', 'key': 'curve', 'sha256': digest}]
    binding['fingerprint']['projections'] = {key: digest}
    if projection == 'unsupported-kind':
        binding['projected_reads'][0]['kind'] = 'arbitrary_selector'
    elif projection == 'mismatched-digest':
        binding['fingerprint']['projections'][key] = 'a' * 64
    elif projection == 'duplicate':
        binding['projected_reads'].append(dict(binding['projected_reads'][0]))
    root = tmp_path / 'semantic'
    commit(root, document, binding, 'native-with-projection')
    monkeypatch.setattr(evidence, 'BackendRouter', lambda *_a: backend)
    before = inventory(tmp_path)
    if projection == 'valid':
        assert evidence.document_evidence(root)['current'] is True
    else:
        with pytest.raises(ValueError):
            evidence.document_evidence(root)
    assert inventory(tmp_path) == before


@pytest.mark.parametrize('cache', ['absent', 'current-marker', 'mutated-native', 'missing-marker', 'owned-intent', 'alias'])
def test_real_managed_fingerprint_reads_only_its_finite_disposable_cache(tmp_path, monkeypatch, cache):
    from test_attached_semantic_repository import application
    from managed_plot_helpers import request_for_source
    from sciplot_core.project_store import FileProjectStore
    from sciplot_core.project_store.runtime import project_runtime
    from sciplot_core.project_lifecycle.attachment_index import Attachment, read_index
    from sciplot_core.project_lifecycle.attachment_projection import metadata_view
    from sciplot_core.project_lifecycle.frozen_namespace import FrozenNamespaceRepository
    from sciplot_core.plot_backends.managed import compiler_identity
    from sciplot_core import task_saved_work_evidence as evidence

    project = tmp_path / 'project'
    project.mkdir()
    store = FileProjectStore(project)
    store.snapshot(import_legacy=True)
    app = application()
    with project_runtime(store):
        created = app.create(request_for_source(project))
    root = Path(created['plot'])
    snapshot = store.snapshot()
    entry = next(iter(read_index(store, snapshot)['attachments'].values()))
    attachment = Attachment(store, entry)
    prefix = entry['namespace'] + '/'
    members = {name.removeprefix(prefix): store.read_bytes(name) for name in snapshot['files'] if name.startswith(prefix)}
    original = FrozenNamespaceRepository(attachment.origin, root, members).load_head(attachment.origin)
    binding = metadata_view(original, attachment)['binding']
    native = Path(binding['document'])
    native.unlink(missing_ok=True)  # Discard only the pure adapter's synthetic output.
    if cache != 'absent':
        native.parent.mkdir(parents=True, exist_ok=True)
        native.write_bytes(b'generated currentness-only native artifact; not a native scientific audit')
        if cache != 'missing-marker':
            (native.parent / 'build.json').write_text(json.dumps({'ir_hash': binding['ir_hash'], 'document_sha256': file_sha256(native)}))
        if cache == 'mutated-native':
            native.write_bytes(native.read_bytes() + b' external change')
        if cache == 'owned-intent':
            (native.parent / 'build.json').unlink()
            (native.parent / 'compile-intent.json').write_text(json.dumps({'ir_hash': binding['ir_hash'],
                'canonical_sha256': binding['canonical_sha256'], 'compiler_identity': compiler_identity(), 'compile_id': 'owned-control'}))
        if cache == 'alias':
            other = tmp_path / 'unselected-marker.json'
            (native.parent / 'build.json').rename(other)
            (native.parent / 'build.json').symlink_to(other)
    before = inventory(tmp_path)
    monkeypatch.setattr(subprocess, 'run', lambda *_a, **_k: pytest.fail('Currentness launched native compilation.'))
    if cache == 'alias':
        with pytest.raises(ValueError):
            evidence.document_evidence(root)
    else:
        result = evidence.document_evidence(root)
        assert result['current'] is (cache in {'absent', 'current-marker', 'owned-intent'})
    assert inventory(tmp_path) == before
    assert store.snapshot()['generation'] == snapshot['generation']


def test_real_managed_cold_source_currentness_does_not_materialize_a_source_view(tmp_path, monkeypatch):
    from test_attached_semantic_repository import application
    from managed_plot_helpers import request_for_source
    from sciplot_core.project_store import FileProjectStore
    from sciplot_core.project_store.runtime import project_runtime
    from sciplot_core.project_lifecycle.attachment_index import Attachment, read_index
    from sciplot_core import task_saved_work_evidence as evidence

    project = tmp_path / 'project'
    project.mkdir()
    external = tmp_path / 'original-sources'
    external.mkdir()
    wire = request_for_source(external)
    store = FileProjectStore(project)
    store.snapshot(import_legacy=True)
    with project_runtime(store):
        created = application().create(wire)
    bundle = store.export_bundle(tmp_path / 'bundle')
    project.rename(tmp_path / 'old-project')
    external.rename(tmp_path / 'offline-source')
    cold = FileProjectStore.import_bundle(bundle, tmp_path / 'cold-project')
    snapshot = cold.snapshot()
    entry = next(iter(read_index(cold, snapshot)['attachments'].values()))
    output = Attachment(cold, entry).output
    assert output is not None
    for product in output.glob('artifacts/*/document.vsz'):
        product.unlink()  # Query the canonical authority with disposable output absent.
    before = inventory(tmp_path)
    monkeypatch.setattr(subprocess, 'run', lambda *_a, **_k: pytest.fail('Discovery started a native process.'))
    result = evidence.document_evidence(cold.root / entry['namespace'])
    assert result['current'] and result['plot_id'] == created['plot_id']
    assert inventory(tmp_path) == before
    assert cold.snapshot()['generation'] == snapshot['generation']


def test_project_directory_names_do_not_hide_candidates(tmp_path):
    source = tmp_path / "raw.csv"
    source.write_text("x,y\n1,2\n")
    project = legacy(tmp_path / "raw", source)
    found = work.find_saved_work(source, search_roots=[tmp_path])
    assert found["matches"][0]["target"] == str(project)


def test_missing_history_still_finds_document_authority(managed):
    root, source, _ = managed
    found = work.find_saved_work(source, search_roots=[root])
    assert not found["tasks"] and found["matches"][0]["continuation_available"]


def test_missing_project_record_is_historical_and_never_recreated(tmp_path):
    source = tmp_path / "raw.csv"
    source.write_text("x,y\n1,2\n")
    task = receipt(tmp_path / "tasks/a", source, tmp_path / "gone")
    before = inventory(tmp_path)
    found = work.find_saved_work(source, search_roots=[task.parent])
    assert found["matches"][0]["state"] == "historical_task"
    continued = work.continue_saved_work(source, search_roots=[task.parent])
    assert continued["status"] == "blocked"
    assert continued["next_step"]["arguments"] == {"task": str(task)}
    assert inventory(tmp_path) == before and not (tmp_path / "gone").exists()


def test_task_for_renamed_source_is_findable_but_cannot_replay_original_location(tmp_path):
    source = tmp_path / "raw.csv"
    source.write_text("x,y\n1,2\n")
    task = receipt(tmp_path / "tasks/a", source)
    renamed = source.with_name("renamed.csv")
    source.rename(renamed)
    found = work.find_saved_work(renamed, search_roots=[task.parent])
    assert found["tasks"][0]["source_relation"] == "same_content_other_path"
    assert not found["tasks"][0]["resume_available"]
    assert work.continue_saved_work(renamed, search_roots=[task.parent])["status"] == "blocked"


def test_moved_task_receipt_is_not_treated_as_a_new_resumable_task(tmp_path):
    source = tmp_path / "raw.csv"
    source.write_text("x,y\n1,2\n")
    task = receipt(tmp_path / "tasks/a", source)
    task.rename(task.parent / "moved")
    found = work.find_saved_work(source, search_roots=[task.parent])
    assert found["tasks"] == [] and not found["scan_complete"]
    assert found["issues"][0]["reason_code"] == "invalid_task"


def test_snapshot_only_and_relocated_delivery_never_claim_current(tmp_path):
    source = tmp_path / "raw.csv"
    source.write_text("x,y\n1,2\n")
    package = delivery(tmp_path / "snapshot", source)
    copied = tmp_path / "copied-export"
    package.rename(copied)
    before = inventory(tmp_path)
    found = work.find_saved_work(source, search_roots=[copied])
    assert found["matches"][0]["state"] == "export_snapshot"
    continued = work.continue_saved_work(source, search_roots=[copied])
    assert continued["status"] == "blocked" and continued["reason_code"] == "export_snapshot"
    assert continued["ready_to_use"] is None and inventory(tmp_path) == before


def test_snapshot_with_missing_project_is_associated_only_by_valid_creation_receipt(tmp_path):
    source = tmp_path / "raw.csv"
    source.write_text("x,y\n1,2\n")
    gone = tmp_path / "gone"
    task = receipt(tmp_path / "tasks/a", source, gone)
    package = delivery(tmp_path / "snapshot", gone / "source", gone)
    copied_source = source.with_name("renamed.csv")
    shutil.copy2(source, copied_source)
    found = work.find_saved_work(copied_source, search_roots=[package, task.parent])
    snapshots = [item for item in found["matches"] if item["kind"] == "delivery"]
    assert snapshots[0]["state"] == "export_snapshot"
    assert snapshots[0]["recorded_source"] == str(source)
    assert work.continue_saved_work(copied_source, search_roots=[package, task.parent], target=package)["status"] == "blocked"


@pytest.mark.parametrize("change", ["bytes", "inventory"])
def test_unmerged_visible_edit_blocks_the_canonical_project_as_well(tmp_path, change):
    source = tmp_path / "raw.csv"
    source.write_text("x,y\n1,2\n")
    project = legacy(tmp_path / "owner", source)
    package = delivery(tmp_path / "visible", source, project)
    request = json.loads((project / "plot_request.json").read_text())
    request["delivery_output"] = str(package)
    (project / "plot_request.json").write_text(json.dumps(request))
    if change == "bytes":
        (package / "project/figure.vsz").write_text("visible saved edits")
    else:
        (package / "project/second.vsz").write_text("another saved native figure")
    before = inventory(tmp_path)
    found = work.find_saved_work(source, search_roots=[project, package])
    owner = next(item for item in found["matches"] if item["target"] == str(project))
    assert owner["state"] == "visible_edits_require_recovery" and not owner["continuation_available"]
    continued = work.continue_saved_work(source, search_roots=[project, package], target=project)
    assert continued["reason_code"] == "visible_edits_require_recovery"
    narrow = work.continue_saved_work(source, search_roots=[project], target=project)
    assert narrow["reason_code"] == "visible_edits_require_recovery"
    assert inventory(tmp_path) == before


@pytest.mark.parametrize("fault", ["symlink_source", "symlink_scope", "symlink_record", "malformed_path", "malformed_json"])
def test_unsafe_or_malformed_paths_fail_closed(tmp_path, fault):
    source = tmp_path / "raw.csv"
    source.write_text("x,y\n1,2\n")
    task = receipt(tmp_path / "tasks/a", source)
    if fault == "symlink_source":
        linked = source.with_name("linked.csv")
        linked.symlink_to(source)
        with pytest.raises(ValueError, match="symlink"):
            work.find_saved_work(linked, search_roots=[task.parent])
    elif fault == "symlink_scope":
        linked = tmp_path / "linked"
        linked.symlink_to(task.parent, target_is_directory=True)
        with pytest.raises(ValueError, match="symlink"):
            work.find_saved_work(source, search_roots=[linked])
    else:
        if fault == "symlink_record":
            original = task / "task.json"
            original.rename(task / "original.json")
            original.symlink_to(task / "original.json")
        elif fault == "malformed_json":
            (task / "task.json").write_text("broken JSON")
        else:
            state = json.loads((task / "task.json").read_text())
            state["project"] = ""
            save_task(task, state)
        found = work.find_saved_work(source, search_roots=[task.parent])
        assert not found["scan_complete"] and found["issue_count"]
        assert work.continue_saved_work(source, search_roots=[task.parent])["status"] == "blocked"


def test_scan_and_read_budgets_do_not_hide_unknown_candidates(managed, tmp_path, monkeypatch):
    root, source, _ = managed
    monkeypatch.setattr(work, "MAX_SCAN_ENTRIES", 1)
    found = work.find_saved_work(source, search_roots=[tmp_path])
    assert not found["scan_complete"] and found["selection_required"]
    monkeypatch.setattr(work, "MAX_SCAN_ENTRIES", 2000)
    monkeypatch.setattr(work, "MAX_RECORD_BYTES", 1)
    found = work.find_saved_work(source, search_roots=[root])
    assert not found["scan_complete"] and not found["matches"]


def test_default_scopes_are_source_adjacent_named_paths_and_broad_scopes_are_rejected(managed):
    _, source, _ = managed
    found = work.find_saved_work(source)
    assert str(source.parent) not in found["search_roots"]
    assert all(Path(path).parent == source.parent or Path(path).parent.parent == source.parent
               for path in found["search_roots"])
    with pytest.raises(TaskControlError, match="too broad"):
        work.find_saved_work(source, search_roots=[Path("/")])
    with pytest.raises(TaskControlError):
        work.find_saved_work(source, search_roots=[])


def test_explicit_target_must_belong_to_discovered_candidates(managed, tmp_path):
    root, source, _ = managed
    result = work.continue_saved_work(source, search_roots=[root], target=tmp_path / "other")
    assert result["status"] == "blocked" and result["reason_code"] == "selected_target_not_discovered"
