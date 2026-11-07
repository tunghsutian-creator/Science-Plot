"""Historical manual-editor argv are inert and use the common CLI error contract."""

import builtins
import json
import os
from pathlib import Path
import subprocess
import webbrowser

import pytest

from sciplot_core import cli
from sciplot_core.cli.dispatch.interfaces import ManualEditorRetired, dispatch_interfaces
from sciplot_core.cli.parsers.builder import build_parser


LEGACY_OPTIONS = (
    (),
    ("--check",),
    ("--portable-fallback",),
    ("--portable-fallback", "--check", "--figure", "次图 有空格"),
    ("--no-open", "--port", "8751", "--session-dir", "unused-session"),
)


@pytest.mark.parametrize("options", LEGACY_OPTIONS)
@pytest.mark.parametrize("json_output", [False, True])
def test_retired_editor_argv_returns_the_existing_cli_error_contract(
    tmp_path, monkeypatch, capsys, options, json_output,
):
    target = tmp_path / "旧工程 有空格" / "Open_in_SciPlot.command"
    original = builtins.__import__

    def no_editor_import(name, *args, **kwargs):
        forbidden = ("sciplot_core.live_editor", "sciplot_core.veusz_worker.live_session",
                     "sciplot_core.studio", "sciplot_gui", "PyQt6", "veusz")
        assert not any(name == prefix or name.startswith(prefix + ".")
                       for prefix in forbidden), f"Retired command imported {name}"
        return original(name, *args, **kwargs)

    def no_effect(*_args, **_kwargs):
        pytest.fail("Retired manual editing must not launch a process or browser")

    monkeypatch.setattr(builtins, "__import__", no_editor_import)
    monkeypatch.setattr(subprocess, "Popen", no_effect)
    monkeypatch.setattr(webbrowser, "open", no_effect)
    options = tuple(str(tmp_path / "unused-session") if item == "unused-session" else item for item in options)
    argv = ["edit", str(target), *options, *(["--json"] if json_output else [])]
    assert cli.main(argv) == 1
    captured = capsys.readouterr()
    if json_output:
        payload = json.loads(captured.out)
        assert payload["kind"] == "sciplot_cli_runtime_error"
        assert payload["version"] == 1 and payload["status"] == "failed"
        assert payload["category"] == "expected_runtime_failure"
        assert payload["reason_code"] == "manual_editor_retired"
        assert payload["exception_type"] == "ManualEditorRetired"
        message = payload["message"]
        assert captured.err == ""
    else:
        assert captured.out == ""
        message = captured.err
    assert "manual_editor_retired" in message
    assert "sciplot task edit TARGET --intent INTENT" in message
    assert "sciplot plot describe PLOT --scope edit --json" in message
    assert not target.parent.exists()
    assert not (tmp_path / "unused-session").exists()


@pytest.mark.parametrize("target_kind", ["project", "document", "launcher", "missing", "symlink"])
@pytest.mark.parametrize("options", LEGACY_OPTIONS)
def test_retirement_never_observes_or_changes_a_target(
    tmp_path, monkeypatch, target_kind, options,
):
    root = tmp_path / "protected"
    root.mkdir()
    document = root / "document.vsz"
    document.write_bytes(b"original saved native document")
    source = root / "measurements.csv"
    source.write_bytes(b"x,y\n1,2\n")
    launcher = root / "Open_in_SciPlot.command"
    launcher.write_bytes(b"historical launcher, never executed")
    link = root / "link"
    link.symlink_to(document)
    target = {"project": root, "document": document, "launcher": launcher,
              "missing": root / "missing", "symlink": link}[target_kind]
    original_bytes = {path: path.read_bytes() for path in (document, source, launcher)}
    args = build_parser().parse_args(["edit", str(target), *options])

    def guarded(function):
        def call(path, *arguments, **keywords):
            if isinstance(path, (str, bytes, os.PathLike)):
                candidate = Path(os.fsdecode(path))
                if candidate == root or root in candidate.parents:
                    pytest.fail("Retired command attempted target IO")
            return function(path, *arguments, **keywords)
        return call

    with monkeypatch.context() as guard:
        for owner, names in ((Path, ("stat", "resolve", "open", "mkdir", "unlink", "rename", "replace")),
                             (os, ("open", "stat", "lstat")), (builtins, ("open",))):
            for name in names:
                guard.setattr(owner, name, guarded(getattr(owner, name)))
        with pytest.raises(ManualEditorRetired, match="manual_editor_retired"):
            dispatch_interfaces(args, None)
    assert {path: path.read_bytes() for path in original_bytes} == original_bytes
    assert link.is_symlink()
    assert sorted(path.name for path in root.iterdir()) == [
        "Open_in_SciPlot.command", "document.vsz", "link", "measurements.csv",
    ]


def test_retired_editor_help_preserves_legacy_parser_without_advertising_an_editor(capsys):
    with pytest.raises(SystemExit) as stopped:
        cli.main(["edit", "--help"])
    assert stopped.value.code == 0
    help_text = capsys.readouterr().out
    assert "Historical target argument; never opened or changed." in help_text
    assert "--portable-fallback" not in help_text and "--session-dir" not in help_text


@pytest.mark.parametrize("argv,reason", [
    (["app", "--json"], "browser_intake_retired"),
    (["studio", "--qt-smoke", "--json"], "native_gui_retired"),
    (["studio", "--new", "--json"], "native_gui_retired"),
])
def test_retired_browser_and_native_window_argv_never_launch_or_read_target(
    tmp_path, monkeypatch, capsys, argv, reason,
):
    target = tmp_path / "never-created"

    def forbidden(*_args, **_kwargs):
        pytest.fail("A retired frontend attempted a process or browser launch")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(webbrowser, "open", forbidden)
    assert cli.main([argv[0], str(target), *argv[1:]]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "failed" and payload["reason_code"] == reason
    assert not target.exists()
