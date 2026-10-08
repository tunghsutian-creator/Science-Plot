"""Compare live legacy authority with the pinned extraction, without rebaselining."""
from pathlib import Path
from typing import Any

from .extraction import extract_house_contract
from .registry import load_contract


def audit_legacy_sources(root: Path) -> dict[str, Any]:
    """Return a machine-readable gate; never update a snapshot after a drift."""
    pinned = load_contract()
    extracted = extract_house_contract(root)
    old, new = pinned["properties"], extracted["properties"]
    differences = [{"property": key, "pinned": old.get(key), "current_source": new.get(key)}
                   for key in sorted(set(old) | set(new)) if old.get(key) != new.get(key)]
    return {"kind": "sciplot_rendering_contract_source_audit", "schema_version": 1,
            "status": "passed" if not differences else "failed", "contract_id": pinned["contract_id"],
            "pinned_content_hash": pinned["content_hash"], "source_content_hash": extracted["content_hash"],
            "checked_properties": len(old), "differences": differences}
