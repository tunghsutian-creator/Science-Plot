"""Generated-data confirmation reaches the original native preparation/publication."""

import json
from pathlib import Path

import pytest

from public_curve_inputs import paired_source
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.intake import application, session_adapter as adapter


@pytest.mark.comprehensive
def test_confirmed_intake_request_prepares_once_and_publishes_exact_generated_science(tmp_path, monkeypatch):
    source, expected = paired_source(tmp_path / "original", "dsc_curve")
    original = source.read_bytes()
    response = adapter.prepare_session(source, output_root=tmp_path / "projects", rule_id="dsc_curve")
    session = Path(response["session"])
    value = json.loads(session.read_text())
    preview = adapter.preview_session_table(session, group_index=0, file_index=0)
    request = value["request"]
    request.update(render_options={"size": "120x55", "series_styles": [
                       {"label": "Generated Cedar", "line_style": "solid"},
                       {"label": "Generated Birch", "line_style": "dashed"}]},
                   exports=["pdf", "tiff_300", "png_300", "png_600", "svg"],
                   replicate_mode="individual", group_order_is_explicit=True,
                   column_confirmations=[preview["confirmation_request"]])
    session.write_text(json.dumps(value))
    calls = []
    create, publish = application.create_intake_project, adapter.publish_prepared_intake_project

    def observe_create(**arguments):
        calls.append("prepare")
        return create(**arguments)

    def observe_publish(project):
        calls.append("publish")
        return publish(project)

    monkeypatch.setattr(application, "create_intake_project", observe_create)
    monkeypatch.setattr(adapter, "publish_prepared_intake_project", observe_publish)
    created = adapter.create_session(session)
    assert calls == ["prepare", "publish"]
    assert created["last_run"]["ready_to_use"] is True, created.get("failure")
    project = Path(created["project_dir"])
    saved_request = json.loads((project / "plot_request.json").read_text())
    assert saved_request["render_options"]["size"] == "120x55"
    assert saved_request["exports"] == request["exports"]
    assert saved_request["replicate_mode"] == "individual"
    spec = json.loads((project / "studio/spec.json").read_text())
    assert [(item["x_values"], item["y_values"]) for item in spec["series"]] == [
        ([point[0] for point in series], [point[1] for point in series]) for series in expected]
    exported = created["studio"]["exports"]
    assert {item["format"] for item in exported} == set(request["exports"])
    assert all(Path(item["path"]).is_file() and Path(item["path"]).stat().st_size for item in exported)
    manifest = json.loads((Path(created["last_run"]["output"]) / "manifest.json").read_text())
    scientific = manifest["result"]["scientific_data_verification"]
    assert scientific["status"] == "passed", scientific
    qa = manifest["qa"]
    assert qa["status"] == qa["publication"]["status"] == "passed"
    assert qa["png_count"] == 2 and qa["svg_count"] == 1
    observed = {item["path"]: item for key in ("pdfs", "tiffs", "pngs", "svgs") for item in qa[key]}
    package = created["last_run"]["delivery_package"]
    assert package["complete"] is True
    delivered = package["figures"]
    assert len(delivered) == len(exported) == 5
    assert {item["export_format"] for item in delivered} == set(request["exports"])
    assert {item["source"] for item in delivered} == {item["path"] for item in exported}
    assert package["verification"]["checks"]["canonical_pdf_tiff_pairs"] is True
    assert manifest["delivery_verification"]["passed"] is True
    assert manifest["delivery_verification"]["issues"] == []
    assert manifest["delivery_verification"]["verified_export_count"] == 5
    exports_by_path = {item["path"]: item for item in exported}
    for item in delivered:
        source_export = exports_by_path[item["source"]]
        evidence = observed[item["source"]]
        assert item["source_sha256"] == item["delivery_sha256"] == source_export["sha256"] == evidence["sha256"]
        assert file_sha256(Path(item["path"])) == file_sha256(Path(item["source"])) == evidence["sha256"]
        assert item["copy_hash_matches"] and item["exists"]
        if item["export_format"].startswith("png_") or item["export_format"] == "svg":
            assert evidence["export_format"] == item["export_format"]
            assert evidence["visual_qa"]["ink_fraction"] > 0
        if item["export_format"].startswith("png_"):
            assert all(value > 0 for value in evidence["pixel_size"])
    assert source.read_bytes() == original
    assert all(item["sha256"] == file_sha256(source) for group in created["groups"] for item in group["files"])
    (tmp_path / "intake-native-evidence.json").write_text(json.dumps({
        "source_sha256": file_sha256(source), "project": str(project), "calls": calls,
        "native_sha256": file_sha256(project / "studio/document.vsz"),
        "science": scientific["status"], "formats": sorted(item["format"] for item in exported),
        "exports": exported, "delivery_figures": delivered,
        "qa_formats": {key: qa[key] for key in ("pdf_count", "tiff_count", "png_count", "svg_count")},
        "additional_qa": {key: qa[key] for key in ("pngs", "svgs")},
        "delivery_verification": manifest["delivery_verification"],
        "selection": created["selection"], "expected_points": expected,
    }, indent=2))
