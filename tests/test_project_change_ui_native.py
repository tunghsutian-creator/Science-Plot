from __future__ import annotations

import csv
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from sciplot_core.veusz_runtime import veusz_worker_environment
from sciplot_core._paths import REPO_ROOT, resolve_fixture_path
from sciplot_core.materials_rules import get_rule


@pytest.mark.comprehensive
def test_native_project_change_worker_review_guards_and_reopen(tmp_path: Path):
    code = r"""
import json
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from dataclasses import replace
from sciplot_core.studio_core.runtime import ensure_veusz_runtime_path
ensure_veusz_runtime_path()
from PyQt6 import QtCore, QtWidgets
from sciplot_core.studio_core.qt_window import _create_veusz_window
from sciplot_gui.studio_project.bridge import attach_studio_project
from sciplot_gui.studio_project.services import configure_studio_project_services
from sciplot_gui.studio_project_services import StudioProjectServices
from sciplot_gui.studio_project.change_dialogs import SourceUpdateDialog, confirm_project_change
from veusz import document
from veusz.document import CommandInterface

app = QtWidgets.QApplication([])
root = Path(sys.argv[1])
project = root / 'project'
(project / 'studio').mkdir(parents=True)
target = project / 'studio/document.vsz'
(project / 'plot_request.json').write_text('{}')
window = _create_veusz_window(None)
interface = CommandInterface(window.document)
interface.SetData('values', [1, 2, 3])
interface.Save(str(target))
window.filename = str(target)
window.show()
old_bytes = target.read_bytes()
candidate = root / 'new.vsz'
replacement = document.Document()
replacement.load(str(target))
commands = CommandInterface(replacement)
commands.SetData('values', [8, 9, 10])
commands.Save(str(candidate))
calls = []
main_thread = threading.get_ident()

def preview(project_path, source=None, *, worksheet=None):
    calls.append(('preview', threading.get_ident(), source, worksheet))
    time.sleep(0.12)
    return {'status': 'ready', 'project': str(project_path), 'candidate': str(candidate), 'document': str(target)}

def apply(project_path, review):
    calls.append(('apply', threading.get_ident()))
    assert review['status'] == 'ready'
    time.sleep(0.12)
    target.write_bytes(candidate.read_bytes())
    return {'status': 'updated', 'document': str(target)}

services = StudioProjectServices(
    atomic_save_document=lambda *_a: {}, export_document=lambda *_a, **_k: {},
    publish_standalone_export=lambda **_k: {}, publish_project_export=lambda **_k: {},
    build_figure_set_scope=lambda *_a, **_k: None,
    is_complete_figure_set_scope=lambda _v: False,
)
configure_studio_project_services(services)
bridge = attach_studio_project(window, target, project_dir=project, request_path=project / 'plot_request.json')
window.resize(1200, 820)
for _ in range(12):
    app.processEvents()
plot_geometry = window.plot.geometry().getRect()
window_size = window.size()
assert isinstance(bridge.dock.widget(), QtWidgets.QScrollArea)
for _ in range(2):
    bridge.dock.toggleViewAction().trigger()
    for _ in range(12):
        app.processEvents()
    assert bridge.dock.isVisible()
    assert window.size() == window_size
    bridge.dock.toggleViewAction().trigger()
    for _ in range(12):
        app.processEvents()
    assert not bridge.dock.isVisible()
    assert window.size() == window_size
    assert window.plot.geometry().getRect() == plot_geometry
bridge.dock.show()
assert not bridge.update_source_button.isEnabled()
services = replace(services, preview_delivery_recovery=preview, apply_delivery_recovery=apply, preview_source_update=preview, apply_source_update=apply)
configure_studio_project_services(services)
bridge._update_controls(bridge.status_snapshot)
assert bridge.update_source_button.isEnabled()

selection = SourceUpdateDialog(window)
selection.source.setText(str(root))
selection.worksheet.setText(' Sheet 2 ')
assert selection.selection() == (root, 'Sheet 2')
assert selection.preview_button.isEnabled()
selection.deleteLater()

window.document.setModified(True)
assert not bridge.start_project_change_preview('delivery_recovery', show_dialog=False)
window.document.setModified(False)
window._sciplot_assistant_bridge = SimpleNamespace(runner=SimpleNamespace(active=True))
assert not bridge.start_project_change_preview('delivery_recovery', show_dialog=False)
del window._sciplot_assistant_bridge
bridge._exporting = True
assert not bridge.start_project_change_preview('delivery_recovery', show_dialog=False)
bridge._exporting = False
assert not calls

ticks = []
timer = QtCore.QTimer()
timer.timeout.connect(lambda: ticks.append(1))
timer.start(5)
def settle():
    deadline = time.monotonic() + 15
    while bridge._project_change_job is not None:
        assert time.monotonic() < deadline, 'Project worker did not finish'
        app.processEvents()
        time.sleep(0.005)
    app.processEvents()

assert bridge.start_project_change_preview('source_update', source=root, worksheet='Sheet 2', show_dialog=False)
assert bridge._project_change_busy
assert not bridge.update_source_button.isEnabled()
assert not bridge.export_button.isEnabled()
assert bridge.export_current_document(show_dialog=False)['ready_to_use'] is False
close_event = QtCore.QEvent(QtCore.QEvent.Type.Close)
assert bridge._project_change_close_guard.eventFilter(window, close_event)
settle()
assert len(ticks) >= 5, 'GUI event loop did not advance during worker'
assert target.read_bytes() == old_bytes, 'Preview must not apply changes'
assert [c[0] for c in calls] == ['preview']
assert calls[0][2:] == (root, 'Sheet 2')
assert calls[0][1] != main_thread
window.document.setModified(True)
window.document.setModified(False)
assert not bridge.apply_project_change_preview(show_dialog=False), 'Changed document must invalidate the preview'
assert len(calls) == 1

assert bridge.start_project_change_preview('delivery_recovery', show_dialog=False)
settle()
loaded_threads = []
original_load = window.loadDocument
def tracked_load(path):
    loaded_threads.append(threading.get_ident())
    return original_load(path)
window.loadDocument = tracked_load
finished = []
bridge.projectChangeFinished.connect(finished.append)
assert bridge.apply_project_change_preview(show_dialog=False)
settle()
assert loaded_threads == [main_thread]
assert list(window.document.data['values'].data) == [8, 9, 10]
assert not window.document.isModified()
assert not window.document.historyundo
assert Path(window.filename) == target
assert target.read_bytes() == candidate.read_bytes()
assert finished[-1]['status'] == 'updated'
assert all(c[1] != main_thread for c in calls)

# The modal review must not treat Enter/default focus as implicit Apply.
def reject_review():
    dialog = app.activeModalWidget()
    assert dialog is not None
    apply_buttons = [b for b in dialog.findChildren(QtWidgets.QPushButton) if b.text() == 'Apply reviewed changes']
    assert len(apply_buttons) == 1 and not apply_buttons[0].isDefault()
    dialog.reject()
QtCore.QTimer.singleShot(20, reject_review)
assert confirm_project_change(window, 'delivery_recovery', {'status': 'ready'}) is False

def broken_preview(*_args, **_kwargs):
    raise ValueError('The source changed during preview')
configure_studio_project_services(replace(services, preview_delivery_recovery=broken_preview))
assert bridge.start_project_change_preview('delivery_recovery', show_dialog=False)
settle()
assert not bridge._project_change_busy
assert finished[-1]['status'] == 'failed'
assert 'source changed' in finished[-1]['message']
assert bridge._project_change_preview is None
assert bridge.recover_delivery_button.isEnabled()
assert target.read_bytes() == candidate.read_bytes()
configure_studio_project_services(services)

# After a committed change, a loader failure must make the old document unsavable.
assert bridge.start_project_change_preview('delivery_recovery', show_dialog=False)
settle()
window.loadDocument = lambda _path: False
assert bridge.apply_project_change_preview(show_dialog=False)
settle()
assert finished[-1]['status'] == 'reopen_failed'
assert window.filename == ''
assert not window.document.data
assert not window.document.historyundo
assert target.read_bytes() == candidate.read_bytes()
timer.stop()
window.document.setModified(False)
window.close()
app.processEvents()
print(json.dumps({'status': 'passed', 'worker_calls': len(calls), 'event_ticks': len(ticks)}))
"""
    result = subprocess.run(
        [sys.executable, "-c", code, str(tmp_path)],
        text=True,
        capture_output=True,
        env=veusz_worker_environment(),
        timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert '"status": "passed"' in result.stdout


@pytest.mark.comprehensive
def test_real_dsc_source_update_from_native_qt_project_dock(tmp_path: Path):
    source = tmp_path / "original.csv"
    shutil.copy2(resolve_fixture_path(str(get_rule("dsc_curve").fixture_path)), source)
    created = subprocess.run(
        [
            str(REPO_ROOT / "skill/scripts/sciplot"),
            "studio",
            str(source),
            "--out",
            str(tmp_path / "delivery"),
            "--rule",
            "dsc_curve",
            "--export",
            "pdf,tiff_300",
            "--json",
        ],
        text=True,
        capture_output=True,
        timeout=120,
    )
    assert created.returncode == 0, created.stdout + created.stderr
    first = json.loads(created.stdout)
    assert first["studio_run"]["ready_to_use"] is True
    replacement = tmp_path / "updated.csv"
    rows = list(csv.reader(source.read_text().splitlines()))
    rows[4][1] = str(float(rows[4][1]) + 0.005)
    with replacement.open("w", newline="") as handle:
        csv.writer(handle).writerows(rows)
    code = r"""
import json
import os
import sys
import threading
import time
from pathlib import Path
from sciplot_core.studio_core.runtime import ensure_veusz_runtime_path
ensure_veusz_runtime_path()
from PyQt6 import QtCore, QtWidgets
from sciplot_core.studio_core.qt_window import _create_veusz_window
from sciplot_gui.main_window_menu import install_studio_window_presentation
app = QtWidgets.QApplication([])
install_studio_window_presentation()
target, source = Path(sys.argv[1]), Path(sys.argv[2])
window = _create_veusz_window(target)
window.show()
bridge = window._sciplot_project_bridge
original = target.read_bytes()
assert os.environ['SCIPLOT_STUDIO_QT_RUNTIME'] == '1'
assert bridge.export_button.text() == 'Save && Export figure set'
assert 'G′' not in bridge.export_button.toolTip()
assert bridge.status_snapshot['provenance']['project_delivery_current'] is True
assert bridge.status_snapshot['workflow']['state'] == 'ready'
bridge.refresh_full()
assert bridge.status_snapshot['workflow']['audit_state'] == 'current'
assert bridge.status_snapshot['workflow']['state'] == 'ready'
request = json.loads((target.parent.parent / 'plot_request.json').read_text())
delivery = Path(request['delivery_output'])
assert bridge.show_delivery_button.isEnabled()
assert bridge.status_snapshot['results']['delivery']['path'] == str(delivery)
assert bridge.status_snapshot['results']['delivery']['evidence_root'] == str(delivery)
opened = []
bridge._open_local_path = lambda path: opened.append(path) or True
assert bridge.show_current_delivery()
assert opened.pop() == delivery
assert bridge.open_current_pdf()
assert opened.pop() == Path(bridge.status_snapshot['results']['pdf']['path'])
assert bridge.reveal_current_vsz()
assert opened.pop() == target.parent
data_file = next((delivery / 'data').glob('*.csv'))
data_before = data_file.read_bytes()
try:
    data_file.write_bytes(data_before + b'\n')
    bridge.refresh_full()
    assert bridge.status_snapshot['workflow']['state'] == 'needs_fix'
    assert bridge.status_snapshot['provenance']['project_delivery_current'] is False
    assert bridge.status_snapshot['qa']['artifact_qa_current'] is True
    assert not bridge.show_delivery_button.isEnabled()
    assert bridge.status_snapshot['results']['delivery']['available'] is False
finally:
    data_file.write_bytes(data_before)
bridge.refresh_full()
assert bridge.status_snapshot['workflow']['state'] == 'ready'
assert bridge.show_delivery_button.isEnabled()
ticks = []
timer = QtCore.QTimer()
timer.timeout.connect(lambda: ticks.append(1))
timer.start(10)
previews, results = [], []
bridge.projectChangePreviewed.connect(previews.append)
bridge.projectChangeFinished.connect(results.append)
def settle():
    deadline = time.monotonic() + 120
    while bridge._project_change_job is not None:
        assert time.monotonic() < deadline, 'Real source update worker timed out'
        app.processEvents()
        time.sleep(0.005)
    app.processEvents()
assert bridge.start_project_change_preview('source_update', source=source, show_dialog=False)
settle()
assert previews and previews[-1]['status'] == 'ready', previews or results
assert target.read_bytes() == original
assert not results
differences = previews[-1]['changes']['figures'][0]['numerical_differences']
assert any(d['changed_value_count'] for d in differences), differences
assert len(ticks) >= 5
main_thread = threading.get_ident()
reopen_threads = []
load = window.loadDocument
def tracked_load(path):
    reopen_threads.append(threading.get_ident())
    return load(path)
window.loadDocument = tracked_load
assert bridge.apply_project_change_preview(show_dialog=False)
settle()
assert results[-1]['status'] == 'updated', results
assert reopen_threads == [main_thread]
assert Path(window.filename) == target
assert not window.document.isModified()
assert not window.document.historyundo
spec = json.loads(target.with_name('spec.json').read_text())
for series in spec['series']:
    assert list(window.document.data[series['y_name']].data) == series['y_values']
assert target.read_bytes() != original
assert results[-1]['ready_to_use'] is False
timer.stop()
window.close()
app.processEvents()
print(json.dumps({'status': 'passed', 'event_ticks': len(ticks)}))
"""
    environment = veusz_worker_environment()
    environment["SCIPLOT_STUDIO_QT_RUNTIME"] = "1"
    result = subprocess.run(
        [sys.executable, "-c", code, first["document"], str(replacement)],
        text=True,
        capture_output=True,
        env=environment,
        timeout=240,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert '"status": "passed"' in result.stdout
    for forbidden in (
        "Cannot create children for a parent that is in a different thread",
        "Timers cannot be",
        "QApplication was not created in the main() thread",
    ):
        assert forbidden not in result.stderr
