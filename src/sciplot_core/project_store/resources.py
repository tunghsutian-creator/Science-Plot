"""Host-selected resource roots, optionally confined to exact relative files."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ResourceRoot:
    path: Path
    members: tuple[str, ...] | None = None
