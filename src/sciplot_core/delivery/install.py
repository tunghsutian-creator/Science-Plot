"""Atomically install a new validated directory, excluding existing outputs."""

from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path

from sciplot_core.studio_core.source_update_commit import reject_symlink_path


def install_new_delivery(candidate: Path, delivery: Path) -> None:
    """Atomically rename a new directory without replacing even an empty target."""
    reject_symlink_path(candidate)
    reject_symlink_path(delivery)
    library = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin" and hasattr(library, "renamex_np"):
        rename = library.renamex_np
        rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        result = rename(os.fsencode(candidate), os.fsencode(delivery), 0x00000004)  # RENAME_EXCL
    elif sys.platform.startswith("linux") and hasattr(library, "renameat2"):
        rename = library.renameat2
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        result = rename(-100, os.fsencode(candidate), -100, os.fsencode(delivery), 1)  # RENAME_NOREPLACE
    else:
        raise RuntimeError("Atomic non-replacing directory installation is unavailable on this platform.")
    if result:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), str(delivery))
