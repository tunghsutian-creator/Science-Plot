"""Hash canonical JSON values for cross-process contract binding."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sciplot_core.foundation.json_values import json_safe


def canonical_json_sha256(value: Any, *, allow_nan: bool = True) -> str:
    """Return the SHA-256 digest of one stable, JSON-safe representation."""

    encoded = json.dumps(
        json_safe(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=allow_nan,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = ["canonical_json_sha256"]
