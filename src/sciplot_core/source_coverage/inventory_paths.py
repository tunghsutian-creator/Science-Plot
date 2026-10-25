"""Scientific source membership is literal; file and directory IO is located."""
from collections.abc import Sequence
from pathlib import Path

from sciplot_core.foundation.source_locations import literal_source_path, resolve_source_path


def source_inventory_contains(path: Path, roots: Sequence[Path]) -> bool:
    """Retain exact source names; an IO view or basename grants no new source."""
    for root in roots:
        # Optional absent roots carry no physical alias to invert. Do not read
        # one unless a declared source actually claims membership under it.
        literal = Path(literal_source_path(root)) if root.exists() else root
        if path == literal:
            return True
        if path.is_relative_to(literal) and resolve_source_path(root).is_dir():
            return True
    return False
