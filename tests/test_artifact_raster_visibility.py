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
