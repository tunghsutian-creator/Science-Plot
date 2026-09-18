from __future__ import annotations

from pathlib import Path

import fitz
import pytest

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
