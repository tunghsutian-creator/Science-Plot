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


def test_failed_empty_sip_directory_is_not_reused(tmp_path):
    command = builder(tmp_path)
    empty = tmp_path / 'sip-threed/output/threed'
    empty.mkdir(parents=True)
    calls = []

    def compile_binding(source, directory):
        calls.append((source, directory))
        output = Path(directory) / 'output/threed'
        output.mkdir(parents=True)
        (output / 'sipthreedcmodule.cpp').write_text('// module entry')

    command._sip_compile = compile_binding
    files = command._sip_sources('src/threed/threed.sip')
    assert len(files) == 1
    assert Path(files[0]).parent != empty
    assert len(calls) == 1
    assert empty.is_dir()


def test_incomplete_generation_fails_closed_and_retry_uses_new_directory(tmp_path):
    command = builder(tmp_path)
    command._sip_compile = lambda *_: None
    with pytest.raises(RuntimeError, match='module entry'):
        command._sip_sources('threed.sip')
    failed_directories = set(tmp_path.iterdir())

    def failed(source, directory):
        assert Path(directory) not in failed_directories
        raise RuntimeError('generation interrupted')

    command._sip_compile = failed
    command.force = True
    with pytest.raises(RuntimeError, match='interrupted'):
        command._sip_sources('threed.sip')
    assert failed_directories < set(tmp_path.iterdir())


def test_changed_sip_source_is_regenerated(tmp_path):
    command = builder(tmp_path / 'build')
    source = tmp_path / 'threed.sip'
    source.write_text('old interface')

    def compile_binding(source, directory):
        output = Path(directory) / 'output/threed'
        output.mkdir(parents=True)
        (output / 'sipthreedcmodule.cpp').write_text(Path(source).read_text())

    command._sip_compile = compile_binding
    first = command._sip_sources(str(source))
    source.write_text('changed interface')
    second = command._sip_sources(str(source))
    assert first != second
    assert Path(first[0]).read_text() == 'old interface'
    assert Path(second[0]).read_text() == 'changed interface'


def test_force_regeneration_does_not_link_removed_generated_classes(tmp_path):
    command = builder(tmp_path)
    calls = []

    def compile_binding(source, directory):
        output = Path(directory) / 'output/threed'
        output.mkdir(parents=True)
        (output / 'sipthreedcmodule.cpp').write_text('// module entry')
        if not calls:
            (output / 'sipthreedRemovedClass.cpp').write_text('// old class')
        calls.append(directory)

    command._sip_compile = compile_binding
    first = command._sip_sources('threed.sip')
    assert len(first) == 2
    command.force = True
    second = command._sip_sources('threed.sip')
    assert len(second) == 1
    assert Path(second[0]).name == 'sipthreedcmodule.cpp'
    assert calls[0] != calls[1]
    assert all(Path(path).is_file() for path in first)


def test_direct_venv_python_uses_its_sip_build_without_path_activation(tmp_path, monkeypatch):
    command = builder(tmp_path / 'build')
    namespace = command._sip_compile.__func__.__globals__
    scripts = tmp_path / 'venv/bin'
    scripts.mkdir(parents=True)
    executable = scripts / 'sip-build'
    executable.write_text('#!/bin/sh\n')
    executable.chmod(0o700)
    platlib = tmp_path / 'venv/lib'
    qtcore = platlib / 'PyQt6/bindings/QtCore'
    qtcore.mkdir(parents=True)
    (qtcore / 'QtCore.toml').write_text('sip-abi-version="13.11"\n')
    monkeypatch.setitem(namespace, 'get_path', lambda name: str(scripts if name == 'scripts' else platlib))
    monkeypatch.setattr(namespace['shutil'], 'which', lambda _: None)
    calls = []

    def generated(args, cwd):
        calls.append(args)
        output = Path(cwd) / 'output'
        (output / 'threed').mkdir()
        (output / 'sip.h').write_text('// generated SIP header')

    monkeypatch.setattr(namespace['subprocess'], 'check_call', generated)
    directory = tmp_path / 'generation'
    directory.mkdir()
    command._sip_compile('threed.sip', str(directory))
    assert calls == [[str(executable), '--no-compile']]
    assert (directory / 'output/threed/sip.h').is_file()
