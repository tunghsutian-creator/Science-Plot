from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from urllib.parse import quote

INTERACTION_ARTIST_ATTR = "_sciplot_interaction"
INTERACTION_GID_PREFIX = "sciplot-interaction"


def tag_interaction_artist(
    artist: Any,
    *,
    payload_type: str,
    payload_id: str,
    kind: str,
    label: str | None = None,
    operations: Sequence[str] = ("select", "quick_edit", "more"),
    part: str = "body",
) -> Any:
    metadata = {
        "payload_type": payload_type,
        "payload_id": payload_id,
        "kind": kind,
        "label": label,
        "operations": list(operations),
        "part": part,
    }
    setattr(artist, INTERACTION_ARTIST_ATTR, metadata)
    set_gid = getattr(artist, "set_gid", None)
    if callable(set_gid):
        set_gid(f"{INTERACTION_GID_PREFIX}:{payload_type}:{quote(payload_id, safe='')}:{quote(part, safe='')}")
    return artist


def interaction_artist_metadata(artist: Any) -> dict[str, Any] | None:
    metadata = getattr(artist, INTERACTION_ARTIST_ATTR, None)
    return metadata if isinstance(metadata, dict) else None


__all__ = [
    "INTERACTION_ARTIST_ATTR",
    "INTERACTION_GID_PREFIX",
    "interaction_artist_metadata",
    "tag_interaction_artist",
]
