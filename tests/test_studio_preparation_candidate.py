"""Private producer failures cannot expose a partial recognized project."""

from io import BytesIO
import json
from zipfile import ZipFile

import pytest

from sciplot_core.project_commands import PreparedFile
from sciplot_core.project_store import FileProjectStore, ProjectConflict
from sciplot_core.project_store.adapters import publish_files
from sciplot_core.studio_core import preparation_commands as commands
from sciplot_core.studio_core.preparation_candidate import (
    install_prepared_figure_set, studio_preparation_candidate,
)


def fixture_store(tmp_path, *, intake=False):
    root = tmp_path / "project"
    (root / "source").mkdir(parents=True)
    (root / "studio").mkdir()
    (root / "source/data.csv").write_bytes(b"x,y\n1,2\n")
    (root / "studio/document.vsz").write_bytes(b"saved manual native")
    (root / "studio/spec.json").write_text('{"scientific_sha256":"retained"}')
    (root / "plot_request.json").write_text(json.dumps({"input": str(root / "source/data.csv"),
        "output": str(root / "runs/old"), "transform_ledger": {"source": str(root / "source/data.csv")}}))
    if intake:
        (root / "intake_manifest.json").write_text('{"project_slug":"project"}')
    store = FileProjectStore(root)
    before = store.snapshot(import_legacy=True)
    return root, store, before


def test_private_candidate_captures_files_and_modes_without_an_authority(tmp_path):
    root, store, before = fixture_store(tmp_path)
    with studio_preparation_candidate(store, snapshot=before) as candidate:
        assert candidate.project_dir != root
        assert not (candidate.project_dir / ".sciplot_store").exists()
        target = candidate.project_dir / "Open.command"
        target.write_bytes(b"portable launcher")
        target.chmod(0o755)
        assert candidate.capture() == {"Open.command": PreparedFile(b"portable launcher", 0o755)}
        assert store.snapshot()["generation"] == before["generation"]
        assert not (root / "Open.command").exists()


def test_frozen_private_deletion_is_idempotent_and_cannot_delete_originals_or_follow_aliases(tmp_path):
    root, store, before = fixture_store(tmp_path)
    native = root / "studio/document.vsz"
    original = native.read_bytes(), native.stat().st_mtime_ns
    with studio_preparation_candidate(store) as candidate:
        candidate.remove_member("studio/document.vsz")
        candidate.remove_member("studio/document.vsz")
        assert candidate.capture() == {"studio/document.vsz": None}
        with pytest.raises(ProjectConflict, match="scientific inputs"):
            candidate.remove_member("source/data.csv")
        alias = candidate.project_dir / "studio/alias.vsz"
        alias.symlink_to(native)
        with pytest.raises(OSError):
            candidate.remove_member("studio/alias.vsz")
        assert alias.is_symlink()
    assert (native.read_bytes(), native.stat().st_mtime_ns) == original
    assert store.snapshot()["generation"] == before["generation"]
    assert not candidate.project_dir.exists()


def test_failed_private_preparation_preserves_every_active_member(tmp_path, monkeypatch):
    root, store, before = fixture_store(tmp_path)
    original = {name: store.read_bytes(name) for name in before["files"]}

    def fail(candidate, **_kwargs):
        (candidate.project_dir / "plot_request.json").write_text('{"new":"request"}')
        (candidate.project_dir / "studio/document.vsz").write_bytes(b"partial native")
        raise RuntimeError("native failure after private primary")

    monkeypatch.setattr(commands, "prepare_studio_candidate", fail)
    with pytest.raises(RuntimeError, match="after private primary"):
        commands.prepare_studio_generation(root)
    assert store.snapshot()["generation"] == before["generation"]
    assert {name: store.read_bytes(name) for name in before["files"]} == original
    assert {name: (root / name).read_bytes() for name in before["files"]} == original


def test_private_candidate_rejects_source_changes_and_aliases(tmp_path):
    root, store, before = fixture_store(tmp_path)
    with studio_preparation_candidate(store, snapshot=before) as candidate:
        (candidate.project_dir / "source/data.csv").write_bytes(b"scientific replacement")
        with pytest.raises(ProjectConflict, match="scientific inputs"):
            candidate.capture()
    with studio_preparation_candidate(store, snapshot=before) as candidate:
        (candidate.project_dir / "alias").symlink_to(root / "plot_request.json")
        with pytest.raises(ProjectConflict, match="aliased"):
            candidate.capture()
    assert (root / "source/data.csv").read_bytes() == b"x,y\n1,2\n"


def test_private_host_projection_never_rewrites_scientific_payload(tmp_path):
    root, store, before = fixture_store(tmp_path)
    with studio_preparation_candidate(store, snapshot=before) as candidate:
        source_literal = str(candidate.project_dir / "source/data.csv")
        request = {"input": source_literal, "transform_ledger": {"literal": source_literal},
                   "resolved_figure_plan": {"outcomes": [{"artifacts": [str(candidate.project_dir / "studio/document.vsz")]}]}}
        projected = candidate.project_payload(request)
        assert projected["input"] == source_literal
        assert projected["transform_ledger"] == request["transform_ledger"]
        assert projected["resolved_figure_plan"]["outcomes"][0]["artifacts"] == [str(root / "studio/document.vsz")]
        assert request["resolved_figure_plan"]["outcomes"][0]["artifacts"] == [str(candidate.project_dir / "studio/document.vsz")]


def test_publication_artifact_and_ledger_keep_original_literals_under_private_io(tmp_path):
    root, store, before = fixture_store(tmp_path)
    from sciplot_core.publication.artifacts import artifact_record
    from sciplot_core.publication.transform_ledger import build_transform_ledger

    source = root / "source/data.csv"
    expected = artifact_record(source, artifact_id="raw", role="input")
    expected_ledger = build_transform_ledger({}, request={}, input_path=source)
    with studio_preparation_candidate(store, snapshot=before) as candidate:
        private = candidate.project_dir / "source/data.csv"
        assert artifact_record(private, artifact_id="raw", role="input") == expected
        assert build_transform_ledger({}, request={}, input_path=private) == expected_ledger
        derived = candidate.project_dir / "studio/derived.csv"
        derived.write_bytes(b"x,y\n1,2\n")
        assert artifact_record(derived, artifact_id="derived", role="output")["path"] == str(root / "studio/derived.csv")


def test_verified_source_request_is_constructed_without_allocating_or_mutating(tmp_path):
    from copy import deepcopy
    from sciplot_core.studio_core.project_creation import request_from_verified_plan

    source = tmp_path / "confirmed.csv"
    source.write_bytes(b"x,y\n1,2\n")
    project = tmp_path / "not_allocated"
    verified = {"rule_id": "uvvis_spectrum", "template": "curve",
                "source_options": {"render_options": {"line_width": 1.5}},
                "resolved_figure_plan": {"outcomes": []}}
    original = deepcopy(verified)
    request = request_from_verified_plan(source, verified=verified, project_dir=project,
                                         delivery_root=tmp_path / "delivery")
    assert not project.exists()
    assert request["input"] == str(source)
    assert request["output"] == str(project / "runs/run_001")
    request["render_options"]["line_width"] = 2
    request["resolved_figure_plan"]["outcomes"].append({"example": "only result"})
    assert verified == original


def test_explicit_new_source_outside_finite_snapshot_cap_is_not_its_parent_member(tmp_path):
    root, _store, _before = fixture_store(tmp_path)
    from sciplot_core.foundation.source_locations import resolve_source_path
    from sciplot_core.project_manifest import _manifest_store

    incoming = tmp_path / "incoming.csv"
    incoming.write_bytes(b"x,y\n1,3\n")
    store = _manifest_store(root)
    assert store.location_members["snapshot"] == ("project.zip",)
    with studio_preparation_candidate(store) as _candidate:
        assert resolve_source_path(incoming) == incoming


def test_active_figure_install_requires_the_explicit_private_context(tmp_path):
    root, _store, _before = fixture_store(tmp_path)
    with pytest.raises(ProjectConflict, match="host-owned private"):
        install_prepared_figure_set(project_dir=root, replacements=[], manual_archive_requests=[], registry=None)


def test_private_install_refuses_aliased_parent_before_touching_active_bytes(tmp_path):
    import shutil
    from sciplot_core.project_store.io import sha

    root, store, before = fixture_store(tmp_path)
    old_native = (root / "studio/document.vsz").read_bytes()
    with studio_preparation_candidate(store, snapshot=before) as candidate:
        staged = candidate.project_dir / "new.vsz"
        staged.write_bytes(b"complete private replacement")
        shutil.rmtree(candidate.project_dir / "studio")
        (candidate.project_dir / "studio").symlink_to(root / "studio", target_is_directory=True)
        with pytest.raises(OSError):
            install_prepared_figure_set(project_dir=candidate.project_dir,
                replacements=[{"staged": staged, "target": candidate.project_dir / "studio/document.vsz",
                               "expected_hash": sha(staged.read_bytes()), "kind": "document"}],
                manual_archive_requests=[], registry=None)
        assert (root / "studio/document.vsz").read_bytes() == old_native
    assert store.snapshot()["generation"] == before["generation"]


def test_unchanged_legacy_reuse_keeps_audit_unevaluated_without_inventing_science(tmp_path, monkeypatch):
    _root, store, before = fixture_store(tmp_path)
    from sciplot_core.source_coverage import document_audit

    def forbidden(**_kwargs):
        raise AssertionError("Unchanged metadata reuse must not execute a new scientific/native audit")

    monkeypatch.setattr(document_audit, "_audit_exact_document_data", forbidden)
    with studio_preparation_candidate(store, snapshot=before) as candidate:
        payload = {"document": str(candidate.project_dir / "studio/document.vsz"),
                   "preserved_existing_document": True}
        audits, _sources = commands.audit_studio_candidate(candidate, payload)
        assert audits == [{"kind": "sciplot_unchanged_native_preparation", "status": "not_evaluated",
                           "reason": "exact_native_preimage_preserved",
                           "sha256": before["files"]["studio/document.vsz"]["sha256"]}]


def test_unchanged_native_with_changed_spec_cannot_skip_the_real_audit(tmp_path, monkeypatch):
    _root, store, before = fixture_store(tmp_path)
    from sciplot_core.source_coverage import document_audit

    def required(**_kwargs):
        raise RuntimeError("real native/spec audit reached")

    monkeypatch.setattr(document_audit, "_audit_exact_document_data", required)
    with studio_preparation_candidate(store, snapshot=before) as candidate:
        (candidate.project_dir / "studio/spec.json").write_text('{"different":"scientific declaration"}')
        payload = {"document": str(candidate.project_dir / "studio/document.vsz"),
                   "preserved_existing_document": True}
        with pytest.raises(RuntimeError, match="native/spec audit reached"):
            commands.audit_studio_candidate(candidate, payload)


def test_explicit_scientific_audit_scope_still_executes_the_native_audit(tmp_path, monkeypatch):
    _root, store, before = fixture_store(tmp_path)
    from sciplot_core.source_coverage import document_audit

    def scientific(**kwargs):
        assert kwargs["check_presentation"] is False
        raise RuntimeError("exact scientific audit reached")

    monkeypatch.setattr(document_audit, "_audit_exact_document_data", scientific)
    with studio_preparation_candidate(store, snapshot=before) as candidate:
        payload = {"document": str(candidate.project_dir / "studio/document.vsz"),
                   "preserved_existing_document": True}
        with pytest.raises(RuntimeError, match="exact scientific audit reached"):
            commands.audit_studio_candidate(candidate, payload, check_presentation=False)


@pytest.mark.parametrize("case", ["saved", "source", "spec", "request", "other-member", "second-native",
                                  "unknown", "regenerate", "rule-override", "request-target", "delivery-override"])
def test_saved_native_reopen_preparation_admits_only_the_explicit_reuse_baseline(tmp_path, monkeypatch, case):
    import subprocess

    from test_series_display import _saved_native_baseline
    from sciplot_core.foundation.source_locations import selected_source_resolver
    from sciplot_core.project_commands import ProjectCommand

    root, store, before, document, audits = _saved_native_baseline(tmp_path, monkeypatch)
    saved = document.read_bytes()
    options = {}
    if case in {"source", "spec", "request", "other-member", "second-native"}:
        member = {"source": "source/data.csv", "spec": "studio/spec.json", "request": "plot_request.json",
                  "other-member": "unregistered-note.txt", "second-native": "studio/figures/second.vsz"}[case]
        path = root / member
        path.write_bytes((path.read_bytes() if path.exists() else b"") + b" changed outside")
    elif case == "unknown":
        command = ProjectCommand.create("style", "unknown-preparation-baseline", project_id=before["project_id"],
            expected_generation=before["generation"], read_set={}, write_set=[], request={})
        store.reserve(command.key, command.command_digest, expected_generation=before["generation"],
                      read_set={}, write_set=[], metadata=command.to_payload())
        store.mark_applying(command.key, command.command_digest)
    elif case == "regenerate":
        options["regenerate_generated"] = True
    elif case == "rule-override":
        options["rule_id"] = "uvvis_spectrum"
    elif case == "request-target":
        options["request_target"] = True
    elif case == "delivery-override":
        options["delivery_root"] = tmp_path / "different-visible"
    records = store.commands()
    physical = {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*")
                if path.is_file() and ".sciplot_store" not in path.relative_to(root).parts}
    reached = []

    class PreparedReached(RuntimeError):
        pass

    def no_process(*_args, **_kwargs):
        pytest.fail("This host admission counter must not start a native process.")

    def prepared(candidate, **_kwargs):
        current = store.snapshot()
        assert not current["outside_changes"]
        assert candidate.snapshot["generation"] == selected_source_resolver().snapshot["generation"] == current["generation"]
        assert candidate.read_member("studio/document.vsz").data == saved
        assert len(audits) == 1
        reached.append(current["generation"])
        raise PreparedReached("reconciled exact-current private preparation")

    monkeypatch.setattr(subprocess, "Popen", no_process)
    monkeypatch.setattr(commands, "prepare_studio_candidate", prepared)
    if case == "saved":
        with pytest.raises(PreparedReached, match="reconciled exact-current"):
            commands.prepare_studio_generation(root, **options)
        assert len(reached) == 1 and reached[0] != before["generation"]
        assert len(store.commands()) == 1 and store.commands()[0]["metadata"]["kind"] == "native_import"
        assert store.commands()[0]["phase"] == "complete"
        after = store.snapshot()
        for name in before["files"]:
            if name != "studio/document.vsz":
                assert after["files"][name] == before["files"][name]
    else:
        with pytest.raises((ValueError, OSError)):
            commands.prepare_studio_generation(root, **options)
        assert not reached and not audits and store.commands() == records
        assert store.snapshot()["generation"] == before["generation"]
    assert document.read_bytes() == saved
    assert {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*")
            if path.is_file() and ".sciplot_store" not in path.relative_to(root).parts} == physical


def test_real_managed_binding_artifact_cannot_acquire_saved_studio_admission(tmp_path, monkeypatch):
    import subprocess
    from pathlib import Path

    from test_managed_source_append import bound_document
    from test_series_display import _saved_native_baseline
    from sciplot_core.plot_engine.managed_state import make_binding
    from sciplot_core.studio_core import request_overrides, studio_prepare

    def no_process(*_args, **_kwargs):
        pytest.fail("This managed-routing counter must not start a native process.")

    monkeypatch.setattr(subprocess, "Popen", no_process)
    root, store, before, document, audits = _saved_native_baseline(tmp_path, monkeypatch)
    managed_source = tmp_path / "managed-source"
    managed_source.mkdir()
    managed = bound_document(managed_source)
    binding = make_binding(managed_source / "store", managed, output=root / "managed-output")
    assert managed["plot_type"] == "ManagedPlot" and binding["kind"] == "sciplot_managed_binding"
    native = Path(binding["document"])
    native.parent.mkdir(parents=True)
    native.write_bytes(binding["ir_hash"].encode())  # Existing lifecycle fixture's synthetic native adapter.
    original_source = (managed_source / "figure.csv").read_bytes()
    saved = document.read_bytes()
    # The existing whole-set guard may reject this owned output before the
    # narrower saved-primary admission; neither path may register its bytes.
    with pytest.raises(ProjectConflict):
        commands.prepare_studio_generation(root)
    monkeypatch.setattr(request_overrides, "upstream_status", lambda: {"veusz": {"fixture": True}})
    readonly = studio_prepare.prepare_studio_document(native)
    assert readonly["mode"] == "vsz" and readonly["document"] == str(native)
    assert not store.commands() and not audits and store.snapshot()["generation"] == before["generation"]
    assert document.read_bytes() == saved and native.read_bytes() == binding["ir_hash"].encode()
    assert (managed_source / "figure.csv").read_bytes() == original_source


def test_source_identity_is_stable_across_versions_and_never_reconnected_by_name():
    from copy import deepcopy

    snapshot = {"project_id": "1" * 32,
                "sources": {"7" * 32: {"a" * 64: {"locator": "/original/data.csv"}}}}
    before = deepcopy(snapshot)
    assert commands.source_identity_for_locator(snapshot, "/original/data.csv") == "7" * 32
    snapshot["sources"]["7" * 32]["b" * 64] = {"locator": "/original/data.csv"}
    assert commands.source_identity_for_locator(snapshot, "/original/data.csv") == "7" * 32
    assert commands.source_identity_for_locator(snapshot, "/elsewhere/data.csv") != "7" * 32
    assert before["sources"]["7" * 32] == {"a" * 64: {"locator": "/original/data.csv"}}
    snapshot["sources"]["8" * 32] = {"c" * 64: {"locator": "/original/data.csv"}}
    with pytest.raises(ValueError, match="ambiguous"):
        commands.source_identity_for_locator(snapshot, "/original/data.csv")


def _prepared(candidate, **_kwargs):
    root = candidate.project_dir
    (root / "studio/document.vsz").write_bytes(b"complete private native")
    return {"kind": "sciplot_studio_prepare", "project_dir": str(root),
            "request": str(root / "plot_request.json"), "document": str(root / "studio/document.vsz"),
            "studio": {"document": str(root / "studio/document.vsz")}}


def test_complete_preparation_publishes_one_generation_and_same_zip(tmp_path, monkeypatch):
    root, _store, _before = fixture_store(tmp_path, intake=True)
    # This fixture's initial Intake manifest is present before import. These
    # pure controls do not claim native/scientific runtime acceptance.
    from sciplot_core.project_manifest import _manifest_store

    store = _manifest_store(root)
    before = store.snapshot()
    monkeypatch.setattr(commands, "prepare_studio_candidate", _prepared)
    monkeypatch.setattr(commands, "audit_studio_candidate", lambda *_args: ([], []))
    result = commands.prepare_studio_generation(root)
    after = store.snapshot()
    assert after["sequence"] == before["sequence"] + 1
    assert result["document"] == str(root / "studio/document.vsz")
    assert (root / "studio/document.vsz").read_bytes() == b"complete private native"
    assert result["project_command"]["generation"] == after["generation"]
    with ZipFile(BytesIO(store.read_bytes("@snapshot/project.zip"))) as archive:
        assert archive.read("project/studio/document.vsz") == b"complete private native"
        assert archive.read("project/source/data.csv") == b"x,y\n1,2\n"


def test_concurrent_writer_wins_without_restore_from_private_candidate(tmp_path, monkeypatch):
    root, store, _before = fixture_store(tmp_path)

    def prepare(candidate, **kwargs):
        result = _prepared(candidate, **kwargs)
        publish_files(store, {"studio/document.vsz": b"other accepted writer"}, kind="save")
        return result

    monkeypatch.setattr(commands, "prepare_studio_candidate", prepare)
    monkeypatch.setattr(commands, "audit_studio_candidate", lambda *_args: ([], []))
    with pytest.raises(ProjectConflict):
        commands.prepare_studio_generation(root)
    assert (root / "studio/document.vsz").read_bytes() == b"other accepted writer"
    assert store.read_bytes("studio/document.vsz") == b"other accepted writer"
