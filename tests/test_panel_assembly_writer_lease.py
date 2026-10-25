"""Owned process fault points exercise panel writer lifetime and publication."""

from pathlib import Path
import select
import signal
import subprocess
import sys

import pytest

from sciplot_core.panel_assembly.model import (
    apply_operations,
    load_document,
    new_document,
    save_document,
)
from sciplot_core.panel_assembly import AssemblyError, storage


_WRITER = r"""
from pathlib import Path
import os
import signal
import sys
from sciplot_core.panel_assembly import storage
from sciplot_core.panel_assembly.model import (
    apply_operations, load_document, new_document, save_document,
)

target, fault = Path(sys.argv[1]), sys.argv[2]
if fault == 'legacy':
    descriptor = os.open(target.with_name(f'.{target.name}.assembly-lock'),
                         os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    print('holding', flush=True)
    signal.pause()
    sys.exit(0)
document = load_document(target) if target.exists() else new_document()
expected = document['revision'] if target.exists() else None
if expected is not None:
    document = apply_operations(document, [
        {'op': 'set_page', 'width_mm': 200, 'height_mm': 140},
    ])

def stop():
    print('holding', flush=True)
    signal.pause()

atomic, link, replace = storage.atomic_write_json, storage.os.link, storage.os.replace
def stage(path, payload):
    result = atomic(path, payload)
    if fault == 'staging':
        stop()
    if fault == 'hard_exit_staging':
        os._exit(37)
    return result
def publish_link(src, dst, *args, **kwargs):
    selected = Path(dst).name == target.name
    fence = Path(dst).name == f'.{target.name}.assembly-lock'
    if selected and fault == 'before_new_publication':
        stop()
    if fence and fault == 'before_fence_publication':
        stop()
    result = link(src, dst, *args, **kwargs)
    if selected and fault == 'after_new_publication':
        stop()
    if fence and fault == 'after_fence_publication':
        stop()
    return result
def publish_replace(src, dst, *args, **kwargs):
    selected = Path(dst).name == target.name
    if selected and fault == 'before_replace':
        stop()
    result = replace(src, dst, *args, **kwargs)
    if selected and fault == 'after_replace':
        stop()
    return result
storage.atomic_write_json = stage
storage.os.link = publish_link
storage.os.replace = publish_replace
save_document(document, target, expected_revision=expected)
"""


def _start_writer(target: Path, fault: str) -> subprocess.Popen[str]:
    process = subprocess.Popen(
        [sys.executable, "-u", "-c", _WRITER, str(target), fault],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=target.parent,
    )
    assert process.stdout is not None
    try:
        readable, _, _ = select.select([process.stdout], [], [], 10)
        assert readable, "Owned child did not reach its fault point."
        line = process.stdout.readline().strip()
        if line != "holding":
            _stdout, stderr = process.communicate(timeout=5)
            pytest.fail(f"Owned child failed before fault point: {stderr}")
        return process
    except BaseException:
        process.kill()
        process.communicate(timeout=5)
        raise


@pytest.mark.parametrize("fault", [
    "before_fence_publication", "after_fence_publication",
    "staging", "before_new_publication", "after_new_publication",
    "before_replace", "after_replace",
])
def test_sigkill_releases_writer_at_staging_and_publication_edges(tmp_path, fault):
    target = tmp_path / "figure.json"
    if fault.endswith("replace"):
        save_document(new_document(), target)
    process = _start_writer(target, fault)
    process.kill()
    process.communicate(timeout=5)
    assert process.returncode == -signal.SIGKILL

    published_revision = {"after_new_publication": 0, "before_replace": 0, "after_replace": 1}.get(fault)
    assert target.exists() == (published_revision is not None)
    if target.exists():
        assert load_document(target)["revision"] == published_revision
    if target.exists():
        current = load_document(target)
        revision = current["revision"]
        updated = apply_operations(current, [
            {"op": "set_page", "width_mm": 210, "height_mm": 140},
        ])
        save_document(updated, target, expected_revision=revision)
        assert load_document(target)["revision"] == revision + 1
    else:
        save_document(new_document(), target)
        assert load_document(target)["revision"] == 0


def test_owned_hard_exit_also_releases_kernel_lease(tmp_path):
    target = tmp_path / "figure.json"
    result = subprocess.run(
        [sys.executable, "-u", "-c", _WRITER, str(target), "hard_exit_staging"],
        cwd=tmp_path, capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 37, result.stderr
    save_document(new_document(), target)
    assert load_document(target)["revision"] == 0


def test_live_process_rejects_same_target_alias_and_other_layout_in_directory(tmp_path):
    target = tmp_path / "figure.json"
    alias = tmp_path.parent / f"{tmp_path.name}-alias"
    alias.symlink_to(tmp_path, target_is_directory=True)
    process = _start_writer(target, "staging")
    try:
        for candidate in [target, alias / target.name, tmp_path / "other.json"]:
            with pytest.raises(AssemblyError) as captured:
                save_document(new_document(), candidate)
            assert captured.value.code == "assembly_file_busy"
        # The permanent fence excludes an actual old O_EXCL caller, too.
        legacy = tmp_path / f".{target.name}.assembly-lock"
        with pytest.raises(FileExistsError):
            descriptor = storage.os.open(legacy, storage.os.O_CREAT | storage.os.O_EXCL | storage.os.O_WRONLY)
            storage.os.close(descriptor)
    finally:
        process.kill()
        process.communicate(timeout=5)
        alias.unlink()


@pytest.mark.parametrize("replacement", ["missing", "regular", "symlink"])
def test_swapped_fence_cannot_steal_live_writer_lease(tmp_path, monkeypatch, replacement):
    target = tmp_path / "figure.json"
    document = new_document()
    save_document(document, target)
    original = target.read_bytes()
    fence = tmp_path / f".{target.name}.assembly-lock"
    retained = tmp_path / "retained-fence"
    atomic = storage.atomic_write_json

    def swap(path, payload):
        result = atomic(path, payload)
        fence.rename(retained)
        if replacement == "regular":
            fence.write_bytes(storage._LEASE_FENCE)
        elif replacement == "symlink":
            fence.symlink_to(retained)
        with pytest.raises(AssemblyError) as captured:
            save_document(new_document(), target)
        assert captured.value.code == "assembly_file_busy"
        return result

    monkeypatch.setattr(storage, "atomic_write_json", swap)
    with pytest.raises(AssemblyError) as captured:
        updated = apply_operations(document, [{"op": "set_page", "width_mm": 200, "height_mm": 140}])
        save_document(updated, target, expected_revision=0)
    assert captured.value.code == "assembly_file_conflict"
    assert target.read_bytes() == original
    assert retained.read_bytes() == storage._LEASE_FENCE
    if replacement == "symlink":
        assert fence.is_symlink()


@pytest.mark.parametrize("payload", [b"", b"unknown writer", b"SciPlot panel writer lease v3\n"])
def test_unknown_legacy_marker_is_never_reclaimed_or_rewritten(tmp_path, payload):
    target = tmp_path / "figure.json"
    fence = tmp_path / f".{target.name}.assembly-lock"
    fence.write_bytes(payload)
    before = fence.stat()
    with pytest.raises(AssemblyError, match="cannot be proven inactive") as captured:
        save_document(new_document(), target)
    assert captured.value.code == "assembly_file_busy"
    assert fence.read_bytes() == payload
    assert fence.stat().st_ino == before.st_ino
    assert not target.exists()


def test_unknown_live_legacy_owner_and_its_hard_exit_marker_require_explicit_recovery(tmp_path):
    target = tmp_path / "figure.json"
    fence = tmp_path / f".{target.name}.assembly-lock"
    process = _start_writer(target, "legacy")
    before = fence.stat()
    try:
        with pytest.raises(AssemblyError, match="cannot be proven inactive") as captured:
            save_document(new_document(), target)
        assert captured.value.code == "assembly_file_busy"
        assert fence.stat().st_ino == before.st_ino
        assert fence.read_bytes() == b""
    finally:
        process.kill()
        process.communicate(timeout=5)
    assert process.returncode == -signal.SIGKILL
    with pytest.raises(AssemblyError, match="cannot be proven inactive"):
        save_document(new_document(), target)
    assert fence.stat().st_ino == before.st_ino
    assert fence.read_bytes() == b""
    alternate = tmp_path / "save-as.json"
    save_document(new_document(), alternate)
    assert load_document(alternate)["revision"] == 0


def test_legacy_writer_winning_fence_publication_race_is_preserved(tmp_path, monkeypatch):
    target = tmp_path / "figure.json"
    fence = tmp_path / f".{target.name}.assembly-lock"
    link = storage.os.link

    def legacy_wins(src, dst, *args, **kwargs):
        if Path(dst).name == fence.name:
            descriptor = storage.os.open(fence, storage.os.O_CREAT | storage.os.O_EXCL | storage.os.O_WRONLY, 0o600)
            storage.os.close(descriptor)
        return link(src, dst, *args, **kwargs)

    monkeypatch.setattr(storage.os, "link", legacy_wins)
    with pytest.raises(AssemblyError, match="legacy") as captured:
        save_document(new_document(), target)
    assert captured.value.code == "assembly_file_busy"
    assert fence.read_bytes() == b""
    assert not target.exists()


def test_parent_path_swap_does_not_publish_into_replacement_directory(tmp_path, monkeypatch):
    directory = tmp_path / "layout"
    directory.mkdir()
    target = directory / "figure.json"
    document = new_document()
    save_document(document, target)
    original = target.read_bytes()
    moved = tmp_path / "moved"
    atomic = storage.atomic_write_json

    def swap(path, payload):
        result = atomic(path, payload)
        directory.rename(moved)
        directory.mkdir()
        (directory / "figure.json").write_text("foreign replacement directory")
        with pytest.raises(AssemblyError) as captured:
            save_document(new_document(), moved / "other.json")
        assert captured.value.code == "assembly_file_busy"
        return result

    monkeypatch.setattr(storage, "atomic_write_json", swap)
    with pytest.raises(AssemblyError) as captured:
        updated = apply_operations(document, [{"op": "set_page", "width_mm": 200, "height_mm": 140}])
        save_document(updated, target, expected_revision=0)
    assert captured.value.code == "assembly_file_conflict"
    assert (moved / "figure.json").read_bytes() == original
    assert target.read_text() == "foreign replacement directory"
    assert not [path for path in moved.glob(".*assembly-*") if path.is_dir()]


def test_alias_load_and_save_share_the_same_revision_baseline(tmp_path):
    directory = tmp_path / "actual"
    directory.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(directory, target_is_directory=True)
    target = directory / "figure.json"
    save_document(new_document(), target)
    document = load_document(alias / target.name)
    updated = apply_operations(document, [{"op": "set_page", "width_mm": 200, "height_mm": 140}])
    assert save_document(updated, target, expected_revision=0) == target
    assert load_document(alias / target.name)["revision"] == 1


def test_cli_mcp_and_compose_observe_the_same_live_writer_and_recover(tmp_path, capsys):
    import anyio
    import json

    from sciplot_core.cli import main
    from sciplot_core.mcp_server.server import Adapter
    from sciplot_core.panel_assembly.service import compose

    target = tmp_path / "figure.json"
    request = {"action": "new", "layout": str(target)}
    process = _start_writer(target, "staging")
    try:
        with pytest.raises(AssemblyError) as captured:
            compose(request)
        assert captured.value.code == "assembly_file_busy"
        assert main(["compose", "new", str(target), "--json"]) == 1
        assert json.loads(capsys.readouterr().out)["reason_code"] == "assembly_file_busy"

        async def busy():
            reply = await Adapter().call("sciplot_compose", {"request": request})
            assert reply.is_error
            assert reply.structured_content["error"]["code"] == "assembly_file_busy"

        anyio.run(busy)
    finally:
        process.kill()
        process.communicate(timeout=5)

    assert main(["compose", "new", str(target), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["revision"] == 0

    async def recover():
        reply = await Adapter().call("sciplot_compose", {"request": {
            "action": "apply", "layout": str(target), "expected_revision": 0,
            "operations": [{"op": "set_page", "width_mm": 200, "height_mm": 140}],
        }})
        assert not reply.is_error
        assert reply.structured_content["revision"] == 1

    anyio.run(recover)
