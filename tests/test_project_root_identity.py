"""Host root identity is separate from current delivery/source byte evidence."""

import shutil
import json
import stat

import pytest

from sciplot_core.foundation.source_locations import literal_source_path
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.launchers.delivery_binding import delivery_binding_from_content
from sciplot_core.project_store import FileProjectStore, ResourceRoot
from sciplot_core.project_host_factory import project_store
from sciplot_core.project_store.io import StoreIO
from sciplot_core.project_store.physical_projection import literal_project_root
from sciplot_core.project_store.runtime import literal_runtime_project_root, project_runtime
from sciplot_core.studio_core.delivery_target import _managed_project
from sciplot_core.studio_core.preparation_candidate import studio_preparation_candidate
from test_project_delivery_runtime import _project_and_delivery


def _inventory(root):
    return {str(path.relative_to(root)): (path.read_bytes(), path.stat().st_mode, path.stat().st_mtime_ns)
            for path in root.rglob("*") if path.is_file()}


def test_exact_root_identity_does_not_read_members_or_certify_their_science(tmp_path, monkeypatch):
    project, delivery, store = _project_and_delivery(tmp_path)
    native = next((delivery / "project").glob("*.vsz"))
    native.write_bytes(native.read_bytes() + b"\nvisible user edit")
    before = _inventory(tmp_path)
    with project_runtime(store):
        with pytest.raises(ValueError, match="changed outside"):
            literal_source_path(delivery)
        def forbidden(*_args, **_kwargs):
            raise AssertionError("Root identity must not read or certify member bytes")
        with monkeypatch.context() as guard:
            guard.setattr(StoreIO, "physical", forbidden)
            assert literal_runtime_project_root(delivery) == str(delivery)
            assert literal_runtime_project_root(project) == str(project)
    assert _inventory(tmp_path) == before


def test_visible_edit_reaches_managed_ownership_without_becoming_source_evidence(tmp_path):
    project, delivery, store = _project_and_delivery(tmp_path)
    binding = delivery_binding_from_content((delivery / "Open_in_Veusz.command").read_text())
    assert binding is not None
    native = next((delivery / "project").glob("*.vsz"))
    native.write_bytes(native.read_bytes() + b"\nvisible user edit")
    before = _inventory(tmp_path)
    with project_runtime(store):
        assert _managed_project(delivery, binding) == project
        with pytest.raises(ValueError, match="differs from the registered generation"):
            store.resolve_path(native)
    assert _inventory(tmp_path) == before


def test_recovery_state_capture_observes_source_trees_without_creating_views(tmp_path, monkeypatch):
    from test_delivery_recovery import recoverable
    from sciplot_core.studio_core.delivery_recovery_state import capture_recovery_state

    project, document, candidate = recoverable.__wrapped__(tmp_path, monkeypatch)
    store = project_store(project)
    store.snapshot(import_legacy=True)
    expected = json.loads((project / "plot_request.json").read_bytes())["resolved_figure_plan"]["source_sha256"]
    before = _inventory(tmp_path)
    assert not (project / ".sciplot_store/directories").exists()
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Recovery state capture must not write Store metadata or source views")
    monkeypatch.setattr(StoreIO, "write", forbidden)
    with project_runtime(store):
        state = capture_recovery_state(project, candidate)
    assert state["hashes"]["candidate"] == file_sha256(candidate)
    assert state["hashes"]["document"] == file_sha256(document)
    assert state["fingerprints"]["source"] == expected
    assert _inventory(tmp_path) == before


@pytest.mark.parametrize("change", ["missing", "extra", "archive_extra", "mode", "alias"])
def test_recovery_tree_observation_keeps_full_namespace_and_version_guards(tmp_path, monkeypatch, change):
    from test_delivery_recovery import recoverable
    from sciplot_core.studio_core.delivery_recovery_state import capture_recovery_state

    project, _document, candidate = recoverable.__wrapped__(tmp_path, monkeypatch)
    store = project_store(project)
    store.snapshot(import_legacy=True)
    source = project / "source/sample.csv"
    if change == "missing":
        source.unlink()
    elif change == "extra":
        (source.parent / "foreign.csv").write_bytes(source.read_bytes())
    elif change == "archive_extra":
        (project / "runs/studio_001/raw/source/foreign.csv").write_bytes(source.read_bytes())
    elif change == "mode":
        original_mode = stat.S_IMODE(source.stat().st_mode)
        source.chmod(original_mode ^ stat.S_IWUSR)
        assert stat.S_IMODE(source.stat().st_mode) != original_mode
    else:
        foreign = tmp_path / "foreign.csv"
        foreign.write_bytes(source.read_bytes())
        source.unlink()
        source.symlink_to(foreign)
    before = _inventory(tmp_path)
    with project_runtime(store), pytest.raises(ValueError):
        capture_recovery_state(project, candidate)
    assert _inventory(tmp_path) == before


def test_recovery_audits_observed_visible_bytes_before_admitting_an_adoption(tmp_path, monkeypatch):
    from sciplot_core.studio_core import delivery_recovery, native_scientific_audit

    project, delivery, store = _project_and_delivery(tmp_path)
    document = project / "studio/document.vsz"
    visible = next((delivery / "project").glob("*.vsz"))
    visible.write_bytes(visible.read_bytes() + b"\nobserved visible edit")
    observed = visible.read_bytes()
    evidence = {"project": str(project), "document": str(document), "candidate": str(visible),
                "hashes": {"baseline": file_sha256(document), "document": file_sha256(document),
                           "candidate": file_sha256(visible)}}
    monkeypatch.setattr(delivery_recovery, "capture_recovery_state", lambda *_args: evidence)
    audits = []
    def reject(candidate, spec, **_kwargs):
        audits.append(candidate)
        assert candidate != visible and candidate.read_bytes() == observed
        assert spec == project / "studio/spec.json"
        raise ValueError("controlled scientific audit rejected the observed data")
    monkeypatch.setattr(native_scientific_audit, "audit_native_candidate", reject)
    before = _inventory(tmp_path)
    generation = store.snapshot()["generation"]
    review = delivery_recovery.preview_delivery_recovery(project)
    assert review["status"] == "blocked" and review["ready_to_apply"] is False
    assert review["message"] == "controlled scientific audit rejected the observed data"
    assert len(audits) == 1 and not audits[0].exists()
    assert store.snapshot()["generation"] == generation and store.commands() == ()
    assert _inventory(tmp_path) == before


@pytest.mark.parametrize("change", [None, "raw", "spec", "visible", "foreign_source"])
def test_observed_recovery_audit_keeps_exact_native_spec_and_source_versions(tmp_path, monkeypatch, change):
    from sciplot_core.studio_core import delivery_recovery, native_scientific_audit

    project, delivery, store = _project_and_delivery(tmp_path)
    document, spec = project / "studio/document.vsz", project / "studio/spec.json"
    source = project / "source/data.csv"
    visible = next((delivery / "project").glob("*.vsz"))
    visible.write_bytes(visible.read_bytes() + b"\nvisible user edit")
    before = document.read_bytes()
    evidence = {"project": str(project), "document": str(document), "candidate": str(visible),
                "hashes": {"baseline": file_sha256(document), "document": file_sha256(document),
                           "candidate": file_sha256(visible)}}
    monkeypatch.setattr(delivery_recovery, "capture_recovery_state", lambda *_args: evidence)
    audits = []
    foreign = tmp_path / "foreign.csv"
    foreign.write_bytes(source.read_bytes())
    def audit(candidate, expected_spec, **_kwargs):
        assert candidate != visible and candidate.read_bytes() == visible.read_bytes()
        assert expected_spec == spec
        audits.append(candidate)
        if change == "raw":
            source.write_bytes(source.read_bytes() + b"changed science")
        elif change == "spec":
            spec.write_bytes(spec.read_bytes() + b" ")
        elif change == "visible":
            visible.write_bytes(visible.read_bytes() + b"concurrent edit")
        elif change == "foreign_source":
            value = json.loads(spec.read_bytes())
            value["series"][0]["source_artifacts"][0]["path"] = str(foreign)
            spec.write_text(json.dumps(value))
        return {"status": "passed", "unit_count": 1, "prepared_unit_count": 1}
    monkeypatch.setattr(native_scientific_audit, "audit_native_candidate", audit)
    original_read = type(foreign).read_bytes
    def checked_read(path):
        assert path != foreign, "A foreign source cannot gain read authority from a changed specification"
        return original_read(path)
    monkeypatch.setattr(type(foreign), "read_bytes", checked_read)
    generation = store.snapshot()["generation"]
    review = delivery_recovery.preview_delivery_recovery(project, _stage=False)
    if change is None:
        assert review["status"] == "ready" and review["ready_to_apply"] is True
        assert review["scientific_audit"]["document_sha256"] == file_sha256(visible)
    else:
        assert review["status"] == "blocked" and review["ready_to_apply"] is False
    assert len(audits) == 1 and not audits[0].exists()
    assert document.read_bytes() == before
    assert store.snapshot()["generation"] == generation and store.commands() == ()


@pytest.mark.parametrize("kind", ["foreign", "child", "alias", "finite", "unregistered_cap", "replacement"])
def test_root_identity_cannot_expand_or_rebind_a_host_capability(tmp_path, kind):
    project, delivery, store = _project_and_delivery(tmp_path)
    selected = delivery
    if kind == "foreign":
        selected = tmp_path / "same-bytes-foreign"
        shutil.copytree(delivery, selected)
    elif kind == "child":
        selected = delivery / "project"
    elif kind == "alias":
        selected = tmp_path / "alias"
        selected.symlink_to(delivery, target_is_directory=True)
    elif kind == "finite":
        store = FileProjectStore(project, locations={"delivery": ResourceRoot(delivery, ("Open_in_Veusz.command",))})
    elif kind == "unregistered_cap":
        selected = tmp_path / "new-host-cap"
        selected.mkdir()
        store = FileProjectStore(project, locations={"delivery": delivery, "other": selected})
    else:
        delivery.rename(tmp_path / "preserved-original")
        delivery.mkdir()
    before = _inventory(tmp_path)
    with pytest.raises(ValueError):
        literal_project_root(store, selected)
    assert _inventory(tmp_path) == before


def test_official_cold_root_identity_uses_the_host_binding_not_a_surviving_origin(tmp_path):
    project, delivery, store = _project_and_delivery(tmp_path)
    bundle = store.export_bundle(tmp_path / "bundle")
    project.rename(tmp_path / "offline-project")
    delivery.rename(tmp_path / "offline-delivery")
    delivery.mkdir()  # A surviving old absolute name supplies no authority.
    moved = FileProjectStore.import_bundle(bundle, tmp_path / "moved")
    binding = delivery_binding_from_content((moved.locations["delivery"] / "Open_in_Veusz.command").read_text())
    assert binding is not None
    before = _inventory(tmp_path)
    with project_runtime(moved):
        assert literal_runtime_project_root(moved.root) == str(project)
        assert literal_runtime_project_root(moved.locations["delivery"]) == str(delivery)
        assert _managed_project(moved.locations["delivery"], binding) == moved.root
        with pytest.raises(ValueError, match="exact bound"):
            literal_runtime_project_root(delivery)
    assert _inventory(tmp_path) == before


def test_private_candidate_is_not_a_current_host_root(tmp_path):
    _project, _delivery, store = _project_and_delivery(tmp_path)
    with studio_preparation_candidate(store) as candidate:
        with pytest.raises(ValueError, match="private candidate"):
            literal_runtime_project_root(candidate.project_dir)


def test_standalone_root_keeps_its_existing_literal_without_gaining_a_store(tmp_path):
    assert literal_runtime_project_root(tmp_path) == literal_source_path(tmp_path)
    assert not (tmp_path / ".sciplot_store").exists()


@pytest.mark.parametrize("store_shaped", [False, True])
def test_root_identity_cannot_initialize_or_import_an_unregistered_project(tmp_path, store_shaped):
    project = tmp_path / "unregistered"
    project.mkdir()
    (project / "source.csv").write_bytes(b"protected input")
    if store_shaped:
        (project / ".sciplot_store").mkdir()
    before, names = _inventory(tmp_path), set(tmp_path.rglob("*"))
    with pytest.raises(ValueError):
        literal_project_root(FileProjectStore(project), project)
    assert _inventory(tmp_path) == before and set(tmp_path.rglob("*")) == names


def test_private_publication_keeps_the_selected_logical_run_name(tmp_path, monkeypatch):
    from sciplot_core.studio_core import publication_prepare
    from sciplot_core.studio_core.project_publication_commands import publish_project_exports

    project, _delivery, store = _project_and_delivery(tmp_path)
    document = project / "studio/document.vsz"
    generation = store.snapshot()["generation"]
    observed = []
    def prepare(**kwargs):
        output = kwargs["output_dir"]
        observed.append(output)
        assert not output.is_relative_to(project)
        assert output.name == "studio_002"
        raise RuntimeError("controlled stop before publication")
    monkeypatch.setattr(publication_prepare, "prepare_studio_export_run", prepare)
    before = _inventory(tmp_path)
    with pytest.raises(RuntimeError, match="controlled stop"):
        publish_project_exports(project_dir=project, request_path=project / "plot_request.json",
            document_path=document, exports=[{"format": "pdf", "path": str(project / "runs/studio_001/document.pdf")}])
    assert len(observed) == 1 and not observed[0].exists()
    assert store.snapshot()["generation"] == generation and store.commands() == ()
    assert _inventory(tmp_path) == before
