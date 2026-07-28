"""Build a validated-envelope registry from acceptance manifests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.materials_rules import (
    iter_public_rules,
)

from sciplot_core.readiness.constants import (
    READY_RULE_ACCEPTANCE_VERSION,
    AUTHORIZATION_READY,
    FIXTURE_HASH_ACCEPTED,
    REQUIRED_ACCEPTANCE_CHECKS,
)

from sciplot_core.readiness.validation import (
    _now,
    _required_text,
    _required_int,
    _required_hash,
    _timestamp,
)

from sciplot_core.readiness.rule_contract import (
    semantic_contract_sha256,
    rule_contract_sha256,
    rule_semantic_contract_sha256,
)

from sciplot_core.readiness.envelope_model import (
    ValidatedRuleEnvelope,
)

from sciplot_core.readiness.registry_model import (
    ValidatedEnvelopeRegistry,
)

from sciplot_core.readiness.evidence import (
    _evidence_strength,
    _evidence_limitations,
    _resolved_manifest_path,
)


def build_validated_envelope_registry(
    acceptance_summary_path: Path,
) -> ValidatedEnvelopeRegistry:
    summary_path = acceptance_summary_path.expanduser().resolve()
    if not summary_path.is_file():
        raise FileNotFoundError(
            f"Ready-rule acceptance summary not found: {summary_path}"
        )
    try:
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("Ready-rule acceptance summary is not valid JSON.") from exc
    if not isinstance(payload, dict):
        raise ValueError("Ready-rule acceptance summary must contain an object.")
    if payload.get("kind") != "sciplot_ready_rule_acceptance":
        raise ValueError("Not a SciPlot ready-rule acceptance summary.")
    acceptance_version = _required_int(
        payload.get("version"),
        "acceptance version",
        minimum=1,
    )
    if acceptance_version != READY_RULE_ACCEPTANCE_VERSION:
        raise ValueError(
            f"Unsupported acceptance version {acceptance_version}; "
            f"expected {READY_RULE_ACCEPTANCE_VERSION}."
        )
    if payload.get("state") != "ready":
        raise ValueError("Acceptance summary must have state=ready.")

    rules = tuple(iter_public_rules())
    rule_by_id = {rule.rule_id: rule for rule in rules}
    coverage = payload.get("coverage")
    if not isinstance(coverage, dict):
        raise ValueError("Acceptance coverage must be an object.")
    expected_count = len(rules)
    for key in (
        "ready_rule_count",
        "lifecycle_passed_count",
        "physical_size_passed_count",
        "real_data_lifecycle_passed_count",
    ):
        if coverage.get(key) != expected_count:
            raise ValueError(
                f"Acceptance coverage `{key}` must equal {expected_count}."
            )
    if coverage.get("lifecycle_complete") is not True:
        raise ValueError("Acceptance lifecycle coverage is incomplete.")
    if coverage.get("physical_size_complete") is not True:
        raise ValueError("Acceptance physical-size coverage is incomplete.")
    if coverage.get("instrument_shaped_gap_count") != 0:
        raise ValueError("Acceptance still contains instrument-shaped evidence gaps.")

    visual = payload.get("visual_review")
    if not isinstance(visual, dict):
        raise ValueError("Acceptance visual_review must be an object.")
    if visual.get("automated_status") != "passed":
        raise ValueError("Acceptance automated physical-artifact review did not pass.")
    if visual.get("manual_visual_status") != "passed":
        raise ValueError("Acceptance manual preview review was not approved.")

    matrix = payload.get("matrix")
    if not isinstance(matrix, list):
        raise ValueError("Acceptance matrix must be a list.")
    selected = payload.get("selected_rule_ids")
    if not isinstance(selected, list) or set(map(str, selected)) != set(rule_by_id):
        raise ValueError("Acceptance summary must select every current ready rule.")
    rows: dict[str, dict[str, Any]] = {}
    for row in matrix:
        if not isinstance(row, dict):
            raise ValueError("Acceptance matrix rows must be objects.")
        rule_id = _required_text(row.get("rule_id"), "acceptance rule_id")
        if rule_id in rows:
            raise ValueError(f"Duplicate acceptance row `{rule_id}`.")
        rows[rule_id] = row
    if set(rows) != set(rule_by_id):
        missing = sorted(set(rule_by_id) - set(rows))
        extra = sorted(set(rows) - set(rule_by_id))
        raise ValueError(
            "Acceptance matrix does not match current ready rules "
            f"(missing={missing}, extra={extra})."
        )

    acceptance_generated_at = _timestamp(
        payload.get("generated_at"),
        "acceptance generated_at",
    )
    entries: list[ValidatedRuleEnvelope] = []
    for rule in rules:
        row = rows[rule.rule_id]
        if row.get("semantic_family") != rule.semantic_family:
            raise ValueError(
                f"Acceptance semantic family drifted for `{rule.rule_id}`."
            )
        if row.get("template") != rule.template or row.get("recipe") != rule.recipe:
            raise ValueError(f"Acceptance render route drifted for `{rule.rule_id}`.")
        if row.get("rule_readiness") != "ready":
            raise ValueError(f"Acceptance rule `{rule.rule_id}` is not ready.")
        if row.get("lifecycle_status") != "passed":
            raise ValueError(f"Acceptance lifecycle failed for `{rule.rule_id}`.")
        checks = row.get("checks")
        if not isinstance(checks, dict):
            raise ValueError(f"Acceptance checks missing for `{rule.rule_id}`.")
        accepted_check_ids = tuple(
            sorted(
                str(check_id) for check_id, passed in checks.items() if passed is True
            )
        )
        if not REQUIRED_ACCEPTANCE_CHECKS.issubset(accepted_check_ids):
            missing = sorted(REQUIRED_ACCEPTANCE_CHECKS - set(accepted_check_ids))
            raise ValueError(
                f"Acceptance checks failed for `{rule.rule_id}`: {', '.join(missing)}"
            )
        if checks.get("validated_rule_contract_current") is not True:
            raise ValueError(
                f"Acceptance rule contract was not current for `{rule.rule_id}`."
            )
        artifact_review = row.get("artifact_review")
        if (
            not isinstance(artifact_review, dict)
            or artifact_review.get("status") != "passed"
        ):
            raise ValueError(
                f"Acceptance physical-size review failed for `{rule.rule_id}`."
            )
        evidence = row.get("evidence")
        if not isinstance(evidence, dict):
            raise ValueError(f"Acceptance evidence missing for `{rule.rule_id}`.")
        if evidence.get("real_data_evidence") is not True:
            raise ValueError(
                f"Acceptance evidence for `{rule.rule_id}` is not real data."
            )
        authorization = str(evidence.get("authorization_status") or "")
        if authorization not in AUTHORIZATION_READY:
            raise ValueError(
                f"Acceptance authorization is insufficient for `{rule.rule_id}`."
            )
        fixture_hash_status = str(evidence.get("fixture_hash_status") or "")
        if fixture_hash_status not in FIXTURE_HASH_ACCEPTED:
            raise ValueError(
                f"Acceptance fixture hash is insufficient for `{rule.rule_id}`."
            )

        manifest_path = _resolved_manifest_path(
            row.get("manifest"),
            acceptance_root=summary_path.parent,
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest_semantic = (
            manifest.get("semantic") if isinstance(manifest, dict) else None
        )
        if not isinstance(manifest_semantic, dict):
            raise ValueError(
                f"Acceptance manifest semantic is missing for `{rule.rule_id}`."
            )
        accepted_semantic_contract = semantic_contract_sha256(manifest_semantic)
        current_semantic_contract = rule_semantic_contract_sha256(rule)
        current_contract = rule_contract_sha256(rule)
        if accepted_semantic_contract != current_semantic_contract:
            raise ValueError(
                f"Accepted semantic contract drifted for `{rule.rule_id}`."
            )
        if row.get("rule_contract_sha256") != current_contract:
            raise ValueError(f"Acceptance rule contract drifted for `{rule.rule_id}`.")
        if row.get("accepted_rule_contract_sha256") != current_contract:
            raise ValueError(
                f"Accepted full rule contract drifted for `{rule.rule_id}`."
            )
        if row.get("semantic_contract_sha256") != current_semantic_contract:
            raise ValueError(
                f"Acceptance semantic contract drifted for `{rule.rule_id}`."
            )
        if row.get("accepted_semantic_contract_sha256") != accepted_semantic_contract:
            raise ValueError(
                f"Accepted manifest semantic hash was not preserved for `{rule.rule_id}`."
            )

        entries.append(
            ValidatedRuleEnvelope(
                rule_id=rule.rule_id,
                semantic_family=rule.semantic_family,
                contract_sha256=current_contract,
                semantic_contract_sha256=current_semantic_contract,
                accepted_manifest_sha256=file_sha256(manifest_path),
                acceptance_generated_at=acceptance_generated_at,
                evidence_tier=_required_text(
                    evidence.get("tier"),
                    f"{rule.rule_id} evidence tier",
                ),
                evidence_strength=_evidence_strength(evidence),
                real_data_evidence=True,
                authorization_status=authorization,
                fixture_hash_status=fixture_hash_status,
                fixture_tree_sha256=_required_hash(
                    evidence.get("fixture_tree_sha256"),
                    f"{rule.rule_id} fixture tree hash",
                ),
                source_hash_status=_required_text(
                    evidence.get("source_hash_status"),
                    f"{rule.rule_id} source hash status",
                ),
                registered_source_hash_count=_required_int(
                    evidence.get("registered_source_hash_count"),
                    f"{rule.rule_id} registered source hash count",
                ),
                unit_status=_required_text(
                    evidence.get("unit_status"),
                    f"{rule.rule_id} unit status",
                ),
                lifecycle_status="passed",
                physical_size_status="passed",
                accepted_check_ids=accepted_check_ids,
                limitations=_evidence_limitations(evidence),
            )
        )

    limitations = tuple(
        _required_text(value, "acceptance limitation", maximum=4096)
        for value in payload.get("limitations", [])
        if isinstance(value, str) and value.strip()
    )
    return ValidatedEnvelopeRegistry(
        generated_at=_now(),
        source_acceptance={
            "kind": "sciplot_ready_rule_acceptance",
            "version": acceptance_version,
            "generated_at": acceptance_generated_at,
            "summary_sha256": file_sha256(summary_path),
            "ready_rule_count": expected_count,
            "lifecycle_passed_count": coverage["lifecycle_passed_count"],
            "physical_size_passed_count": coverage["physical_size_passed_count"],
            "real_data_lifecycle_passed_count": coverage[
                "real_data_lifecycle_passed_count"
            ],
            "limitations": list(limitations),
        },
        entries=tuple(entries),
        limitations=(
            "A validated envelope proves the accepted deterministic rule/render "
            "contract and real-data lifecycle, not blanket journal compliance.",
            "Runtime input recognition, mapping, QA, exact-current export, and "
            "delivery must still pass for every new input.",
            "Automated acceptance and source certificates do not count as human "
            "Veusz-first daily-use validation.",
        ),
    )
