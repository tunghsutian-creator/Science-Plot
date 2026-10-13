"""Incomplete SIP generation cannot be reused as a successful native build."""
import importlib.util
from pathlib import Path

import pytest
from setuptools import Distribution


def builder(tmp_path):
    path = Path(__file__).resolve().parents[1] / 'third_party/veusz/pyqt_setuptools.py'
    spec = importlib.util.spec_from_file_location('sciplot_test_sip_builder', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    command = module.sip_build_ext(Distribution())
    command.build_temp = str(tmp_path)
    command.force = False
    return command


def test_failed_empty_sip_directory_is_regenerated_and_success_can_be_reused(tmp_path):
    command = builder(tmp_path)
    output = tmp_path / 'sip-threed/output/threed'
    output.mkdir(parents=True)
    calls = []

    def compile_binding(source, directory):
        calls.append((source, directory))
        (output / 'sipthreedcmodule.cpp').write_text('// module entry')

    command._sip_compile = compile_binding
    assert command._sip_sources('src/threed/threed.sip') == [str(output / 'sipthreedcmodule.cpp')]
    command._sip_sources('src/threed/threed.sip')
    assert len(calls) == 1
    (output / 'sipthreedcmodule.cpp').unlink()
    command._sip_sources('src/threed/threed.sip')
    assert len(calls) == 2


def test_incomplete_generation_fails_closed_and_force_failure_invalidates_marker(tmp_path):
    command = builder(tmp_path)
    command._sip_compile = lambda *_: None
    with pytest.raises(RuntimeError, match='module entry'):
        command._sip_sources('threed.sip')
    marker = tmp_path / 'sip-threed/.sciplot-sip-complete'
    assert not marker.exists()
    output = tmp_path / 'sip-threed/output/threed'
    output.mkdir(parents=True)
    (output / 'sipthreedcmodule.cpp').write_text('// module entry')
    marker.write_text('threed\n')
    command.force = True

    def failed(*_):
        raise RuntimeError('generation interrupted')

    command._sip_compile = failed
    with pytest.raises(RuntimeError, match='interrupted'):
        command._sip_sources('threed.sip')
    assert not marker.exists()
