"""Resolved IR is lowered without template resolution or legacy artifact reads."""

from copy import deepcopy

import pytest

from sciplot_core.plot_backends.managed_plan import drawing_plan, native_datasets, native_name
from sciplot_core.plot_ir import seal_ir


def managed_ir():
    def axis(name):
        return {"id": "axis:" + name, "label": name, "unit": "s" if name == "x" else "Pa",
            "scale": "linear", "limits": [0, 4], "ticks": [0, 1, 2, 3, 4], "font_family": "Arial", "font_size_pt": 8,
            "visible": True, "label_visible": True, "line_width_pt": 0.5, "line_color": "#000000",
            "tick_length_pt": 2, "tick_direction": "out"}
    x, y = [0, 1.11111111111111, 2, 3], [1, 2, None, 3]
    dataset = {"id": "raw:A", "columns": {"column:0": {"label": "x", "unit": "s", "values": x},
                "column:1": {"label": "y", "unit": "Pa", "values": y}},
        "provenance": {"sources": [{"source_id": "source:A", "sha256": "a" * 64,
            "table_selection": {"sheet": None, "header_rows": [0], "data_start_row": 1, "data_end_row": 5},
            "column_indices": {"column:0": 0, "column:1": 1}, "rows": [1, 2, 3, 4]}], "transforms": []}}
    return seal_ir({"kind": "sciplot_plot_ir", "schema_version": 1, "scientific_hash": "0" * 64,
        "presentation_hash": "1" * 64, "datasets": {"raw:A": dataset}, "series": [{"id": "series:A", "label": "A",
            "dataset_id": "raw:A", "x_column": "column:0", "y_column": "column:1", "x": x, "y": y,
            "style": {"line_color": "#0000FF", "line_width_pt": 0.7, "marker": "circle", "marker_size_pt": 3,
                "marker_color": "#0000FF", "line_visible": True, "marker_visible": True, "line_style": "solid",
                "marker_line_width_pt": 0.5, "line_join": "bevel"}}], "axes": {"x": axis("x"), "y": axis("y")},
        "dimensions": {"width_mm": 60, "height_mm": 55},
        "layout": {"margins_mm": {"left": 12, "right": 3, "top": 3, "bottom": 10}},
        "legend": {"id": "legend:main", "visible": True, "position": [0.55, 0.85], "font_family": "Arial", "font_size_pt": 8},
        "annotations": [{"id": "annotation:A", "text": "test", "visible": True, "coordinate_mode": "relative",
            "position": [0.5, 0.8], "font_family": "Arial", "font_size_pt": 8, "color": "#000000"}],
        "background_color": "#FFFFFF"})


def test_native_names_follow_stable_ids_and_preserve_source_values():
    ir = managed_ir()
    before = deepcopy(ir)
    plan = drawing_plan(ir)
    series = next(node for node in plan if node["type"] == "xy")
    assert series["path"].endswith(native_name("series", "series:A"))
    assert series["settings"]["PlotLine/width"] == "0.7pt"
    assert ir == before
    assert len(native_datasets(ir)) == 2


def test_unsupported_ir_field_rejected_before_native_or_file_activity(tmp_path):
    from sciplot_core.plot_backends.managed import ManagedVeuszCompiler
    from sciplot_core.plot_document import DocumentError

    ir = managed_ir()
    ir["native_object_paths"] = {"series:A": "/arbitrary"}
    compiler = ManagedVeuszCompiler(warm=False)
    with pytest.raises(DocumentError):
        compiler.compile_ir(ir, tmp_path / "never-created")
    assert not (tmp_path / "never-created").exists()


@pytest.mark.parametrize("unsupported", ["miter", "rgba"])
def test_valid_ir_but_unsupported_backend_capability_is_explicit(tmp_path, unsupported):
    from sciplot_core.plot_backends.managed import ManagedVeuszCompiler
    from sciplot_core.plot_document import DocumentError

    ir = managed_ir()
    if unsupported == "miter":
        ir["series"][0]["style"]["line_join"] = "miter"
    else:
        ir["series"][0]["style"]["line_color"] = "#ff000080"
    ir = seal_ir(ir)
    with pytest.raises(DocumentError) as failure:
        ManagedVeuszCompiler(warm=False).compile_ir(ir, tmp_path / "unsupported")
    assert failure.value.reason_code == "unsupported_capability"
    assert not (tmp_path / "unsupported").exists()


def test_compile_receipt_cannot_combine_old_audit_with_new_native_bytes(tmp_path, monkeypatch):
    from contextlib import nullcontext
    from types import SimpleNamespace

    from sciplot_core.foundation.file_hashing import file_sha256
    from sciplot_core.veusz_worker import managed

    document = tmp_path / "document.vsz"
    ir = managed_ir()
    monkeypatch.setattr(managed, "_read_ir", lambda _: ir)
    monkeypatch.setattr(managed, "fresh_document", lambda _: nullcontext(object()))
    monkeypatch.setattr(managed, "import_module", lambda _: SimpleNamespace(
        CommandInterface=lambda _: SimpleNamespace(Save=lambda _: document.write_bytes(b"audited native"))))
    monkeypatch.setattr(managed, "native_state", lambda _: {})
    monkeypatch.setattr(managed, "inspect_plot_ir", lambda *_: {"status": "unchanged",
        "document_sha256": file_sha256(document), "scientific_audit": {"status": "passed"}})
    monkeypatch.setattr(managed, "loaded_native_document", lambda _: nullcontext(object()))

    def raced_preview(*_):
        document.write_bytes(b"external changed native")
        return {"path": "raced-preview.png"}

    monkeypatch.setattr(managed, "_preview", raced_preview)
    with pytest.raises(ValueError, match="between its compilation audit and preview"):
        managed.compile_plot_ir(tmp_path / "ir.json", document, tmp_path / "preview.png")


def test_render_receipt_binds_the_exact_audited_native_bytes(tmp_path, monkeypatch):
    from sciplot_core.foundation.file_hashing import file_sha256
    from sciplot_core.plot_backends.managed import ManagedVeuszCompiler

    document = tmp_path / "document.vsz"
    document.write_bytes(b"audited native")
    audited = file_sha256(document)
    compiler = ManagedVeuszCompiler(warm=False)
    monkeypatch.setattr(compiler, "_require_exact", lambda *_: {"document_sha256": audited})

    def raced_render(_):
        document.write_bytes(b"external changed native")
        return {"document": {"sha256": file_sha256(document)}, "preview": {"path": "raced.png"}}

    monkeypatch.setattr(compiler, "_run", raced_render)
    with pytest.raises(ValueError, match="between audit and preview"):
        compiler.render_ir(managed_ir(), document, tmp_path / "preview.png")
