"""Real Veusz rebuild, exact numeric persistence and native mutation boundaries."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from sciplot_core.plot_backends.managed import ManagedVeuszCompiler
from sciplot_core.plot_backends.managed_plan import native_name
from sciplot_core.plot_document import DocumentError
from sciplot_core.plot_ir import seal_ir
from test_managed_backend import managed_ir


@pytest.mark.comprehensive
def test_complete_ir_rebuild_after_artifact_deletion_and_external_mutation(tmp_path):
    from PIL import Image

    ir = managed_ir()
    compiler = ManagedVeuszCompiler()
    try:
        first = compiler.compile_ir(ir, tmp_path / "artifacts")
        first_export = compiler.export_ir(ir, Path(first["document"]), tmp_path / "artifacts/exports")
        pixels = Image.open(first["preview"]["path"]).tobytes()
        native_evidence = deepcopy(first["scientific_audit"])
        # Canonical IR/source state survives outside the disposable backend tree.
        # Remove its generated IR copy, logs and every native/render/export file.
        import shutil

        assert first_export["ready_to_use"]
        shutil.rmtree(tmp_path / "artifacts")
        compiler.close()
        compiler = ManagedVeuszCompiler()
        rebuilt = compiler.compile_ir(ir, tmp_path / "artifacts")
        rebuilt_export = compiler.export_ir(ir, Path(rebuilt["document"]), tmp_path / "artifacts/exports")
        assert rebuilt["scientific_audit"] == native_evidence
        assert rebuilt["native_state_hash"] == first["native_state_hash"]
        assert rebuilt["ir_hash"] == first["ir_hash"] == ir["ir_hash"]
        assert Image.open(rebuilt["preview"]["path"]).tobytes() == pixels
        assert rebuilt_export["ready_to_use"]
        assert {record["format"] for record in rebuilt_export["exports"]} == {"pdf", "tiff_300"}
        path = f"/page1/graph1/{native_name('series', 'series:A')}"
        batch = tmp_path / "edit.json"
        batch.write_text(json.dumps([{"object_path": path, "setting_path": path + "/PlotLine/width",
            "expected_value": "0.7pt", "value": "1pt"}]))
        changed = tmp_path / "changed.vsz"
        compiler._run(["edit-document", rebuilt["document"], "--changes", str(batch),
                       "--output-document", str(changed), "--preview-png", str(tmp_path / "changed.png")])
        mutation = compiler.inspect_ir(ir, changed)
        assert mutation["opaque_native_change"] is False
        assert mutation["semantic_diff"] == [{"target": "series:A", "property": "style.line.width",
            "before": "0.7pt", "after": "1pt"}]
        assert mutation["scientific_audit"]["status"] == "passed"
        candidate = deepcopy(ir)
        candidate["series"][0]["style"]["line_width_pt"] = 1.0
        candidate = seal_ir(candidate)
        assert compiler.inspect_ir(candidate, changed)["status"] == "unchanged"
        batch.write_text(json.dumps([{"object_path": path, "setting_path": path + "/markerSize",
            "expected_value": "3.0pt", "value": "5pt"}]))
        opaque = tmp_path / "opaque.vsz"
        compiler._run(["edit-document", str(changed), "--changes", str(batch),
                       "--output-document", str(opaque), "--preview-png", str(tmp_path / "opaque.png")])
        assert compiler.inspect_ir(candidate, opaque)["opaque_native_change"] is True
        with pytest.raises(DocumentError, match="differs"):
            compiler.export_ir(candidate, opaque, tmp_path / "must-not-export")
        assert not (tmp_path / "must-not-export").exists()
    finally:
        compiler.close()


@pytest.mark.comprehensive
@pytest.mark.parametrize("mode", ["reference", "expression"])
def test_equal_looking_unrepresented_native_state_is_still_opaque(tmp_path, mode):
    import subprocess
    import sys

    from sciplot_core.veusz_runtime import veusz_worker_environment

    ir = managed_ir()
    compiler = ManagedVeuszCompiler()
    try:
        result = compiler.compile_ir(ir, tmp_path / "baseline")
        script = tmp_path / "mutate_native_test_fixture.py"
        script.write_text('''import sys
from pathlib import Path
from sciplot_core.veusz_worker.document_edit import loaded_native_document
from sciplot_core.plot_backends.managed_plan import native_name,dataset_name
with loaded_native_document(Path(sys.argv[1])) as doc:
    from veusz.document import CommandInterface
    interface=CommandInterface(doc)
    path='/page1/graph1/'+native_name('series','series:A')
    if sys.argv[3]=='reference':
        interface.SetToReference(path+'/PlotLine/color',path+'/MarkerLine/color')
    else:
        name=dataset_name('raw:A','column:0')
        interface.SetDataExpression(name,repr(doc.data[name].data.tolist()),linked=True)
    interface.Save(sys.argv[2])
''')
        modified = tmp_path / "modified.vsz"
        mutation = subprocess.run([sys.executable, str(script), result["document"], str(modified), mode],
                                  env=veusz_worker_environment(), capture_output=True, text=True, timeout=120)
        assert mutation.returncode == 0, mutation.stderr
        observed = compiler.inspect_ir(ir, modified)
        assert observed["status"] == "external_mutation"
        assert observed["opaque_native_change"] is True
        assert observed["semantic_diff"] == []
        if mode == "expression":
            assert observed["scientific_audit"]["status"] == "failed"
        with pytest.raises(DocumentError):
            compiler.audit_ir(ir, modified)
    finally:
        compiler.close()
