"""Serialize an explicitly staged private project tree to one complete archive."""

import os
from pathlib import Path
import zipfile
from uuid import uuid4


def write_project_archive(project_root: Path, zip_path: Path) -> None:
    if zip_path.is_symlink():
        raise PermissionError("Refusing to replace a symlink-backed SciPlot ZIP.")
    files = []
    for path in sorted(project_root.rglob("*")):
        if path.is_symlink():
            raise PermissionError(f"Refusing to archive symlink-backed project entry: {path}")
        if path.is_file():
            files.append(path)
    staged = zip_path.parent / f".{zip_path.name}.sciplot-tmp-{uuid4().hex}"
    try:
        with staged.open("xb") as stream:
            with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for path in files:
                    archive.write(path, path.relative_to(project_root.parent))
            stream.flush()
            os.fsync(stream.fileno())
        with zipfile.ZipFile(staged) as archive:
            if archive.testzip() is not None:
                raise OSError("SciPlot ZIP verification failed.")
        if zip_path.is_symlink():
            raise PermissionError("Refusing to replace a symlink-backed SciPlot ZIP.")
        os.replace(staged, zip_path)
    finally:
        staged.unlink(missing_ok=True)
