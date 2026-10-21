"""Scientific identity of an explicitly selected original source view."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sciplot_core.mapping_contract.values import _safe_id


def source_view_id(source_namespace: str, selection: dict[str, Any], columns: list[int], *,
                   selector: dict[str, Any] | None = None) -> str:
    """Mint once from the physical view, independently of aliases and list position.

    The saved namespace identifies the physical source; its SHA separately
    binds a version. Explicitly rebinding that same original view preserves its
    logical ID, while scientific sample/condition facts still require proof.
    """
    value = {"source_namespace": source_namespace, "sheet": selection["sheet"],
             "data_start_row": selection["data_start_row"],
             "data_end_row": selection["data_end_row"], "columns": columns}
    if selector is not None:
        value["selector"] = selector
    digest = hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                      separators=(",", ":")).encode()).hexdigest()
    return "group_" + digest[:32]


def validate_source_identity(value: dict[str, Any]) -> None:
    if (not isinstance(value, dict) or set(value) != {"version", "source_namespace", "category", "condition"}
            or type(value["version"]) is not int or value["version"] != 1
            or any(not isinstance(value[key], str) or not value[key].strip()
                   for key in ("source_namespace", "category"))
            or (value["condition"] is not None and (
                not isinstance(value["condition"], str) or not value["condition"].strip()))):
        raise ValueError("Source identity requires version 1, original category and a known condition or null.")


def proposal_source_identities(proposal: Any) -> dict[str, dict[str, Any]]:
    """Return an all-or-none current projection; historical sources stay absent."""
    identities = {source.source_id: dict(source.identity) for source in proposal.sources if source.identity}
    if identities and len(identities) != len(proposal.sources):
        raise ValueError("A mapping cannot mix structured and historical source identities.")
    return identities


def scientific_group_binding(value: dict[str, Any]) -> dict[str, Any]:
    """Validate the renderer's closed projection of the saved correspondence."""
    if isinstance(value, dict) and type(value.get("version")) is int and value["version"] == 2:
        if (set(value) != {"version", "source_id", "source_namespace", "categories", "condition", "value_column"}
                or not isinstance(value["source_namespace"], str) or not value["source_namespace"].strip()
                or not isinstance(value["categories"], list) or not value["categories"]
                or any(not isinstance(item, str) or not item.strip() for item in value["categories"])
                or len(value["categories"]) != len(set(value["categories"]))
                or type(value["value_column"]) is not int or value["value_column"] < 0
                or (value["condition"] is not None and (not isinstance(value["condition"], str) or not value["condition"].strip()))):
            raise ValueError("Categorical series binding requires original categories, condition and value column.")
        _safe_id(value["source_id"], "source_id")
        return dict(value)
    if (not isinstance(value, dict) or set(value) != {"version", "source_id", "source_namespace", "sample", "category", "condition"}
            or not isinstance(value["sample"], str) or not value["sample"].strip()):
        raise ValueError("Scientific group binding requires its complete original correspondence.")
    _safe_id(value["source_id"], "source_id")
    validate_source_identity({key: value[key] for key in ("version", "source_namespace", "category", "condition")})
    return dict(value)
