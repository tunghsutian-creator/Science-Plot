"""The public project and task creators share one real Managed frequency owner."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

from sciplot_core.cli import main
from sciplot_core.plan_preview import build_plan_preview
from sciplot_core.plot_backends.managed import ManagedVeuszCompiler
from sciplot_core.project_store import FileProjectStore
from test_rheology_mean_suite_publication import _mean_input


@pytest.mark.comprehensive
def test_project_create_managed_frequency_keeps_external_delivery_and_reopens(tmp_path, capsys, monkeypatch):
    raw, _ = _mean_input(tmp_path)
    out, plan_file = tmp_path / "Deliverables", tmp_path / "plan.json"
    plan = build_plan_preview(raw, request={"rule_id": "rheology_frequency_sweep"})
    plan_file.write_text(json.dumps(plan), encoding="utf-8")
    create = ["project", "create", str(raw), "--expected-plan", str(plan_file), "--out", str(out), "--json"]
    assert main(create) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["document_authority"] == "managed_figure_group"
    assert result["studio_run"]["delivery_package"] == {"path": str(out), "complete": True}
    assert result["studio_run"]["ready_to_use"] is True
    manifest = json.loads(Path(result["studio_run"]["manifest"]).read_bytes())
    assert manifest["publication_qa"]["status"] == "passed" and manifest["publication_qa"]["coverage_complete"]
    assert len(result["figures"]) == 4 and all(Path(item["document"]).is_file() and len(item["exports"]) == 2
                                               for item in result["figures"])
    assert not Path(result["project_dir"]).joinpath("studio").exists()
    assert main(["project", "inspect", result["project_dir"], "--figure", result["primary_figure_id"], "--full"]) == 0
    current = json.loads(capsys.readouterr().out)
    assert current["ready_to_use"] and current["selected_figure"]["plot"] == result["figures"][0]["plot"]
    assert current["publication_scope"] == "selected_managed_revision"
    assert current["initial_group_publication"]["currentness_evaluated"] is False
    selected = current["selected_figure"]
    assert selected["revision"] == 0 and selected["export_current"]["byte_inventory_verified"] is True
    assert selected["document"] != result["figures"][0]["document"]
    assert [artifact["format"] for artifact in selected["exports"]][:2] == ["pdf", "tiff_300"]
    assert main(["project", "inspect", str(out), "--full"]) == 0
    assert json.loads(capsys.readouterr().out)["project"] == result["project_dir"]
    secondary = result["figures"][1]
    assert main(["project", "inspect", secondary["document"], "--full"]) == 0
    assert json.loads(capsys.readouterr().out)["selected_figure"]["figure_id"] == secondary["figure_id"]
    unknown = Path(secondary["document"]).with_name("unregistered.vsz")
    inspect_unknown = ["project", "inspect", str(unknown), "--full", "--json"]
    assert main(inspect_unknown) != 0
    assert "document does not exist" in capsys.readouterr().out
    unknown.write_bytes(Path(secondary["document"]).read_bytes())
    assert main(inspect_unknown) != 0
    assert "not registered in this delivery" in capsys.readouterr().out
    unknown.unlink()
    store = FileProjectStore(Path(result["project_dir"]))
    generation = store.snapshot()["generation"]

    def no_native(*args, **kwargs):
        pytest.fail("The exact project retry must reuse its delivered group.")

    with monkeypatch.context() as no_render:
        no_render.setattr(ManagedVeuszCompiler, "compile_ir", no_native)
        no_render.setattr(ManagedVeuszCompiler, "export_ir", no_native)
        assert main(create) == 0
        assert json.loads(capsys.readouterr().out) == result and store.snapshot()["generation"] == generation
        document = Path(result["document"])
        original = document.read_bytes()
        manual = original + b"\n# user edit\n"
        document.write_bytes(manual)
        try:
            assert main(create) != 0
            assert "Saved Veusz copy has local edits" in capsys.readouterr().out
            assert document.read_bytes() == manual
        finally:
            document.write_bytes(original)

        # The archive of the selected secondary is still exact when the
        # primary member's saved publication is not.
        primary_pdf, = (store.root / "figures" / result["primary_figure_id"]).glob("*.pdf")
        original_pdf = primary_pdf.read_bytes()
        primary_pdf.unlink()
        try:
            assert main(["project", "inspect", str(store.root), "--full"]) == 0
            historical = json.loads(capsys.readouterr().out)
            assert historical["publication_scope"] == "initial_managed_group_delivery"
            assert not historical["qa"]["current"]
            assert main(["project", "inspect", str(store.root), "--figure", secondary["figure_id"], "--full"]) == 0
            exact = json.loads(capsys.readouterr().out)
            assert exact["ready_to_use"] and exact["selected_figure"]["revision"] == 0
            assert all(Path(item["path"]).is_relative_to(store.root)
                       for item in exact["selected_figure"]["exports"])
            assert not primary_pdf.exists()
        finally:
            primary_pdf.write_bytes(original_pdf)

    # An interactive export of a newer head is current even though the
    # archived initial group is still generation zero for this plot.
    from sciplot_core.plot_engine.service import PlotService

    service = PlotService()
    try:
        head = service.describe(Path(secondary["plot"]), description={"scope": "summary"})
        patch = service.patch(Path(secondary["plot"]), {"plot_id": head["plot_id"], "base_revision": 0,
            "idempotency_key": "current-secondary-axis-label", "intent_class": "presentation",
            "changes": [{"op": "set", "target": ["axis:x"], "property": "axis.label", "value": "Angular frequency (rad/s)"}]})
        assert patch["revision"] == 1 and patch["ready_to_use"]
    finally:
        service.close()
    current_generation = store.snapshot()["generation"]
    assert current_generation != generation
    assert main(["project", "inspect", str(store.root), "--full"]) == 0
    assert not json.loads(capsys.readouterr().out)["qa"]["current"]
    assert main(["project", "inspect", secondary["document"], "--full"]) == 0
    exact = json.loads(capsys.readouterr().out)
    assert exact["ready_to_use"] and exact["selected_figure"]["revision"] == 1
    assert exact["initial_group_publication"]["generation"] == generation
    assert store.snapshot()["generation"] == current_generation

def _cold_task(root: Path, crash: bool) -> int:
    import os

    from sciplot_core.workflow import frequency_managed_suite as owner

    real = owner._figure

    def recording(store, snapshot, key, figure_id, request, compiler, private):
        with (root / "calls.txt").open("a", encoding="utf-8") as stream:
            stream.write(figure_id + "\n")
        if crash and figure_id == "complex_viscosity_vs_frequency":
            os._exit(47)
        return real(store, snapshot, key, figure_id, request, compiler, private)

    owner._figure = recording
    from sciplot_core.task_control import resume_task, start_task

    task = root / "Task"
    if crash:
        result = start_task({"version": 1, "action": "create", "source": str(root / "raw"), "rule_id": "rheology_frequency_sweep",
                             "out": str(root / "Delivered")}, task_dir=task)
    else:
        result = resume_task(task, {"retry": True})
    print(json.dumps(result))
    return 0 if result["status"] == "complete" else 1


@pytest.mark.comprehensive
def test_task_create_managed_frequency_cold_resume_uses_exact_owner(tmp_path):
    _mean_input(tmp_path)
    command = [sys.executable, "-c",
               "import sys; from pathlib import Path; from test_managed_frequency_creation import _cold_task;"
               "sys.exit(_cold_task(Path(sys.argv[1]), sys.argv[2] == 'crash'))", str(tmp_path)]
    first = subprocess.run([*command, "crash"], capture_output=True, text=True, timeout=120)
    assert first.returncode == 47, first.stderr + first.stdout
    task = tmp_path / "Task" / "task.json"
    state = json.loads(task.read_bytes())
    assert state["phase"] == "creating" and state["frequency_creation_plan"]["rule_id"] == "rheology_frequency_sweep"
    assert not (tmp_path / "Delivered").exists()
    completed = subprocess.run([*command, "continue"], capture_output=True, text=True, timeout=120)
    assert completed.returncode == 0, completed.stderr + completed.stdout
    result = json.loads(completed.stdout)
    assert result["status"] == "complete" and result["result"]["document_authority"] == "managed_figure_group"
    assert result["current_project"]["ready_to_use"] is True
    assert FileProjectStore(Path(result["project"])).snapshot()["sequence"] == 1
    calls = (tmp_path / "calls.txt").read_text().splitlines()
    assert calls == ["storage_modulus_vs_frequency", "loss_modulus_vs_frequency", "loss_factor_vs_frequency",
                     "complex_viscosity_vs_frequency", "complex_viscosity_vs_frequency"]
