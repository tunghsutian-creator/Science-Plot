"""Prepare the task's source-bound replicate disclosure and missing decision."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sciplot_core.semantic_sources.impact_replicate_disclosure import (
    validate_replicate_disclosure as validate_replicate_disclosure,
    wide_replicate_evidence as wide_replicate_evidence,
)
from sciplot_core.task_missing_values import require_missing_policy


def prepare_replicate_disclosure(state: dict[str, Any], source: Path) -> dict[str, Any] | None:
    evidence = wide_replicate_evidence(source)
    too_small = [group for group in evidence["groups"] if group["valid_n"] < 2]
    if too_small:
        raise ValueError("Sample SD is undefined for original groups with fewer than two valid numeric observations: " + ", ".join(f"{group['sample']} ({group['condition']}): n={group['valid_n']}" for group in too_small))
    policy = require_missing_policy(state, evidence)
    return None if policy is None else {**evidence, "missing_values": policy}
