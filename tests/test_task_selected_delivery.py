"""Selected deliveries use the first figure's existing Managed publication."""

import json
from pathlib import Path
from shutil import copytree
import subprocess

import pytest

from sciplot_core._paths import REPO_ROOT
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.project_lifecycle import figure_handoff
from sciplot_core.project_lifecycle.contracts import AuthorityMode, RevisionToken
from sciplot_core.task_contract import TaskControlError, validate_task_request
from sciplot_core.task_control import inspect_task, resume_task
from sciplot_core.task_group_contract import normalize_group_request
from sciplot_core.task_semantic_owner import local_managed_actions
from sciplot_core.task_storage import load_task, save_task


def _request(source, out, formats):
    return {"version": 1, "action": "create", "sources": [str(source)], "out": str(out),
            "intent": {"x": {"quantity": "time", "unit": "s"}, "y": {"quantity": "mass", "unit": "%"}},
            "formats": formats}


def test_formats_are_normalized_and_only_accepted_for_standalone_semantic_creation(tmp_path):
    source = tmp_path / "original.csv"
    source.write_text("Time,Mass\ns,%\n0,100\n10,96\n")
    request = _request(source, tmp_path / "output", ["tiff_300", "pdf"])
    assert validate_task_request(request)["formats"] == ["pdf", "tiff_300"]
    for bad in ([], ["tiff_300"], ["pdf", "pdf"], ["pdf", "png"], ["plotted_csv"], ["pdf", "plotted_csv"], ["editable_vsz"], "pdf"):
        with pytest.raises(TaskControlError):
            validate_task_request({**request, "formats": bad})
    with pytest.raises(TaskControlError, match="formats"):
        validate_task_request({"version": 1, "action": "create", "source": str(source), "formats": ["pdf"]})
    with pytest.raises(TaskControlError, match="formats"):
        normalize_group_request({"version": 1, "title": "Group", "items": [
            {"id": "first", "label": "First", "request": request}]})
    assert not (tmp_path / "output").exists()


@pytest.fixture
def saved_figure(tmp_path, monkeypatch):
    """Only the sealed native publication is substituted; install and task journal are real."""
    tmp_path = tmp_path.resolve()
    root, out, plot = (tmp_path / name for name in ("task", "figure", "canonical"))
    plot.mkdir()
    source = tmp_path / "data.csv"
    source.write_text("Time,Mass\ns,%\n0,100\n10,96\n")
    pdf = plot / "figure.pdf"
    pdf.write_bytes(b"%PDF-test original immutable publication")
    token = RevisionToken("plot:first", AuthorityMode.MANAGED, 0, "a" * 64, "b" * 64)
    result = {"status": "complete", "ready_to_use": True, "plot": str(plot), **token.to_payload(),
              "exports": [{"path": str(pdf), "format": "pdf", "sha256": file_sha256(pdf)}]}
    save_task(root, {"kind": "sciplot_task", "version": 1, "task_dir": str(root), "intent_revision": 1,
                    "phase": "delivering", "status": "running", "project": str(plot), "result": result,
                    "request": _request(source, out, ["pdf"]), "source_hashes": {str(source): file_sha256(source)}})

    def publication(_root, _out, _request, _backend, *, cold_export=False):
        assert not cold_export
        return token, result["exports"]

    monkeypatch.setattr(figure_handoff, "_publication", publication)

    def handoff(path, request, **options):
        assert path == plot
        return figure_handoff.handoff_figure(path, request, None, **options)

    def forbidden(*_args):
        pytest.fail("The selected-file path may not rebuild or package the saved figure.")

    with local_managed_actions(forbidden, forbidden, forbidden, handoff=handoff):
        yield root, out, source


def test_interruption_after_atomic_install_recovers_without_another_install(saved_figure, monkeypatch):
    root, out, source = saved_figure
    real_install = figure_handoff.install_new_delivery

    class LostReply(BaseException):
        pass

    def interrupted(staged, selected):
        assert load_task(root)["figure_install"]["directory_identity"][1] == staged.stat().st_ino
        real_install(staged, selected)
        raise LostReply()

    monkeypatch.setattr(figure_handoff, "install_new_delivery", interrupted)
    with pytest.raises(LostReply):
        resume_task(root, {"retry": True})
    frozen = load_task(root)
    assert frozen["status"] == "running" and "delivery_result" not in frozen
    recovered = resume_task(root, {"retry": True})
    assert recovered["ready_to_use"] is True and recovered["figure_handoff_current"] is True
    receipt = (root / "task.json").read_bytes()
    assert inspect_task(root)["next_step"]["files"] == [{"pdf": str(out / "figure.pdf")}]
    assert resume_task(root, {"retry": True})["ready_to_use"] is True
    assert (root / "task.json").read_bytes() == receipt

    source.write_text("Time,Mass\ns,%\n0,100\n10,95\n")
    stale = inspect_task(root)
    assert stale["ready_to_use"] is False and stale["blocker"]["reason_code"] == "source_changed"
    assert (root / "task.json").read_bytes() == receipt and (out / "figure.pdf").is_file()


def test_identical_foreign_output_winning_install_race_is_never_claimed(saved_figure, monkeypatch):
    root, out, _source = saved_figure
    real_install = figure_handoff.install_new_delivery

    def occupied(staged, selected):
        copytree(staged, selected)
        assert selected.stat().st_ino != staged.stat().st_ino
        real_install(staged, selected)

    monkeypatch.setattr(figure_handoff, "install_new_delivery", occupied)
    failed = resume_task(root, {"retry": True})
    assert failed["blocker"]["reason_code"] == "figure_handoff_destination_exists"
    file = out / "figure.pdf"
    original = file.stat().st_ino, file.read_bytes()
    retry = resume_task(root, {"retry": True})
    assert retry["blocker"]["reason_code"] == "figure_handoff_install_changed"
    assert retry["next_step"]["action"] == "export_selected_files"
    assert (file.stat().st_ino, file.read_bytes()) == original


@pytest.mark.comprehensive
def test_cli_first_figure_can_deliver_only_pdf_and_reopen_same_project(tmp_path):
    from test_task_control_native import _cli

    source = tmp_path / "synthetic-tga.csv"
    source.write_text("Time,Mass\ns,%\n0,100\n10,98\n20,95\n30,91\n40,90\n")
    original = source.read_bytes()
    out, task, request = (tmp_path / name for name in ("figure", "task", "request.json"))
    request.write_text(json.dumps(_request(source, out, ["pdf"])))
    result = _cli("task", "start", "--request", request, "--task-dir", task)
    assert result["ready_to_use"] is True and result["model_calls_by_sciplot"] == 0
    assert result["result"]["revision"] == 0
    assert "exports" not in result["result"]  # The internal PDF/TIFF/VSZ are not extra deliverables.
    files, = result["next_step"]["files"]
    assert set(files) == {"pdf"} and list(out.iterdir()) == [Path(files["pdf"])]
    assert Path(files["pdf"]).read_bytes().startswith(b"%PDF")
    assert "images" not in result["next_step"] and "plotting_data" not in result["next_step"]
    project = Path(result["project"])
    assert project.is_dir() and not project.is_relative_to(out.resolve())
    before = (task / "task.json").read_bytes()
    reopened = _cli("task", "inspect", task)
    assert reopened["current_project"] == result["current_project"]
    assert reopened["next_step"]["files"] == result["next_step"]["files"]
    assert _cli("task", "resume", task, "--retry")["ready_to_use"] is True
    pdf_bytes = Path(files["pdf"]).read_bytes()
    Path(files["pdf"]).unlink()
    status = subprocess.run([REPO_ROOT / "skill/scripts/sciplot", "task", "resume", task, "--retry", "--json"],
                            cwd=REPO_ROOT, capture_output=True, text=True, timeout=120, check=False)
    assert status.returncode == 1, status.stdout + status.stderr
    changed = json.loads(status.stdout)
    assert changed["ready_to_use"] is False and changed["next_step"]["action"] == "export_selected_files"
    assert "delivery_result" not in changed
    assert not list(out.iterdir()) and (task / "task.json").read_bytes() == before
    export_argv = [tmp_path / "fresh-output" if arg == "NEW_OUTPUT_DIR" else arg
                   for arg in changed["next_step"]["cli_argv"][1:-1]]
    reexported = _cli(*export_argv)
    copied, = reexported["exports"]
    assert copied["format"] == "pdf" and Path(copied["path"]).read_bytes() == pdf_bytes
    assert not list(out.iterdir())
    assert project.is_dir() and source.read_bytes() == original


@pytest.mark.comprehensive
def test_daily_mcp_selects_raw_blocks_then_hands_off_only_pdf_and_tiff(tmp_path):
    import anyio
    from PIL import Image

    pytest.importorskip("mcp")
    from mcp import Client
    from test_mcp_stdio import _call, _parameters
    from test_task_semantic_creation import _single_table_spectral_control
    from managed_plot_helpers import read_managed_head_and_ir
    from sciplot_core.plot_backends.native_primitives import dataset_name
    from sciplot_core.veusz_worker.document_edit import loaded_native_document

    source, intent = _single_table_spectral_control(tmp_path)
    original = source.read_bytes().replace(b"4000,55", b",")
    source.write_bytes(original)
    task, out = tmp_path / "task", tmp_path / "figure"
    intent.pop("selection")
    intent.pop("labels")

    async def scenario():
        async with Client(_parameters(cli=True, profile="daily"), read_timeout_seconds=60) as client:
            request = {**_request(source, out, ["tiff_300", "pdf"]), "intent": intent,
                       "choose_columns": True, "curve_display": "raw_overlay"}
            pending = await _call(client, "sciplot_task_start", {"request": request, "task_dir": str(task)})
            assert pending["status"] == "needs_input" and not out.exists()
            assert load_task(task.resolve())["request"]["formats"] == ["pdf", "tiff_300"]
            question = pending["question"]
            decision, = question["plan"]["decisions"]
            assert decision["field"] == "blocks" and len(decision["options"]) == 3
            answer = {"expected_question_id": question["question_id"], "confirm_plan": True,
                      "choices": {"blocks": [decision["options"][index] for index in (0, 2)]}}
            done = await _call(client, "sciplot_task_resume", {"task": str(task), "response": answer})
            assert done["ready_to_use"] is True and done["source_plan"]["selection"]["selected_block_count"] == 2
            assert done["result"]["revision"] == 0
            selection = done["source_plan"]["selection"]
            assert selection["selected_point_count"] == 5
            assert [(entry["data_start_row"], entry["data_end_row"]) for entry in selection["selected"]] == [(3, 6), (3, 5)]
            assert [entry["sample"] for entry in selection["selected"]] == ["Resin blue", "Excluded resin"]
            assert [entry["block_id"] for entry in selection["excluded"]] == ["block:1"]
            files, = done["next_step"]["files"]
            assert set(files) == {"pdf", "tiff_300"}
            assert set(out.resolve().iterdir()) == {Path(path) for path in files.values()}
            assert "plotting_data" not in done["next_step"]
            assert Path(files["pdf"]).read_bytes().startswith(b"%PDF")
            with Image.open(files["tiff_300"]) as image:
                assert image.format == "TIFF" and image.info["dpi"] == pytest.approx((300, 300))
            assert done["next_step"]["images"] == [files["tiff_300"]]
        async with Client(_parameters(cli=True, profile="daily"), read_timeout_seconds=60) as client:
            reopened = await _call(client, "sciplot_task_inspect", {"task": str(task)})
            assert reopened["ready_to_use"] is True and reopened["project"] == done["project"]
            assert reopened["next_step"]["files"] == done["next_step"]["files"]
            assert reopened["source_plan"]["selection"] == selection

        head, ir = read_managed_head_and_ir(Path(done["project"]))
        with loaded_native_document(Path(head["binding"]["document"])) as loaded:
            for layer, x, y in zip(ir["views"][0]["layers"], [[700., 2600., 3900.], [800., 2700.]],
                                   [[84., 62., 79.], [51., 43.]], strict=True):
                assert loaded.data[dataset_name(layer["dataset_id"], "x")].data.tolist() == x
                assert loaded.data[dataset_name(layer["dataset_id"], "y")].data.tolist() == y

    anyio.run(scenario)
    assert source.read_bytes() == original
