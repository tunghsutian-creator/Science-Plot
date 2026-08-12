"""Validated-envelope readiness API and compatibility facade."""

from __future__ import annotations

from sciplot_core.readiness.constants import (  # noqa: F401
    VALIDATED_ENVELOPE_REGISTRY_KIND,
    VALIDATED_ENVELOPE_REGISTRY_VERSION,
    VALIDATED_ENVELOPE_EVALUATION_KIND,
    VALIDATED_ENVELOPE_EVALUATION_VERSION,
    VALIDATED_RENDER_REQUEST_CONTRACT_KIND,
    VALIDATED_RENDER_REQUEST_CONTRACT_VERSION,
    VALIDATED_RENDER_REQUEST_POLICY_VERSION,
    RULE_CONTRACT_VERSION,
    READY_RULE_ACCEPTANCE_VERSION,
    DEFAULT_VALIDATED_ENVELOPE_REGISTRY,
    INSIDE_VALIDATED_ENVELOPE,
    NEEDS_HUMAN_CONFIRMATION,
    NEEDS_RULE_REPAIR,
    HIGH_CONFIDENCE_THRESHOLD,
    MEDIUM_CONFIDENCE_THRESHOLD,
    AUTHORIZATION_READY,
    FIXTURE_HASH_ACCEPTED,
    MAPPING_STATES,
    EVIDENCE_STRENGTHS,
    REQUIRED_ACCEPTANCE_CHECKS,
    _HASH_PATTERN,
    _SEMANTIC_CONTRACT_FIELDS,
    _RECOGNITION_CONTRACT_FIELDS,
    _EVALUATION_FIELDS,
    _EVALUATION_EVIDENCE_FIELDS,
    _EVALUATION_AUTHORITY_FIELDS,
    _RENDER_REQUEST_PACKAGE_FIELDS,
    _RENDER_REQUEST_CONTRACT_FIELDS,
)
from sciplot_core.readiness.validation import (  # noqa: F401
    _now,
    _required_text,
    _required_bool,
    _required_int,
    _required_hash,
    _timestamp,
    _closed_object,
    _text_list,
    _canonical_sha256,
)
from sciplot_core.readiness.semantic_contract import (  # noqa: F401
    semantic_contract_payload,
    _certified_render_option_baseline,
)
from sciplot_core.readiness.render_request_contract import (  # noqa: F401
    validated_render_request_policy_payload,
    _render_request_route,
    render_request_contract_payload,
    _render_request_policy_evaluation,
)
from sciplot_core.readiness.rule_contract import (  # noqa: F401
    RuleContractHashes,
    rule_contract_payload,
    rule_contract_hashes,
    semantic_contract_sha256,
    rule_contract_sha256,
    rule_semantic_contract_sha256,
)
from sciplot_core.readiness.rule_certification import (  # noqa: F401
    CurrentCertifiedRuleContractSnapshot,
    RuleCertificationStatus,
    current_certified_rule_contract_snapshot,
)
from sciplot_core.readiness.envelope_model import (  # noqa: F401
    ValidatedRuleEnvelope,
)
from sciplot_core.readiness.registry_model import (  # noqa: F401
    ValidatedEnvelopeRegistry,
)
from sciplot_core.readiness.registry_io import (  # noqa: F401
    load_validated_envelope_registry,
    write_validated_envelope_registry,
)
from sciplot_core.readiness.evidence import (  # noqa: F401
    _evidence_strength,
    _evidence_limitations,
    _resolved_manifest_path,
)
from sciplot_core.readiness.registry_build import (  # noqa: F401
    build_validated_envelope_registry,
)
from sciplot_core.readiness.registry_merge import (  # noqa: F401
    merge_validated_envelope_registry,
)
from sciplot_core.readiness.status import (  # noqa: F401
    validated_envelope_status,
)
from sciplot_core.readiness.evaluation_readiness import (  # noqa: F401
    _confidence,
    validated_envelope_evaluation_ready,
)
from sciplot_core.readiness.evaluation import (  # noqa: F401
    evaluate_validated_envelope,
)

__all__ = [
    "AUTHORIZATION_READY",
    "DEFAULT_VALIDATED_ENVELOPE_REGISTRY",
    "EVIDENCE_STRENGTHS",
    "HIGH_CONFIDENCE_THRESHOLD",
    "INSIDE_VALIDATED_ENVELOPE",
    "MEDIUM_CONFIDENCE_THRESHOLD",
    "NEEDS_HUMAN_CONFIRMATION",
    "NEEDS_RULE_REPAIR",
    "READY_RULE_ACCEPTANCE_VERSION",
    "REQUIRED_ACCEPTANCE_CHECKS",
    "RULE_CONTRACT_VERSION",
    "CurrentCertifiedRuleContractSnapshot",
    "RuleCertificationStatus",
    "RuleContractHashes",
    "VALIDATED_ENVELOPE_EVALUATION_KIND",
    "VALIDATED_ENVELOPE_EVALUATION_VERSION",
    "VALIDATED_ENVELOPE_REGISTRY_KIND",
    "VALIDATED_ENVELOPE_REGISTRY_VERSION",
    "VALIDATED_RENDER_REQUEST_CONTRACT_KIND",
    "VALIDATED_RENDER_REQUEST_CONTRACT_VERSION",
    "VALIDATED_RENDER_REQUEST_POLICY_VERSION",
    "ValidatedEnvelopeRegistry",
    "ValidatedRuleEnvelope",
    "build_validated_envelope_registry",
    "evaluate_validated_envelope",
    "load_validated_envelope_registry",
    "merge_validated_envelope_registry",
    "render_request_contract_payload",
    "rule_contract_payload",
    "rule_contract_hashes",
    "rule_contract_sha256",
    "rule_semantic_contract_sha256",
    "semantic_contract_payload",
    "semantic_contract_sha256",
    "validated_envelope_evaluation_ready",
    "validated_envelope_status",
    "validated_render_request_policy_payload",
    "current_certified_rule_contract_snapshot",
    "write_validated_envelope_registry",
]
