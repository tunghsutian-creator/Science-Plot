from __future__ import annotations

import json
from pathlib import Path
import selectors
import shutil
import subprocess
import sys

from PIL import Image
import pytest

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.render import render_to_dir
from sciplot_core.veusz_runtime import veusz_worker_environment


@pytest.fixture(scope="module")
def native_figure(tmp_path_factory):
    root = tmp_path_factory.mktemp("live-native-figure")
    source = root / "values.csv"
    source.write_text(
        "Time,Force,Time,Force,Time,Force,Time,Force,Time,Force\n"
        "s,N,s,N,s,N,s,N,s,N\nA,A,B,B,C,C,D,D,E,E\n"
        "0,1,0,2,0,3,0,4,0,5\n1,3,1,4,1,5,1,6,1,7\n2,2,2,3,2,4,2,5,2,6\n"
    )
    result = render_to_dir(source, template="curve", output_dir=root / "render",
                           export_formats=("pdf",), options={"size": "60x55"})
    return source, Path(result["veusz_documents"][0]), Path(result["veusz_specs"][0])


class Worker:
    def __init__(self, root, document, spec):
        self.errors = (root / "worker.stderr").open("w+")
        self.process = subprocess.Popen(
            [sys.executable, "-m", "sciplot_core.veusz_worker.live_session", "--document", str(document),
             "--spec", str(spec), "--out", str(root / "frames")],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.errors, text=True,
            env=veusz_worker_environment(),
        )
        self.number = 0

    def request(self, op, **values):
        self.number += 1
        request_id = f"request-{self.number}"
        self.process.stdin.write(json.dumps({"request_id": request_id, "op": op, **values}) + "\n")
        self.process.stdin.flush()
        with selectors.DefaultSelector() as selector:
            selector.register(self.process.stdout, selectors.EVENT_READ)
            assert selector.select(timeout=30), "Native session did not return a response."
        line = self.process.stdout.readline()
        if not line:
            self.errors.seek(0)
            pytest.fail(self.errors.read())
        result = json.loads(line)
        assert result["request_id"] == request_id, result
        return result

    def close(self):
        try:
            if self.process.poll() is None:
                assert self.request("close")["closed"]
            self.process.wait(timeout=10)
        finally:
            if self.process.poll() is None:
                self.process.kill()
                self.process.wait(timeout=10)
            self.errors.close()


def changed(state, path, field_id, value):
    field = next(field for field in state["objects"][path]["editable_fields"] if field["field_id"] == field_id)
    return {"object_path": path, "setting_path": field["setting_path"],
            "expected_value": field["current_value"], "value": value}


def native_command(*args):
    result = subprocess.run([sys.executable, "-m", "sciplot_core.veusz_worker", *map(str, args)],
                            capture_output=True, text=True, env=veusz_worker_environment(), timeout=60)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.comprehensive
def test_live_session_native_edits_undo_redo_and_final_patch_match_transaction_preview(tmp_path, native_figure):
    source, document, spec = native_figure
    hashes = [file_sha256(path) for path in native_figure]
    worker = Worker(tmp_path, document, spec)
    try:
        initial = worker.request("state")["state"]
        assert initial["render_revision"] == 1 and not initial["dirty"]
        assert not initial["can_undo"] and not initial["can_redo"]
        assert worker.request("state")["state"] == initial
        static = native_command("preview-document", document, "--out", tmp_path / "static.png")
        assert static["preview"]["sha256"] == initial["preview"]["sha256"]
        curve = "/page1/graph1/series_1"
        first_changes = [changed(initial, curve, "series_line_color", "#A020F0"),
                         changed(initial, curve, "series_line_width", "2pt")]
        first = worker.request("set", changes=first_changes)["state"]
        assert first["render_revision"] == 2 and first["changes"] == first_changes
        second = worker.request("set", changes=[changed(first, curve, "series_line_color", "#E04030")])["state"]
        assert len(second["changes"]) == 2
        assert second["changes"][0] == {**first_changes[0], "value": "#E04030"}
        legend = next(path for path, item in second["objects"].items() if item["type"] == "key")
        font = next(field for field in second["objects"][legend]["editable_fields"]
                    if field["setting_path"].endswith("/Text/size"))
        third = worker.request("set", changes=[changed(second, legend, font["field_id"], "8pt")])["state"]
        assert len(third["changes"]) == 3
        assert third["preview"]["sha256"] != initial["preview"]["sha256"]
        patch = tmp_path / "changes.json"
        patch.write_text(json.dumps(third["changes"]))
        replay = native_command("edit-document", document, "--changes", patch,
                                "--output-document", tmp_path / "candidate.vsz",
                                "--preview-png", tmp_path / "candidate.png", "--audit-spec", spec)
        assert replay["document_audit"]["status"] == "passed"
        assert replay["preview"]["sha256"] == third["preview"]["sha256"]
        assert worker.request("undo")["state"]["changes"] == second["changes"]
        assert worker.request("undo")["state"]["changes"] == first["changes"]
        undone = worker.request("undo")["state"]
        assert undone["changes"] == [] and not undone["dirty"] and undone["can_redo"]
        assert undone["preview"]["sha256"] == initial["preview"]["sha256"]
        for _ in range(3):
            redone = worker.request("redo")["state"]
        assert redone["changes"] == third["changes"]
        assert redone["preview"]["sha256"] == third["preview"]["sha256"]
        assert redone["render_revision"] > third["render_revision"]
    finally:
        worker.close()
    assert [file_sha256(path) for path in (source, document, spec)] == hashes


@pytest.mark.comprehensive
def test_invalid_or_stale_setting_batch_does_not_change_live_values_or_frame(tmp_path, native_figure):
    _source, document, spec = native_figure
    worker = Worker(tmp_path, document, spec)
    try:
        initial = worker.request("state")["state"]
        curve = "/page1/graph1/series_1"
        valid = changed(initial, curve, "series_line_color", "#A020F0")
        invalid = {"object_path": curve, "setting_path": curve + "/yData", "expected_value": "y", "value": "other"}
        for batch in ([valid, invalid], [{**valid, "expected_value": "stale"}], [{**valid, "value": "invalid-color"}]):
            rejected = worker.request("set", changes=batch)
            assert rejected["status"] == "error" and not rejected["error"]["fatal"]
            assert worker.request("state")["state"] == initial
        no_op = worker.request("set", changes=[{**valid, "value": valid["expected_value"]}])["state"]
        assert no_op["changes"] == [] and not no_op["can_undo"]
        assert no_op["render_revision"] == initial["render_revision"] + 1
    finally:
        worker.close()


@pytest.mark.comprehensive
def test_hit_uses_native_paint_records_and_rejects_old_frame_and_invalid_pixels(tmp_path, native_figure):
    _source, document, spec = native_figure
    worker = Worker(tmp_path, document, spec)
    try:
        initial = worker.request("state")["state"]
        curve = "/page1/graph1/series_1"
        state = worker.request("set", changes=[changed(initial, curve, "series_line_color", "#A020F0"),
                                               changed(initial, curve, "series_line_width", "2pt")])["state"]
        image = Image.open(state["preview"]["path"]).convert("RGB")
        pixels = [(x, y) for y in range(image.height) for x in range(image.width)
                  if sum(abs(actual - expected) for actual, expected in
                         zip(image.getpixel((x, y)), (160, 32, 240), strict=True)) < 40]
        assert pixels
        targets = [pixels[len(pixels) * fraction // 4] for fraction in (1, 2, 3)]
        hits = [worker.request("hit", x=x, y=y, render_revision=state["render_revision"])
                for x, y in targets]
        assert any(hit["object_path"] == curve for hit in hits)
        assert all(hit["state"]["render_revision"] == state["render_revision"] for hit in hits)
        for values in ({"x": targets[0][0], "y": targets[0][1], "render_revision": initial["render_revision"]},
                       {"x": -1, "y": 1, "render_revision": state["render_revision"]},
                       {"x": True, "y": 1, "render_revision": state["render_revision"]}):
            result = worker.request("hit", **values)
            assert result["status"] == "error" and not result["error"]["fatal"]
        assert worker.request("state")["state"] == state
    finally:
        worker.close()


@pytest.mark.comprehensive
@pytest.mark.parametrize("invalidated", ["document_removed", "spec_changed"])
def test_invalidated_session_inputs_terminate_without_publishing_another_frame(tmp_path, native_figure, invalidated):
    _source, document, spec = native_figure
    snapshot, copied_spec = tmp_path / "snapshot.vsz", tmp_path / "spec.json"
    shutil.copyfile(document, snapshot)
    shutil.copyfile(spec, copied_spec)
    worker = Worker(tmp_path, snapshot, copied_spec)
    try:
        initial = worker.request("state")["state"]
        if invalidated == "document_removed":
            snapshot.unlink()
        else:
            copied_spec.write_text(copied_spec.read_text() + "\n")
        rejected = worker.request("render")
        assert rejected["status"] == "error" and rejected["error"]["fatal"]
        assert worker.process.wait(timeout=10) == 1
        frames = list((tmp_path / "frames").glob("*.png"))
        assert frames == [Path(initial["preview"]["path"])]
    finally:
        worker.close()


@pytest.mark.comprehensive
def test_native_key_drag_uses_recorded_geometry_and_replays_saved_pixels(tmp_path, native_figure):
    _source, document, spec = native_figure
    original_hash = file_sha256(document)
    worker = Worker(tmp_path, document, spec)
    try:
        initial = worker.request("state")["state"]
        key = next(path for path, widget in initial["objects"].items() if widget["type"] == "key")
        handle = initial["objects"][key]["drag_handle"]
        assert handle["kind"] == "key"
        assert not any("drag_handle" in widget for widget in initial["objects"].values() if widget["type"] != "key")
        before = handle["bounds"]
        moved = worker.request("move_key", object_path=key, dx=-23, dy=-37,
                               render_revision=initial["render_revision"])["state"]
        after = moved["objects"][key]["drag_handle"]["bounds"]
        assert after == pytest.approx([before[0] - 23, before[1] - 37, *before[2:]])
        values = {field["setting_path"].rsplit("/", 1)[-1]: field["current_value"]
                  for field in moved["objects"][key]["editable_fields"]}
        assert values["horzPosn"] == values["vertPosn"] == "manual"
        assert all(change["object_path"] == key for change in moved["changes"])
        assert len(moved["changes"]) <= 4 and moved["can_undo"]
        patch = tmp_path / "key-changes.json"
        patch.write_text(json.dumps(moved["changes"]))
        replay = native_command("edit-document", document, "--changes", patch,
                                "--output-document", tmp_path / "moved.vsz",
                                "--preview-png", tmp_path / "replay.png", "--audit-spec", spec)
        reopened = native_command("preview-document", tmp_path / "moved.vsz", "--out", tmp_path / "reopened.png")
        assert replay["document_audit"]["status"] == "passed"
        assert moved["preview"]["sha256"] == replay["preview"]["sha256"] == reopened["preview"]["sha256"]
        undone = worker.request("undo")["state"]
        assert undone["changes"] == [] and undone["objects"][key]["drag_handle"] == handle
        assert undone["preview"]["sha256"] == initial["preview"]["sha256"]
        redone = worker.request("redo")["state"]
        assert redone["preview"]["sha256"] == moved["preview"]["sha256"]
        for fields in ({"object_path": key, "dx": 1, "dy": 1, "render_revision": initial["render_revision"]},
                       {"object_path": "/page1/graph1/series_1", "dx": 1, "dy": 1},
                       {"object_path": key, "dx": 99999, "dy": 0},
                       {"object_path": key, "dx": False, "dy": 1}):
            result = worker.request("move_key", **{"render_revision": redone["render_revision"], **fields})
            assert result["status"] == "error" and not result["error"]["fatal"]
            assert worker.request("state")["state"] == redone
    finally:
        worker.close()
    assert file_sha256(document) == original_hash


@pytest.mark.comprehensive
def test_key_drag_preserves_all_nine_native_alignment_snap_targets(tmp_path, native_figure):
    _source, document, spec = native_figure
    script = '''
import json, sys
from pathlib import Path
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.veusz_worker.live_session import LiveNativeSession, loaded_native_document
document, spec, output = map(Path, sys.argv[1:])
with loaded_native_document(document) as native:
    session = LiveNativeSession(native, document, spec, output,
        document_sha256=file_sha256(document), spec_sha256=file_sha256(spec))
    initial = session.state()
    path = next(p for p, w in initial['objects'].items() if w['type'] == 'key')
    widget = native.resolveWidgetPath(None, path)
    control = session.paint_helper.getControlGraph(widget)[0]
    item = control.createGraphicsItem(None)
    targets = [(names, (point.x()/control.cgscale, point.y()/control.cgscale))
               for names, point in item.highlightpoints.items()]
    assert len(targets) == 9
    for (horizontal, vertical), (x, y) in targets:
        current = session.state()
        bounds = current['objects'][path]['drag_handle']['bounds']
        moved = session.dispatch(dict(op='move_key', object_path=path,
            dx=x-bounds[0]+2, dy=y-bounds[1]-2, render_revision=current['render_revision']))['state']
        assert widget.settings.horzPosn == horizontal and widget.settings.vertPosn == vertical
        assert widget.settings.horzManual == 0 and widget.settings.vertManual == 0
        result = moved['objects'][path]['drag_handle']['bounds']
        assert abs(result[0]-x) < 1e-9 and abs(result[1]-y) < 1e-9
        session.dispatch(dict(op='undo'))
    # Leaving an aligned anchor must restore both position modes to manual.
    current = session.state()
    origin = current['objects'][path]['drag_handle']['bounds']
    x, y = next(point for names, point in targets if names == ('left', 'top'))
    anchored = session.dispatch(dict(op='move_key', object_path=path,
        dx=x-origin[0], dy=y-origin[1], render_revision=current['render_revision']))['state']
    manual = session.dispatch(dict(op='move_key', object_path=path,
        dx=21, dy=31, render_revision=anchored['render_revision']))['state']
    assert widget.settings.horzPosn == widget.settings.vertPosn == 'manual'
    result = manual['objects'][path]['drag_handle']['bounds']
    assert abs(result[0]-x-21) < 1e-9 and abs(result[1]-y-31) < 1e-9
    session.dispatch(dict(op='undo'))
    session.dispatch(dict(op='undo'))
    assert session.state()['preview']['sha256'] == initial['preview']['sha256']
    print(json.dumps({'verified_native_targets': len(targets)}))
'''
    result = subprocess.run([sys.executable, "-c", script, str(document), str(spec), str(tmp_path / "frames")],
                            capture_output=True, text=True, env=veusz_worker_environment(), timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["verified_native_targets"] == 9


@pytest.mark.comprehensive
def test_native_partial_failure_terminates_protocol_without_persisting_document(tmp_path, native_figure):
    _source, document, spec = native_figure
    before = file_sha256(document)
    script = '''
import io, json, sys
from pathlib import Path
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.veusz_worker.live_session import LiveNativeSession, serve, loaded_native_document
document, spec, output = map(Path, sys.argv[1:])
with loaded_native_document(document) as native:
    session = LiveNativeSession(native, document, spec, output,
        document_sha256=file_sha256(document), spec_sha256=file_sha256(spec))
    original = native.applyOperation
    def fail_after_mutation(operation):
        original(operation)
        raise RuntimeError('injected partial native failure')
    native.applyOperation = fail_after_mutation
    path = '/page1/graph1/series_1'
    field = next(f for f in session.state()['objects'][path]['editable_fields'] if f['field_id'] == 'series_line_width')
    commands = [dict(request_id='bad', op='set', changes=[dict(object_path=path,
        setting_path=field['setting_path'], expected_value=field['current_value'], value='3pt')]),
        dict(request_id='must-not-run', op='state')]
    stream = io.StringIO()
    code = serve(session, io.StringIO(''.join(json.dumps(c)+'\\n' for c in commands)), stream)
    results = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert code == 1 and session.closed and len(results) == 1
    assert results[0]['request_id'] == 'bad' and results[0]['error']['fatal']
    print(json.dumps(results[0]))
'''
    result = subprocess.run([sys.executable, "-c", script, str(document), str(spec), str(tmp_path / "frames")],
                            capture_output=True, text=True, env=veusz_worker_environment(), timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["error"]["fatal"]
    assert file_sha256(document) == before


@pytest.mark.comprehensive
def test_marker_activation_is_visible_undoable_and_survives_save_none_and_reopen(tmp_path, native_figure):
    _source, document, spec = native_figure
    original = file_sha256(document)
    curve = "/page1/graph1/series_1"
    worker = Worker(tmp_path, document, spec)
    try:
        initial = worker.request("state")["state"]
        fields = {field["field_id"]: field for field in initial["objects"][curve]["editable_fields"]}
        assert fields["series_marker"]["current_value"] == "none"
        assert "none" in fields["series_marker"]["choices"]
        assert fields["series_marker_line_hidden"]["current_value"] is True
        assert fields["series_fill_hidden"]["current_value"] is True
        marked = worker.request("set", changes=[changed(initial, curve, "series_marker", "circle")])["state"]
        assert marked["preview"]["sha256"] != initial["preview"]["sha256"]
        assert marked["changes"][-1] == {"object_path": curve, "setting_path": curve + "/MarkerLine/hide",
                                         "expected_value": True, "value": False}
        undone = worker.request("undo")["state"]
        assert undone["changes"] == [] and undone["preview"]["sha256"] == initial["preview"]["sha256"]
        assert worker.request("redo")["state"]["preview"]["sha256"] == marked["preview"]["sha256"]
        patch = tmp_path / "marker.json"
        patch.write_text(json.dumps(marked["changes"]))
        saved = native_command("edit-document", document, "--changes", patch,
                               "--output-document", tmp_path / "circle.vsz",
                               "--preview-png", tmp_path / "circle.png", "--audit-spec", spec)
        assert saved["document_audit"]["status"] == "passed"
        assert saved["preview"]["sha256"] == marked["preview"]["sha256"]
        removed = worker.request("set", changes=[changed(marked, curve, "series_marker", "none")])["state"]
        assert removed["preview"]["sha256"] == initial["preview"]["sha256"]
        assert removed["changes"] == [marked["changes"][-1]]  # Visibility remains explicit in the final diff.
    finally:
        worker.close()
    # A saved circle can become none, be saved, and then be reactivated after reopening.
    current_document = tmp_path / "circle.vsz"
    for index, marker in enumerate(("none", "circle"), 1):
        folder = tmp_path / f"reopened-{index}"
        folder.mkdir()
        reopened = Worker(folder, current_document, spec)
        try:
            state = reopened.request("state")["state"]
            changed_state = reopened.request("set", changes=[changed(state, curve, "series_marker", marker)])["state"]
            expected_png = initial if marker == "none" else marked
            assert changed_state["preview"]["sha256"] == expected_png["preview"]["sha256"]
            changes = folder / "changes.json"
            changes.write_text(json.dumps(changed_state["changes"]))
            saved = native_command("edit-document", current_document, "--changes", changes,
                                   "--output-document", folder / "saved.vsz",
                                   "--preview-png", folder / "saved.png", "--audit-spec", spec)
            assert saved["preview"]["sha256"] == changed_state["preview"]["sha256"]
            current_document = folder / "saved.vsz"
        finally:
            reopened.close()
    assert file_sha256(document) == original


@pytest.mark.comprehensive
def test_point_only_native_series_cannot_lose_its_last_visible_marker(tmp_path, native_figure):
    _source, document, spec = native_figure
    point_document = tmp_path / "point-only.vsz"
    script = '''
import sys
from pathlib import Path
from importlib import import_module
from sciplot_core.veusz_worker.document_edit import loaded_native_document
with loaded_native_document(Path(sys.argv[1])) as native:
    operations = import_module('veusz.document.operations')
    path = '/page1/graph1/series_1/'
    values = {'PlotLine/hide': True, 'marker': 'circle', 'MarkerLine/hide': False, 'MarkerFill/hide': True}
    native.applyOperation(operations.OperationMultiple([
        operations.OperationSettingSet(path+suffix, value) for suffix, value in values.items()]))
    import_module('veusz.document').CommandInterface(native).Save(sys.argv[2])
'''
    setup = subprocess.run([sys.executable, "-c", script, str(document), str(point_document)],
                           capture_output=True, text=True, env=veusz_worker_environment(), timeout=60)
    assert setup.returncode == 0, setup.stderr
    worker = Worker(tmp_path, point_document, spec)
    curve = "/page1/graph1/series_1"
    try:
        initial = worker.request("state")["state"]
        marker = next(field for field in initial["objects"][curve]["editable_fields"] if field["field_id"] == "series_marker")
        assert "none" not in marker["choices"]
        for change in (changed(initial, curve, "series_marker", "none"),
                       changed(initial, curve, "series_marker_line_hidden", True)):
            rejected = worker.request("set", changes=[change])
            assert rejected["status"] == "error" and not rejected["error"]["fatal"]
            assert worker.request("state")["state"] == initial
        fill_only = worker.request("set", changes=[
            changed(initial, curve, "series_marker_line_hidden", True),
            changed(initial, curve, "series_fill_hidden", False)])["state"]
        # Native lineplus cannot be filled; shape selection must enable its outline.
        plus = worker.request("set", changes=[changed(fill_only, curve, "series_marker", "lineplus")])["state"]
        assert next(field["current_value"] for field in plus["objects"][curve]["editable_fields"]
                    if field["field_id"] == "series_marker_line_hidden") is False
        assert plus["preview"]["sha256"] != fill_only["preview"]["sha256"]
        assert worker.request("undo")["state"]["preview"]["sha256"] == fill_only["preview"]["sha256"]
    finally:
        worker.close()
