from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from sciplot_core.launchers import (
    inspect_delivery_editor_launcher_contract,
    write_delivery_editor_launcher,
)
from sciplot_core.policy import DELIVERY_EDITOR_LAUNCHER


def _stub_cli(root: Path) -> Path:
    command = root / "skill" / "scripts" / "sciplot"
    command.parent.mkdir(parents=True)
    command.write_text('#!/bin/zsh\nprint -rl -- "$@"\n', encoding="utf-8")
    command.chmod(0o755)
    return command


def test_editor_launcher_forwards_exact_arguments_after_moving_chinese_package(
    tmp_path: Path,
):
    original = tmp_path / "原始 交付"
    write_delivery_editor_launcher(original)
    moved = tmp_path / "复制后的 图"
    shutil.copytree(original, moved)
    launcher = moved / DELIVERY_EDITOR_LAUNCHER
    repo = tmp_path / "本地 程序"
    _stub_cli(repo)
    completed = subprocess.run(
        ["zsh", str(launcher), "--figure", "次图 有空格", "--check"],
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, "SCIPLOT_REPO": str(repo), "SCIPLOT_LAUNCH_DRY_RUN": "0"},
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.splitlines() == [
        "edit",
        str(moved),
        "--portable-fallback",
        "--figure",
        "次图 有空格",
        "--check",
    ]
    contract = inspect_delivery_editor_launcher_contract(moved)
    assert contract["ready"] is True
    assert contract["path"] == str(launcher)


def test_editor_launcher_dry_run_does_not_invoke_cli(tmp_path: Path):
    launcher = write_delivery_editor_launcher(tmp_path / "交付 文件")
    repo = tmp_path / "program"
    command = _stub_cli(repo)
    command.write_text("#!/bin/zsh\nexit 99\n", encoding="utf-8")
    completed = subprocess.run(
        ["zsh", str(launcher), "--figure", "secondary"],
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, "SCIPLOT_REPO": str(repo), "SCIPLOT_LAUNCH_DRY_RUN": "1"},
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.splitlines() == [
        str(command),
        "edit",
        str(launcher.parent),
        "--portable-fallback",
        "--figure",
        "secondary",
    ]


@pytest.mark.parametrize("change", ["command", "comment", "executable", "symlink"])
def test_editor_launcher_contract_rejects_altered_entry(tmp_path: Path, change: str):
    launcher = write_delivery_editor_launcher(tmp_path)
    if change == "command":
        launcher.write_text(
            launcher.read_text().replace(
                'edit "${DELIVERY_DIR}"', 'studio "${DELIVERY_DIR}"'
            )
        )
    elif change == "comment":
        launcher.write_text(launcher.read_text() + "# extra unrecorded content\n")
    elif change == "executable":
        launcher.chmod(0o644)
    else:
        target = launcher.with_suffix(".elsewhere")
        launcher.rename(target)
        launcher.symlink_to(target)
    assert inspect_delivery_editor_launcher_contract(tmp_path)["ready"] is False
