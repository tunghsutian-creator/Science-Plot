"""Exact directory handoff with the real installation and a small native-export double."""

from contextlib import nullcontext
import json
from pathlib import Path

from PIL import Image
import fitz
import pytest

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.plot_engine.errors import EngineError
from sciplot_core.plot_engine.service import PlotService
from sciplot_core.project_lifecycle import figure_handoff
from test_plot_typed_intent import _document


def test_directory_selected_handoff_renders_only_missing_formats_and_leaves_no_cache(tmp_path, monkeypatch):
    root = tmp_path / "plot"
    root.mkdir()
    native = root / "figure.vsz"
    native.write_bytes(b"existing native revision")
    ir = root / "figure.ir.json"
    ir.write_text("{}")
    cold_document = _document(tmp_path)
    binding = {"document": str(native), "ir_path": str(ir), "ir_hash": "current",
               "canonical_sha256": "canonical", "output": str(root)}
    head = {"document": cold_document, "binding": binding}
    monkeypatch.setattr(figure_handoff, "project_query", lambda _root: nullcontext())
    monkeypatch.setattr(figure_handoff, "has_head", lambda _root: True)
    monkeypatch.setattr(figure_handoff, "load_head", lambda _root: head)
    monkeypatch.setattr(figure_handoff, "active", lambda _root: None)
    monkeypatch.setattr(figure_handoff, "require_current", lambda *_: None)
    formats_sent = []
    native_digest = file_sha256(native)
    fixed_evidence = {str(native): native_digest, str(ir): file_sha256(ir)}

    class Backend:
        def export_selected(self, selected, output, formats):
            assert selected == binding
            formats_sent.append(formats)
            exports = []
            for fmt in formats:
                path = output / ("figure.pdf" if fmt == "pdf" else "figure_300dpi.tiff")
                if fmt == "pdf":
                    with fitz.open() as pdf:
                        pdf.new_page().insert_text((20, 30), "selected revision")
                        pdf.save(path)
                else:
                    Image.new("RGB", (50, 30), "black").save(path, dpi=(300, 300))
                exports.append({"format": fmt, "path": str(path), "sha256": file_sha256(path)})
            return {"status": "exported", "ready_to_use": True, "ir_hash": "current", "exports": exports,
                    "publication_qa": {"status": "passed"}, "scientific_audit": {"status": "passed"},
                    "native_export_audit": {"native_state_hash": "exact", "ir_hash": "current",
                        "canonical_sha256": "canonical", "ir_sha256": fixed_evidence[str(ir)],
                        "document_sha256": native_digest},
                    "evidence_files": {**fixed_evidence, **{item["path"]: item["sha256"] for item in exports}}}

    service = PlotService(Backend())

    def selected(name, formats):
        out = tmp_path / name
        receipt = service.export(root, handoff={"output_dir": str(out), "formats": formats, "revision": 0,
                                               "plot_id": cold_document["plot_id"]})
        assert receipt["ready_to_use"] and receipt["revision"] == 0
        assert {item["format"] for item in receipt["exports"]} == set(formats)
        assert set(out.iterdir()) == {Path(item["path"]) for item in receipt["exports"]}
        assert not list(tmp_path.glob(".sciplot-*"))
        return receipt

    rendered = selected("cold", ["tiff_300"])
    assert formats_sent == [("tiff_300",)]
    [tiff] = rendered["exports"]
    with Image.open(tiff["path"]) as image:
        image.load()
        assert image.format == "TIFF" and image.info["dpi"] == (300, 300)
    assert set(root.iterdir()) == {native, ir}

    # A valid PDF-only cache can supply PDF unchanged while the missing TIFF
    # is rendered privately. The directory cache is not replaced by either use.
    warm = Backend().export_selected(binding, root, ("pdf",))
    cache = root / "export-cache.json"
    cache.write_text(json.dumps({"export": warm, "artifact_files": warm["evidence_files"]}))
    before = cache.read_bytes()
    selected("warm", ["pdf"])
    assert formats_sent == [("tiff_300",), ("pdf",)]
    pair = selected("pair", ["pdf", "tiff_300"])
    assert formats_sent[-1:] == [("tiff_300",)] and len(formats_sent) == 3
    assert next(item["sha256"] for item in pair["exports"] if item["format"] == "pdf") == warm["exports"][0]["sha256"]
    assert cache.read_bytes() == before and file_sha256(native) == native_digest

    Path(warm["exports"][0]["path"]).write_text("changed after publication")
    with pytest.raises(EngineError) as failed:
        selected("damaged", ["tiff_300"])
    assert failed.value.reason_code == "figure_handoff_publication_unready"
    assert len(formats_sent) == 3 and not (tmp_path / "damaged").exists()
