"""The real figure-set probe uses admitted mutations and explicit source updates."""
import json
from pathlib import Path
import subprocess

import pytest

from sciplot_core.native_process.session import _close_workers
from sciplot_core.studio_figure_set_probe import run_studio_figure_set_probe


@pytest.mark.comprehensive
def test_figure_set_probe_preserves_rollback_and_missing_metric_source_history(tmp_path, monkeypatch):
    children, popen = [], subprocess.Popen
    def observed(*args, **kwargs):
        child = popen(*args, **kwargs)
        children.append(child)
        return child
    monkeypatch.setattr(subprocess, 'Popen', observed)
    try:
        result = run_studio_figure_set_probe(output_root=tmp_path / 'probe')
        assert result['status'] == 'passed', result
        assert result['summary']['check_count'] == result['summary']['passed_count'] == 10
        assert result['summary']['failed_ids'] == []
        rollback = next(item for item in result['checks'] if item['id'] == 'second_replace_failure_rolls_back_secondary_transaction')
        assert rollback['detail']['canonical_bytes_unchanged'] is True
        assert rollback['detail']['history_unchanged'] is True
        assert rollback['detail']['replace_calls'][-1]['actual_target'] != rollback['detail']['replace_calls'][-1]['target']
        assert Path(result['artifacts']['synthetic_project']).is_dir()
    finally:
        _close_workers()
        assert all(child.poll() is not None for child in children)
        (tmp_path / 'figure-set-probe-workers.json').write_text(json.dumps(
            [{'pid': child.pid, 'returncode': child.returncode} for child in children], indent=2))
