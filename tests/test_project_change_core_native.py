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
def test_real_dsc_source_update_from_headless_project_commands(tmp_path: Path):
    source = tmp_path / "original.csv"
    shutil.copy2(resolve_fixture_path(str(get_rule("dsc_curve").fixture_path)), source)
    raw_before = source.read_bytes()
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
import sys
from pathlib import Path
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.studio_core.runtime import ensure_veusz_runtime_path
ensure_veusz_runtime_path()
from PyQt6 import QtWidgets
from sciplot_core.studio_core.qt_compat import ensure_veusz_loader_compat
from sciplot_core.studio_core.project_query import inspect_project
from sciplot_core.studio_core.source_update import preview_project_source_update, apply_project_source_update
from veusz import document

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
ensure_veusz_loader_compat()
target, source = Path(sys.argv[1]), Path(sys.argv[2])
project = target.parent.parent
original = target.read_bytes()
source_hash = file_sha256(source)
request = json.loads((project / 'plot_request.json').read_text())
delivery = Path(request['delivery_output'])
first = inspect_project(project)
assert first['source']['current'] is True
assert first['qa']['current'] is True
assert first['delivery']['current'] is True
assert first['delivery']['path'] == str(delivery)
assert first['live_gui_state_evaluated'] is False

data_file = next((delivery / 'data').glob('*.csv'))
data_before = data_file.read_bytes()
try:
    data_file.write_bytes(data_before + b'\n')
    stale = inspect_project(project)
    assert stale['delivery']['current'] is False
    assert stale['qa']['current'] is True
finally:
    data_file.write_bytes(data_before)
assert inspect_project(project)['delivery']['current'] is True

preview = preview_project_source_update(project, source)
assert preview['status'] == 'ready', preview
assert target.read_bytes() == original, 'Preview must not apply changes'
assert file_sha256(source) == source_hash
assert preview['changes']['figures']
differences = preview['changes']['figures'][0]['numerical_differences']
assert any(d['changed_value_count'] for d in differences), differences
result = apply_project_source_update(project, preview)
assert result['status'] == 'updated', result
assert Path(result['document']) == target
assert result['ready_to_use'] is False
assert target.read_bytes() != original
assert file_sha256(source) == source_hash

# Reopen the committed saved document in a fresh headless Document, not an
# unsaved editor or a stand-in for the original window's state.
reopened = document.Document()
reopened.load(str(target))
assert not reopened.isModified()
assert not reopened.historyundo
spec = json.loads(target.with_name('spec.json').read_text())
for series in spec['series']:
    assert list(reopened.data[series['y_name']].data) == series['y_values']
assert target.read_bytes() == Path(result['document']).read_bytes()
print(json.dumps({'status': 'passed', 'saved_document': str(target), 'source_sha256': source_hash}))
"""
    environment = veusz_worker_environment()
    result = subprocess.run(
        [sys.executable, "-c", code, first["document"], str(replacement)],
        text=True,
        capture_output=True,
        env=environment,
        timeout=240,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert source.read_bytes() == raw_before
    assert '"status": "passed"' in result.stdout
    for forbidden in (
        "Cannot create children for a parent that is in a different thread",
        "Timers cannot be",
        "QApplication was not created in the main() thread",
    ):
        assert forbidden not in result.stderr
