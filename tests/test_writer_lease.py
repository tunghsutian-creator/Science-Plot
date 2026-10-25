"""The shared lease has one kernel owner and no recoverable pathname state."""

import pytest

from sciplot_core.foundation.writer_lease import (
    DirectoryWriterLease,
    WriterLeaseBusy,
    WriterLeaseChanged,
    exclusive_directory_lease,
)


@pytest.mark.parametrize("failure", [RuntimeError, KeyboardInterrupt, SystemExit])
def test_every_python_exit_releases_lease_and_close_is_idempotent(tmp_path, failure):
    with pytest.raises(failure), exclusive_directory_lease(tmp_path) as lease:
        with pytest.raises(WriterLeaseBusy):
            DirectoryWriterLease(tmp_path)
        raise failure()
    lease.close()
    with pytest.raises(WriterLeaseChanged):
        lease.verify()
    with exclusive_directory_lease(tmp_path) as following:
        following.verify()
    assert list(tmp_path.iterdir()) == []


def test_aliases_share_kernel_identity_and_parent_rename_does_not_release_lease(tmp_path):
    directory = tmp_path / "directory"
    directory.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(directory, target_is_directory=True)
    moved = tmp_path / "moved"
    with exclusive_directory_lease(directory) as lease:
        with pytest.raises(WriterLeaseBusy):
            DirectoryWriterLease(alias)
        directory.rename(moved)
        directory.mkdir()
        with pytest.raises(WriterLeaseChanged):
            lease.verify()
        with pytest.raises(WriterLeaseBusy):
            DirectoryWriterLease(moved)
        # A replacement inode is a distinct storage location, never the old lease.
        with exclusive_directory_lease(directory) as replacement:
            replacement.verify()
    with exclusive_directory_lease(moved) as recovered:
        recovered.verify()
