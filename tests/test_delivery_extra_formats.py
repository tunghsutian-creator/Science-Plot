"""The finite native export matrix keeps every requested artifact and QA binding."""

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path

import pymupdf as fitz
from PIL import Image, ImageDraw
import pytest

from sciplot_core.delivery.package_builder import build_delivery_package
from sciplot_core.delivery.package_validation import verify_delivery_package
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.policy.frame_export import CANONICAL_EXPORT_FORMATS
from sciplot_core.policy.export_formats import export_format_from_path, export_suffix
from sciplot_core.qa.run import run_qa
from sciplot_core.studio_core.export_verification import _verify_qa_artifact_hashes
from test_delivery_project_documents import _builder_manifest


def _extras(tmp_path, formats, *, planned=True):
    run, manifest, plan = _builder_manifest(tmp_path)
    outcomes = []
    for outcome in plan.outcomes:
        pdf = Path(next(path for path in outcome.artifacts if path.endswith(".pdf")))
        added = []
        for fmt in formats:
            path = pdf.with_name(pdf.stem + export_suffix(fmt)[0])
            path.write_bytes(b"generated metadata-only " + fmt.encode())
            added.append(str(path))
            manifest["figures"].append(str(path))
            manifest["result"]["exports"].append({"path": str(path), "figure_id": outcome.figure_id, "format": fmt})
            manifest["qa"].setdefault("pngs" if fmt.startswith("png") else "svgs", []).append(
                {"path": str(path), "sha256": file_sha256(path), "export_format": fmt})
        outcomes.append(replace(outcome, artifacts=(*outcome.artifacts, *added)))
    payload = replace(plan, outcomes=tuple(outcomes)).to_payload()
    for container in (manifest, manifest["result"], manifest["study_model"]["run"]):
        if planned:
            container["resolved_figure_plan"] = payload
        else:
            container.pop("resolved_figure_plan", None)
    if not planned:
        manifest["semantic"] = {"rule_id": "unknown"}
        manifest["request"] = {"rule_id": "unknown"}
    return run, manifest


@pytest.mark.parametrize("planned", [False, True])
@pytest.mark.parametrize("formats", [(), ("png_300",), ("png_600",), ("svg",), ("png_300", "png_600", "svg")])
def test_builder_delivers_every_supported_additional_format_without_replacing_the_pair(tmp_path, formats, planned):
    run, manifest = _extras(tmp_path, formats, planned=planned)
    originals = {path: Path(path).read_bytes() for path in manifest["figures"]}
    record = build_delivery_package(run, manifest=manifest)
    assert record["complete"], record["verification"]
    assert len(record["figures"]) == len(manifest["figures"])
    assert {item["export_format"] for item in record["figures"]} == {"pdf", "tiff_300", *formats}
    for item in record["figures"]:
        assert Path(item["path"]).parent == Path(record["path"]) / "figures"
        assert Path(item["path"]).read_bytes() == originals[item["source"]]
        assert item["source_sha256"] == item["delivery_sha256"] == file_sha256(Path(item["source"]))
    assert record["verification"]["checks"]["canonical_pdf_tiff_pairs"] is True
    assert all(Path(path).read_bytes() == content for path, content in originals.items())


@pytest.mark.parametrize("change", ["bytes", "missing", "omit_every_png", "duplicate", "wrong_format", "unknown_file", "pair_missing"])
@pytest.mark.parametrize("planned", [False, True])
def test_additional_artifacts_keep_exact_current_membership_and_refuse_drift(tmp_path, change, planned):
    run, manifest = _extras(tmp_path, ("png_300", "svg"), planned=planned)
    record = build_delivery_package(run, manifest=manifest)
    assert record["complete"]
    png = next(item for item in record["figures"] if item["export_format"] == "png_300")
    if change == "bytes":
        Path(png["path"]).write_bytes(b"changed PNG")
    elif change == "missing":
        Path(png["path"]).unlink()
    elif change == "omit_every_png":
        for item in record["figures"]:
            if item["export_format"] == "png_300":
                Path(item["path"]).unlink()
        record["figures"] = [item for item in record["figures"] if item["export_format"] != "png_300"]
    elif change == "duplicate":
        record["figures"].append(deepcopy(png))
    elif change == "wrong_format":
        png["export_format"] = "png_600"
    elif change == "unknown_file":
        (Path(record["path"]) / "figures/unknown.jpg").write_bytes(b"unregistered format")
    else:
        tiff = next(item for item in record["figures"] if item["export_format"] == "tiff_300")
        Path(tiff["path"]).unlink()
        record["figures"].remove(tiff)
    observed = verify_delivery_package(record, expected_root=Path(record["path"]), expected_manifest=manifest)
    assert observed["passed"] is False
    if change == "pair_missing":
        assert observed["checks"]["canonical_pdf_tiff_pairs"] is False


def _real_artifacts(root):
    root.mkdir()
    with fitz.open() as document:
        page = document.new_page(width=100, height=50)
        page.draw_line((10, 10), (90, 40))
        page.insert_text((10, 30), "Generated", fontsize=7)
        document.save(root / "a.pdf")
    for fmt in ("tiff_300", "png_300", "png_600"):
        suffix, dpi = export_suffix(fmt)
        image = Image.new("RGB", (round(100 * dpi / 72), round(50 * dpi / 72)), "white")
        ImageDraw.Draw(image).line((10, 10, image.width - 10, image.height - 10), fill="black", width=2)
        image.save(root / ("a" + suffix), dpi=(dpi, dpi))
    (root / "a.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" width="100pt" height="50pt"><path d="M10 10L90 40" stroke="black"/></svg>')
    (root / "request_snapshot.json").write_text(json.dumps({"exports": sorted(CANONICAL_EXPORT_FORMATS)}))
    return root


def test_all_five_native_formats_have_actual_qa_hashes_and_bounded_png_canvas(tmp_path):
    root = _real_artifacts(tmp_path / "actual")
    report = run_qa(root)
    assert report["status"] == "passed"
    assert {item["export_format"] for item in report["pngs"]} == {"png_300", "png_600"}
    assert len(report["svgs"]) == 1
    exports = [{"path": str(path), "format": export_format_from_path(path), "sha256": file_sha256(path)}
               for path in root.iterdir() if export_format_from_path(path) is not None]
    _verify_qa_artifact_hashes(report, exports=exports, covered_formats=set(CANONICAL_EXPORT_FORMATS))
    report["pngs"][0]["sha256"] = "0" * 64
    with pytest.raises(RuntimeError, match="QA hashes"):
        _verify_qa_artifact_hashes(report, exports=exports, covered_formats=set(CANONICAL_EXPORT_FORMATS))


@pytest.mark.parametrize("change", ["dpi", "pixels", "blank", "svg_canvas", "svg_external", "missing_png", "missing_svg"])
def test_png_svg_actual_qa_refuses_bad_or_missing_requested_artifacts(tmp_path, change):
    root = _real_artifacts(tmp_path / "actual")
    path = root / "a_300dpi.png"
    if change in {"dpi", "pixels", "blank"}:
        image = Image.new("RGB", (10, 10) if change == "pixels" else (417, 208), "white")
        if change != "blank":
            ImageDraw.Draw(image).line((1, 1, image.width - 1, image.height - 1), fill="black")
        image.save(path, dpi=(72, 72) if change == "dpi" else (300, 300))
    elif change == "svg_canvas":
        (root / "a.svg").write_text((root / "a.svg").read_text().replace('width="100pt"', 'width="200pt"'))
    elif change == "svg_external":
        (root / "a.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" width="100pt" height="50pt"><image href="file:///ungranted.png"/></svg>')
    else:
        (path if change == "missing_png" else root / "a.svg").unlink()
    with pytest.raises(ValueError):
        run_qa(root)
