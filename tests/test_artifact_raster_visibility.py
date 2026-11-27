from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

import fitz
import pytest
from PIL import Image, TiffImagePlugin

from sciplot_core.qa import run_qa


def _write_pdf(path: Path, *, sparse_stroke: bool) -> None:
    document = fitz.open()
    page = document.new_page(width=1000, height=1000)
    if sparse_stroke:
        page.draw_line(
            fitz.Point(10, 10),
            fitz.Point(14, 10),
            color=(0, 0, 0),
            width=0.5,
        )
    document.save(path)
    document.close()


def test_sparse_nonblank_pdf_remains_artifact_qa_evidence(tmp_path: Path) -> None:
    source = tmp_path / "sparse.pdf"
    _write_pdf(source, sparse_stroke=True)

    payload = run_qa(tmp_path)

    ink_fraction = payload["pdfs"][0]["visual_qa"]["ink_fraction"]
    assert payload["status"] == "passed"
    assert 0 < ink_fraction < 0.0005


def test_truly_blank_pdf_is_still_rejected(tmp_path: Path) -> None:
    source = tmp_path / "blank.pdf"
    _write_pdf(source, sparse_stroke=False)

    with pytest.raises(ValueError, match="PDF raster appears blank"):
        run_qa(tmp_path)


def test_compact_vector_style_scan_matches_full_drawing_evidence(tmp_path, monkeypatch):
    from sciplot_core.qa.pdf_graphics import _stroke_info, _vector_color_info
    from sciplot_core.qa.pdf_inspection import _pdf_info

    path = tmp_path/'styles.pdf'
    document = fitz.open()
    page = document.new_page(width=200,height=200)
    page.draw_line((10,10),(190,190), color=(0.2,0.4,0.6), width=0.8)
    page.draw_rect((20,20,80,80), color=None, fill=(0.1,0.2,0.3))
    page = document.new_page(width=200,height=200)
    page.draw_rect((30,30,160,160), color=(1,0,0), fill=(0,1,0), width=2.2)
    document.save(path)
    document.close()
    with fitz.open(path) as source:
        full = [page.get_drawings() for page in source]
        expected_strokes = _stroke_info(source, styles=full)
        expected_colors = _vector_color_info(source, styles=full)
    count = []
    original = fitz.Page.get_cdrawings
    def scan(page, *args, **kwargs):
        count.append(page.number)
        return original(page,*args,**kwargs)
    monkeypatch.setattr(fitz.Page,'get_cdrawings',scan)
    result = _pdf_info(path)
    assert result['strokes'] == expected_strokes
    assert result['vector_colors'] == expected_colors
    assert count == [0,1]



def test_qa_pair_uses_the_same_pdf_and_tiff_bytes_for_decoding_and_hashing(tmp_path, monkeypatch):
    pdf, tiff = tmp_path / "figure.pdf", tmp_path / "figure_300dpi.tiff"
    with fitz.open() as document:
        page = document.new_page(width=48, height=24)
        page.draw_line((1, 1), (45, 21))
        document.save(pdf)
    with Image.new("RGB", (200, 100), "navy") as image:
        image.save(tiff, format="TIFF", dpi=(300, 300))

    before = {path: path.read_bytes() for path in (pdf, tiff)}
    calls = []
    original_rasterize = fitz.Page.get_pixmap
    original_load = TiffImagePlugin.TiffImageFile.load

    def replace_after_decode(path):
        if path in calls:  # Pillow may complete one TIFF through nested load calls.
            return
        candidate = path.with_suffix(".replacement")
        candidate.write_bytes(b"Replacement not decoded for this report")
        candidate.replace(path)
        calls.append(path)

    def rasterize(page, *args, **kwargs):
        decoded = original_rasterize(page, *args, **kwargs)
        replace_after_decode(pdf)
        return decoded

    def load_pixels(image, *args, **kwargs):
        pixels = original_load(image, *args, **kwargs)
        replace_after_decode(tiff)
        return pixels

    monkeypatch.setattr(fitz.Page, "get_pixmap", rasterize)
    monkeypatch.setattr(TiffImagePlugin.TiffImageFile, "load", load_pixels)
    result = run_qa(tmp_path)
    assert result["status"] == "passed" and calls == [pdf, tiff]
    for field, path in (("pdfs", pdf), ("tiffs", tiff)):
        report, = result[field]
        assert report["path"] == str(path)
        assert report["size_bytes"] == len(before[path])
        assert report["sha256"] == sha256(before[path]).hexdigest()
        assert report["sha256"] != sha256(path.read_bytes()).hexdigest()
    assert result["pdfs"][0]["media_box_pt"] == [48, 24]
    assert result["tiffs"][0]["pixel_size"] == [200, 100]
    assert result["tiffs"][0]["dpi"] == [300, 300]


def test_qa_does_not_admit_corrupt_tiff_pixels_or_renamed_png(tmp_path):
    pdf, tiff = tmp_path / "figure.pdf", tmp_path / "figure_300dpi.tiff"
    _write_pdf(pdf, sparse_stroke=True)
    with Image.new("RGB", (40, 20), "navy") as image:
        image.save(tiff, format="TIFF", dpi=(300, 300))
    with Image.open(tiff) as image:
        # Keep the TIFF directory intact while removing part of the actual strip.
        strip_offset, = image.tag_v2[273]
    tiff.write_bytes(tiff.read_bytes()[:strip_offset + 5])
    with Image.open(tiff) as metadata_only:
        assert metadata_only.size == (40, 20) and metadata_only.info["dpi"] == (300, 300)
    with pytest.raises(ValueError, match="Cannot decode the declared TIFF artifact"):
        run_qa(tmp_path)

    with Image.new("RGB", (40, 20), "navy") as image:
        image.save(tiff, format="PNG", dpi=(300, 300))
    with pytest.raises(ValueError, match="declared TIFF artifact"):
        run_qa(tmp_path)
    tiff.replace(pdf)
    with pytest.raises(ValueError, match="declared PDF artifact"):
        run_qa(tmp_path)



def test_qa_cli_strict_without_profile_is_not_evaluated_but_keeps_artifact_evidence(tmp_path, capsys):
    from sciplot_core.cli import main

    _write_pdf(tmp_path / "figure.pdf", sparse_stroke=True)
    with Image.new("RGB", (200, 100), "navy") as image:
        image.save(tmp_path / "figure_300dpi.tiff", format="TIFF", dpi=(300, 300))

    assert main(["qa", str(tmp_path)]) == 0
    ordinary = json.loads(capsys.readouterr().out)
    assert ordinary["status"] == "passed" and "publication" not in ordinary

    assert main(["qa", str(tmp_path), "--strict-publication"]) == 1
    strict = json.loads(capsys.readouterr().out)
    assert strict["status"] == "failed" and strict["publication_strict"] is True
    assert strict["publication"]["status"] == "not_evaluated"
    assert strict["publication"]["reason_code"] == "publication_profile_missing"
    assert strict["publication"]["checked_constraints_passed"] is None
    assert strict["pdfs"] == ordinary["pdfs"] and strict["tiffs"] == ordinary["tiffs"]



def test_semantic_inventory_reports_missing_label_on_its_own_exported_figure(tmp_path, monkeypatch):
    from sciplot_core.publication import get_publication_profile, list_publication_profiles
    from sciplot_core.qa import run as qa_run

    records, audited = [], []
    for figure_id, printed_text in (("first", "Stress (MPa)"), ("second", "Temperature (K)")):
        native = tmp_path / f"{figure_id}.vsz"
        native.write_text(f"# isolated native-audit fixture for {figure_id}")
        native_digest = sha256(native.read_bytes()).hexdigest()
        pdf = tmp_path / f"{figure_id}.pdf"
        with fitz.open() as document:
            page = document.new_page(width=170.079, height=142)
            page.insert_text((15, 20), printed_text, fontsize=8)
            document.save(pdf)
        records.append({"format": "pdf", "figure_id": figure_id, "path": str(pdf),
                        "sha256": sha256(pdf.read_bytes()).hexdigest(), "document": str(native),
                        "document_sha256": native_digest})
        audited.append({"path": str(native), "sha256": native_digest,
                        "pages": [{"page": 1, "path": "/page1", "size_mm": [60, 50]}],
                        "semantic_labels": [{"path": "/page1/graph1/x", "role": "axis_label",
                                             "text": "Stress (MPa)"}]})
    (tmp_path / "manifest.json").write_text(json.dumps({"result": {"exports": records}}))
    monkeypatch.setattr(qa_run, "_run_veusz_audit", lambda _: ({"documents": audited}, None))
    profile = get_publication_profile(list_publication_profiles()[0]["id"])

    plain = run_qa(tmp_path)
    assert plain["status"] == "passed" and plain["pdf_count"] == 2
    evaluated = run_qa(tmp_path, publication_profile=profile)
    check = next(item for item in evaluated["publication"]["checks"] if item["id"] == "semantic_label_inventory")
    assert check["status"] == "failed" and check["severity"] == "error"
    missing, = check["actual"]["missing"]
    assert missing["text"] == "Stress (MPa)" and missing["figure_id"] == "second"
    assert missing["pdf_path"] == str(tmp_path / "second.pdf") and missing["page"] == 1
    matched, = check["actual"]["matched"]
    assert matched["figure_id"] == "first" and matched["page"] == 1

    # A current producer supplies its own records; a stale target digest forfeits
    # that scope rather than borrowing text from the first PDF or the manifest.
    records[1]["sha256"] = "0" * 64
    evaluated = run_qa(tmp_path, publication_profile=profile, _export_artifacts=records)
    check = next(item for item in evaluated["publication"]["checks"] if item["id"] == "semantic_label_inventory")
    assert check["severity"] == "warning"
    assert check["actual"]["missing"] == [] and not check["actual"]["coverage_complete"]
    unverified, = check["actual"]["unverified"]
    assert ":" + str(tmp_path / "second.vsz") + ":" in unverified["source"]


def test_an_identically_styled_label_on_another_page_cannot_prove_panel_typography(tmp_path):
    from sciplot_core.publication import get_publication_profile

    with fitz.open() as document:
        axis_only = document.new_page(width=252, height=142)
        axis_only.insert_text((20, 111), "a", fontsize=8, fontname="hebo")
        intended_panel = document.new_page(width=252, height=142)
        intended_panel.insert_text((15, 20), "Temperature (K)", fontsize=7)
        document.save(tmp_path / "panels.pdf")

    intent = {"layout_status": "confirmed", "panels": [
        {"panel_label": "a", "confirmation_status": "confirmed"},
    ]}
    profile = get_publication_profile("nature_flagship_research_2026_v1")
    (tmp_path / "publication_intent.json").write_text(json.dumps(intent))
    result = run_qa(tmp_path, publication_profile=profile)
    qa = result["publication"]
    checks = {check["id"]: check for check in qa["checks"]}
    semantic = checks["semantic_label_inventory"]["actual"]
    assert semantic["observed_lines"] == ["a", "Temperature (K)"]
    assert semantic["matched"] == []
    assert semantic["unverified"][0]["text"] == "a"
    typography = checks["panel_label_typography"]["actual"]
    assert not typography["passed"] and not typography["coverage_complete"]
    assert typography["reason_code"] == "panel_text_role_unbound"
    assert qa["coverage"]["semantic_panel_and_required_label_inventory"] is False
