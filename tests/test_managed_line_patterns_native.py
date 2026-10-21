"""Actual saved line-pattern/export/rebuild controls for the combined milestone."""

import json
from pathlib import Path
import shutil

import pytest

from sciplot_core.plot_backends.managed import ManagedVeuszCompiler
from sciplot_core.plot_backends.managed_plan import drawing_plan
from sciplot_core.plot_document import DocumentError
from test_managed_line_patterns import pattern_ir


@pytest.mark.comprehensive
@pytest.mark.parametrize("mode", ["v1", "v2-house"])
def test_saved_dash_dot_export_rebuild_and_exact_native_mutation_detection(tmp_path, mode):
    ir = pattern_ir(mode, "dash-dot")
    compiler = ManagedVeuszCompiler()
    try:
        output = tmp_path / "artifacts"
        built = compiler.compile_ir(ir, output)
        assert built["scientific_audit"]["status"] == "passed"
        inspected = compiler.inspect_ir(ir, Path(built["document"]))
        assert inspected["status"] == "unchanged" and inspected["native_differences"] == []
        exported = compiler.export_ir(ir, Path(built["document"]), tmp_path / "exports")
        assert exported["ready_to_use"] and exported["scientific_audit"] == built["scientific_audit"]
        original_preview = Path(built["preview"]["path"]).read_bytes()
        plan = drawing_plan(ir)
        curve = next(node for node in plan if node["settings"].get("PlotLine/style") == "dash-dot" and node["settings"].get("xData"))
        changes = [{"object_path": curve["path"], "setting_path": curve["path"] + "/PlotLine/style",
                    "expected_value": "dash-dot", "value": "dashed"}]
        change_file = tmp_path / "pattern-change.json"
        change_file.write_text(json.dumps(changes))
        modified = tmp_path / "modified.vsz"
        compiler._run(["edit-document", built["document"], "--changes", str(change_file),
                       "--output-document", str(modified), "--preview-png", str(tmp_path / "changed.png")])
        drift = compiler.inspect_ir(ir, modified)
        assert drift["status"] == "external_mutation" and drift["opaque_native_change"]
        assert drift["scientific_audit"] == built["scientific_audit"]
        assert drift["native_differences"] == [{"path": curve["path"], "setting": "PlotLine/style",
                                               "before": "dash-dot", "after": "dashed"}]
        with pytest.raises(DocumentError, match="differs"):
            compiler.export_ir(ir, modified, tmp_path / "must-not-export")
        assert not (tmp_path / "must-not-export").exists()
        shutil.rmtree(output)
        rebuilt = compiler.compile_ir(ir, output)
        assert rebuilt["scientific_audit"] == built["scientific_audit"]
        assert rebuilt["native_state_hash"] == built["native_state_hash"]
        assert Path(rebuilt["preview"]["path"]).read_bytes() == original_preview
    finally:
        compiler.close()
