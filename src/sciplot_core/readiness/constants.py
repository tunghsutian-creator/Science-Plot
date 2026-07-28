"""Declare versioned validated-envelope states and schema field sets."""

from __future__ import annotations

import re

from sciplot_core._paths import PACKAGE_ROOT

VALIDATED_ENVELOPE_REGISTRY_KIND = "sciplot_validated_envelope_registry"


VALIDATED_ENVELOPE_REGISTRY_VERSION = 1


VALIDATED_ENVELOPE_EVALUATION_KIND = "sciplot_validated_envelope_evaluation"


VALIDATED_ENVELOPE_EVALUATION_VERSION = 2


VALIDATED_RENDER_REQUEST_CONTRACT_KIND = "sciplot_validated_render_request"


VALIDATED_RENDER_REQUEST_CONTRACT_VERSION = 1


VALIDATED_RENDER_REQUEST_POLICY_VERSION = 2


RULE_CONTRACT_VERSION = 4


READY_RULE_ACCEPTANCE_VERSION = 3


DEFAULT_VALIDATED_ENVELOPE_REGISTRY = PACKAGE_ROOT / "validated_envelopes.json"


INSIDE_VALIDATED_ENVELOPE = "inside_validated_envelope"


NEEDS_HUMAN_CONFIRMATION = "needs_human_confirmation"


NEEDS_RULE_REPAIR = "needs_rule_repair"


HIGH_CONFIDENCE_THRESHOLD = 80.0


MEDIUM_CONFIDENCE_THRESHOLD = 70.0


AUTHORIZATION_READY = frozenset(
    {
        "license_verified",
        "license_recorded",
        "user_authorized",
        "user_authorized_archive",
    }
)


FIXTURE_HASH_ACCEPTED = frozenset({"verified", "computed_unregistered"})


MAPPING_STATES = frozenset(
    {"auto", "confirmed", NEEDS_HUMAN_CONFIRMATION, NEEDS_RULE_REPAIR}
)


EVIDENCE_STRENGTHS = frozenset(
    {
        "registered_fixture_source_and_units",
        "registered_fixture_and_source",
        "verified_fixture",
        "computed_fixture_hash",
    }
)


REQUIRED_ACCEPTANCE_CHECKS = frozenset(
    {
        "semantic_rule_selected",
        "validated_rule_contract_current",
        "supported_templates_exercised",
        "vsz_reopen_export",
        "manual_edit_preserved",
        "canonical_pdf_tiff_pair",
        "qa_passed",
        "delivery_complete",
        "provenance_complete",
    }
)


_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")


_SEMANTIC_CONTRACT_FIELDS = (
    "rule_id",
    "semantic_family",
    "recommended_recipe",
    "template",
    "presentation_contract",
    "render_options",
    "rule_readiness",
    "axis_plan",
    "unit_plan",
    "analysis_plan",
    "available_metrics",
    "experiment_recommendation",
    "rule_priority",
)


_RECOGNITION_CONTRACT_FIELDS = (
    "keywords",
    "path_keywords",
    "column_aliases",
    "vendor_models",
    "experiment_families",
)


_EVALUATION_FIELDS = frozenset(
    {
        "kind",
        "version",
        "state",
        "ready_without_ai",
        "rule_id",
        "semantic_family",
        "current_contract_sha256",
        "certified_contract_sha256",
        "presented_semantic_contract_sha256",
        "current_semantic_contract_sha256",
        "certified_semantic_contract_sha256",
        "presented_render_request_sha256",
        "request_policy_version",
        "request_contract_current",
        "contract_current",
        "mapping_state",
        "confidence",
        "repair_reasons",
        "confirmation_reasons",
        "accepted_evidence",
        "authority",
    }
)


_EVALUATION_EVIDENCE_FIELDS = frozenset(
    {
        "tier",
        "strength",
        "authorization_status",
        "fixture_hash_status",
        "source_hash_status",
        "unit_status",
        "acceptance_generated_at",
        "accepted_manifest_sha256",
        "limitations",
    }
)


_EVALUATION_AUTHORITY_FIELDS = frozenset(
    {
        "provider_ready_flags_are_ignored",
        "current_rule_contract_must_match_acceptance",
        "render_request_must_match_versioned_policy",
        "new_input_mapping_and_qa_still_required",
    }
)


_RENDER_REQUEST_PACKAGE_FIELDS = frozenset(
    {
        "kind",
        "version",
        "path",
        "rule_id",
        "recipe",
        "template",
        "exports",
        "render_engine",
        "figure_size",
        "render_options",
        "split_policy",
        "series_order",
        "explicit_render_option_keys",
    }
)


_RENDER_REQUEST_CONTRACT_FIELDS = frozenset(
    {
        "kind",
        "version",
        "policy_version",
        "rule_id",
        "route",
        "requested_recipe",
        "effective_recipe",
        "requested_template",
        "effective_template",
        "exports",
        "render_engine",
        "figure_size",
        "render_options",
        "split_policy",
        "series_order",
        "explicit_render_option_keys",
    }
)
