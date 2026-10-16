"""Publish only a complete audited native Save, without replacing unknown bytes."""

from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.veusz_worker import managed
from test_managed_backend import managed_ir


def test_compile_preview_cannot_alias_canonical_document(tmp_path, monkeypatch):
    monkeypatch.setattr(managed, "_read_ir", lambda _: pytest.fail("Must reject before reading IR"))
    native = tmp_path / "document.vsz"
    with pytest.raises(ValueError, match="cannot overwrite"):
        managed.compile_plot_ir(tmp_path / "ir.json", native, native)
    assert not native.exists()


@pytest.mark.parametrize("failure", [None, "save", "audit", "preview", "concurrent_native"])
def test_managed_compile_stages_native_until_audited_and_rendered(tmp_path, monkeypatch, failure):
    native, preview = tmp_path / "document.vsz", tmp_path / "preview.png"
    source = tmp_path / "source.csv"
    source.write_bytes(b"original user bytes\n")
    ir = managed_ir()
    staged = []

    def save(path):
        path = Path(path)
        staged.append(path)
        assert path != native and path.parent.parent == tmp_path
        assert not native.exists()
        path.write_bytes(b"complete native Save")
        if failure == "save":
            raise RuntimeError("interrupted Save")

    def inspect(_ir, candidate):
        assert not native.exists()
        return {"status": "unchanged", "document_sha256": file_sha256(candidate),
                "scientific_audit": {"status": "passed"},
                "publication_qa": {"status": "failed" if failure == "audit" else "passed"}}

    def render(_loaded, path):
        assert not native.exists()
        if failure == "preview":
            raise RuntimeError("interrupted painter")
        path.write_bytes(b"complete preview")
        if failure == "concurrent_native":
            native.write_bytes(b"unknown external native")
        return {"path": str(path), "sha256": file_sha256(path)}

    monkeypatch.setattr(managed, "_read_ir", lambda _: ir)
    monkeypatch.setattr(managed, "fresh_document", lambda _: nullcontext(object()))
    monkeypatch.setattr(managed, "import_module", lambda _: SimpleNamespace(
        CommandInterface=lambda _: SimpleNamespace(Save=save)))
    monkeypatch.setattr(managed, "native_state", lambda _: {})
    monkeypatch.setattr(managed, "inspect_plot_ir", inspect)
    monkeypatch.setattr(managed, "loaded_native_document", lambda _: nullcontext(object()))
    monkeypatch.setattr(managed, "_preview", render)
    if failure:
        with pytest.raises((RuntimeError, ValueError, FileExistsError)):
            managed.compile_plot_ir(tmp_path / "ir.json", native, preview)
        assert not preview.exists()
        if failure == "concurrent_native":
            assert native.read_bytes() == b"unknown external native"
        else:
            assert not native.exists()
    else:
        result = managed.compile_plot_ir(tmp_path / "ir.json", native, preview)
        assert result["document"] == str(native)
        assert result["document_sha256"] == file_sha256(native)
        assert result["preview"]["path"] == str(preview)
        assert result["preview"]["sha256"] == file_sha256(preview)
        assert native.read_bytes() == b"complete native Save"
    assert source.read_bytes() == b"original user bytes\n"
    assert staged and not staged[0].exists()
