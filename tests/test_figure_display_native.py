"""Actual native save/reopen/export keeps display curves separate from all raw points."""
from pathlib import Path

import pytest

from sciplot_core.plot_backends.managed import ManagedVeuszCompiler
from test_figure_display import interpolated
from test_figure_grammar import resolve


@pytest.mark.comprehensive
def test_native_display_curve_keeps_duplicate_knots_gaps_and_raw_marker_arrays(tmp_path):
    spec, raw = interpolated()
    dataset = raw["raw:A"]
    dataset["columns"]["column:0"]["values"] = [0, 1, 1, 2, None, 3, 4]
    dataset["columns"]["column:1"]["values"] = [1, 2, 7, 8, None, 12, 14]
    dataset["provenance"]["sources"][0]["rows"] = list(range(2, 9))
    dataset["provenance"]["sources"][0]["table_selection"]["data_end_row"] = 9
    ir = resolve(spec, raw)
    compiler = ManagedVeuszCompiler()
    try:
        built = compiler.compile_ir(ir, tmp_path / "native")
        assert built["publication_qa"]["status"] == "passed"
        assert built["publication_qa"]["native_text_checked"]
        audit = built["scientific_audit"]
        assert audit["status"] == "passed" and len(audit["datasets"]) == 4
        assert len(ir["datasets"]["raw:A"]["columns"]["column:0"]["values"]) == 7
        curve = next(iter(ir["display_curves"].values()))["curve"]
        assert len(curve["runs"]) == 3
        assert [curve["x"][i] for i in curve["original_indices"]] == dataset["columns"]["column:0"]["values"]
        # export_ir reopens the saved native document and validates all arrays,
        # native geometry and QA before writing actual PDF/TIFF artifacts.
        exported = compiler.export_ir(ir, Path(built["document"]), tmp_path / "exported")
        assert exported["ready_to_use"]
        assert any(path.suffix == ".pdf" and path.stat().st_size > 0 for path in (tmp_path / "exported").iterdir())
        assert any(path.suffix in {".tif", ".tiff"} and path.stat().st_size > 0 for path in (tmp_path / "exported").iterdir())
    finally:
        compiler.close()
