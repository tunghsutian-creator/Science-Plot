"""Independent whole-file copying of sealed ordinary figures, without rendering."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from sciplot_core._paths import REPO_ROOT
from sciplot_core.plot_ir.figure_document import figure_spec
from sciplot_core.project_lifecycle.capabilities import COMPATIBILITY_CAPABILITIES
from sciplot_core.project_lifecycle.errors import EngineError
from sciplot_core.project_lifecycle.project_file_append import project_file_append_xy, project_file_create_xy
from sciplot_core.project_lifecycle.project_file_save_as import save_project_file_as
from sciplot_core.project_lifecycle.project_file_summary import project_file_figure, project_file_read_session
from test_project_file_append import _coordinates, _ordinary_request, _save_axis_revision


def _cli(*args):
    run = subprocess.run([str(REPO_ROOT / "skill/scripts/sciplot"), *map(str, args), "--json"],
                         env={**os.environ, "SCIPLOT_PYTHON": sys.executable}, text=True,
                         capture_output=True, timeout=30, check=False)
    assert run.returncode == 0, run.stdout + run.stderr
    return json.loads(run.stdout)


def _seal_archive(folder: Path):
    archive = folder / "研究项目.sciplot"
    source = folder / "four measurements.csv"
    payloads = []
    figures = []
    for value in range(4):
        payload = f"Temperature,Heat Flow\nC,W/g\nSample Z,Sample Z\n66,-0.023\n61,{value}\n53,-0.016\n".encode()
        payloads.append(payload)
        source.write_bytes(payload)
        request = _ordinary_request(source)
        request["idempotency_key"] = f"figure-{value}"
        if not figures:
            result = project_file_create_xy(archive, request, capabilities=COMPATIBILITY_CAPABILITIES)
        else:
            result = project_file_append_xy(archive, request, expected_generation=figures[-1]["generation"],
                                            capabilities=COMPATIBILITY_CAPABILITIES)
        figures.append(result)
    source.unlink()
    return archive, figures, payloads


def test_whole_file_save_as_copies_all_current_figures_and_sealed_versions(tmp_path):
    folder = tmp_path.resolve()
    original, prior, payloads = _seal_archive(folder)
    _save_axis_revision(original, prior[0]["plot_id"], "Cooling temperature (C)")
    original_bytes = original.read_bytes()
    opened = _cli("plot", "open", original, "--figure", prior[0]["plot_id"], "--scope", "summary", "--direct")
    copied = folder / "independent sample.sciplot"
    result = _cli("project", "save-as-file", original, "--project-id", opened["project_id"],
                  "--expected-generation", opened["generation"], "--out", copied)
    assert result["status"] == "saved" and not result["history_copied"]
    assert result["project_id"] != opened["project_id"] and result["generation"] != opened["generation"]
    assert len(result["figures"]) == 4
    mapping = {figure["original"]["plot_id"]: figure for figure in result["figures"]}
    assert set(mapping) == {figure["plot_id"] for figure in prior}
    edits = {}
    for original_id, report in mapping.items():
        old = report["original"]
        target = report["plot_id"]
        assert target != old["plot_id"] and report["figure_id"] != old["figure_id"]
        assert report["open_arguments"]["target"] == str(copied) and report["open_arguments"]["figure_id"] == target
        with project_file_figure(original, original_id) as (_, original_owner, before):
            with project_file_figure(copied, target) as (_, copied_owner, after):
                assert old["revision"] == before["revision"]
                assert after["revision"] == 0
                assert _coordinates(original_owner, before) == _coordinates(copied_owner, after)
                assert all(before[key] == after[key] for key in ("scientific", "presentation", "scientific_hash", "presentation_hash"))
                assert original_owner.load_head(original_owner.attachment.root)["binding"]["ir_hash"] == (
                    copied_owner.load_head(copied_owner.attachment.root)["binding"]["ir_hash"]
                )
                edits[original_id] = figure_spec(after)["views"][0]["axes"][0]["id"]
        with pytest.raises(EngineError) as absent:
            with project_file_figure(copied, original_id):
                pytest.fail("the original identity still opens in the new project")
        assert absent.value.reason_code == "project_file_figure_not_found"

    with project_file_read_session(original) as source, project_file_read_session(copied) as fork:
        [old_id] = source.store.snapshot()["sources"]
        [new_id] = fork.store.snapshot()["sources"]
        assert old_id != new_id and fork.store.snapshot()["sequence"] == 1
        old_versions, new_versions = source.store.snapshot()["sources"][old_id], fork.store.snapshot()["sources"][new_id]
        assert old_versions.keys() == new_versions.keys()
        assert {fork.store.resolve_source(new_id, version).read_bytes() for version in new_versions} == set(payloads)
        for version, metadata in new_versions.items():
            assert old_id in metadata["aliases"]
            assert all(metadata[key] == old_versions[version][key] for key in ("mode", "locator", "sha256"))

    first_id = prior[0]["plot_id"]
    after_id = mapping[first_id]["plot_id"]
    request = folder / "edit.json"
    request.write_text(json.dumps({"mode": "plan", "plot_id": after_id, "base_revision": 0,
            "idempotency_key": "independent-axis", "property": "axis.label", "target_id": edits[first_id],
            "value": "New temperature label"}), encoding="utf-8")
    planned = _cli("plot", "intent", copied, "--request", request, "--direct")
    assert planned["status"] == "ready" and planned["before"] == "Cooling temperature (C)"
    # Exercise the semantic save owner without running the external renderer.
    _save_axis_revision(copied, after_id, "New temperature label")
    assert original.read_bytes() == original_bytes
    for old_id, report in mapping.items():
        with project_file_figure(copied, report["plot_id"]) as (_, _, figure):
            assert figure["revision"] == int(old_id == first_id)


def test_save_as_rejects_stale_occupied_and_opaque_archive(tmp_path):
    folder = tmp_path.resolve()
    archive, prior, _ = _seal_archive(folder)
    expected = {"expected_project_id": prior[-1]["project_id"], "expected_generation": prior[-1]["generation"]}
    before = archive.read_bytes()
    destination = folder / "copy.sciplot"
    with pytest.raises(EngineError) as stale:
        save_project_file_as(archive, destination, **{**expected, "expected_generation": prior[0]["generation"]})
    assert stale.value.reason_code == "project_file_save_as_stale" and not destination.exists()
    os.link(archive, destination)
    with pytest.raises(EngineError) as occupied:
        save_project_file_as(archive, destination, **expected)
    assert occupied.value.reason_code == "project_file_destination_exists"
    assert destination.read_bytes() == before
    destination.unlink()

    # Portable Store members outside the logical generation are also accounted for.
    with project_file_read_session(archive) as session:
        hidden = session.store.root / ".sciplot_store" / "native_work" / "retained.vsz"
        hidden.parent.mkdir()
        hidden.write_bytes(b"separately retained native run output")
        session.save(expected_generation=session.opened_generation)
    with pytest.raises(EngineError) as unhandled:
        save_project_file_as(archive, destination, **expected)
    assert unhandled.value.reason_code == "project_file_save_as_unsupported" and not destination.exists()
    archive.write_bytes(before)

    # A registered other project resource cannot be rebound to the copy.
    with project_file_read_session(archive) as session:
        name = "unhandled.pdf"
        scope = dict(expected_generation=session.opened_generation, read_set={name: None}, write_set=[name])
        session.store.reserve("opaque-fixture", "opaque-fixture", **scope)
        session.store.publish("opaque-fixture", "opaque-fixture", writes={name: b"%PDF-fixture"}, result={})
        opaque = session.save(expected_generation=session.store.snapshot()["generation"])
    source_bytes = archive.read_bytes()
    with pytest.raises(EngineError) as unsupported:
        save_project_file_as(archive, destination, **{**expected, "expected_generation": opaque.generation})
    assert unsupported.value.reason_code == "project_file_save_as_unsupported"
    assert not destination.exists() and archive.read_bytes() == source_bytes
