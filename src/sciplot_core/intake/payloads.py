"""Decode browser request payloads into typed intake inputs."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from .models import IncomingFile, IntakeGroupInput


def _decode_group_payload(payload: dict[str, Any]) -> list[IntakeGroupInput]:
    groups: list[IntakeGroupInput] = []
    for group in payload.get("groups", []):
        sample = str(group.get("sample") or "").strip()
        files: list[IncomingFile] = []
        for item in group.get("files", []):
            name = str(item.get("name") or "file")
            source_path = str(item.get("source_path") or "").strip()
            if source_path:
                path = Path(source_path).expanduser()
                files.append(
                    IncomingFile(name=name or path.name, content=path.read_bytes())
                )
            else:
                content_base64 = str(item.get("content_base64") or "")
                if "," in content_base64:
                    content_base64 = content_base64.split(",", 1)[1]
                files.append(
                    IncomingFile(name=name, content=base64.b64decode(content_base64))
                )
        groups.append(IntakeGroupInput(sample=sample, files=tuple(files)))
    return groups
