"""Real native common edits preserve scientific state and unrelated presentation."""

from argparse import ArgumentParser
from copy import deepcopy
import json
from pathlib import Path
import subprocess

import pytest
from test_figure_document import request_for_figure

from sciplot_core._paths import REPO_ROOT
from sciplot_core.cli.dispatch.common_edits import dispatch_common_edit
from sciplot_core.cli.parsers.common_edits import register_common_edit_command
from sciplot_core.plot_engine.errors import EngineError
from sciplot_core.plot_engine.service import PlotService
from sciplot_core.plot_engine.storage import load_head, read
from sciplot_core.plot_ir.figure_document import figure_spec
from sciplot_core.task_common_edits import edit_task


def _parser():
    parser = ArgumentParser()
    register_common_edit_command(parser.add_subparsers(dest="task_action", required=True))
    return parser


@pytest.mark.comprehensive
def test_native_cli_common_batch_preserves_original_science_and_exports_once(tmp_path, capsys):
    request = request_for_figure(tmp_path)
    spec = request["template_definition"]["figure_spec"]
    spec["views"][0]["axes"][0]["style"] = {"line_width_pt": 1.1, "tick_direction": "out"}
    spec["views"][0]["layers"][0]["marks"][0]["style"] = {"line_width_pt": 1.3, "line_style": "dash"}
    service = PlotService()
    try:
        created = service.create(request)
        root = Path(created["plot"])
        initial = load_head(root)
        source = tmp_path / "figure.csv"
        source_bytes = source.read_bytes()
        original_ir = read(Path(initial["binding"]["ir_path"]))
        entry = tmp_path / "common-entry"
        arguments = ["edit", str(root), "--intent", "换配色 tol_bright；统一字号 9pt；图例字号 7pt", "--task-dir", str(entry), "--json"]
        assert dispatch_common_edit(_parser().parse_args(arguments)) == 0
        result = json.loads(capsys.readouterr().out)
        assert result["status"] == "complete" and result["ready_to_use"]
        assert result["revision"] == 1 and result["scientific_hash"] == initial["document"]["scientific_hash"]
        after = load_head(root)
        actual_ir = read(Path(after["binding"]["ir_path"]))
        assert actual_ir["datasets"] == original_ir["datasets"]
        assert actual_ir["scales"] == original_ir["scales"]
        assert source.read_bytes() == source_bytes
        actual = figure_spec(after["document"])
        assert actual["layout"] == spec["layout"] and actual["composition"] == spec["composition"]
        assert actual["views"][0]["axes"][0]["style"]["tick_direction"] == "out"
        assert actual["views"][0]["axes"][0]["style"]["line_width_pt"] == 1.1
        assert actual["views"][0]["layers"][0]["marks"][0]["style"]["line_style"] == "dash"
        assert actual["views"][0]["layers"][0]["marks"][0]["style"]["line_width_pt"] == 1.3
        assert actual_ir["views"][0]["panel_label_style"]["font_size_pt"] == 9.
        assert all(axis["style"]["font_size_pt"] == 9. for axis in actual_ir["views"][0]["axes"])
        assert actual_ir["guides"][0]["style"]["font_size_pt"] == 7.
        assert actual_ir["views"][0]["layers"][0]["marks"][0]["style"]["line_color"] == "#4477aa"
        assert actual_ir["views"][0]["layers"][0]["marks"][1]["style"]["marker_color"] == "#4477aa"
        assert Path(after["binding"]["document"]).is_file()
        assert {item["format"] for item in result["exports"]} >= {"pdf", "tiff_300", "vsz"}
        assert all(Path(item["path"]).is_file() for item in result["exports"])
        assert result["publication_qa"]["status"] == "passed" and result["publication_qa"]["native_text_checked"]
        journal = read(entry / "semantic-edit.json")
        replay = edit_task(root, task_dir=entry, palette="tol_bright", font_size="9pt", legend_font_size="7pt")
        assert replay["replayed"] and replay["revision"] == 1
        assert read(entry / "semantic-edit.json") == journal
        assert load_head(root) == after
        # Existing rollback is the recovery authority; the shortcut adds none.
        undo = service.rollback(root, {"base_revision": 1, "target_revision": 0, "idempotency_key": "restore-native-original"})
        if undo["status"] == "needs_review":
            undo = service.decide(root, undo["next_step"]["request"])
        assert undo["status"] == "complete"
        restored = load_head(root)["document"]
        assert restored["presentation_hash"] == initial["document"]["presentation_hash"]
        assert restored["scientific_hash"] == initial["document"]["scientific_hash"]
    finally:
        service.close()


@pytest.mark.comprehensive
def test_native_font_family_applies_to_all_represented_typography(tmp_path):
    from PyQt6.QtGui import QFontDatabase, QGuiApplication

    application = QGuiApplication.instance() or QGuiApplication([])
    available = sorted(QFontDatabase.families())
    assert application and available, "A native Qt font catalog is required for this acceptance."
    family = next((name for name in ("Helvetica", "Liberation Sans", "DejaVu Sans") if name in available), available[0])
    request = request_for_figure(tmp_path)
    spec = request["template_definition"]["figure_spec"]
    spec["annotations"] = [{"id": "annotation:note", "space": "view", "view_id": "view:A", "x": .5, "y": .5, "text": "N", "visible": True, "style": {"font_family": "Arial", "font_size_pt": 6.}}]
    service = PlotService()
    try:
        created = service.create(request)
        root = Path(created["plot"])
        before = load_head(root)
        result = edit_task(root, font_family=family, service=service)
        assert result["ready_to_use"] and result["scientific_hash"] == before["document"]["scientific_hash"]
        head = load_head(root)
        ir = read(Path(head["binding"]["ir_path"]))
        fonts = [axis["style"]["font_family"] for view in ir["views"] for axis in view["axes"]]
        fonts += [view["panel_label_style"]["font_family"] for view in ir["views"]]
        fonts += [guide["style"]["font_family"] for guide in ir["guides"]]
        fonts += [annotation["style"]["font_family"] for annotation in ir["annotations"]]
        assert fonts and set(fonts) == {family}
        assert ir["annotations"][0]["style"]["font_size_pt"] == 6.
        with pytest.raises(EngineError):
            edit_task(root, font_family="This font does not exist 2987", service=service)
        assert load_head(root) == head
    finally:
        service.close()


@pytest.mark.comprehensive
def test_native_legacy_legend_edit_keeps_vsz_and_shadow_science_authoritative(tmp_path):
    source = tmp_path / "ordinary.csv"
    source.write_text("Wavelength,Absorbance,Wavelength,Absorbance\nnm,a.u.,nm,a.u.\nA,A,B,B\n400,1,400,2\n450,2,450,3\n500,3,500,4\n")
    created = subprocess.run([str(REPO_ROOT / "skill/scripts/sciplot"), "studio", str(source), "--rule", "uvvis_spectrum", "--export", "pdf,tiff_300", "--json"], capture_output=True, text=True, timeout=180, cwd=REPO_ROOT)
    assert created.returncode == 0, created.stdout + created.stderr
    project = Path(json.loads(created.stdout)["project_dir"])
    service = PlotService()
    try:
        opened = service.open(project)
        root = Path(opened["plot"])
        before = load_head(root)
        assert before["document"].get("plot_type", "LegacyPlot") == "LegacyPlot"
        source_bytes = source.read_bytes()
        result = edit_task(root, intent="隐藏图例", task_dir=tmp_path / "legacy-entry", service=service)
        assert result["status"] == "needs_review"
        result = service.decide(root, result["next_step"]["request"])
        assert result["ready_to_use"] and result["scientific_hash"] == before["document"]["scientific_hash"]
        after = load_head(root)
        assert after["document"].get("plot_type", "LegacyPlot") == "LegacyPlot"
        assert after["document"]["coverage"] == before["document"]["coverage"]
        assert after["document"]["scientific"] == before["document"]["scientific"]
        assert after["binding"]["document"] == before["binding"]["document"]
        assert source.read_bytes() == source_bytes
        assert [obj["properties"]["legend.visible"] for obj in after["document"]["presentation"]["objects"].values() if obj["kind"] == "legend"] == [False]
        before_objects = deepcopy(before["document"]["presentation"]["objects"])
        after_objects = deepcopy(after["document"]["presentation"]["objects"])
        for obj in before_objects.values():
            if obj["kind"] == "legend":
                obj["properties"]["legend.visible"] = False
        assert after_objects == before_objects
    finally:
        service.close()
