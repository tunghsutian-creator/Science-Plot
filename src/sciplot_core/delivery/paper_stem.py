"""Filenames for frozen group selections, independent of display text."""

from sciplot_core.foundation.json_hashing import canonical_json_sha256


def group_paper_stem(index: int, item_id: str, figure_id: str) -> str:
    identity = canonical_json_sha256([item_id, figure_id])
    return f"{index:03d}_{identity[:24]}"
