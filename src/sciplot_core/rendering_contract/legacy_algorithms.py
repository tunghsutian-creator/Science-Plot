"""Pin the retained layout algorithms while their policy injection is incomplete.

The package resources work in source trees and installed wheels. This is a
compiler implementation binding, not a second rendering-style contract. A
runtime checks it once; the persistent service's source-byte guard rejects hot
changes before reusing that process. A different implementation needs a reviewed
compiler binding, never an automatic runtime rebaseline.
"""
from __future__ import annotations

import ast
import hashlib
import json
from copy import deepcopy
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from typing import Any

from .extraction import HOUSE_CONTRACT_ID, content_hash, seal_contract
from .registry import contract_binding, require_binding

ALGORITHM_ID = "sciplot-legacy-layout-algorithms-v1"
_PINNED_MANIFEST_HASH = "2e9d099a3643b86cdb86239b52395356e1b8660d1ecc7dc719e3e889ad0ff279"
_ROOT_MODULES = ("sciplot_core.studio_render.legend_placement", "sciplot_core.studio_render.value_parsing")


def extract_algorithm_binding(source_root: Path) -> dict[str, Any]:
    """Development extraction of the algorithms' explicit first-party closure.

    Import package initializers are sealed by the persistent runtime's complete
    source guard. This narrower closure contains every directly imported policy
    and helper reachable from the retained algorithms, including lazy imports.
    """
    pending = list(_ROOT_MODULES)
    seen: dict[str, str] = {}
    while pending:
        module = pending.pop()
        relative = module.removeprefix("sciplot_core.").replace(".", "/") + ".py"
        target = source_root / relative
        if not target.is_file():
            relative = relative.removesuffix(".py") + "/__init__.py"
            target = source_root / relative
        if relative in seen or not target.is_file():
            continue
        data = target.read_bytes()
        seen[relative] = hashlib.sha256(data).hexdigest()
        for node in ast.walk(ast.parse(data)):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("sciplot_core."):
                pending.append(node.module)
            elif isinstance(node, ast.Import):
                pending.extend(alias.name for alias in node.names if alias.name.startswith("sciplot_core."))
    policy = "policy/plot_contract.json"
    seen[policy] = hashlib.sha256((source_root / policy).read_bytes()).hexdigest()
    return seal_contract({"kind": "sciplot_compiler_algorithm_binding", "schema_version": 1,
                          "algorithm_id": ALGORITHM_ID, "rendering_contract": contract_binding(),
                          "roots": list(_ROOT_MODULES), "sources": dict(sorted(seen.items()))})


@lru_cache(maxsize=1)
def _checked_algorithms(house_hash: str) -> dict[str, Any]:
    manifest: dict[str, Any] = json.loads(files("sciplot_core.rendering_contract").joinpath(
        "styles", ALGORITHM_ID + ".json").read_text())
    if (manifest.get("kind") != "sciplot_compiler_algorithm_binding"
            or manifest.get("algorithm_id") != ALGORITHM_ID or manifest.get("content_hash") != content_hash(manifest)
            or manifest.get("content_hash") != _PINNED_MANIFEST_HASH
            or manifest.get("rendering_contract") != {"contract_id": HOUSE_CONTRACT_ID, "content_hash": house_hash}):
        raise ValueError("Retained rendering algorithm binding does not match this pinned house contract.")
    package = files("sciplot_core")
    changed = []
    for relative, expected in manifest["sources"].items():
        try:
            actual = hashlib.sha256(package.joinpath(relative).read_bytes()).hexdigest()
        except (OSError, FileNotFoundError):
            actual = "missing"
        if actual != expected:
            changed.append(relative)
    if changed:
        raise ValueError("Retained rendering algorithm or policy bytes changed: " + ", ".join(changed))
    return {"algorithm_id": ALGORITHM_ID, "content_hash": manifest["content_hash"],
            "rendering_contract": manifest["rendering_contract"], "checked_sources": len(manifest["sources"]),
            "source": "pinned compiler algorithm binding"}


def require_legacy_algorithms(binding: dict[str, Any]) -> dict[str, Any]:
    require_binding(binding)
    if binding["contract_id"] != HOUSE_CONTRACT_ID:
        raise ValueError("Retained algorithms require the house rendering contract.")
    return deepcopy(_checked_algorithms(binding["content_hash"]))
