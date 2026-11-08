"""Host grants do not travel with portable scientific/project bytes."""

import json
from pathlib import Path
import shutil

import pymupdf
import pytest

from sciplot_core.project_store import FileProjectStore
from sciplot_core.visual_review import pdf_review_binding as review
from test_pdf_review_binding import current as current, inventory, pdf, publish_record


@pytest.mark.parametrize("phase", ["complete", "staged", "legacy-binding"])
def test_official_bundle_import_refuses_old_review_before_external_path_io(current, tmp_path, monkeypatch, phase):
    project, _ = current
    output = tmp_path / "review"
    if phase == "staged":
        def refuse(*args, **kwargs):
            raise PermissionError("generated copy write refusal after staging")
        with monkeypatch.context() as patcher:
            patcher.setattr(review, "write_review_copy", refuse)
            with pytest.raises(PermissionError):
                review.create_pdf_review(project, review_dir=output)
        record = FileProjectStore(project).commands()[0]
        review_id = record["metadata"]["request"]["binding"]["review_id"]
    else:
        created = review.create_pdf_review(project, review_dir=output)
        review_id = created["review_id"]
    original = FileProjectStore(project)
    if phase == "legacy-binding":
        logical = f"reviews/pdf/{review_id}.json"
        legacy = json.loads(original.read_bytes(logical))
        del legacy["host_origin"]
        publish_record(original, logical, json.dumps(legacy).encode())
    bundle = original.export_bundle(tmp_path / "bundle")
    imported = FileProjectStore.import_bundle(bundle, tmp_path / "imported")
    assert imported.snapshot()["project_id"] == original.snapshot()["project_id"]
    if phase != "staged":
        logical = f"reviews/pdf/{review_id}.json"
        assert imported.read_bytes(logical) == original.read_bytes(logical)
    before = inventory(imported.root)
    calls = []
    def forbid(*args, **kwargs):
        calls.append(args)
        pytest.fail("An imported review must be refused before record-derived external IO")
    with monkeypatch.context() as patcher:
        patcher.setattr(review, "capture_pdf", forbid)
        patcher.setattr(review, "review_directory_binding", forbid)
        if phase != "staged":
            with pytest.raises(ValueError, match="no grant on this project host"):
                review.read_pdf_review(imported.root, review_id=review_id)
        with pytest.raises(ValueError, match="no grant on this project host"):
            review.create_pdf_review(imported.root, review_dir=output)
    assert calls == [] and inventory(imported.root) == before


def test_ordinary_copied_store_is_rejected_by_existing_root_binding(current, tmp_path, monkeypatch):
    project, _ = current
    created = review.create_pdf_review(project, review_dir=tmp_path / "review")
    copied = tmp_path / "copied"
    shutil.copytree(project, copied)
    def forbid(*args, **kwargs):
        pytest.fail("A foreign copied Store must not reach PDF capture")
    with monkeypatch.context() as patcher:
        patcher.setattr(review, "capture_pdf", forbid)
        with pytest.raises(ValueError, match="ownership identity"):
            review.read_pdf_review(copied, review_id=created["review_id"])


def test_original_host_accepts_atomic_pdf_save_and_reply_replay(current, tmp_path):
    project, original = current
    original_bytes = original.read_bytes()
    output = tmp_path / "review"
    created = review.create_pdf_review(project, review_dir=output)
    copy = Path(created["review_pdf"])
    inode = copy.stat().st_ino
    with pymupdf.open(copy) as document:
        document[0].add_text_annot((20, 40), "Atomic Preview-style annotation save")
        marked = document.tobytes()
    replacement = output / "atomic.pdf"
    replacement.write_bytes(marked)
    replacement.replace(copy)
    assert copy.stat().st_ino != inode
    assert review.read_pdf_review(project, review_id=created["review_id"])["annotation_count"] == 1
    retried = review.create_pdf_review(project, review_dir=output)
    assert retried["review_id"] == created["review_id"] and copy.read_bytes() == marked
    assert original.read_bytes() == original_bytes


@pytest.mark.parametrize("action", ["read", "replay-create"])
def test_replaced_review_directory_cannot_reuse_old_location_grant(current, tmp_path, action):
    project, _ = current
    output = tmp_path / "review"
    created = review.create_pdf_review(project, review_dir=output)
    output.rename(tmp_path / "old-review")
    output.mkdir()
    copy = output / "review.pdf"
    copy.write_bytes((tmp_path / "old-review/review.pdf").read_bytes())
    before = inventory(project)
    with pytest.raises(ValueError, match="directory changed"):
        if action == "read":
            review.read_pdf_review(project, review_id=created["review_id"])
        else:
            review.create_pdf_review(project, review_dir=output)
    assert inventory(project) == before


def test_directory_identity_is_checked_inside_actual_capture_not_only_preflight(current, tmp_path, monkeypatch):
    project, _ = current
    output = tmp_path / "review"
    created = review.create_pdf_review(project, review_dir=output)
    actual = review.capture_pdf
    def replace_just_before_capture(path, **kwargs):
        if kwargs.get("review"):
            output.rename(tmp_path / "old-review")
            output.mkdir()
            (output / "review.pdf").write_bytes((tmp_path / "old-review/review.pdf").read_bytes())
        return actual(path, **kwargs)
    with monkeypatch.context() as patcher:
        patcher.setattr(review, "capture_pdf", replace_just_before_capture)
        with pytest.raises(ValueError, match="directory changed"):
            review.read_pdf_review(project, review_id=created["review_id"])


def test_unregistered_original_pdf_is_refused_before_binding_byte_capture(current, tmp_path, monkeypatch):
    project, _ = current
    foreign = tmp_path / "generated-foreign.pdf"
    data = pdf("Generated outside the project; not a private file")
    foreign.write_bytes(data)
    import hashlib
    manifest_path = project / "runs/studio_001/manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    for record in (manifest["qa"]["pdfs"][0], manifest["result"]["exports"][0]):
        record.update(path=str(foreign), sha256=hashlib.sha256(data).hexdigest())
    manifest_path.write_text(json.dumps(manifest))
    actual_query = review.inspect_project
    def upstream_claim(*args, **kwargs):
        result = actual_query(*args, **kwargs)
        assert result["qa"]["current"] is False
        result["qa"]["current"] = True  # Inject an incorrect upstream claim; host admission must still hold.
        return result
    calls = []
    def forbid_capture(*args, **kwargs):
        calls.append(args)
        pytest.fail("The binding owner must admit an original resource before byte capture")
    with monkeypatch.context() as patcher:
        patcher.setattr(review, "inspect_project", upstream_claim)
        patcher.setattr(review, "projected_runtime_artifact", lambda path: path)
        patcher.setattr(review, "capture_pdf", forbid_capture)
        with pytest.raises(ValueError, match="outside all explicitly trusted"):
            review.create_pdf_review(project, review_dir=tmp_path / "review")
    assert calls == [] and not (tmp_path / "review").exists()
