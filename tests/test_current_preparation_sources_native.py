"""A supported multi-file sweep survives a cold public native lifecycle."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.native_process.session import _close_workers
from sciplot_core.project_store import FileProjectStore
from sciplot_core.studio import export_native_document_artifacts, prepare_studio_document
from sciplot_core.studio_core.project_command_scope import project_store
from sciplot_core.studio_core.source_update import apply_project_source_update, preview_project_source_update
from test_project_source_update_native import _cli, _files, _native


def _sweep(directory: Path, offset: int) -> dict[str, list[int]]:
    directory.mkdir()
    expected = {"A": [100 + offset, 120 + offset, 140 + offset],
                "B": [200 + offset, 240 + offset, 280 + offset]}
    for sample, values in expected.items():
        # This is the existing registered frequency-sweep table contract used
        # by test_rheology_sweep_domain, not a new source adapter.
        (directory / f"{sample}.csv").write_text(
            "Angular Frequency,Storage Modulus\nrad/s,Pa\n"
            + "".join(f"{x},{y}\n" for x, y in zip((1, 10, 100), values, strict=True)))
    (directory / "unused.md").write_bytes(b"Preserve this unplotted original source member.\n")
    (directory / "empty").mkdir()
    return expected


def _arrays(document: Path, expected: dict[str, list[int]]) -> None:
    state = _native(document)
    assert set(state["series"]) == set(expected)
    for sample, values in expected.items():
        assert state["series"][sample]["x"] == [1, 10, 100]
        assert state["series"][sample]["y"] == values


@pytest.mark.comprehensive
def test_current_cold_directory_public_prepare_regenerates_and_exports_native(tmp_path, monkeypatch):
    initial, incoming = tmp_path / "initial", tmp_path / "incoming"
    _sweep(initial, 0)
    expected = _sweep(incoming, 7)
    original_input = _files(initial), _files(incoming)
    starts, popen = [], subprocess.Popen

    def observe(*args, **kwargs):
        process = popen(*args, **kwargs)
        starts.append(process)
        return process

    monkeypatch.setattr(subprocess, "Popen", observe)
    try:
        print("directory-native: public frequency-sweep create", flush=True)
        created = _cli(initial, "--out", tmp_path / "visible", "--rule", "rheology_frequency_sweep", "--prepare-only")
        project, document = Path(created["project_dir"]), Path(created["document"])
        _arrays(document, {"A": [100, 120, 140], "B": [200, 240, 280]})
        repository = project_store(project, with_snapshot=True)
        before = repository.snapshot()
        raw = _files(project / "raw"), _files(project / "source")
        old_native = document.read_bytes()

        print("directory-native: real source-update preview and single publication", flush=True)
        review = preview_project_source_update(project, incoming)
        assert review["status"] == "ready" and review["source_kind"] == "directory", review
        inventory = {name: file_sha256(incoming / name) for name in ("A.csv", "B.csv", "unused.md")}
        assert review["source_files"] == inventory
        assert document.read_bytes() == old_native
        applied = apply_project_source_update(project, review)
        assert applied["status"] == "updated", applied
        updated = repository.snapshot()
        assert updated["sequence"] == before["sequence"] + 1
        for identity, versions in before["sources"].items():
            for digest, entry in versions.items():
                assert updated["sources"][identity][digest] == entry
        record = repository.query(review["command_key"])
        assert record["phase"] == "complete"
        proof = record["source_tree_origins"][str(incoming)]
        assert set(proof["members"]) == {"A.csv", "B.csv", "unused.md", "empty"}
        assert record["metadata"]["source_trees"] == [{"locator": str(incoming), "tree_sha256": review["source_tree_sha256"]}]
        source_versions = {}
        for name, digest in inventory.items():
            owners = [identity for identity, versions in updated["sources"].items()
                      if versions.get(digest, {}).get("locator") == str(incoming / name)]
            assert len(owners) == 1
            source_versions[name] = {"source_id": owners[0], "sha256": digest}
            assert repository.resolve_source(owners[0], digest).read_bytes() == original_input[1][name]
        _arrays(document, expected)
        assert (_files(project / "raw"), _files(project / "source")) == raw
        assert (_files(initial), _files(incoming)) == original_input

        print("directory-native: complete bundle import with original directories offline", flush=True)
        _close_workers()
        assert all(process.poll() is not None for process in starts)
        cold = FileProjectStore.import_bundle(repository.export_bundle(tmp_path / "bundle"), tmp_path / "cold")
        project.rename(tmp_path / "project-offline")
        initial.rename(tmp_path / "initial-offline")
        incoming.rename(tmp_path / "incoming-offline")
        cached_tree = cold.prepared_tree_path(review["command_key"], record["command_digest"],
            decision_id=record["decision_id"], locator=str(incoming), tree_sha256=review["source_tree_sha256"])
        assert cached_tree is not None and (cached_tree / "empty").is_dir()
        assert _files(cached_tree) == original_input[1]

        print("directory-native: public cold preparation forces real reader/native regeneration", flush=True)
        prepared = prepare_studio_document(cold.root, regenerate_generated=True)
        assert prepared["project_dir"] == str(cold.root)
        cold_document = Path(prepared["document"])
        _arrays(cold_document, expected)
        request = json.loads((cold.root / "plot_request.json").read_bytes())
        assert request["input"] == str(incoming)
        assert request["resolved_figure_plan"]["source_sha256"] == review["source_tree_sha256"]
        assert (_files(cold.root / "raw"), _files(cold.root / "source")) == raw

        print("directory-native: public cold PDF/TIFF export and exact saved-native science audit", flush=True)
        exported = export_native_document_artifacts(cold_document, formats=["pdf", "tiff_300"])
        assert exported["standalone_export"]["export_ready"] is True, exported
        assert exported["document_audit"]["status"] == "passed", exported
        assert {item["format"] for item in exported["exports"]} == {"pdf", "tiff_300"}
        assert all(Path(item["path"]).is_file() and file_sha256(Path(item["path"])) == item["sha256"]
                   for item in exported["exports"])
        assert not project.exists() and not initial.exists() and not incoming.exists()
        assert (_files(tmp_path / "initial-offline"), _files(tmp_path / "incoming-offline")) == original_input
        current = project_store(cold.root, with_snapshot=True).snapshot()
        for name, version in source_versions.items():
            assert current["sources"][version["source_id"]][version["sha256"]]["locator"] == str(incoming / name)
        (tmp_path / "directory-native-evidence.json").write_text(json.dumps({
            "rule_id": "rheology_frequency_sweep", "project_id": updated["project_id"],
            "review_generation": updated["generation"], "cold_generation": current["generation"],
            "original_input": str(incoming), "tree_sha256": review["source_tree_sha256"],
            "sources": source_versions, "native_sha256": file_sha256(cold_document),
            "scientific_arrays": expected, "audit_status": exported["document_audit"]["status"],
            "checks": ["actual_directory_reader_and_native", "complete_source_update_capture",
                       "unused_file_and_empty_directory", "previous_source_versions_preserved",
                       "original_directories_offline", "public_cold_native_regeneration",
                       "original_locator_and_current_versions", "public_native_pdf_tiff_audit"]}, indent=2))
    finally:
        _close_workers()
        assert all(process.poll() is not None for process in starts)
        (tmp_path / "directory-native-workers.json").write_text(json.dumps([
            {"pid": process.pid, "returncode": process.returncode} for process in starts], indent=2))
