from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from sciplot_core.launchers import (
    inspect_delivery_editor_launcher_contract,
)
from sciplot_core import launchers
from sciplot_core.launchers import delivery_editor_launcher
from sciplot_core.policy import DELIVERY_EDITOR_LAUNCHER


def _legacy_launcher(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / DELIVERY_EDITOR_LAUNCHER
    # Describe a historical fixture without an active production writer.
    path.write_text(
        "\n".join(delivery_editor_launcher._delivery_editor_launcher_lines()) + "\n",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def test_legacy_editor_contract_is_read_only_after_moving_chinese_package(
    tmp_path: Path,
):
    original = tmp_path / "原始 交付"
    historical = _legacy_launcher(original)
    content = historical.read_bytes()
    moved = tmp_path / "复制后的 图"
    shutil.copytree(original, moved)
    launcher = moved / DELIVERY_EDITOR_LAUNCHER
    before = launcher.stat()
    contract = inspect_delivery_editor_launcher_contract(moved)
    assert contract["ready"] is True
    assert contract["path"] == str(launcher)
    assert launcher.read_bytes() == historical.read_bytes() == content
    assert launcher.stat().st_mtime_ns == before.st_mtime_ns
    assert launcher.stat().st_mode == before.st_mode


def test_retired_editor_launcher_has_no_production_writer():
    assert not hasattr(launchers, "write_delivery_editor_launcher")
    assert not hasattr(delivery_editor_launcher, "write_delivery_editor_launcher")


@pytest.mark.parametrize("change", ["command", "comment", "executable", "symlink"])
def test_editor_launcher_contract_rejects_altered_entry(tmp_path: Path, change: str):
    launcher = _legacy_launcher(tmp_path)
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
