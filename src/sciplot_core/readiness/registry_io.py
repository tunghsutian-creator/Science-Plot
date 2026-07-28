"""Load and atomically write validated-envelope registries."""

from __future__ import annotations

import json
from pathlib import Path
from sciplot_core.foundation.json_io import atomic_write_json

from sciplot_core.readiness.constants import (
    DEFAULT_VALIDATED_ENVELOPE_REGISTRY,
)

from sciplot_core.readiness.registry_model import (
    ValidatedEnvelopeRegistry,
)


def load_validated_envelope_registry(
    path: Path | None = None,
) -> ValidatedEnvelopeRegistry:
    registry_path = (
        path.expanduser().resolve()
        if path is not None
        else DEFAULT_VALIDATED_ENVELOPE_REGISTRY
    )
    if not registry_path.is_file():
        raise FileNotFoundError(
            f"Validated-envelope registry not found: {registry_path}"
        )
    try:
        payload = json.loads(registry_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Validated-envelope registry is not valid JSON: {registry_path}"
        ) from exc
    return ValidatedEnvelopeRegistry.from_dict(payload)


def write_validated_envelope_registry(
    path: Path,
    registry: ValidatedEnvelopeRegistry,
) -> Path:
    return atomic_write_json(path.expanduser().resolve(), registry.to_dict())
