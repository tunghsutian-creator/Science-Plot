"""One canonical-path expectation for each current scientific input file."""

from pathlib import Path
from typing import Any

from .errors import EngineError


def physical_path(path: str) -> str:
    """The existing filesystem-path identity, never an equal-content identity."""
    return str(Path(path).resolve())


def source_groups(document: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for source in document["scientific"]["data_sources"]:
        groups.setdefault(physical_path(source["path"]), []).append(source)
    return groups


def add_input(files: dict[str, str], path: str, sha256: str) -> None:
    canonical = physical_path(path)
    if canonical in files and files[canonical] != sha256:
        raise EngineError("managed_input_identity_conflict", "One physical input path cannot have conflicting expected hashes.",
                          action="inspect_document", path=canonical)
    files[canonical] = sha256
