"""Evaluate mapped-source coverage for a render result."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from sciplot_core.source_coverage.artifacts import (
    _series_source_artifacts,
    _expected_mapping_outputs,
)


def evaluate_mapping_source_coverage(
    rendered_units: Iterable[dict[str, Any]],
    *,
    mapping_application: dict[str, Any],
    template: str,
    allow_downstream_sources: bool = False,
    artifact_inventory: dict[str, str] | None = None,
) -> dict[str, Any]:
    mapped_output_values = mapping_application.get("mapped_outputs")
    mapped_output_paths = {
        str(Path(str(item.get("path") or "")).expanduser().resolve())
        for item in (
            mapped_output_values if isinstance(mapped_output_values, list) else []
        )
        if isinstance(item, dict)
    }
    expected_inventory = (
        artifact_inventory
        if artifact_inventory is not None
        and mapped_output_paths
        and mapped_output_paths <= set(artifact_inventory)
        else None
    )
    expected = _expected_mapping_outputs(
        mapping_application,
        artifact_inventory=expected_inventory,
    )
    normalized_units: list[dict[str, Any]] = []
    for index, raw in enumerate(rendered_units, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"Rendered unit {index} is not an object.")
        identity = str(raw.get("identity") or "").strip()
        if not identity:
            raise ValueError(f"Rendered unit {index} has no stable identity.")
        normalized_units.append(
            {
                "identity": identity,
                "kind": str(raw.get("kind") or "series"),
                "source_artifacts": _series_source_artifacts(
                    raw.get("source_artifacts"),
                    label=f"rendered unit {identity!r}",
                    artifact_inventory=artifact_inventory,
                ),
            }
        )
    if not normalized_units:
        raise ValueError("The rendered Veusz specification contains no data units.")
    unit_identities = [unit["identity"] for unit in normalized_units]
    if len(unit_identities) != len(set(unit_identities)):
        raise ValueError("Rendered source coverage repeats a unit identity.")

    expected_keys = {(record["path"], record["sha256"]) for record in expected}
    contribution_counts = {key: 0 for key in expected_keys}
    rendered_source_keys: set[tuple[str, str]] = set()
    for unit in normalized_units:
        unit_keys = {
            (record["path"], record["sha256"]) for record in unit["source_artifacts"]
        }
        rendered_source_keys.update(unit_keys)
        for key in expected_keys & unit_keys:
            contribution_counts[key] += 1
    unexpected_keys = rendered_source_keys - expected_keys
    if unexpected_keys and not allow_downstream_sources:
        mapped_output_contributes = any(
            count > 0 for count in contribution_counts.values()
        )
        unambiguous_single_output_transform = (
            len(expected) == 1
            and not mapped_output_contributes
            and len(rendered_source_keys) == 1
        )
        if not unambiguous_single_output_transform:
            paths = ", ".join(path for path, _ in sorted(unexpected_keys))
            raise ValueError(
                "Rendered Veusz data consume files outside the confirmed "
                f"mapped output inventory: {paths}"
            )

    exact_missing = [
        record
        for record in expected
        if contribution_counts[(record["path"], record["sha256"])] == 0
    ]
    if not exact_missing:
        coverage_mode = "exact_per_output"
    elif len(expected) == 1:
        # With one confirmed mapping output there is no sibling source that can
        # be silently omitted. Downstream recipe/semantic transforms are bound
        # independently by the transform ledger and terminal snapshot checks.
        coverage_mode = "transitive_single_output"
    else:
        missing_paths = ", ".join(record["path"] for record in exact_missing)
        raise ValueError(
            "Rendered Veusz data do not consume every confirmed mapped output: "
            f"{missing_paths}"
        )

    return {
        "kind": "sciplot_rendered_mapping_source_coverage",
        "version": 1,
        "status": "passed",
        "proposal_id": mapping_application.get("proposal_id"),
        "template": str(template),
        "coverage_mode": coverage_mode,
        "expected_outputs": expected,
        "expected_output_count": len(expected),
        "rendered_units": normalized_units,
        "rendered_unit_count": len(normalized_units),
        "contribution_counts": [
            {
                **record,
                "rendered_unit_count": contribution_counts[
                    (record["path"], record["sha256"])
                ],
            }
            for record in expected
        ],
        "silent_omission_detected": False,
    }
