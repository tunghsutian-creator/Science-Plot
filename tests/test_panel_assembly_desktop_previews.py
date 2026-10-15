"""Native preview bytes are asynchronous and versioned independently of layout."""

from pathlib import Path
import threading
import time

import test_panel_assembly_desktop as support

qt = support.qt
workbench = support.workbench


def test_preview_worker_keeps_layout_responsive_and_cache_tracks_explicit_versions(workbench, qt, tmp_path, monkeypatch):
    from sciplot_core.panel_assembly import preview
    from sciplot_core.panel_assembly.desktop_previews import preview_key

    window = workbench
    path = support.image(tmp_path)
    calls, updates, ticks = [], [], []
    main_thread = threading.get_ident()

    def rendering(source):
        calls.append((source, threading.get_ident()))
        time.sleep(0.15)
        return Path(source["path"]).read_bytes()

    monkeypatch.setattr(preview, "render_preview", rendering)
    window.previews.updated.connect(lambda _key: updates.append(threading.get_ident()))
    timer = qt[1].QTimer()
    timer.timeout.connect(lambda: ticks.append(1))
    timer.start(5)
    assert window.add_source({"kind": "image", "path": str(path)})
    deadline = time.monotonic() + 5
    while not window.previews.busy or window.busy:
        assert time.monotonic() < deadline
        qt[2].QTest.qWait(5)
    assert window.apply([{"op": "set_spacing", "gap_x_mm": 8, "gap_y_mm": 5}])
    support.settle(window, qt)
    timer.stop()
    first = window.document["panels"][0]["source"]
    assert not window.previews.get(first).isNull()
    assert len(ticks) >= 5 and len(calls) == 1
    assert calls[0][1] != main_thread and updates == [main_thread]
    for gap in (7, 9, 6):
        assert window.apply([{"op": "set_spacing", "gap_x_mm": gap, "gap_y_mm": 5}])
    assert len(calls) == 1 and not window.previews.busy
    support.image(tmp_path, color="#c86143")
    assert window.previews.get(first).toImage().pixelColor(0, 0).name() == "#8ca1b5"
    assert window.refresh_selected()
    support.settle(window, qt)
    current = window.document["panels"][0]["source"]
    assert preview_key(current) != preview_key(first)
    assert len(calls) == 2
    assert window.previews.get(current).toImage().pixelColor(0, 0).name() == "#c86143"
    assert window.previews.get(first).toImage().pixelColor(0, 0).name() == "#8ca1b5"
