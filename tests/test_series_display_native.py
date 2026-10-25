"""Real public CLI display edits, cold reopen/export, replay and conflict guards."""

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

import pytest
from test_figure_document import request_for_figure

from sciplot_core._paths import REPO_ROOT
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.plot_engine.storage import load_head, read
from sciplot_core.plot_ir.figure_document import figure_spec


def _cli(*args, success=True):
    result = subprocess.run([str(REPO_ROOT / "skill/scripts/sciplot"), *map(str, args), "--json"],
                            cwd=REPO_ROOT, text=True, capture_output=True, timeout=180)
    if success:
        assert result.returncode == 0, result.stdout + result.stderr
    else:
        assert result.returncode != 0, result.stdout + result.stderr
    return json.loads(result.stdout)


def _complete(root, result, tmp_path):
    if result["status"] == "needs_review":
        assert result["scientific_audit"]["status"] == "passed"
        decision = tmp_path / ("decision-" + str(result["next_step"]["request"]["base_revision"]) + ".json")
        decision.write_text(json.dumps(result["next_step"]["request"]))
        result = _cli("plot", "decide", root, "--request", decision, "--direct")
    assert result["status"] == "complete" and result["ready_to_use"]
    return result


def _native_save(path, *, opaque=False):
    """Exercise an actual external native Save, with no VSZ text edits."""
    code = """
import sys
from pathlib import Path
from sciplot_core.veusz_worker.document_edit import loaded_native_document
with loaded_native_document(Path(sys.argv[1])) as document:
    from veusz.document import CommandInterface
    from veusz.document.operations import OperationSettingSet
    if sys.argv[2] == 'opaque':
        document.applyOperation(OperationSettingSet('/page1/graph1/Background/color', '#fafafa'))
        document.applyOperation(OperationSettingSet('/page1/graph1/series_2/PlotLine/style', 'dashed'))
    else:
        widgets = []
        document.walkNodes(lambda path, node: widgets.append(node) if node.typename == 'xy' else None, nodetypes=('widget',))
        document.applyOperation(OperationSettingSet(widgets[0].path + '/PlotLine/width', '1.7pt'))
    CommandInterface(document).Save(sys.argv[1])
"""
    result = subprocess.run([sys.executable, "-c", code, str(path), "opaque" if opaque else "style"], text=True, capture_output=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr


def _create(tmp_path, authority, *, collision=False):
    if authority == "legacy":
        source = tmp_path / "spectrum.csv"
        values = (2, 3, 4) if collision else (0.3, 0.7, 0.9)
        source.write_text("Wavelength,Absorbance,Wavelength,Absorbance\nnm,a.u.,nm,a.u.\nA,A,B,B\n"
                          f"500,3,410,{values[0]}\n450,2,470,{values[1]}\n450,2.5,490,{values[2]}\n400,1,,\n")
        made = _cli("studio", source, "--rule", "uvvis_spectrum", "--export", "pdf,tiff_300")
        _native_save(Path(made["project_dir"]) / "studio" / "document.vsz", opaque=True)
        opened = _cli("plot", "open", made["project_dir"], "--direct")
        return Path(opened["plot"]), [source], "series:A", "series:B"
    request = request_for_figure(tmp_path)
    source = tmp_path / "figure.csv"
    source.write_text("Frequency,Modulus\nHz,Pa\n10,15\n5,5\n5,7\n0,1\n")
    binding = request["data_binding"]
    binding["data_sources"][0].update(sha256=file_sha256(source))
    binding["data_sources"][0]["table_selection"]["data_end_row"] = 6
    second = tmp_path / "second.csv"
    second.write_text("Frequency,Modulus\nHz,Pa\n1,4\n7,8\n9,12\n")
    data = deepcopy(binding["data_sources"][0])
    data.update(source_id="raw:B", path=str(second), sha256=file_sha256(second))
    data["table_selection"]["data_end_row"] = 5
    binding["data_sources"].append(data)
    slot = deepcopy(binding["slots"]["modulus"])
    slot.update(series_id="layer:B", sample="B")
    slot["x"]["source_id"] = slot["y"]["source_id"] = "raw:B"
    binding["slots"]["B"] = slot
    layers = request["template_definition"]["figure_spec"]["views"][0]["layers"]
    other = deepcopy(layers[0])
    other.update(id="layer:B", dataset_id="raw:B", label="B", legend={"label": "B", "visible": True}, z_order=2)
    for mark in other["marks"]:
        mark["id"] += ":B"
    layers.append(other)
    for guide in request["template_definition"]["figure_spec"]["guides"]:
        for field in ("layer_ids", "order"):
            if guide[field]:
                guide[field].append("layer:B")
    path = tmp_path / "create.json"
    path.write_text(json.dumps(request))
    made = _cli("plot", "create", "--request", path, "--direct")
    assert made["ready_to_use"]
    return Path(made["plot"]), [source, second], "layer:modulus", "layer:B"


def _collision_stays_blocked(directory):
    directory.mkdir()
    root, sources, first, second = _create(directory, "legacy", collision=True)
    original = load_head(root)
    raw = {path: path.read_bytes() for path in sources}
    def legends(head):
        return [obj for obj in head["document"]["presentation"]["objects"].values() if obj["kind"] == "legend"]
    original_position = legends(original)[0]["properties"]["legend.position"]
    _complete(root, _cli("task", "edit", root, "--rename-series", first, "Control [A]", "--hide-series", second,
                        "--legend-columns", "2", "--task-dir", directory / "first"), directory)
    pending = _cli("task", "edit", root, "--show-series", second, "--task-dir", directory / "second")
    assert pending["status"] == "needs_review"
    decision = directory / "collision-decision.json"
    decision.write_text(json.dumps(pending["next_step"]["request"]))
    blocked = _cli("plot", "decide", root, "--request", decision, "--direct", success=False)
    assert blocked["status"] == "blocked" and blocked["commit_status"] == "committed" and not blocked["ready_to_use"]
    head = load_head(root)
    assert head["document"]["revision"] == 2 and head["document"]["scientific"] == original["document"]["scientific"]
    assert legends(head)[0]["properties"]["legend.position"] == original_position
    assert legends(head)[0]["properties"]["legend.columns"] == 2
    spec = json.loads(Path(head["binding"]["spec"]).read_text())
    assert spec["presentation_series_selection"]["active_order"] == ["A", "B"]
    assert spec["series"][0]["legend_key"] == "Control [A]" and spec["series"][0]["x_values"] == [500., 450., 450., 400.]
    assert all(path.read_bytes() == content for path, content in raw.items())
    manifests = [json.loads(path.read_text()) for path in (Path(head["binding"]["project"]) / "runs").glob("studio_*/manifest.json")]
    issues = [issue for manifest in manifests for issue in manifest.get("qa", {}).get("studio_layout", {}).get("critical_issues", [])]
    assert any(issue["id"] == "legend_curve_clearance_below_target" for issue in issues)


@pytest.mark.comprehensive
def test_public_cli_v2_series_style_cold_reopen_replay_and_rollback(tmp_path):
    request = request_for_figure(tmp_path)
    layer = request["template_definition"]["figure_spec"]["views"][0]["layers"][0]
    layer["marks"][0]["style"] = {"line_width_pt": 1.3, "line_style": "dashed", "line_opacity": 1.}
    layer["marks"][1]["style"] = {"marker": "square", "marker_size_pt": 4., "marker_line_width_pt": .9}
    path = tmp_path / "create-style.json"
    path.write_text(json.dumps(request))
    root = Path(_cli("plot", "create", "--request", path, "--direct")["plot"])
    source = tmp_path / "figure.csv"
    raw = source.read_bytes()
    initial = load_head(root)
    _complete(root, _cli("task", "edit", root, "--rename-series", "layer:modulus", "Control A",
                        "--task-dir", tmp_path / "rename"), tmp_path)
    before = load_head(root)
    old_spec = figure_spec(before["document"])
    entry = tmp_path / "style"
    arguments = ["task", "style", root, "--sample", "Control A", "--width", "1.1pt",
                 "--color", "#990000", "--task-dir", entry]
    result = _complete(root, _cli(*arguments), tmp_path)
    after = load_head(root)
    assert result["revision"] == 2
    assert after["document"]["scientific"] == initial["document"]["scientific"]
    assert after["document"]["scientific_hash"] == initial["document"]["scientific_hash"]
    expected = deepcopy(old_spec)
    marks = expected["views"][0]["layers"][0]["marks"]
    marks[0]["style"].update(line_color="#990000", line_width_pt=1.1)
    marks[1]["style"].update(marker_color="#990000")
    assert figure_spec(after["document"]) == expected
    before_ir, after_ir = (read(Path(head["binding"]["ir_path"])) for head in (before, after))
    assert after_ir["datasets"] == before_ir["datasets"] and after_ir["scales"] == before_ir["scales"]
    assert after_ir["guides"][0]["entries"][0]["marks"] == after_ir["views"][0]["layers"][0]["marks"]
    assert {item["format"] for item in result["exports"]} >= {"pdf", "tiff_300", "vsz"}
    assert all(Path(item["path"]).is_file() for item in result["exports"])
    record = read(entry / "semantic-style.json")
    assert _cli(*arguments)["replayed"] and load_head(root) == after
    assert read(entry / "semantic-style.json") == record
    opened = _cli("plot", "open", root, "--direct")
    assert opened["status"] == "current" and opened["revision"] == 2
    bad_entry = tmp_path / "bad-style"
    _cli("task", "style", root, "--sample", "Control A", "--sample", "unknown",
         "--color", "#000000", "--task-dir", bad_entry, success=False)
    assert not (bad_entry / "semantic-style.json").exists() and load_head(root) == after
    rollback = tmp_path / "rollback.json"
    rollback.write_text(json.dumps({"base_revision": 2, "target_revision": 1, "idempotency_key": "undo-style"}))
    _complete(root, _cli("plot", "rollback", root, "--request", rollback, "--direct"), tmp_path)
    assert load_head(root)["document"]["presentation_hash"] == before["document"]["presentation_hash"]
    assert source.read_bytes() == raw


@pytest.mark.comprehensive
@pytest.mark.parametrize("authority", ["managed", "legacy"])
def test_public_cli_series_display_cold_reopen_replay_and_rollback(tmp_path, authority):
    root, sources, first, second = _create(tmp_path, authority)
    before = load_head(root)
    raw = {str(path): path.read_bytes() for path in sources}
    science = deepcopy(before["document"]["scientific"])
    entry = tmp_path / "display-entry"
    arguments = ["task", "edit", root, "--rename-series", first, "Control [A]", "--hide-series", second, "--legend-columns", "2", "--task-dir", entry]
    if authority == "legacy":
        legend = next(obj for obj in before["document"]["presentation"]["objects"].values() if obj["kind"] == "legend")
        # The user explicitly selects this measured clear placement. The separate
        # collision case retains the original placement and must stay blocked.
        arguments += ["--legend-position", str(legend["properties"]["legend.position"][0]) + ",0.98"]
    result = _complete(root, _cli(*arguments), tmp_path)
    after = load_head(root)
    assert after["document"]["scientific"] == science
    assert after["document"]["coverage"] == before["document"]["coverage"]
    assert result["revision"] == 1
    replay = _cli(*arguments)
    assert replay["replayed"] and replay["revision"] == 1 and load_head(root) == after
    opened = _cli("plot", "open", root, "--direct")
    assert opened["status"] == "current" and opened["revision"] == 1
    if authority == "managed":
        summary = _cli("plot", "describe", root, "--scope", "summary", "--direct")
        assert "series.visible" in summary["edit_targets"][second]["properties"]
        assert "legend.columns" in summary["edit_targets"]["guide:legend"]["properties"]
        columns = _cli("plot", "describe", root, "--scope", "edit", "--target-id", "guide:legend", "--property", "legend.columns", "--direct")
        assert columns["current_value"] == 2
        assert columns["figure_edit_contract"]["guide:legend"]["legend.columns"] == opened["figure_edit_contract"]["guide:legend"]["legend.columns"]
    else:
        assert opened["objects"][second]["properties"]["series.visible"] is False
        assert opened["objects"][first]["properties"]["series.display_label"] == "Control [A]"
    restored = _complete(root, _cli("task", "edit", root, "--show-series", second, "--task-dir", tmp_path / "restore-entry"), tmp_path)
    assert restored["revision"] == 2
    head = load_head(root)
    assert head["document"]["scientific"] == science
    exported = _cli("plot", "export", root, "--direct")
    assert exported["ready_to_use"]
    assert _cli(*arguments)["revision"] == 1 and load_head(root) == head
    if authority == "managed":
        ir = read(Path(head["binding"]["ir_path"]))
        assert [len(ir["datasets"][name]["columns"]["column:0"]["values"]) for name in ("raw:A", "raw:B")] == [4, 3]
        assert ir["datasets"]["raw:A"]["columns"]["column:0"]["values"] == [10., 5., 5., 0.]
        layer = figure_spec(head["document"])["views"][0]["layers"][0]
        assert layer["label"] == layer["legend"]["label"] == "Control [A]"
        assert figure_spec(head["document"])["guides"][0]["columns"] == 2
        assert ir["guides"][0]["columns"] == 2 and len(ir["guides"][0]["entries"]) == 2
    else:
        spec = json.loads(Path(head["binding"]["spec"]).read_text())
        assert [item["label"] for item in spec["series"]] == ["A", "B"]
        assert spec["series"][0]["legend_key"] == "Control [A]"
        assert [len(item["x_values"]) for item in spec["series"]] == [4, 3]
        legends = [obj for obj in head["document"]["presentation"]["objects"].values() if obj["kind"] == "legend"]
        assert [obj["properties"]["legend.columns"] for obj in legends] == [2]
        assert legends[0]["properties"]["legend.position"][1] == .98
        from sciplot_core.studio_core.document_edit_state import run_document_worker

        native_state = run_document_worker("inspect-document-state", head["binding"]["document"])
        assert native_state["widgets"]["/page1/graph1"]["settings"]["Background/color"] == "#fafafa"
        assert native_state["widgets"]["/page1/graph1/series_2"]["settings"]["PlotLine/style"] == "dashed"
    rollback = tmp_path / "rollback.json"
    rollback.write_text(json.dumps({"base_revision": 2, "target_revision": 0, "idempotency_key": "restore-original"}))
    undone = _complete(root, _cli("plot", "rollback", root, "--request", rollback, "--direct"), tmp_path)
    assert undone["revision"] == 3
    assert load_head(root)["document"]["presentation_hash"] == before["document"]["presentation_hash"]
    assert all(Path(path).read_bytes() == value for path, value in raw.items())
    # A real external native Save and raw-byte tampering both invalidate binding.
    native = Path(load_head(root)["binding"]["document"])
    baseline = native.read_bytes()
    _native_save(native)
    assert native.read_bytes() != baseline
    blocked = _cli("task", "edit", root, "--hide-series", second, "--task-dir", tmp_path / "blocked", success=False)
    assert blocked.get("status") == "blocked" or blocked.get("reason_code")
    assert load_head(root)["document"]["revision"] == 3
    if authority == "legacy":
        _collision_stays_blocked(tmp_path / "collision")
    native.write_bytes(baseline)
    bound_raw = Path(science["data_sources"][0]["path"])
    bound_raw.write_bytes(bound_raw.read_bytes() + b"\n")
    blocked = _cli("task", "edit", root, "--hide-series", second, "--task-dir", tmp_path / "raw-blocked", success=False)
    assert blocked.get("status") == "blocked" or blocked.get("reason_code")
    assert load_head(root)["document"]["revision"] == 3
