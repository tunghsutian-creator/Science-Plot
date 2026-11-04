"""Fresh kernel names for live descriptors, without identity or access claims."""
from __future__ import annotations

import os
import sys


def descriptor_name(descriptor: int) -> str:
    """Observe this FD now; callers must validate filesystem identity and access.

    Linux may return pipe/socket labels or a deleted-path suffix. This primitive
    preserves them for the caller's own policy, along with real OS failures.
    """
    if sys.platform == "darwin":
        import fcntl
        return os.fsdecode(fcntl.fcntl(descriptor, fcntl.F_GETPATH, b"\0" * 1024).split(b"\0", 1)[0])
    elif sys.platform.startswith("linux"):
        return os.readlink(f"/proc/self/fd/{descriptor}")
    else:
        raise NotImplementedError("No supported kernel descriptor-name observation.")
