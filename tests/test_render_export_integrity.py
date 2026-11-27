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


def test_terminal_render_reports_exact_outputs_left_by_install_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    import errno
    import json

    from sciplot_core.cli import main
    from sciplot_core.render import export_files, panel_render

    source = tmp_path / "sample.csv"
    source.write_text("x,y\n0,1\n1,2\n", encoding="utf-8")
    native = tmp_path / "payload"
    rendered = []
    for fmt in ("pdf", "tiff_300"):
        artifact = native.with_suffix(f".{fmt}")
        artifact.write_bytes(fmt.encode())
        rendered.append({"format": fmt, "path": str(artifact)})
    monkeypatch.setattr(panel_render, "_render_studio_exports", lambda *a, **k: {"exports": rendered})
    install = export_files.install_new_delivery

    def fail_tiff(candidate: Path, destination: Path) -> None:
        if destination.suffix == ".tiff":
            raise OSError(errno.EIO, "write failed", str(destination))
        install(candidate, destination)

    monkeypatch.setattr(export_files, "install_new_delivery", fail_tiff)
    output = tmp_path / "figures"
    args = ["render", str(source), "--template", "curve", "--out", str(output), "--json"]
    assert main(args) == 1
    result = json.loads(capsys.readouterr().out)
    pdf = output / "sample_curve.pdf"
    assert result["reason_code"] == "partial_terminal_render"
    assert result["diagnostics"]["installed_outputs"] == [str(pdf)]
    assert "Use a new output directory" in result["message"]
    assert "sample_curve_300dpi.tiff" in result["message"]
    assert pdf.read_bytes() == b"pdf"
    assert not (output / "sample_curve_300dpi.tiff").exists()

    assert main(args) == 1
    retry = json.loads(capsys.readouterr().out)
    assert "Choose a new output directory" in retry["message"]
    assert pdf.read_bytes() == b"pdf"
