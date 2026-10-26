"""Known byte versions survive protected external and host/literal readers."""
import io
import json
from pathlib import Path

from PIL import Image
import pytest
from test_managed_delivery import case as case
from test_panel_assembly_export import add
from test_project_store import fixture_store

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.panel_assembly import export, preview
from sciplot_core.panel_assembly.model import new_document
from sciplot_core.panel_assembly.sources import capture_source
from sciplot_core.project_commands import PreparedSource, ProjectCommand, ProjectCommands, ProjectMutation
from sciplot_core.project_store import FileProjectStore
from sciplot_core.project_store.runtime import project_runtime
from sciplot_core import task_paper_sources as paper


def register(store, paths):
    before = store.snapshot()
    sources = tuple(PreparedSource(f"{index:032x}", str(path), file_sha256(path), path.read_bytes(), (), 0o644)
                    for index, path in enumerate(paths, 1))
    mutation = ProjectMutation({}, {}, prepared_sources=sources)
    command = ProjectCommand.create("attachment_import", "external-reader-inputs",
        project_id=before["project_id"], expected_generation=before["generation"],
        read_set={}, write_set=[], request={"prepared_digest": mutation.prepared_digest})
    ProjectCommands(store).publish_prepared(command, mutation)


@pytest.fixture
def image(tmp_path):
    path = tmp_path / "external/image.png"
    path.parent.mkdir()
    Image.new("RGB", (100, 60), "blue").save(path)
    source = capture_source({"kind": "image", "path": str(path)})
    store, _before = fixture_store(tmp_path)
    register(store, [path])
    return store, path, source


@pytest.mark.parametrize("reader", ["preview", "public_preview", "package", "composition"])
def test_bound_image_readers_use_the_registered_byte_version(image, tmp_path, reader):
    store, path, source = image
    original = path.read_bytes()
    before = store.snapshot()["generation"]
    with project_runtime(store):
        if reader in {"preview", "public_preview"}:
            payload = (preview._image_preview(source) if reader == "preview" else preview.render_preview(source))
            with Image.open(io.BytesIO(payload)) as result:
                assert result.size == (100, 60)
        elif reader == "package":
            records = export._source_package(source, tmp_path / "packaged")
            assert len(records) == 1 and records[0]["sha256"] == file_sha256(path)
        else:
            result = export.export_document(add(new_document(), source), tmp_path / "composed")
            assert result["status"] == "complete", result
    assert path.read_bytes() == original and store.snapshot()["generation"] == before


def test_managed_delivery_uses_each_registered_original_version(case, tmp_path):
    service, request, heads, _calls, _failures = case
    guarded = tmp_path / "guarded"
    guarded.mkdir()
    store, _before = fixture_store(guarded)
    paths = [Path(head["document"]["scientific"]["data_sources"][0]["path"]) for head in heads.values()]
    register(store, paths)
    originals = {path: path.read_bytes() for path in paths}
    with project_runtime(store):
        result = service.deliver(request)
    assert result["status"] == "complete", result
    assert {path: path.read_bytes() for path in paths} == originals


def test_paper_capture_keeps_digest_when_host_member_has_a_different_literal(tmp_path, monkeypatch):
    store, before = fixture_store(tmp_path)
    command = ProjectCommand.create("publish", "paper-request", project_id=before["project_id"],
        expected_generation=before["generation"], read_set={"plot_request.json": None},
        write_set=["plot_request.json"], request={"synthetic": True})
    ProjectCommands(store).execute(command, lambda: ProjectMutation({"plot_request.json": b"{}"}, {}))
    bundle = store.export_bundle(tmp_path / "bundle")
    original_root = store.root
    original_root.rename(tmp_path / "offline")
    cold = FileProjectStore.import_bundle(bundle, tmp_path / "cold")
    host, literal = cold.root / "raw/same.csv", original_root / "raw/same.csv"
    specification = tmp_path / "paper-spec.json"
    specification.write_text(json.dumps({"series": [{"source_artifacts": [
        {"path": str(host), "sha256": file_sha256(host)}]}]}))
    selected = {"project": str(cold.root), "figure_id": "primary", "document": str(cold.root / "studio/document.vsz"),
                "spec": str(specification), "document_sha256": file_sha256(cold.root / "studio/document.vsz"),
                "spec_sha256": file_sha256(specification)}
    monkeypatch.setattr(paper, "resolve_project_figure", lambda *_args: selected)
    monkeypatch.setattr(paper, "project_snapshot", lambda *_args: ({}, {}, [{"figure_id": "primary"}]))
    monkeypatch.setattr(paper, "source_indicators", lambda *_args: {"current": True, "prepared": {"current": True}, "scope": "generated fixture"})
    monkeypatch.setattr(paper, "native_link_sources", lambda *_args: [])
    with project_runtime(cold):
        selection = paper.capture_selection(cold.root, "primary")
        assert selection["source_files"] == {str(literal): file_sha256(host)}
        paper.assert_selection_current(selection)
    assert host != literal and not literal.exists()


@pytest.mark.parametrize("change", [None, "file_hash", "composite_hash", "namespace", "raw_drift"])
def test_categorical_disclosure_uses_its_bound_file_hash_not_its_composite(tmp_path, change):
    from sciplot_core.categorical_plan import build_categorical_preview
    from sciplot_core.source_coverage.replicate_disclosure import verify_replicate_summary_request

    source = tmp_path / "categorical.csv"
    source.write_text("Sample,Strength (MPa)\nA,1\nA,3\nB,2\nB,4\n")
    binding = {"source_sha256": file_sha256(source), "mode": "mean_sample_sd_n",
        "table_selection": {"sheet": None, "header_rows": [0], "data_start_row": 1, "data_end_row": 5},
        "sample_column": 0, "value_columns": [{"column_index": 1}]}
    plan = build_categorical_preview(source, request={"categorical_binding": binding})
    request = {"input": str(source), "template": plan["template"], **plan["source_options"]}
    store, _before = fixture_store(tmp_path)
    register(store, [source])
    declaration = request["replicate_summary_disclosure"]
    assert declaration["source_sha256"] != binding["source_sha256"]
    if change == "file_hash":
        request["categorical_binding"]["source_sha256"] = "0" * 64
    elif change == "composite_hash":
        declaration["source_sha256"] = "0" * 64
    elif change == "namespace":
        request["categorical_binding"]["source_namespace"] = str(tmp_path / "foreign.csv")
    elif change == "raw_drift":
        source.write_bytes(source.read_bytes().replace(b"A,1", b"A,9"))
    with project_runtime(store):
        if change is not None:
            with pytest.raises(ValueError):
                verify_replicate_summary_request(request)
            return
        result = verify_replicate_summary_request(request)
    assert result["status"] == "passed" and result["source_file_sha256"] == binding["source_sha256"]
    assert result["source_sha256"] == declaration["source_sha256"]


@pytest.mark.parametrize("reader", ["public_preview", "composition"])
@pytest.mark.parametrize("change", ["wrong_hash", "source_drift", "foreign_equal_bytes"])
def test_current_image_reader_refuses_wrong_versions_and_foreign_members(image, tmp_path, reader, change):
    from copy import deepcopy

    store, path, original_source = image
    source = deepcopy(original_source)
    before = store.snapshot()["generation"]
    if change == "wrong_hash":
        source["binding"]["snapshot"]["sha256"] = "0" * 64
    elif change == "source_drift":
        Image.new("RGB", (100, 60), "red").save(path)
    else:
        foreign = store.root / "foreign.png"
        foreign.write_bytes(path.read_bytes())
        source["path"] = str(foreign)
    with project_runtime(store), pytest.raises(ValueError):
        if reader == "public_preview":
            preview.render_preview(source)
        else:
            export.export_document(add(new_document(), source), tmp_path / "rejected")
    assert store.snapshot()["generation"] == before and not (tmp_path / "rejected").exists()


def test_source_tree_file_proof_never_reinterprets_a_directory_or_composite(tmp_path):
    from sciplot_core.foundation.source_tree import source_tree_sha256

    source = tmp_path / "source.csv"
    source.write_bytes(b"x,y\n1,2\n")
    byte_hash = file_sha256(source)
    composite = source_tree_sha256(source)
    assert composite != byte_hash
    assert source_tree_sha256(source, expected_file_sha256=byte_hash) == composite
    with pytest.raises(ValueError, match="exact declared byte version"):
        source_tree_sha256(source, expected_file_sha256=composite)
    assert source_tree_sha256(tmp_path) is not None
    with pytest.raises(ValueError, match="directory composite"):
        source_tree_sha256(tmp_path, expected_file_sha256=byte_hash)
