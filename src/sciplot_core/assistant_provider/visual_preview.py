"""Validate bounded PNG visual previews."""

from __future__ import annotations

import base64
import binascii
import hashlib
from io import BytesIO
from typing import Any
from PIL import Image
from sciplot_core.json_contract import (
    reject_unknown_keys,
    require_json_int,
    require_json_object,
)

from sciplot_core.assistant_provider.contracts import (
    ASSISTANT_VISUAL_PREVIEW_MAX_BYTES,
    _MAX_VISUAL_PREVIEW_BASE64_LENGTH,
)

from sciplot_core.assistant_provider.text_validation import (
    _sha256,
)


def _png_dimensions(payload: bytes) -> tuple[int, int]:
    if not payload.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("Assistant visual_preview must contain a PNG image.")
    try:
        with Image.open(BytesIO(payload)) as image:
            if image.format != "PNG":
                raise ValueError("Assistant visual_preview must contain a PNG image.")
            width, height = image.size
            image.verify()
    except (OSError, SyntaxError, ValueError) as exc:
        raise ValueError(
            "Assistant visual_preview must contain a structurally valid PNG image."
        ) from exc
    return int(width), int(height)


def _validate_visual_preview(
    value: object,
    *,
    base_revision: int,
) -> dict[str, Any] | None:
    if value is None:
        return None
    preview = require_json_object(value, label="Assistant visual_preview")
    fields = {"base64", "sha256", "width", "height", "revision"}
    reject_unknown_keys(preview, fields, label="Assistant visual_preview")
    missing = sorted(fields.difference(preview))
    if missing:
        raise ValueError(
            f"Assistant visual_preview is missing required fields: {missing!r}"
        )
    encoded = preview["base64"]
    if not isinstance(encoded, str) or not encoded:
        raise ValueError("Assistant visual_preview base64 must be a non-empty string.")
    if len(encoded) > _MAX_VISUAL_PREVIEW_BASE64_LENGTH:
        raise ValueError("Assistant visual_preview must decode to at most 4 MiB.")
    try:
        encoded_bytes = encoded.encode("ascii")
        image = base64.b64decode(encoded_bytes, validate=True)
    except (UnicodeEncodeError, ValueError, binascii.Error) as exc:
        raise ValueError(
            "Assistant visual_preview base64 must be canonical standard base64."
        ) from exc
    if base64.b64encode(image).decode("ascii") != encoded:
        raise ValueError(
            "Assistant visual_preview base64 must be canonical standard base64."
        )
    if not image or len(image) > ASSISTANT_VISUAL_PREVIEW_MAX_BYTES:
        raise ValueError(
            "Assistant visual_preview must decode to 1 byte through 4 MiB."
        )
    png_width, png_height = _png_dimensions(image)
    supplied_sha = _sha256(preview["sha256"], "visual_preview sha256")
    expected_sha = hashlib.sha256(image).hexdigest()
    if supplied_sha != expected_sha:
        raise ValueError(
            "Assistant visual_preview sha256 does not match the PNG bytes."
        )
    width = require_json_int(preview["width"], label="visual_preview width")
    height = require_json_int(preview["height"], label="visual_preview height")
    if width != png_width or height != png_height:
        raise ValueError(
            "Assistant visual_preview dimensions do not match the PNG IHDR."
        )
    revision = require_json_int(
        preview["revision"],
        label="visual_preview revision",
    )
    if revision < 0:
        raise ValueError("Assistant visual_preview revision must be non-negative.")
    if revision != base_revision:
        raise ValueError("Assistant visual_preview revision must match base_revision.")
    return {
        "base64": encoded,
        "sha256": expected_sha,
        "width": width,
        "height": height,
        "revision": revision,
    }
