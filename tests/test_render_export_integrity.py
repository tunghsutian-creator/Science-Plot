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


def test_terminal_render_preserves_preexisting_files(
    tmp_path: Path,
) -> None:
    source = tmp_path / "sample.csv"
    source.write_text("x,y\n0,1\n1,2\n", encoding="utf-8")
    output = tmp_path / "figures"
    scratch = output / "_veusz"
    scratch.mkdir(parents=True)
    note = scratch / "research.txt"
    note.write_bytes(b"user")
    destination = output / "sample_curve.pdf"
    destination.write_bytes(b"previous figure")
    with pytest.raises(FileExistsError, match="_veusz"):
        render.render_to_dir(source, template="curve", output_dir=output)
    assert note.read_bytes() == b"user"

    second = tmp_path / "other"
    second.mkdir()
    collision = second / destination.name
    collision.write_bytes(destination.read_bytes())
    with pytest.raises(FileExistsError, match="sample_curve.pdf"):
        render.render_to_dir(source, template="curve", output_dir=second)
    assert list(second.iterdir()) == [collision]
    assert collision.read_bytes() == b"previous figure"

    with pytest.raises(FileExistsError):
        render._copy_veusz_exports(
            {"exports": [{"format": "pdf", "path": str(source)}]},
            output_dir=second, output_base="sample_curve",
        )
    assert list(second.iterdir()) == [collision]
    assert collision.read_bytes() == b"previous figure"
