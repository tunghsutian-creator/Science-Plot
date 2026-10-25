"""Nonblocking POSIX writer exclusion bound to a directory inode.

The directory must already exist. Every cooperating writer in that directory
uses this lease; separate files in one directory deliberately share exclusion.
There is no lock pathname to unlink or reclaim. Closing the descriptor, including
process termination, releases the kernel lock. This is not a distributed lease.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import stat


class WriterLeaseBusy(RuntimeError):
    """Another live writer owns this directory's kernel lease."""


class WriterLeaseChanged(RuntimeError):
    """The leased directory no longer occupies its canonical pathname."""


class DirectoryWriterLease:
    """Own one directory descriptor until close; publication may use its fd."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory.expanduser().resolve(strict=True)
        self._fd: int | None = os.open(
            self.directory,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
        )
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.verify()
        except BlockingIOError as exc:
            self.close()
            raise WriterLeaseBusy("Another writer owns this directory's save lease.") from exc
        except BaseException:
            self.close()
            raise

    @property
    def fd(self) -> int:
        if self._fd is None:
            raise WriterLeaseChanged("The writer lease is already closed.")
        return self._fd

    def verify(self) -> None:
        """Check identity before using path-based staging or publishing results."""
        opened = os.fstat(self.fd)
        try:
            current = self.directory.lstat()
        except OSError as exc:
            raise WriterLeaseChanged("The leased directory path changed.") from exc
        if (not stat.S_ISDIR(current.st_mode)
                or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino)):
            raise WriterLeaseChanged("The leased directory path changed.")

    def close(self) -> None:
        if self._fd is not None:
            descriptor, self._fd = self._fd, None
            os.close(descriptor)


@contextmanager
def exclusive_directory_lease(directory: Path) -> Iterator[DirectoryWriterLease]:
    lease = DirectoryWriterLease(directory)
    try:
        yield lease
    finally:
        lease.close()
