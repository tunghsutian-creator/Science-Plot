"""The project CLI reuses the verified ordinary Managed curve and delivery owner."""
import json
from pathlib import Path

import pytest

from sciplot_core.cli import main
from sciplot_core.plan_preview import build_plan_preview
from sciplot_core.plot_backends.managed import ManagedVeuszCompiler
from sciplot_core.plot_backends.figure_marks import coordinates
from sciplot_core.plot_engine.storage import load_head
from sciplot_core.plot_protocol.server import make_service
from sciplot_core.studio_core.project_creation import create_project
from sciplot_core.task_semantic_owner import local_managed_actions


@pytest.mark.comprehensive
def test_verified_curve_project_creates_managed_and_recovers_existing_delivery(tmp_path, capsys, monkeypatch):
    import pymupdf

    raw = tmp_path / "UVvis.csv"
    original = b"Wavelength,Absorbance\nnm,a.u.\nA,A\n400,2\n460,5\n500,1\n"
    raw.write_bytes(original)
    planned = build_plan_preview(raw, request={})
    old = create_project(raw, expected_plan=planned, output_dir=tmp_path / "old", _creation_owner="legacy-fixture")
    old_spec = json.loads(Path(old["document"]).with_name("spec.json").read_bytes())
    plan, out = tmp_path / "plan.json", tmp_path / "New"
    plan.write_text(json.dumps(planned), encoding="utf-8")
    cmd = ["project", "create", str(raw), "--expected-plan", str(plan), "--out", str(out), "--json"]
    service = make_service()
    deliver = service.deliver

    def delivery_interrupted(_):
        return {"status": "blocked", "ready_to_use": False, "blocker": {"reason_code": "interrupted",
                "message": "Simulated lost delivery connection."}}

    def no_native(*args, **kwargs):
        pytest.fail("Retry should package the saved current plot, not recreate or export it.")

    try:
        with local_managed_actions(service.create, service.describe, delivery_interrupted):
            assert main(cmd) != 0
        blocked = json.loads(capsys.readouterr().out)
        assert blocked["document_authority"] == "managed_plot" and not out.exists()
        plot = Path(blocked["project_dir"])
        head = load_head(plot)
        assert head["document"]["plot_type"] == "ManagedPlot" and head["document"]["revision"] == 0
        ir = json.loads(Path(head["binding"]["ir_path"]).read_bytes())
        layer, = ir["views"][0]["layers"]
        xy = coordinates(ir, layer)
        assert (xy["x"], xy["y"]) == (old_spec["series"][0]["x_values"], old_spec["series"][0]["y_values"])
        assert [item["unit"] for item in ir["scales"]] == ["nm", "a.u."]
        monkeypatch.setattr(ManagedVeuszCompiler, "compile_ir", no_native)
        monkeypatch.setattr(ManagedVeuszCompiler, "export_ir", no_native)
        with local_managed_actions(service.create, service.describe, deliver):
            assert main(cmd) == 0
            result = json.loads(capsys.readouterr().out)
            assert result["project_dir"] == str(plot) and result["analysis_metrics"][0]["value"] == 460
            assert Path(result["document"]).is_file()
            assert result["studio_run"]["delivery_package"] == {"path": str(out), "complete": True}
            old_pdf = old["figures"][0]["exports"][0]["path"]
            new_pdf = result["figures"][0]["exports"][0]["path"]
            with pymupdf.open(old_pdf) as a, pymupdf.open(new_pdf) as b:
                assert a[0].rect == b[0].rect
                assert "Wavelength (nm)" in b[0].get_text() and "Absorbance (a.u.)" in b[0].get_text()
            assert main(cmd) == 0
            assert json.loads(capsys.readouterr().out) == result
            document = Path(result["document"])
            edited = document.read_bytes() + b"\n# local edits\n"
            document.write_bytes(edited)
            assert main(cmd) != 0
            assert json.loads(capsys.readouterr().out)["status"] == "blocked"
            assert document.read_bytes() == edited
        assert load_head(plot)["document"]["revision"] == 0
        assert raw.read_bytes() == original
    finally:
        service.close()
