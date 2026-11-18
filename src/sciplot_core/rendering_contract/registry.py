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

CURRENT_HOUSE_CONTRACT_ID = "sciplot-house-style-v2"
LOG_MINOR_ALGORITHM_ID = "sciplot-current-log-minor-ticks-v1"
INSIDE_BEST_ALGORITHM_ID = "sciplot-current-inside-best-v1"


_PINNED_CONTENT_HASHES = {
    CURRENT_HOUSE_CONTRACT_ID: "36d58b2240edc6b40007542651ef0d5d9ba484355be1f341643d1399f50bf030",
    HOUSE_CONTRACT_ID: "cb9d4af22f1905ede7acc956ccbc9d664f4d9171a4dad9afb2ca878cf96cd821",
    COMPOSITION_CONTRACT_ID: "345c47f305fc9e2b57defd08662abad0e6232a1ac00d649725ea20e8829bf283",
}


@lru_cache(maxsize=4)
def _snapshot(contract_id: str) -> dict[str, Any]:
    if contract_id not in _PINNED_CONTENT_HASHES:
        raise ValueError(f"Unsupported rendering contract: {contract_id}")
    if contract_id == CURRENT_HOUSE_CONTRACT_ID:
        # V2 deliberately inherits exact, immutable V1 visual values.
        payload = load_contract(HOUSE_CONTRACT_ID)
        payload.update(contract_id=contract_id, authority="current_rendering_policy")
        payload["properties"]["axis.log_minor_algorithm"] = {
            "status": "specified", "value": LOG_MINOR_ALGORITHM_ID,
            "source_file": "src/sciplot_core/rendering_contract/current_ticks.py", "source_symbol": "log_minor_ticks",
            "notes": "Open-decade minor ticks consume the pinned axis.log_minor_multipliers, not the legacy runtime policy.",
        }
        payload["properties"]["legend.inside_best_algorithm"] = {
            "status": "specified", "value": INSIDE_BEST_ALGORITHM_ID,
            "source_file": "src/sciplot_core/rendering_contract/current_inside_best.py", "source_symbol": "inside_best_geometry",
            "notes": "Explicit well-separated axes use the equivalent physical footprint, corner scoring and anchor.",
        }
        payload["content_hash"] = content_hash(payload)
    else:
        payload = json.loads(files(__package__).joinpath("styles", contract_id + ".json").read_text())
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


def writer_binding() -> dict[str, str]:
    """Bind fresh semantic requests; unmarked imported templates retain v1."""
    return contract_binding(CURRENT_HOUSE_CONTRACT_ID)


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
