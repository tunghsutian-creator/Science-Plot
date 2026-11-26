"""The project CLI reuses the verified ordinary Managed curve and delivery owner."""
import json
from pathlib import Path

import pytest

from sciplot_core.cli import main
from sciplot_core.plan_preview import build_plan_preview
from sciplot_core.plot_backends.managed import ManagedVeuszCompiler
from sciplot_core.plot_backends.figure_marks import coordinates
from sciplot_core.project_lifecycle.context import repository_scope
from sciplot_core.project_lifecycle.repository_router import ComposedProjectRepository
from sciplot_core.plot_protocol.server import make_service
from sciplot_core.studio_core.project_creation import create_project
from sciplot_core.task_semantic_owner import local_managed_actions


def _load_head(plot: Path) -> dict:
    repository = ComposedProjectRepository()
    with repository_scope(repository), repository.query_scope(plot):
        return repository.load_head(plot)


@pytest.mark.comprehensive
def test_verified_curve_project_creates_managed_and_recovers_existing_delivery(tmp_path, capsys, monkeypatch):
    import pymupdf

    from sciplot_core.studio_core import project_creation

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
        head = _load_head(plot)
        assert plot.parent.name == ".sciplot_semantic"
        assert (plot.parent.parent / ".sciplot_store" / "head.json").is_file()
        assert not (plot.parent.parent / "managed-creation.json").exists()
        assert head["document"]["plot_type"] == "ManagedPlot" and head["document"]["revision"] == 0
        ir = json.loads(Path(head["binding"]["ir_path"]).read_bytes())
        layer, = ir["views"][0]["layers"]
        xy = coordinates(ir, layer)
        assert (xy["x"], xy["y"]) == (old_spec["series"][0]["x_values"], old_spec["series"][0]["y_values"])
        assert [item["unit"] for item in ir["scales"]] == ["nm", "a.u."]
        monkeypatch.setattr(ManagedVeuszCompiler, "compile_ir", no_native)
        monkeypatch.setattr(ManagedVeuszCompiler, "export_ir", no_native)
        monkeypatch.setattr(project_creation, "resolve_expected_plan", no_native)
        with local_managed_actions(no_native, service.describe, deliver):
            # The full plan and source still belong to the original creation.
            plan.write_text(json.dumps({**planned, "unexpected": True}), encoding="utf-8")
            assert main(cmd) != 0
            assert "different source-bound Managed creation" in capsys.readouterr().out
            plan.write_text(json.dumps(planned), encoding="utf-8")
            raw.write_bytes(original.replace(b"460,5", b"460,6"))
            assert main(cmd) != 0
            assert "Source changed since the expected plan" in capsys.readouterr().out
            raw.write_bytes(original)
            assert not out.exists()
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
            for target in (str(plot), str(out), result["document"], result["request"]):
                assert main(["project", "inspect", target, "--full", "--json", "--figure", result["primary_figure_id"]]) == 0
                inspected = json.loads(capsys.readouterr().out)
                assert inspected["project"] == str(plot) and inspected["ready_to_use"] is True
                assert inspected["selected_figure"]["figure_id"] == result["primary_figure_id"]
            # Current figure evidence is independent of its creation task.
            journal = Path(result["request"])
            parked_journal = journal.with_name("parked-task.json")
            journal.rename(parked_journal)
            try:
                assert main(["project", "inspect", str(plot), "--full", "--json"]) == 0
                inspected = json.loads(capsys.readouterr().out)
                assert inspected["request"] is None and inspected["ready_to_use"] is True
                assert inspected["figures"][0]["plot_id"] == head["document"]["plot_id"]
                assert inspected["publication_scope"] == "selected_managed_revision"
            finally:
                parked_journal.rename(journal)
            missing = Path(result["document"]).with_name("missing.vsz")
            assert main(["project", "inspect", str(missing), "--full", "--json"]) != 0
            assert "does not exist" in capsys.readouterr().out
            document = Path(result["document"])
            edited = document.read_bytes() + b"\n# local edits\n"
            document.write_bytes(edited)
            assert main(cmd) != 0
            assert json.loads(capsys.readouterr().out)["status"] == "blocked"
            assert document.read_bytes() == edited
        assert _load_head(plot)["document"]["revision"] == 0
        assert raw.read_bytes() == original
    finally:
        service.close()


@pytest.mark.comprehensive
def test_source_only_uvvis_single_and_group_keep_managed_authority_through_retry_and_cold_edit(
    tmp_path, capsys, monkeypatch,
):
    import subprocess

    from sciplot_core import task_execution, task_group_review, task_semantic_creation
    from sciplot_core._paths import REPO_ROOT
    from sciplot_core.task_storage import load_task

    raw = tmp_path / "UVvis.csv"
    original = b"Wavelength,Absorbance\nnm,a.u.\nA,A\n460,5\n400,2\n500,1\n"
    raw.write_bytes(original)
    group_root = tmp_path / "group"
    group_request = tmp_path / "group.json"
    group_out = tmp_path / "group-figures"
    group_request.write_text(json.dumps({"version": 1, "title": "UV–vis", "items": [{
        "id": "spectrum", "label": "Original absorbance", "request": {
            "version": 1, "action": "create", "source": str(raw), "out": str(group_out)}}]}))
    single_root = tmp_path / "single"
    service = make_service()
    from sciplot_core.semantic_sources import scientific_source_single_curve as curve_owner

    real_admit, real_deliver = task_semantic_creation.admit_raw_curve, service.deliver
    real_resolve = curve_owner.resolve_single_curve_transform
    attempts, admits, observations = [], [], []

    def resolve_once(source, **kwargs):
        observations.append(source)
        return real_resolve(source, **kwargs)

    monkeypatch.setattr(curve_owner, "resolve_single_curve_transform", resolve_once)

    def native_ordinary_forbidden(*_args, **_kwargs):
        pytest.fail("A verified Managed UV–vis creation cannot dispatch the native compatibility route.")

    def admit(state, plan, observed):
        admits.append(state["task_dir"])
        assert observed is not None
        return real_admit(state, plan, observed)

    def lose_delivery(wire):
        # Drop a response after the actual delivery owner completed its write.
        result = real_deliver(wire)
        attempts.append(wire)
        if Path(wire["out"]) == group_out and len([item for item in attempts if Path(item["out"]) == group_out]) == 1:
            raise RuntimeError("lost delivery reply after publication")
        return result

    def cli(arguments):
        code = main([*arguments, "--json"])
        payload = json.loads(capsys.readouterr().out)
        assert code == 0, payload
        return payload

    monkeypatch.setattr(task_semantic_creation, "admit_raw_curve", admit)
    monkeypatch.setattr(task_execution, "create_project", native_ordinary_forbidden)
    monkeypatch.setattr(task_group_review, "inspect_project", native_ordinary_forbidden)
    try:
        with local_managed_actions(service.create, service.describe, lose_delivery):
            single = cli(["task", "create", str(raw), "--out", str(tmp_path / "single-figures"),
                          "--task-dir", str(single_root)])
            blocked = cli(["task", "group", "start", "--request", str(group_request),
                           "--group-dir", str(group_root)])
        child = Path(blocked["items"][0]["task_dir"])
        frozen = load_task(child)
        assert blocked["items"][0]["status"] == "blocked"
        assert blocked["items"][0]["task"]["blocker"]["message"] == "lost delivery reply after publication"
        assert observations == [raw, raw]  # Exactly one observation for each original creation.
        assert frozen["analysis_metrics"][0]["value"] == 460.
        assert frozen["creation_admission"] == {"route": "managed_plot", "reason_code": "verified_raw_curve"}
        assert frozen["phase"] == "delivering" and (group_out / "index.json").is_file()
        before_delivery = {p.relative_to(group_out): p.read_bytes() for p in group_out.rglob("*") if p.is_file()}
        response_file = tmp_path / "responses.json"
        response_file.write_text(json.dumps([{"item_id": "spectrum", "task_dir": str(child),
                                             "response": {"retry": True}}]))
    finally:
        service.close()

    # Only retry the persisted delivery intent with a fresh real owner. Neither
    # new source admission nor Managed creation may execute after the lost reply.
    service = make_service()
    try:
        with local_managed_actions(native_ordinary_forbidden, service.describe, service.deliver):
            group = cli(["task", "group", "resume", str(group_root), "--responses", str(response_file)])
            item, = group["items"]
            assert group["counts"] == {"complete": 1} and item["ready_to_use"] is True
            assert item["source"] == str(raw) and item["source_current"] is True
            assert item["plot_objects"] == item["task"]["plot_objects"]
            assert item["document_authority"] == "managed_plot"
            gallery = Path(group["overview"]).read_text()
            assert 'data-attention="false"' in gallery and item["project"] in gallery
            old_item = cli(["task", "group", "inspect", str(group_root)])["items"][0]
            assert old_item["plot_objects"] == item["plot_objects"]
    finally:
        service.close()
    assert admits == [str(single_root), str(child)]
    resumed = load_task(child)
    assert resumed["managed_request"] == frozen["managed_request"]
    assert resumed["creation_attempts"] == frozen["creation_attempts"]
    assert resumed["delivery_request"] == frozen["delivery_request"]
    assert {p.relative_to(group_out): p.read_bytes() for p in group_out.rglob("*") if p.is_file()} == before_delivery

    def cold_plot(action, plot, *args):
        result = subprocess.run([str(REPO_ROOT / "skill/scripts/sciplot"), "plot", action, plot, "--direct", "--json", *args],
                                cwd=REPO_ROOT, capture_output=True, text=True, timeout=90, check=False)
        assert result.returncode == 0, result.stdout + result.stderr
        return json.loads(result.stdout)

    single_handle, = single["plot_objects"]
    group_handle, = item["plot_objects"]
    assert single_handle["plot_id"] != group_handle["plot_id"]
    for handle in (single_handle, group_handle):
        assert handle["plot_type"] == "ManagedPlot" and handle["revision"] == 0
        head = _load_head(Path(handle["plot"]))
        ir = json.loads(Path(head["binding"]["ir_path"]).read_bytes())
        layer, = ir["views"][0]["layers"]
        xy = coordinates(ir, layer)
        assert (xy["x"], xy["y"]) == ([460.0, 400.0, 500.0], [5.0, 2.0, 1.0])
        assert [scale["unit"] for scale in ir["scales"]] == ["nm", "a.u."]
        wire = load_task(single_root if handle == single_handle else child)["managed_request"]
        assert wire["storage"] == "project_store_v2" and "out" not in wire
        slot, = wire["data_binding"]["slots"].values()
        assert (slot["sample"], slot["x_unit"], slot["y_unit"]) == ("A", "nm", "a.u.")
        before = cold_plot("describe", handle["plot"], "--scope", "summary")
        assert (before["plot_id"], before["revision"]) == (handle["plot_id"], 0)
        before_edit = cold_plot("describe", handle["plot"], "--scope", "edit", "--target-id", layer["marks"][0]["id"],
                                "--property", "style")
        next_step = before_edit["next_step"]
        assert next_step["action"] == "plot.patch"
        patch_file = tmp_path / "patch.json"
        patch_file.write_text(json.dumps({**{key: next_step[key] for key in ("plot_id", "base_revision", "intent_class")},
            "idempotency_key": "a1-color-control",
            "changes": [{"op": "set", "target": [next_step["target"]], "property": next_step["property"],
                         "value": {"line_color": "#2277aa"}}]}))
        changed = cold_plot("patch", handle["plot"], "--request", str(patch_file))
        assert changed["plot_id"] == before["plot_id"] and changed["revision"] == 1
        reopened = cold_plot("describe", handle["plot"], "--scope", "summary")
        assert (reopened["plot_id"], reopened["revision"]) == (before["plot_id"], 1)
        assert reopened["scientific_hash"] == before["scientific_hash"]
        assert reopened["presentation_hash"] != before["presentation_hash"]
        after_head = _load_head(Path(handle["plot"]))
        after_ir = json.loads(Path(after_head["binding"]["ir_path"]).read_bytes())
        after_layer, = after_ir["views"][0]["layers"]
        assert after_layer["marks"][0]["style"]["line_color"] == "#2277aa"
        assert coordinates(after_ir, after_layer) == xy
        assert raw.read_bytes() == original
        if handle == single_handle:
            single_edit = before_edit
        else:
            assert before_edit["figure_edit_contract"] == single_edit["figure_edit_contract"]
            assert before_edit["current_value"] == single_edit["current_value"]
    assert {p.relative_to(group_out): p.read_bytes() for p in group_out.rglob("*") if p.is_file()} == before_delivery


@pytest.mark.comprehensive
def test_source_only_uvvis_without_a_verified_sample_uses_native_and_reports_why(tmp_path, capsys):
    raw = tmp_path / "UVvis.csv"
    original = b"Wavelength,Absorbance\nnm,a.u.\n400,2\n460,5\n500,1\n"
    raw.write_bytes(original)
    task = tmp_path / "task"
    code = main(["task", "create", str(raw), "--out", str(tmp_path / "figures"), "--task-dir", str(task), "--json"])
    result = json.loads(capsys.readouterr().out)
    assert code == 0, result
    assert result["creation_admission"]["route"] == "native_compatibility"
    assert result["creation_admission"]["reason_code"] == "raw_science_not_verified_for_managed"
    assert result.get("source_plan") is None and result.get("plot_objects") is None
    assert result["status"] == "complete"
    assert Path(result["current_project"]["figures"][0]["document"]).is_file()
    assert raw.read_bytes() == original
