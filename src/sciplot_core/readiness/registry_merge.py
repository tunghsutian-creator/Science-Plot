"""Merge scoped acceptance evidence into one validated-envelope registry."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.materials_rules import iter_public_rules
from sciplot_core.readiness.constants import (
    VALIDATED_ENVELOPE_ACCEPTANCE_LINEAGE_KIND,
    VALIDATED_ENVELOPE_ACCEPTANCE_LINEAGE_VERSION,
)
from sciplot_core.readiness.registry_build import (
    _acceptance_lineage_record,
    _acceptance_limitations,
    _acceptance_rows,
    _load_acceptance_summary,
    _validate_visual_review,
    _validated_entry_from_row,
)
from sciplot_core.readiness.registry_model import ValidatedEnvelopeRegistry
from sciplot_core.readiness.rule_contract import rule_contract_hashes
from sciplot_core.readiness.validation import _now, _required_text


def merge_validated_envelope_registry(
    base_registry: ValidatedEnvelopeRegistry,
    acceptance_summary_path: Path,
) -> ValidatedEnvelopeRegistry:
    """Replace only the rules selected by one validated partial acceptance run."""

    summary_path, payload, version, generated_at = _load_acceptance_summary(
        acceptance_summary_path
    )
    if payload.get("state") not in {"ready", "in_progress"}:
        raise ValueError("Scoped acceptance summary has an invalid state.")
    if payload.get("selected_state") != "ready":
        raise ValueError("Scoped acceptance summary must have selected_state=ready.")
    selected_value = payload.get("selected_rule_ids")
    if not isinstance(selected_value, list) or not selected_value:
        raise ValueError("Scoped acceptance must select at least one ready rule.")
    selected_ids = tuple(
        _required_text(value, "selected rule_id") for value in selected_value
    )
    if len(set(selected_ids)) != len(selected_ids):
        raise ValueError("Scoped acceptance selected_rule_ids must be unique.")
    failed_value = payload.get("failed_rule_ids")
    if not isinstance(failed_value, list):
        raise ValueError("Scoped acceptance failed_rule_ids must be a list.")
    failed_ids = {
        _required_text(value, "failed rule_id") for value in failed_value
    }
    if failed_ids.intersection(selected_ids):
        raise ValueError("Scoped acceptance selected rules cannot be failed.")

    rules = tuple(iter_public_rules())
    rule_by_id = {rule.rule_id: rule for rule in rules}
    unknown = sorted(set(selected_ids) - set(rule_by_id))
    if unknown:
        raise ValueError("Scoped acceptance selected unknown rules: " + ", ".join(unknown))
    coverage = payload.get("coverage")
    if not isinstance(coverage, dict) or coverage.get("ready_rule_count") != len(rules):
        raise ValueError("Scoped acceptance ready-rule coverage is not current.")
    _validate_visual_review(payload)
    visual = payload["visual_review"]
    if visual.get("eligible_rule_count") != len(selected_ids):
        raise ValueError("Scoped acceptance visual review does not match selection.")
    rows = _acceptance_rows(payload)
    if set(rows) != set(rule_by_id):
        raise ValueError("Scoped acceptance matrix does not match current ready rules.")

    base_entries = {entry.rule_id: entry for entry in base_registry.entries}
    if set(base_entries) != set(rule_by_id):
        raise ValueError("Base registry does not match current ready rules.")
    selected_set = set(selected_ids)
    for rule in rules:
        if rule.rule_id in selected_set:
            continue
        entry = base_entries[rule.rule_id]
        current = rule_contract_hashes(rule)
        if (
            entry.semantic_family != rule.semantic_family
            or entry.contract_sha256 != current.contract_sha256
            or entry.semantic_contract_sha256 != current.semantic_contract_sha256
        ):
            raise ValueError(
                f"Base registry contract is not current for `{rule.rule_id}`."
            )

    replacements = {
        rule_id: _validated_entry_from_row(
            rule=rule_by_id[rule_id],
            row=rows[rule_id],
            summary_path=summary_path,
            acceptance_generated_at=generated_at,
        )
        for rule_id in selected_ids
    }
    records: list[dict[str, object]] = []
    for source in base_registry.acceptance_lineage_records():
        remaining = [
            rule_id for rule_id in source["rule_ids"] if rule_id not in selected_set
        ]
        if remaining:
            preserved = deepcopy(source)
            preserved["rule_ids"] = remaining
            records.append(preserved)
    records.append(
        _acceptance_lineage_record(
            version=version,
            generated_at=generated_at,
            summary_sha256=file_sha256(summary_path),
            rule_ids=selected_ids,
            limitations=_acceptance_limitations(payload),
        )
    )
    return ValidatedEnvelopeRegistry(
        generated_at=_now(),
        source_acceptance={
            "kind": VALIDATED_ENVELOPE_ACCEPTANCE_LINEAGE_KIND,
            "version": VALIDATED_ENVELOPE_ACCEPTANCE_LINEAGE_VERSION,
            "records": records,
        },
        entries=tuple(
            replacements.get(entry.rule_id, entry) for entry in base_registry.entries
        ),
        limitations=base_registry.limitations,
    )


__all__ = ["merge_validated_envelope_registry"]
