"""Immutable delivery binding value and its one strict payload schema."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import re


@dataclass(frozen=True)
class DeliveryBinding:
    root: str
    request: str | None
    source: str | None
    primary: str
    documents: tuple[tuple[str, str], ...]

    def to_payload(self) -> dict[str, Any]:
        return {"root": self.root, "request": self.request, "source": self.source,
                "primary": self.primary, "documents": dict(self.documents)}

def delivery_binding_from_payload(value: object) -> DeliveryBinding:
    if not isinstance(value, dict) or set(value) != {
        "root",
        "request",
        "source",
        "primary",
        "documents",
    }:
        raise ValueError("The delivery identity is malformed.")
    for key in ("root", "request", "source"):
        path = value[key]
        if key != "root" and path is None:
            continue
        if not isinstance(path, str) or not path or not Path(path).is_absolute():
            raise ValueError(f"The delivery identity {key} must be an absolute path.")
    documents = value["documents"]
    if not isinstance(documents, dict) or not documents:
        raise ValueError("The delivery identity requires editable documents.")
    for name, digest in documents.items():
        if (
            not isinstance(name, str)
            or Path(name).name != name
            or Path(name).suffix.lower() != ".vsz"
            or not isinstance(digest, str)
            or re.fullmatch(r"[a-f0-9]{64}", digest) is None
        ):
            raise ValueError("The delivery editable-document baseline is malformed.")
    if not isinstance(value["primary"], str) or value["primary"] not in documents:
        raise ValueError("The delivery primary document is not in its baseline.")
    if (value["request"] is None) != (value["source"] is None):
        raise ValueError("The delivery project identity is incomplete.")
    return DeliveryBinding(
        root=value["root"],
        request=value["request"],
        source=value["source"],
        primary=value["primary"],
        documents=tuple(sorted(documents.items())),
    )

