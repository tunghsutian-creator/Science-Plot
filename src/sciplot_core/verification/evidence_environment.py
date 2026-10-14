"""Semantic environment identity; actual launch routing stays in its ledger."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any

from sciplot_core.foundation.json_hashing import canonical_json_sha256

POLICY = "active-private-observer-routing-v1"
ROUTING = ["SCIPLOT_PRIVATE_AUDIT_PARENT", "SCIPLOT_PRIVATE_AUDIT_CHILD"]
SCOPE = ["SCIPLOT_PRIVATE_AUDIT_DIR", "SCIPLOT_PRIVATE_AUDIT_ROOTS", "SCIPLOT_PRIVATE_AUDIT_RUN"]
AUDIT_KEYS = {*SCOPE, *ROUTING, "SCIPLOT_PRIVATE_AUDIT_CONTINUATION"}


def semantic_environment(environment: dict[str, str]) -> tuple[dict[str, str], dict[str, Any] | None]:
    """Only a supported active observer can identify its temporary routing keys."""
    if not all(environment.get(key) for key in SCOPE):
        return environment, None
    try:
        from sciplot_core.verification.private_observer import (
            Observer, bootstrap_hashes, current_observer, source_hashes,
        )
    except ImportError:
        return environment, None
    from sciplot_core.verification.private_process_boundaries import root_scope

    observer = current_observer()
    if (not isinstance(observer, Observer) or observer.sealed
            or any(key.startswith("SCIPLOT_PRIVATE_AUDIT_") and key not in AUDIT_KEYS for key in environment)
            or environment.get(SCOPE[0]) != str(observer.directory)
            or environment.get(SCOPE[1]) != observer.wrapper_environment.get(SCOPE[1])
            or environment.get(SCOPE[2]) != observer.run):
        return environment, None
    try:
        roots = json.loads(environment[SCOPE[1]])
        bootstrap = Path(getattr(sys.modules.get("sitecustomize"), "__file__", ""))
        startup_hash = hashlib.sha256(bootstrap.read_bytes()).hexdigest()
        supported = {value for name, value in bootstrap_hashes().items() if name.endswith("sitecustomize.py")}
        if root_scope(roots) != observer.root_scope or startup_hash not in supported:
            return environment, None
    except (OSError, TypeError, ValueError, RuntimeError):
        return environment, None
    binding = {"policy": POLICY, "excluded_keys": ROUTING,
               "audit_scope_sha256": canonical_json_sha256({key: environment[key] for key in SCOPE}, allow_nan=False),
               "observer_sources_sha256": canonical_json_sha256(source_hashes(), allow_nan=False),
               "startup_sha256": startup_hash}
    return {key: value for key, value in environment.items() if key not in ROUTING}, binding


def binding_valid(binding: object) -> bool:
    """Validate finite historical metadata without looking up receipt paths."""
    return (isinstance(binding, dict) and set(binding) == {
        "policy", "excluded_keys", "audit_scope_sha256", "observer_sources_sha256", "startup_sha256",
    } and binding.get("policy") == POLICY and binding.get("excluded_keys") == ROUTING
        and all(isinstance(binding[key], str) and re.fullmatch("[0-9a-f]{64}", binding[key]) is not None
                for key in ("audit_scope_sha256", "observer_sources_sha256", "startup_sha256")))
