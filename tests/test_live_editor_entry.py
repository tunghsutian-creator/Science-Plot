"""Delivery entry selection, legacy visible edits and portable-copy boundaries."""
from pathlib import Path
import shutil

import pytest

from sciplot_core.live_editor.entry import resolve_editor_input
from sciplot_core.launchers.delivery_editor_launcher import write_delivery_editor_launcher
from test_delivery_project_continuation import _linked_delivery

pytestmark = pytest.mark.focused


def test_legacy_delivery_and_new_entry_preserve_current_project_target(tmp_path):
    root, _, _, _ = _linked_delivery(tmp_path)
    assert resolve_editor_input(root) == (root, False)
    entry = write_delivery_editor_launcher(root)
    assert resolve_editor_input(entry) == (root, False)


@pytest.mark.parametrize("form", ["directory", "entry", "vsz"])
def test_changed_visible_copy_blocks_editor_before_loading_another_document(tmp_path, form):
    root, _, canonical, _ = _linked_delivery(tmp_path)
    entry = write_delivery_editor_launcher(root)
    visible = root / "project/primary.vsz"
    visible.write_text("previous human edits")
    target = {"directory": root, "entry": entry, "vsz": visible}[form]
    with pytest.raises(ValueError, match="skip these edits"):
        resolve_editor_input(target, portable_fallback=True)
    assert visible.read_text() == "previous human edits"
    assert canonical.read_bytes() == b"canonical Veusz project"


@pytest.mark.parametrize("mode", ["copy", "move", "missing_project"])
def test_portable_delivery_requires_explicit_fallback_and_never_reattaches(tmp_path, mode):
    root, project, _, _ = _linked_delivery(tmp_path)
    write_delivery_editor_launcher(root)
    if mode == "copy":
        target = tmp_path / "复制 交付"
        shutil.copytree(root, target)
    elif mode == "move":
        target = tmp_path / "搬移 交付"
        root.rename(target)
    else:
        target = root
        shutil.rmtree(project)
    with pytest.raises(ValueError, match="脱离原工程"):
        resolve_editor_input(target)
    assert resolve_editor_input(target, portable_fallback=True) == (target / "project/primary.vsz", True)


def test_modified_editor_launcher_is_rejected_even_for_directory_input(tmp_path):
    root, _, _, _ = _linked_delivery(tmp_path)
    launcher = write_delivery_editor_launcher(root)
    launcher.write_text(launcher.read_text() + "echo changed\n")
    with pytest.raises(ValueError, match="启动入口已变化"):
        resolve_editor_input(root)


def test_missing_explicit_portable_document_does_not_silently_choose_primary(tmp_path):
    root, _, _, _ = _linked_delivery(tmp_path)
    copied = tmp_path / "copy"
    shutil.copytree(root, copied)
    with pytest.raises(FileNotFoundError, match="不存在"):
        resolve_editor_input(copied / "project/missing.vsz", portable_fallback=True)


def test_cli_portable_check_does_not_open_gui_or_serve_editor(tmp_path, monkeypatch, capsys):
    from sciplot_core.cli.parsers.builder import build_parser
    from sciplot_core.cli.dispatch.interfaces import dispatch_interfaces
    from sciplot_core.live_editor import server
    import sciplot_core.studio as studio
    root, _, _, _ = _linked_delivery(tmp_path)
    copied = tmp_path / "copy"
    shutil.copytree(root, copied)
    monkeypatch.setattr(server, "serve_editor", lambda *a, **k: pytest.fail("No browser server for portable copy"))
    monkeypatch.setattr(studio, "run_studio_command", lambda **k: pytest.fail("Check must not start GUI"))
    args = build_parser().parse_args(["edit", str(copied), "--portable-fallback", "--check"])
    assert dispatch_interfaces(args, None, serve_intake=None) == 0
    assert '"mode": "portable_veusz"' in capsys.readouterr().out


def test_cli_portable_fallback_only_opens_the_copied_document(tmp_path, monkeypatch):
    from sciplot_core.cli.parsers.builder import build_parser
    from sciplot_core.cli.dispatch.interfaces import dispatch_interfaces
    import sciplot_core.studio as studio
    root, _, _, _ = _linked_delivery(tmp_path)
    copied = tmp_path / "copy"
    shutil.copytree(root, copied)
    calls = []
    monkeypatch.setattr(studio, "run_studio_command", lambda **k: calls.append(k) or 0)
    args = build_parser().parse_args(["edit", str(copied), "--portable-fallback"])
    assert dispatch_interfaces(args, None, serve_intake=None) == 0
    assert calls[0]["target"] == copied / "project/primary.vsz"
    assert Path(calls[0]["original_argv"][1]).is_relative_to(copied)
