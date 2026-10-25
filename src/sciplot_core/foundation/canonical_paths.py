"""Pure NoFollow canonical path validation shared by host composition."""
from pathlib import Path


def canonical_path(value: Path) -> Path:
    path = value.expanduser().absolute()
    if any(member.is_symlink() for member in (path, *path.parents)):
        raise ValueError(f"Managed project queries cannot follow a symlink: {path}")
    return path.resolve()

