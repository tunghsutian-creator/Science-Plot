"""Load immutable rendering resources without importing legacy renderer owners."""
from __future__ import annotations

import json
from copy import deepcopy
from functools import lru_cache
from importlib.resources import files
from typing import Any

from jsonschema import Draft202012Validator

from .composition import COMPOSITION_CONTRACT_ID
from .extraction import HOUSE_CONTRACT_ID, content_hash
from .schema import binding_schema, rendering_contract_schema

_PINNED_CONTENT_HASHES = {
    HOUSE_CONTRACT_ID: "cb9d4af22f1905ede7acc956ccbc9d664f4d9171a4dad9afb2ca878cf96cd821",
    COMPOSITION_CONTRACT_ID: "345c47f305fc9e2b57defd08662abad0e6232a1ac00d649725ea20e8829bf283",
}


@lru_cache(maxsize=4)
def _snapshot(contract_id: str) -> dict[str, Any]:
    if contract_id not in {HOUSE_CONTRACT_ID, COMPOSITION_CONTRACT_ID}:
        raise ValueError(f"Unsupported rendering contract: {contract_id}")
    payload: dict[str, Any] = json.loads(files(__package__).joinpath("styles", contract_id + ".json").read_text())
    Draft202012Validator(rendering_contract_schema()).validate(payload)
    if (payload["contract_id"] != contract_id or payload["content_hash"] != content_hash(payload)
            or payload["content_hash"] != _PINNED_CONTENT_HASHES[contract_id]):
        raise ValueError("Rendering contract snapshot identity mismatch.")
    return payload


def load_contract(contract_id: str = HOUSE_CONTRACT_ID) -> dict[str, Any]:
    """Return an independent snapshot; callers cannot mutate the registry cache."""
    return deepcopy(_snapshot(contract_id))


def contract_binding(contract_id: str = HOUSE_CONTRACT_ID) -> dict[str, str]:
    contract = _snapshot(contract_id)
    return {"contract_id": contract_id, "content_hash": str(contract["content_hash"])}


def require_binding(binding: dict[str, Any]) -> dict[str, Any]:
    Draft202012Validator(binding_schema()).validate(binding)
    if binding != contract_binding(binding["contract_id"]):
        raise ValueError("Rendering contract content changed: the document requires its pinned version.")
    return load_contract(binding["contract_id"])


def contract_value(key: str, binding: dict[str, Any] | None = None) -> Any:
    contract = require_binding(binding) if binding is not None else load_contract()
    entry = contract["properties"][key]
    if entry["status"] == "unspecified":
        raise ValueError(f"Rendering contract does not specify {key}; provide an explicit override.")
    return deepcopy(entry["value"])
