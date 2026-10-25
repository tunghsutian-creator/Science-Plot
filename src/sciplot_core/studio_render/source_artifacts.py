"""Project only a newly produced scientific artifact's path into its literal ID."""
from pathlib import Path

from sciplot_core.foundation.source_locations import literal_source_path, selected_source_resolver


def literal_source_artifact(path: str | Path, sha256: str) -> tuple[str, str]:
    """Keep captured bytes/hash intact; no-scope callers retain their old spelling."""
    literal = literal_source_path(Path(path)) if selected_source_resolver() is not None else str(path)
    return literal, sha256
