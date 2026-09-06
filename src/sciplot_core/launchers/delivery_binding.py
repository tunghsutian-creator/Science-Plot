"""Read inert delivery identity and editable-file baselines from the launcher."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DELIVERY_BINDING_PREFIX = "# SCIPLOT_DELIVERY_BINDING_V1 "


@dataclass(frozen=True)
class DeliveryBinding:
    root: str
    request: str | None
    source: str | None
    primary: str
    documents: tuple[tuple[str, str], ...]

    def to_line(self) -> str:
        return DELIVERY_BINDING_PREFIX + json.dumps(
            {
                "root": self.root,
                "request": self.request,
                "source": self.source,
                "primary": self.primary,
                "documents": dict(self.documents),
            },
            sort_keys=True,
            ensure_ascii=True,
            separators=(",", ":"),
        )


def delivery_binding_from_content(content: str) -> DeliveryBinding | None:
    lines = [
        line
        for line in content.splitlines()
        if line.startswith(DELIVERY_BINDING_PREFIX)
    ]
    if not lines:
        return None
    if len(lines) != 1:
        raise ValueError("The delivery launcher contains multiple identity records.")
    value = json.loads(lines[0][len(DELIVERY_BINDING_PREFIX) :])
    if not isinstance(value, dict) or set(value) != {
        "root",
        "request",
        "source",
        "primary",
        "documents",
    }:
        raise ValueError("The delivery launcher identity is malformed.")
    for key in ("root", "request", "source"):
        path = value[key]
        if key != "root" and path is None:
            continue
        if not isinstance(path, str) or not path or not Path(path).is_absolute():
            raise ValueError(f"The delivery launcher {key} must be an absolute path.")
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


def make_delivery_binding(
    *,
    root: Path,
    manifest: dict[str, Any],
    documents: list[dict[str, Any]],
) -> DeliveryBinding | None:
    if not documents:
        return None
    baseline = tuple(
        (Path(str(item["path"])).name, str(item["delivery_sha256"]))
        for item in documents
    )
    request_value = manifest.get("request_path")
    request_path = (
        Path(request_value).expanduser().resolve()
        if isinstance(request_value, str)
        else None
    )
    source = None
    if (
        request_path is not None
        and request_path.name == "plot_request.json"
        and request_path.is_file()
    ):
        try:
            request = json.loads(request_path.read_text(encoding="utf-8"))
            delivery = (
                request.get("delivery_output") if isinstance(request, dict) else None
            )
            source_value = request.get("input") if isinstance(request, dict) else None
            if (
                not isinstance(delivery, str)
                or Path(delivery).expanduser().resolve() != root
            ):
                request_path = None
            elif isinstance(source_value, str) and source_value.strip():
                source_path = Path(source_value).expanduser()
                if not source_path.is_absolute():
                    source_path = request_path.parent / source_path
                source = str(source_path.resolve())
            else:
                request_path = None
        except (OSError, ValueError):
            request_path = None
    else:
        request_path = None
    plan = manifest.get("resolved_figure_plan")
    primary_id = plan.get("primary_figure_id") if isinstance(plan, dict) else None
    primary = next(
        (
            Path(str(item["path"])).name
            for item in documents
            if item.get("figure_id") == primary_id
        ),
        baseline[0][0],
    )
    return DeliveryBinding(
        root=str(root),
        request=str(request_path) if request_path else None,
        source=source,
        primary=primary,
        documents=baseline,
    )
