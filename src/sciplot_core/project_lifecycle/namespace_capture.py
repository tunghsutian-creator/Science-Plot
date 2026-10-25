"""Capture only an explicitly owned namespace, never its source parent or siblings."""
import os
from pathlib import Path
import stat

from sciplot_core.project_store.io import read_file
from .attachment_index import OWNER
from .errors import EngineError


def namespace_bytes(root: Path, *, modes: dict[str, int] | None = None) -> dict[str, bytes]:
    if any(member.is_symlink() for member in (root, *root.parents)) or not root.is_dir():
        raise EngineError("semantic_attachment_import_invalid", "Import requires this exact existing semantic namespace.")
    result = {}
    for directory, names, files in os.walk(root, followlinks=False):
        parent = Path(directory)
        for name in names:
            if (parent / name).is_symlink():
                raise EngineError("semantic_attachment_import_invalid", "A semantic namespace cannot contain symbolic directories.")
        descriptor = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for name in sorted(files):
                path = parent / name
                if path == root / OWNER:
                    continue
                if not stat.S_ISREG(path.lstat().st_mode):
                    raise EngineError("semantic_attachment_import_invalid", "A semantic namespace must contain regular files.")
                relative = path.relative_to(root).as_posix()
                data, mode = read_file(descriptor, name)
                result[relative] = data
                if modes is not None:
                    modes[relative] = mode
        finally:
            os.close(descriptor)
    return result
