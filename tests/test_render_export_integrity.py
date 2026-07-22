from __future__ import annotations

from pathlib import Path

import pytest

from sciplot_core import render


def test_equivalent_export_aliases_are_rejected() -> None:
    with pytest.raises(ValueError, match="same output artifact"):
        render._normalize_export_formats(["tiff", "tiff_300"])


def test_missing_worker_export_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="missing or empty"):
        render._copy_veusz_exports(
            {"exports": [{"format": "pdf", "path": str(tmp_path / "missing.pdf")}]},
            output_dir=tmp_path,
            output_base="figure",
        )


def test_worker_export_set_must_match_request() -> None:
    with pytest.raises(RuntimeError, match=r"missing=\['tiff_300'\]"):
        render._validate_export_records(
            [{"format": "pdf"}], requested=("pdf", "tiff_300")
        )


def test_stale_generated_exports_are_removed_without_touching_other_files(
    tmp_path: Path,
) -> None:
    stale = [
        tmp_path / "sample_curve.pdf",
        tmp_path / "sample_curve_300dpi.tiff",
        tmp_path / "sample_curve_part02.pdf",
    ]
    for path in stale:
        path.write_bytes(b"stale")
    unrelated = tmp_path / "notes.pdf"
    unrelated.write_bytes(b"user")

    render._remove_stale_render_exports(
        tmp_path, source_stem="sample", template="curve"
    )

    assert all(not path.exists() for path in stale)
    assert unrelated.read_bytes() == b"user"
