"""Generated torque curation reaches one native preparation and current publication."""

import json
from pathlib import Path

import pytest

from curation_fixture_helpers import _generated_torque_sources, _points
from sciplot_core import curate, studio
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.native_process.session import _close_workers
from sciplot_core.project_host_factory import project_store
from sciplot_core.studio_core.project_export import export_project_document
from test_project_source_update_native import _native


@pytest.mark.comprehensive
def test_public_generated_torque_curation_prepares_once_then_exports_exact_selected_science(
    tmp_path, monkeypatch
):
    source = tmp_path / "original"
    original = _generated_torque_sources(source)
    actual_prepare, preparations = studio.prepare_studio_document, []

    def observe_native_prepare(project, **options):
        # Delegate to the real renderer/Store; this observer is not a native stub.
        result = actual_prepare(project, **options)
        store = project_store(project)
        snapshot = store.snapshot()
        preparations.append(
            {
                "result": result,
                "options": options,
                "request": store.read_bytes(
                    "plot_request.json", generation=snapshot["generation"]
                ),
                "selection": store.read_bytes(
                    "curation/torque_selection.json", generation=snapshot["generation"]
                ),
            }
        )
        return result

    monkeypatch.setattr(studio, "prepare_studio_document", observe_native_prepare)
    try:
        result = curate.curate_torque_project(
            source,
            output_root=tmp_path / "projects",
            project_name="Generated native torque",
        )
        assert len(preparations) == 1
        assert preparations[0]["options"] == {"_new_creation": True}
        project = Path(result["project_dir"])
        store = project_store(project, with_snapshot=True)
        assert store.snapshot()["outside_changes"] == {}
        request_path, selection_path = (
            project / "plot_request.json",
            Path(result["selection_path"]),
        )
        request_bytes, selection_bytes = (
            request_path.read_bytes(),
            selection_path.read_bytes(),
        )
        assert (
            preparations[0]["request"]
            == store.read_bytes("plot_request.json")
            == request_bytes
        )
        assert (
            preparations[0]["selection"]
            == store.read_bytes("curation/torque_selection.json")
            == selection_bytes
        )
        selection = json.loads(selection_bytes)
        expected = []
        for item in selection["samples"]:
            raw = Path(item["source_path"])
            original_path, content, full_points = original[file_sha256(raw)]
            assert raw.read_bytes() == content == original_path.read_bytes()
            assert curate._read_torque_full_series(raw).points == full_points
            points = tuple(
                (x - item["start_s"], y)
                for x, y in full_points
                if item["start_s"] <= x <= item["end_s"]
            )
            assert 1200 < len(points) < len(full_points)
            expected.append(points)
        assert _points(result["plot_data_path"]) == expected
        document = project / "studio/document.vsz"
        native_bytes = document.read_bytes()
        native = _native(document)["series"]
        for item, points in zip(selection["samples"], expected, strict=True):
            series = native[item["plot_label"]]
            assert tuple(zip(series["x"], series["y"], strict=True)) == points
        published = export_project_document(
            project_dir=project, formats=["pdf", "tiff_300"]
        )
        run = published.run_payload
        assert published.ready_to_use, run
        assert run["qa"]["status"] == "passed", run
        assert run["result"]["scientific_data_verification"]["status"] == "passed", run
        assert run["delivery_verification"]["passed"] is True, run
        assert {item["format"] for item in published.exports} == {"pdf", "tiff_300"}
        assert all(Path(item["path"]).is_file() for item in published.exports)
        assert len(preparations) == 1
        assert document.read_bytes() == native_bytes
        assert (
            request_path.read_bytes()
            == store.read_bytes("plot_request.json")
            == request_bytes
        )
        assert (
            selection_path.read_bytes()
            == store.read_bytes("curation/torque_selection.json")
            == selection_bytes
        )
        assert store.snapshot()["outside_changes"] == {}
        assert not list((project / "curation").rglob("*.html"))
        assert all(
            path.read_bytes() == content for path, content, _ in original.values()
        )
        (tmp_path / "curation-native-evidence.json").write_text(
            json.dumps(
                {
                    "kind": "generated_torque_curation_native_proof",
                    "native_preparations": len(preparations),
                    "project": str(project),
                    "generation": store.snapshot()["generation"],
                    "request_sha256": file_sha256(request_path),
                    "selection_sha256": file_sha256(selection_path),
                    "native_sha256": file_sha256(document),
                    "selected_counts": list(map(len, expected)),
                    "original_counts": [
                        len(points) for _, _, points in original.values()
                    ],
                    "qa": run["qa"]["status"],
                    "scientific": run["result"]["scientific_data_verification"][
                        "status"
                    ],
                    "delivery": run["delivery_verification"],
                    "scope": "generated public sources; actual native renderer and publication",
                },
                indent=2,
            )
        )
    finally:
        _close_workers()
