"""Native Qt edits and command clients share the same saved figure revisions."""

from contextlib import closing
import os
from pathlib import Path
import shutil
import signal

import pytest

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.plot_engine.service import PlotService
from sciplot_core.plot_protocol.paths import read_owner
from sciplot_core.project_lifecycle import project_file
from sciplot_core.project_lifecycle.project_file import ProjectFileSaveUnconfirmed, create_project_file, open_project_file
from sciplot_core.project_store.repository import FileProjectStore


@pytest.mark.comprehensive
def test_project_file_editor_and_daily_mcp_share_one_archive(tmp_path, monkeypatch):
    import anyio
    from mcp import Client
    from PyQt6 import QtCore, QtTest, QtWidgets
    from socket_fixture_helpers import socket_directory
    from test_figure_document import request_for_figure
    from test_mcp_stdio import _parameters

    from sciplot_core.plot_editor import PlotEditor

    root = tmp_path.resolve()
    original = root / "origin"
    project = original / "project"
    project.mkdir(parents=True)
    store = FileProjectStore(project)
    store.snapshot(import_legacy=True)
    request = request_for_figure(original)
    source = (original / "figure.csv").read_bytes()
    with closing(PlotService()) as service:
        created = service.create(request, project=project)
        assert created["ready_to_use"], created
    archive = original / "原图.sciplot"
    created_file = create_project_file(archive, store, expected_generation=store.snapshot()["generation"])
    destination = root / "独立项目"
    destination.mkdir()
    moved = archive.rename(destination / "频率数据.sciplot")
    shutil.rmtree(original)

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    native_views = []
    actual_view = PlotEditor._view

    def record_view(window, path, seal, **kwargs):
        native_views.append(path)
        actual_view(window, path, seal, **kwargs)

    monkeypatch.setattr(PlotEditor, "_view", record_view)
    first = PlotEditor(moved, socket_path=None, timeout=90)
    stale = PlotEditor(moved, socket_path=None, timeout=90)
    first.show()
    stale.show()

    def click(widget):
        QtTest.QTest.mouseClick(widget, QtCore.Qt.MouseButton.LeftButton)

    def draw(window):
        QtTest.QTest.qWait(180)
        assert window.viewer.__class__.__module__ == "veusz.windows.plotwindow"
        assert window.viewer.painthelper is not None
        pixmap = window.viewer.pixmapitem.pixmap()
        assert not pixmap.isNull() and pixmap.width() > 1
        pixels = QtCore.QBuffer()
        assert pixels.open(QtCore.QIODeviceBase.OpenModeFlag.WriteOnly)
        assert pixmap.save(pixels, "PNG")
        return bytes(pixels.data())

    def edit(window, value, *, save=True, expect_prompt=True):
        axis = window.axes.findData("axis:xb")
        assert axis > 0
        window.axes.setCurrentIndex(axis)
        window.label.setText(value)
        original_hash = file_sha256(moved)
        prompts = []

        def decide():
            dialog = app.activeModalWidget()
            if dialog is None:
                return
            texts = [label.text() for label in dialog.findChildren(QtWidgets.QLabel)]
            prompts.append((texts, file_sha256(moved)))
            buttons = dialog.findChild(QtWidgets.QDialogButtonBox)
            button = buttons.StandardButton.Save if save else buttons.StandardButton.Cancel
            click(buttons.button(button))

        if expect_prompt:
            QtCore.QTimer.singleShot(0, decide)
        click(window.review)
        if expect_prompt:
            [(texts, still_original)] = prompts
            assert any(value in text and "Hz" in text for text in texts)
            assert still_original == original_hash

    with socket_directory(prefix="sp-file-editor-", dir="/tmp") as directory:
        socket = Path(directory) / "engine.sock"
        parameters = _parameters(cli=True, profile="daily")
        parameters.env = {**(parameters.env or {}), "SCIPLOT_ENGINE_SOCKET": str(socket)}

        async def mcp_edit(observed_revision, next_label):
            async with Client(parameters, read_timeout_seconds=90) as client:
                found = await client.call_tool("sciplot_project_open", {"target": str(moved)})
                assert not found.is_error, found.content
                current = found.structured_content
                assert (current["project_file"], current["project_id"], current["plot_id"],
                        current["revision"], current["scientific_hash"]) == (
                            str(moved), created_file.project_id, created["plot_id"],
                            observed_revision, created["scientific_hash"])
                target, axis = next((target, axis) for target, axis in current["edit_targets"].items()
                                    if axis["label"] == "GUI next")
                saved = await client.call_tool("sciplot_plot_intent", {"plot": current["project_file"], "request": {
                    "mode": "apply", "plot_id": current["plot_id"], "base_revision": current["revision"],
                    "idempotency_key": f"mcp-axis-{observed_revision}", "property": axis["properties"][0],
                    "target_id": target, "value": next_label}})
                if saved.is_error:
                    pytest.fail(str(saved.structured_content))
                assert saved.structured_content["saved"] and saved.structured_content["revision"] == observed_revision + 1

        try:
            initial, stale_native = native_views
            before = draw(first)
            assert initial.is_file() and stale_native.is_file() and file_sha256(moved) == created_file.sha256
            edit(first, "GUI first", save=False)
            assert file_sha256(moved) == created_file.sha256
            edit(first, "GUI next")
            assert first.summary["revision"] == 1 and first.summary["edit_targets"]["axis:xb"]["label"] == "GUI next"
            assert draw(first) != before and not initial.exists() and stale_native.exists()
            anyio.run(mcp_edit, 1, "MCP second")
            after_mcp = file_sha256(moved)
            edit(stale, "Stale must not save", expect_prompt=False)
            assert "未保存" in stale.status.text() and not stale.review.isEnabled()
            assert file_sha256(moved) == after_mcp
            click(stale.refresh)
            assert stale.summary["revision"] == 2 and stale.summary["edit_targets"]["axis:xb"]["label"] == "MCP second"
            assert draw(stale) != before and not stale_native.exists()

            original_publish = project_file._publish

            def lose_ack(path, stage, candidate, baseline):
                original_publish(path, stage, candidate, baseline)
                raise ProjectFileSaveUnconfirmed(candidate.receipt)

            with monkeypatch.context() as fault:
                fault.setattr(project_file, "_publish", lose_ack)
                edit(stale, "Unconfirmed third")
            expected, command = stale.archive_request
            pending = expected, dict(command)
            assert pending[1]["value"] == "Unconfirmed third" and not stale.review.isEnabled()
            assert "未确认" in stale.status.text()
            # Advance the archive through a separate owner while this window
            # still holds the original unresolved request.
            with closing(PlotService()) as service:
                next_saved = service.intent(moved, {**command, "base_revision": 3,
                    "idempotency_key": "unrelated-edit", "value": "Frequency / Hz"})
            assert next_saved["saved"] and next_saved["revision"] == 4
            latest = file_sha256(moved)
            click(stale.refresh)
            assert stale.summary["revision"] == 4 and stale.archive_request == pending
            assert not stale.review.isEnabled()
            click(stale.retry)
            assert stale.archive_request is None and not stale.retry.isVisible() and file_sha256(moved) == latest
            assert stale.summary["edit_targets"]["axis:xb"]["label"] == "Frequency / Hz"
        finally:
            first.close()
            stale.close()
            QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
            if socket.exists():
                os.kill(read_owner(socket)["pid"], signal.SIGTERM)

    assert all(not native.exists() for native in native_views)
    with open_project_file(moved) as session:
        [(source_id, versions)] = session.store.snapshot()["sources"].items()
        assert session.store.resolve_source(source_id, next(iter(versions))).read_bytes() == source
    assert not original.exists() and list(destination.iterdir()) == [moved]


@pytest.mark.comprehensive
def test_managed_editor_and_cli_share_axis_ticks_on_same_native_figure(tmp_path):
    import json
    import subprocess

    from PyQt6 import QtCore, QtTest, QtWidgets
    from socket_fixture_helpers import socket_directory
    from test_current_view import current
    from test_figure_document import request_for_figure

    from sciplot_core.plot_editor import PlotEditor

    project = tmp_path.resolve() / "project"
    project.mkdir()
    FileProjectStore(project).snapshot(import_legacy=True)
    request = request_for_figure(project)
    request["template_definition"]["figure_spec"] = current()[0]
    source_bytes = (project / "figure.csv").read_bytes()
    create_request = project.parent / "create.json"
    create_request.write_text(json.dumps(request))
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    cli = Path(__file__).resolve().parents[1] / "skill/scripts/sciplot"
    target = "axis:xb"

    with socket_directory(prefix="sp-edit-ticks-") as directory:
        socket = Path(directory) / "engine.sock"

        def command(action, *parameters):
            result = subprocess.run([cli, "plot", action, "--socket", socket, "--json", *parameters],
                                    capture_output=True, text=True, timeout=75)
            assert result.returncode == 0, result.stdout + result.stderr
            return json.loads(result.stdout)

        def describe():
            return command("describe", plot, "--scope", "edit", "--target-id", target, "--property", "axis.ticks")

        def click(widget):
            QtTest.QTest.mouseClick(widget, QtCore.Qt.MouseButton.LeftButton)

        def choose_ticks(window):
            window.axes.setCurrentIndex(window.axes.findData(target))
            window.edit_property.setCurrentIndex(window.edit_property.findData("axis.ticks"))
            assert window.review.isEnabled()

        def press_save(window, *, save=True):
            prompts = []

            def decide():
                dialog = app.activeModalWidget()
                if dialog is None:
                    return
                labels = dialog.findChildren(QtWidgets.QLabel)
                if not prompts:
                    assert dialog.windowTitle() == "核对主刻度"
                    assert any("Hz" in label.text() for label in labels)
                prompts.append(dialog.windowTitle())
                buttons = dialog.findChild(QtWidgets.QDialogButtonBox)
                click(buttons.button(buttons.StandardButton.Save if save else buttons.StandardButton.Cancel))

            QtCore.QTimer.singleShot(0, decide)
            click(window.review)
            return prompts

        window = None
        try:
            created = command("create", "--request", create_request, "--project", project)
            assert created["ready_to_use"], created
            plot = Path(created["plot"])
            assert describe()["export_current"]["publication"]["ready_to_use"]
            window = PlotEditor(plot, socket_path=socket, timeout=75)
            window.show()
            choose_ticks(window)
            assert window.label.text() == "" and "自动" in window.label.placeholderText()
            window.label.setText("nan")
            click(window.review)
            assert "有限数字" in window.status.text() and describe()["revision"] == 0
            window.label.setText("2，6，9")
            assert press_save(window, save=False) == ["核对主刻度"]
            assert describe()["current_value"] == {"mode": "automatic"}
            assert press_save(window)[0] == "核对主刻度"
            manual = describe()
            assert manual["revision"] == 1 and manual["current_value"] == [2, 6, 9]
            assert manual["scientific_hash"] == created["scientific_hash"]
            assert "Set('MajorTicks/manualTicks', [2.0, 6.0, 9.0])" in Path(manual["artifact"]).read_text()
            choose_ticks(window)

            # The AI command changes the exact same target via the public CLI.
            patch = project.parent / "agent-change.json"
            patch.write_text(json.dumps({"plot_id": manual["plot_id"], "base_revision": 1,
                "idempotency_key": "foreign-tick-step", "intent_class": "presentation",
                "changes": [{"op": "set", "target": [target], "property": "axis.ticks", "value": [1, 3, 7]}]}))
            agent = command("patch", plot, "--request", patch)
            assert agent["ready_to_use"] and agent["revision"] == 2
            window.label.setText("4, 8")
            click(window.review)
            assert "无法确认保存" in window.status.text() and not window.review.isEnabled()
            assert describe()["current_value"] == [1, 3, 7]
            click(window.refresh)
            choose_ticks(window)
            assert [float(number) for number in window.label.text().split(",")] == [1, 3, 7]
            assert window.viewer.__class__.__module__ == "veusz.windows.plotwindow"
            window.label.clear()
            assert press_save(window)[0] == "核对主刻度"
            final = describe()
            assert final["revision"] == 3 and final["current_value"] == {"mode": "automatic"}
            assert final["plot_id"] == created["plot_id"] and final["scientific_hash"] == created["scientific_hash"]
            assert final["target_context"]["domain"] == manual["target_context"]["domain"]
            assert (project / "figure.csv").read_bytes() == source_bytes
        finally:
            if window is not None:
                window.close()
                QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
            if socket.exists():
                os.kill(read_owner(socket)["pid"], signal.SIGTERM)


@pytest.mark.comprehensive
def test_standalone_editor_and_cli_save_major_ticks_in_the_same_relocated_archive(tmp_path, monkeypatch):
    import json
    import subprocess

    from PyQt6 import QtCore, QtTest, QtWidgets
    from test_current_view import current
    from test_figure_document import request_for_figure

    from sciplot_core.plot_editor import PlotEditor

    root = tmp_path.resolve()
    origin = root / "origin"
    project = origin / "project"
    project.mkdir(parents=True)
    store = FileProjectStore(project)
    store.snapshot(import_legacy=True)
    request = request_for_figure(origin)
    request["template_definition"]["figure_spec"] = current()[0]
    source = (origin / "figure.csv").read_bytes()
    with closing(PlotService()) as service:
        created = service.create(request, project=project)
        assert created["ready_to_use"], created
    archive = origin / "Original.sciplot"
    initial = create_project_file(archive, store, expected_generation=store.snapshot()["generation"])
    destination = root / "Moved"
    destination.mkdir()
    moved = archive.rename(destination / "Frequency.sciplot")
    shutil.rmtree(origin)

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    cli = Path(__file__).resolve().parents[1] / "skill/scripts/sciplot"
    target = "axis:xb"
    views = []
    original_view = PlotEditor._view

    def record_view(window, path, seal, **kwargs):
        views.append(path)
        original_view(window, path, seal, **kwargs)

    monkeypatch.setattr(PlotEditor, "_view", record_view)
    literal = {"idempotency_key": "cli-ticks", "plot_id": created["plot_id"], "base_revision": 1,
               "property": "axis.ticks", "target_id": target, "value": [1, 3, 7]}

    def cli_edit(mode):
        req = root / "edit.json"
        req.write_text(json.dumps({**literal, "mode": mode}))
        result = subprocess.run([cli, "plot", "intent", moved, "--request", req, "--json", "--direct"],
                                capture_output=True, text=True, timeout=75)
        assert result.returncode == 0, result.stdout + result.stderr
        return json.loads(result.stdout)

    def click(widget):
        QtTest.QTest.mouseClick(widget, QtCore.Qt.MouseButton.LeftButton)

    def choose_ticks():
        window.axes.setCurrentIndex(window.axes.findData(target))
        window.edit_property.setCurrentIndex(window.edit_property.findData("axis.ticks"))
        assert window.review.isEnabled()

    def edit(ticks, *, save=True):
        prompts = []
        unchanged = file_sha256(moved)
        window.label.setText(ticks)

        def confirm():
            dialog = app.activeModalWidget()
            assert dialog.windowTitle() == "核对主刻度"
            assert any("Hz" in label.text() for label in dialog.findChildren(QtWidgets.QLabel))
            prompts.append(file_sha256(moved))
            buttons = dialog.findChild(QtWidgets.QDialogButtonBox)
            click(buttons.button(buttons.StandardButton.Save if save else buttons.StandardButton.Cancel))

        QtCore.QTimer.singleShot(0, confirm)
        click(window.review)
        assert prompts == [unchanged]

    window = PlotEditor(moved, socket_path=None, timeout=75)
    window.show()
    try:
        choose_ticks()
        assert window.label.text() == "" and "自动" in window.label.placeholderText()
        edit("2，6，9", save=False)
        assert file_sha256(moved) == initial.sha256 and window.summary["revision"] == 0
        edit("2，6，9")
        assert window.summary["revision"] == 1 and window.summary["axis_ticks"][target] == [2, 6, 9]
        assert "Set('MajorTicks/manualTicks', [2.0, 6.0, 9.0])" in views[-1].read_text()
        assert window.viewer.__class__.__module__ == "veusz.windows.plotwindow"

        after_manual = file_sha256(moved)
        planned = cli_edit("plan")
        assert not planned["saved"] and planned["before"] == [2, 6, 9] and planned["target_context"]["unit"] == "Hz"
        assert file_sha256(moved) == after_manual
        assert cli_edit("apply")["revision"] == 2

        choose_ticks()
        window.label.setText("4, 8")
        click(window.review)
        assert "未保存" in window.status.text() and not window.review.isEnabled()
        click(window.refresh)
        choose_ticks()
        assert [float(number) for number in window.label.text().split(",")] == [1, 3, 7]
        edit("")
        assert window.summary["revision"] == 3 and window.summary["axis_ticks"][target] == {"mode": "automatic"}
        assert window.summary["scientific_hash"] == created["scientific_hash"]
        newest = file_sha256(moved)
        confirmed = cli_edit("apply")
        assert (confirmed["status"], confirmed["revision"], confirmed["current_revision"]) == ("already_saved", 2, 3)
        assert file_sha256(moved) == newest and list(destination.iterdir()) == [moved]
    finally:
        window.close()
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)

    with open_project_file(moved) as session:
        [(source_id, versions)] = session.store.snapshot()["sources"].items()
        assert session.store.resolve_source(source_id, next(iter(versions))).read_bytes() == source
    assert all(not path.exists() for path in views)


@pytest.mark.comprehensive
def test_multi_figure_editor_opens_only_the_explicitly_selected_saved_plot(tmp_path, monkeypatch):
    import pymupdf
    from PyQt6 import QtCore, QtTest, QtWidgets
    from test_figure_document import request_for_figure

    from sciplot_core.plot_editor import PlotEditor
    from sciplot_core.project_lifecycle.project_file_summary import project_file_summary

    root = tmp_path.resolve()
    original = root / "original"
    project = original / "project"
    project.mkdir(parents=True)
    store = FileProjectStore(project)
    store.snapshot(import_legacy=True)
    plots = {}
    with closing(PlotService()) as service:
        for figure in ("A", "B"):
            folder = original / figure
            folder.mkdir()
            request = request_for_figure(folder)
            request["idempotency_key"] = figure
            request["template_definition"]["figure_spec"]["views"][0]["axes"][0]["label"] = f"Frequency {figure} (Hz)"
            saved = service.create(request, project=project)
            assert saved["ready_to_use"], saved
            plots[figure] = saved["plot_id"]
    archive = original / "Original.sciplot"
    initial = create_project_file(archive, store, expected_generation=store.snapshot()["generation"])
    delivery = root / "Delivery"
    delivery.mkdir()
    moved = archive.rename(delivery / "Moved.sciplot")
    shutil.rmtree(original)
    before_a = project_file_summary(moved, plots["A"])

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def click(widget):
        QtTest.QTest.mouseClick(widget, QtCore.Qt.MouseButton.LeftButton)

    windows = []
    try:
        # Finder dispatches this exact constructor without a figure argument.
        window = PlotEditor(moved, socket_path=None, timeout=75)
        windows.append(window)
        window.show()
        assert window.figures.isVisible() and window.figures.currentData() is None
        assert not window.axes.isEnabled() and not window.review.isEnabled()
        assert not window.summary and window.viewer is None
        assert not window.export_pdf.isEnabled()
        assert {window.figures.itemData(i) for i in range(window.figures.count())} == set(plots.values())
        assert file_sha256(moved) == initial.sha256

        window.figures.setCurrentIndex(window.figures.findData(plots["B"]))
        assert window.summary["plot_id"] == plots["B"] and window.summary["revision"] == 0
        assert window.viewer.__class__.__module__ == "veusz.windows.plotwindow"
        window.axes.setCurrentIndex(window.axes.findData("axis:xb"))
        assert window.label.text() == "Frequency B (Hz)"
        window.label.setText("Edited B (Hz)")
        prompts = []

        def confirm():
            dialog = app.activeModalWidget()
            prompts.append(file_sha256(moved))
            buttons = dialog.findChild(QtWidgets.QDialogButtonBox)
            click(buttons.button(buttons.StandardButton.Save))

        QtCore.QTimer.singleShot(0, confirm)
        click(window.review)
        assert prompts == [initial.sha256]
        assert window.summary["plot_id"] == plots["B"] and window.summary["revision"] == 1
        assert window.summary["edit_targets"]["axis:xb"]["label"] == "Edited B (Hz)"
        assert window.axes.currentData() == "axis:xb" and window.label.text() == "Edited B (Hz)"
        after_b = file_sha256(moved)
        assert after_b != initial.sha256
        assert project_file_summary(moved, plots["A"]) == before_a

        target = delivery / "Selected B.pdf"
        names = iter(("", str(target.with_suffix("")), str(target), str(delivery / "stale.pdf")))
        monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName", lambda *_a, **_kw: (next(names), "PDF (*.pdf)"))
        assert window.export_pdf.isEnabled()
        window.export_pdf.trigger()
        assert list(delivery.iterdir()) == [moved]
        window.export_pdf.trigger()
        assert "已导出修订 1" in window.status.text()
        with pymupdf.open(target) as pdf:
            assert "Edited B (Hz)" in pdf[0].get_text()
            assert "Frequency A (Hz)" not in pdf[0].get_text()
        selected_bytes = target.read_bytes()
        window.export_pdf.trigger()
        assert "目标文件已存在" in window.status.text() and target.read_bytes() == selected_bytes
        assert file_sha256(moved) == after_b

        window.figures.setCurrentIndex(window.figures.findData(plots["A"]))
        assert window.summary["plot_id"] == plots["A"] and window.summary["revision"] == 0
        assert window.axes.currentData() is None and not window.review.isEnabled()
        window.axes.setCurrentIndex(window.axes.findData("axis:xb"))
        assert window.label.text() == "Frequency A (Hz)"

        # The editor entry used by --figure bypasses the chooser entirely.
        direct = PlotEditor(moved, socket_path=None, timeout=75, figure_id=plots["B"])
        windows.append(direct)
        direct.show()
        assert direct.figures.isHidden() and direct.summary["plot_id"] == plots["B"]
        assert direct.summary["revision"] == 1 and direct.viewer is not None
        direct.axes.setCurrentIndex(direct.axes.findData("axis:xb"))
        assert direct.label.text() == "Edited B (Hz)"
        assert file_sha256(moved) == after_b and set(delivery.iterdir()) == {moved, target}

        with closing(PlotService()) as service:
            changed = service.intent(moved, {"mode": "apply", "property": "axis.label", "target_id": "axis:xb",
                "plot_id": plots["B"], "base_revision": 1, "idempotency_key": "new-b", "value": "Newest B (Hz)"})
            assert changed["revision"] == 2
        latest = file_sha256(moved)
        direct.export_pdf.trigger()
        assert "项目或图已更新" in direct.status.text() and not direct.export_pdf.isEnabled()
        assert file_sha256(moved) == latest and set(delivery.iterdir()) == {moved, target}
        click(direct.refresh)
        assert direct.summary["plot_id"] == plots["B"] and direct.summary["revision"] == 2
        assert direct.axes.currentData() == "axis:xb" and direct.label.text() == "Newest B (Hz)"
        assert direct.review.isEnabled() and direct.export_pdf.isEnabled()
        assert project_file_summary(moved, plots["A"]) == before_a and file_sha256(moved) == latest
    finally:
        for window in windows:
            window.close()
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
