"""A real native edit and the daily MCP operate on one relocated standalone file."""

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
