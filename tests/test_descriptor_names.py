"""Kernel descriptor names are fresh observations, never filesystem authority."""
import errno
import hashlib
import os
from pathlib import Path

import pytest

from sciplot_core.foundation import descriptor_names


def test_descriptor_names_follow_ancestor_moves_aliases_dup_and_descriptor_reuse(tmp_path):
    tmp_path = tmp_path.resolve()
    parent = tmp_path / "parent"
    root = parent / "root"
    root.mkdir(parents=True)
    other = tmp_path / "other"
    other.mkdir()
    moved = tmp_path / "moved"
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    duplicate = os.dup(descriptor)
    replacement = os.open(other, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        assert Path(descriptor_names.descriptor_name(descriptor)) == root
        assert descriptor_names.descriptor_name(duplicate) == str(root)
        parent.rename(moved)
        parent.symlink_to(moved, target_is_directory=True)
        assert Path(descriptor_names.descriptor_name(descriptor)) == moved / "root"
        assert descriptor_names.descriptor_name(duplicate) == str(moved / "root")
        os.dup2(replacement, duplicate)
        assert descriptor_names.descriptor_name(duplicate) == str(other)
    finally:
        os.close(descriptor)
        os.close(duplicate)
        os.close(replacement)
        if parent.is_symlink():
            parent.unlink()


def test_descriptor_name_preserves_invalid_descriptor_os_error(tmp_path):
    source = tmp_path / "generated.bin"
    source.write_bytes(b"generated")
    descriptor = os.open(source, os.O_RDONLY)
    os.close(descriptor)
    with pytest.raises(OSError) as error:
        descriptor_names.descriptor_name(descriptor)
    # Linux's procfs observation returns ENOENT; Darwin's fcntl returns EBADF.
    assert error.value.errno in {errno.ENOENT, errno.EBADF}


def test_descriptor_name_without_a_supported_kernel_is_unprovable(monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr(descriptor_names.sys, "platform", "unsupported-test-platform")
        with pytest.raises(NotImplementedError, match="descriptor-name"):
            descriptor_names.descriptor_name(0)


def test_observer_source_closure_binds_the_actual_shared_descriptor_primitive():
    from sciplot_core.verification.private_process_boundaries import source_hashes

    source = Path(descriptor_names.__file__)
    assert source_hashes()["../foundation/descriptor_names.py"] == hashlib.sha256(source.read_bytes()).hexdigest()
