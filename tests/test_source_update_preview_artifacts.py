"""Before/candidate images use exact native artifact roles and distinct roots."""
import json
import pytest

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.project_store import FileProjectStore, ProjectConflict
from sciplot_core.project_store.candidate_runtime import ProjectCandidateResolver
from sciplot_core.project_store.native_artifacts import resolve_native_artifact
from sciplot_core.foundation.source_locations import selected_source_resolver
from sciplot_core.studio_core.preparation_candidate import studio_preparation_candidate
from sciplot_core import task_source_update


@pytest.mark.parametrize("replace_parent", [False, True], ids=["exact-old-new", "replaced-output-parent"])
def test_review_previews_read_the_distinct_old_and_private_native_with_exact_output_roles(tmp_path, monkeypatch, replace_parent):
    project = tmp_path / "project"
    (project / "studio").mkdir(parents=True)
    source = tmp_path / "raw.csv"
    source.write_bytes(b"original science")
    (project / "plot_request.json").write_text(json.dumps({"input": str(source)}))
    (project / "studio/spec.json").write_text(json.dumps({"series": [{"source_artifacts": [
        {"path": str(source), "sha256": file_sha256(source)}]}]}))
    (project / "studio/document.vsz").write_bytes(b"old native")
    store = FileProjectStore(project)
    before = store.snapshot(import_legacy=True)
    seen = []

    def prepare(_project, _source, *, on_candidate, **_kwargs):
        with studio_preparation_candidate(store) as private:
            private.write_member("studio/document.vsz", b"new private native")
            on_candidate(private.project_dir, {})
        return {"status": "ready", "project": str(project)}

    def render(command, document, _option, output):
        assert command == "preview-document" and _option == "--out"
        actual = resolve_native_artifact(document, role="document")
        with pytest.raises(ProjectConflict, match="frozen role"):
            resolve_native_artifact(output.with_name("unbound.png"), role="out", output=True)
        if replace_parent:
            output.parent.rename(output.parent.with_name(output.parent.name + "-before"))
            output.parent.mkdir(mode=0o700)
        target = resolve_native_artifact(output, role="out", output=True)
        assert actual == document and target == output
        data = actual.read_bytes()
        candidate = isinstance(selected_source_resolver(), ProjectCandidateResolver)
        assert candidate == (data == b"new private native")
        target.write_bytes(data)
        seen.append((data, candidate))
        return {"document": {"path": str(document), "sha256": file_sha256(document)},
                "preview": {"path": str(target), "sha256": file_sha256(target)}}

    monkeypatch.setattr(task_source_update, "preview_project_source_update", prepare)
    monkeypatch.setattr(task_source_update, "run_document_worker", render)
    if replace_parent:
        with pytest.raises(ProjectConflict, match="parent changed"):
            task_source_update.prepare_source_update_review(project, source, review_path=tmp_path / "review.json")
        assert not seen and not (tmp_path / "review.json").exists()
    else:
        result = task_source_update.prepare_source_update_review(project, source, review_path=tmp_path / "review.json")
        assert result["status"] == "ready" and [item["scope"] for item in result["previews"]] == ["before", "candidate"]
        assert seen == [(b"old native", False), (b"new private native", True)]
    assert (project / "studio/document.vsz").read_bytes() == b"old native"
    assert source.read_bytes() == b"original science"
    assert store.snapshot()["generation"] == before["generation"]
