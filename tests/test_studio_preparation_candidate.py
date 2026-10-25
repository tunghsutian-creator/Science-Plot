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


def test_active_figure_install_requires_the_explicit_private_context(tmp_path):
    root, _store, _before = fixture_store(tmp_path)
    with pytest.raises(ProjectConflict, match="host-owned private"):
        install_prepared_figure_set(project_dir=root, replacements=[], manual_archive_requests=[], registry=None)


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
