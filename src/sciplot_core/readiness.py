from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sciplot_core._utils import file_sha256, json_safe
from sciplot_core._utils import atomic_write_json
from sciplot_core.materials_rules import (
    SemanticRule,
    get_rule,
    iter_public_rules,
    resolve_rule_template,
    semantic_payload_from_rule,
)
from sciplot_core.policy import (
    DEFAULT_EXPORT_FORMATS_POLICY,
    DEFAULT_FIGURE_SIZE,
    FIGURE_SIZE_PRESETS,
    RENDER_OPTION_KEYS,
    SUPPORTED_EXPORT_FORMATS,
    VALIDATED_VISUAL_OVERRIDE_KEYS,
    canonical_export_format,
)

VALIDATED_ENVELOPE_REGISTRY_KIND = "sciplot_validated_envelope_registry"
VALIDATED_ENVELOPE_REGISTRY_VERSION = 1
VALIDATED_ENVELOPE_EVALUATION_KIND = "sciplot_validated_envelope_evaluation"
VALIDATED_ENVELOPE_EVALUATION_VERSION = 2
VALIDATED_RENDER_REQUEST_CONTRACT_KIND = "sciplot_validated_render_request"
VALIDATED_RENDER_REQUEST_CONTRACT_VERSION = 1
VALIDATED_RENDER_REQUEST_POLICY_VERSION = 2
RULE_CONTRACT_VERSION = 4
READY_RULE_ACCEPTANCE_VERSION = 3
DEFAULT_VALIDATED_ENVELOPE_REGISTRY = Path(__file__).with_name(
    "validated_envelopes.json"
)

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


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _required_text(
    value: object,
    label: str,
    *,
    maximum: int = 2048,
) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be text.")
    text = value.strip()
    if not text:
        raise ValueError(f"{label} cannot be empty.")
    if len(text) > maximum:
        raise ValueError(f"{label} exceeds {maximum} characters.")
    return text


def _required_bool(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{label} must be a JSON boolean.")
    return value


def _required_int(value: object, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an integer.")
    if value < minimum:
        raise ValueError(f"{label} must be at least {minimum}.")
    return value


def _required_hash(value: object, label: str) -> str:
    text = _required_text(value, label, maximum=64).casefold()
    if not _HASH_PATTERN.fullmatch(text):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest.")
    return text


def _timestamp(value: object, label: str) -> str:
    text = _required_text(value, label, maximum=128)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO-8601 timestamp.") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must include a timezone.")
    return text


def _closed_object(
    payload: object,
    *,
    label: str,
    expected: frozenset[str],
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be an object.")
    keys = {str(key) for key in payload}
    missing = sorted(expected - keys)
    extra = sorted(keys - expected)
    if missing or extra:
        detail = []
        if missing:
            detail.append(f"missing: {', '.join(missing)}")
        if extra:
            detail.append(f"unsupported: {', '.join(extra)}")
        raise ValueError(f"{label} has invalid fields ({'; '.join(detail)}).")
    return {str(key): value for key, value in payload.items()}


def _text_list(
    value: object,
    label: str,
    *,
    maximum_items: int = 128,
    maximum_text: int = 2048,
) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list.")
    if len(value) > maximum_items:
        raise ValueError(f"{label} exceeds {maximum_items} items.")
    return tuple(
        _required_text(item, f"{label}[{index}]", maximum=maximum_text)
        for index, item in enumerate(value)
    )


def _canonical_sha256(payload: object) -> str:
    encoded = json.dumps(
        json_safe(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def semantic_contract_payload(semantic: dict[str, Any]) -> dict[str, Any]:
    """Return the deterministic rule/render contract accepted by a lifecycle."""

    if not isinstance(semantic, dict):
        raise ValueError("semantic contract source must be an object.")
    payload: dict[str, Any] = {}
    for field in _SEMANTIC_CONTRACT_FIELDS:
        if field not in semantic:
            raise ValueError(f"semantic contract is missing `{field}`.")
        registered_field = {
            "axis_plan": "registered_axis_plan",
            "unit_plan": "registered_unit_plan",
        }.get(field)
        value = (
            semantic.get(registered_field)
            if registered_field
            and isinstance(semantic.get(registered_field), dict)
            else semantic[field]
        )
        payload[field] = deepcopy(json_safe(value))
    if not isinstance(payload["rule_id"], str) or not payload["rule_id"].strip():
        raise ValueError("semantic contract rule_id must be non-empty text.")
    if (
        not isinstance(payload["semantic_family"], str)
        or not payload["semantic_family"].strip()
    ):
        raise ValueError("semantic contract semantic_family must be non-empty text.")
    if not isinstance(payload["template"], str) or not payload["template"].strip():
        raise ValueError("semantic contract template must be non-empty text.")
    if not isinstance(payload["render_options"], dict):
        raise ValueError("semantic contract render_options must be an object.")
    for field in (
        "axis_plan",
        "unit_plan",
        "experiment_recommendation",
    ):
        if not isinstance(payload[field], dict):
            raise ValueError(f"semantic contract {field} must be an object.")
    for field in ("analysis_plan", "available_metrics"):
        if not isinstance(payload[field], list):
            raise ValueError(f"semantic contract {field} must be a list.")
    return payload


def _certified_render_option_baseline(rule: SemanticRule) -> dict[str, Any]:
    semantic = semantic_payload_from_rule(
        rule,
        confidence=100.0,
        reason=f"Validated render-request baseline for `{rule.rule_id}`.",
    )
    baseline = deepcopy(semantic_contract_payload(semantic)["render_options"])
    axis_plan = semantic.get("axis_plan")
    if isinstance(axis_plan, dict):
        for axis_name in ("x", "y"):
            axis = axis_plan.get(axis_name)
            display_label = (
                axis.get("display_label") if isinstance(axis, dict) else None
            )
            if isinstance(display_label, str) and display_label.strip():
                baseline.setdefault(
                    f"{axis_name}_label_override",
                    display_label.strip(),
                )
    return baseline


def validated_render_request_policy_payload(
    rule: SemanticRule | str,
) -> dict[str, Any]:
    """Return the closed runtime-variation policy bound into a rule certificate."""

    resolved = get_rule(rule) if isinstance(rule, str) else rule
    unknown_visual_keys = VALIDATED_VISUAL_OVERRIDE_KEYS - RENDER_OPTION_KEYS
    if unknown_visual_keys:
        raise ValueError(
            "Validated visual override policy contains unknown render options: "
            + ", ".join(sorted(unknown_visual_keys))
        )
    exact_keys = RENDER_OPTION_KEYS - VALIDATED_VISUAL_OVERRIDE_KEYS
    return {
        "version": VALIDATED_RENDER_REQUEST_POLICY_VERSION,
        "allowed_routes": ["auto"],
        "template_policy": "explicit_supported_template_or_default",
        "default_template": resolved.template,
        "supported_templates": list(resolved.presentation_templates),
        "effective_recipe": resolved.recipe,
        "required_exports": list(DEFAULT_EXPORT_FORMATS_POLICY),
        "allowed_exports": sorted(SUPPORTED_EXPORT_FORMATS),
        "figure_size_presets": list(FIGURE_SIZE_PRESETS),
        "split_policy": "empty_only",
        "visual_override_keys": sorted(VALIDATED_VISUAL_OVERRIDE_KEYS),
        "exact_certified_value_keys": sorted(exact_keys),
        "certified_axis_label_source": "semantic_axis_display_label_v1",
    }


def _render_request_route(
    *,
    requested_recipe: str | None,
    requested_template: str | None,
) -> str:
    if requested_recipe == "auto" or (
        requested_recipe is None and requested_template is None
    ):
        return "auto"
    if requested_recipe is not None:
        return "recipe"
    return "render"


def render_request_contract_payload(
    rule: SemanticRule | str,
    render_request: dict[str, Any],
) -> dict[str, Any]:
    """Build the portable portion of the actual runtime render request."""

    resolved = get_rule(rule) if isinstance(rule, str) else rule
    requested_recipe = render_request.get("recipe")
    requested_template = render_request.get("template")
    route = _render_request_route(
        requested_recipe=(
            requested_recipe if isinstance(requested_recipe, str) else None
        ),
        requested_template=(
            requested_template if isinstance(requested_template, str) else None
        ),
    )
    effective_recipe = resolved.recipe if route == "auto" else requested_recipe
    effective_template = (
        resolve_rule_template(resolved, requested_template)
        if route == "auto"
        else requested_template
    )
    exports = render_request.get("exports")
    normalized_exports = (
        sorted(dict.fromkeys(str(item) for item in exports))
        if isinstance(exports, list)
        else []
    )
    explicit_keys = render_request.get("explicit_render_option_keys")
    normalized_explicit_keys = (
        sorted(dict.fromkeys(str(item) for item in explicit_keys))
        if isinstance(explicit_keys, list)
        else []
    )
    return {
        "kind": VALIDATED_RENDER_REQUEST_CONTRACT_KIND,
        "version": VALIDATED_RENDER_REQUEST_CONTRACT_VERSION,
        "policy_version": VALIDATED_RENDER_REQUEST_POLICY_VERSION,
        "rule_id": resolved.rule_id,
        "route": route,
        "requested_recipe": requested_recipe,
        "effective_recipe": effective_recipe,
        "requested_template": requested_template,
        "effective_template": effective_template,
        "exports": normalized_exports,
        "render_engine": render_request.get("render_engine"),
        "figure_size": render_request.get("figure_size"),
        "render_options": deepcopy(json_safe(render_request.get("render_options"))),
        "split_policy": deepcopy(json_safe(render_request.get("split_policy"))),
        "series_order": deepcopy(json_safe(render_request.get("series_order"))),
        "explicit_render_option_keys": normalized_explicit_keys,
    }
def _render_request_policy_evaluation(
    rule: SemanticRule,
    render_request: object,
) -> tuple[dict[str, Any] | None, list[str], list[str]]:
    repair_reasons: list[str] = []
    confirmation_reasons: list[str] = []
    try:
        package = _closed_object(
            render_request,
            label="render request package",
            expected=_RENDER_REQUEST_PACKAGE_FIELDS,
        )
    except ValueError:
        return None, ["render_request_contract_invalid"], []

    if (
        package.get("kind") != "sciplot_render_request"
        or isinstance(package.get("version"), bool)
        or not isinstance(package.get("version"), int)
        or package.get("version") != 1
    ):
        repair_reasons.append("render_request_package_contract_invalid")
    try:
        _required_text(package.get("path"), "render request path", maximum=8192)
    except ValueError:
        repair_reasons.append("render_request_path_invalid")

    presented_rule_id = package.get("rule_id")
    if presented_rule_id is not None:
        try:
            presented_rule_id = _required_text(
                presented_rule_id,
                "render request rule_id",
            )
        except ValueError:
            repair_reasons.append("render_request_rule_invalid")
        else:
            if presented_rule_id != rule.rule_id:
                repair_reasons.append("render_request_rule_mismatch")

    requested_recipe = package.get("recipe")
    if requested_recipe is not None:
        try:
            requested_recipe = _required_text(
                requested_recipe,
                "render request recipe",
            )
        except ValueError:
            repair_reasons.append("render_request_recipe_invalid")
            requested_recipe = None
    requested_template = package.get("template")
    if requested_template is not None:
        try:
            requested_template = _required_text(
                requested_template,
                "render request template",
            )
        except ValueError:
            repair_reasons.append("render_request_template_invalid")
            requested_template = None

    route = _render_request_route(
        requested_recipe=requested_recipe,
        requested_template=requested_template,
    )
    if route != "auto":
        confirmation_reasons.append("render_route_outside_validated_policy")
    if (
        requested_template is not None
        and requested_template not in rule.presentation_templates
    ):
        repair_reasons.append("render_template_unsupported_for_rule")
    if package.get("render_engine") != "veusz":
        repair_reasons.append("render_engine_contract_invalid")

    exports = package.get("exports")
    normalized_exports: list[str] = []
    if not isinstance(exports, list) or not exports:
        repair_reasons.append("render_exports_invalid")
    else:
        for index, value in enumerate(exports):
            try:
                export = _required_text(
                    value,
                    f"render export[{index}]",
                    maximum=32,
                ).casefold()
            except ValueError:
                repair_reasons.append("render_exports_invalid")
                continue
            try:
                normalized_exports.append(canonical_export_format(export))
            except ValueError:
                repair_reasons.append("render_export_unsupported")
        if len(set(normalized_exports)) != len(normalized_exports):
            repair_reasons.append("render_exports_not_unique")
        if not set(DEFAULT_EXPORT_FORMATS_POLICY).issubset(normalized_exports):
            repair_reasons.append("canonical_pdf_tiff_exports_missing")

    render_options = package.get("render_options")
    if not isinstance(render_options, dict):
        repair_reasons.append("render_options_contract_invalid")
        render_options = {}
    elif any(not isinstance(key, str) for key in render_options):
        repair_reasons.append("render_options_contract_invalid")
    else:
        unknown_keys = set(render_options) - RENDER_OPTION_KEYS
        if unknown_keys:
            repair_reasons.append("render_options_unsupported")
        effective_template = (
            requested_template
            if requested_template in rule.presentation_templates
            else rule.template
        )
        try:
            from sciplot_core.request_contract import normalize_render_options

            normalized_options = normalize_render_options(
                render_options,
                template=effective_template,
            )
        except ValueError:
            repair_reasons.append("render_options_contract_invalid")
        else:
            if json_safe(normalized_options) != json_safe(render_options):
                repair_reasons.append("render_options_not_canonical")

    figure_size = package.get("figure_size")
    expected_size = render_options.get("size") or DEFAULT_FIGURE_SIZE
    if (
        not isinstance(figure_size, str)
        or figure_size not in FIGURE_SIZE_PRESETS
        or figure_size != expected_size
    ):
        repair_reasons.append("render_figure_size_invalid")

    split_policy = package.get("split_policy")
    if not isinstance(split_policy, dict):
        repair_reasons.append("render_split_policy_invalid")
    elif split_policy:
        confirmation_reasons.append("render_split_policy_requires_confirmation")

    series_order = package.get("series_order")
    normalized_series_order: list[str] = []
    if not isinstance(series_order, list):
        repair_reasons.append("render_series_order_invalid")
    else:
        for index, value in enumerate(series_order):
            try:
                normalized_series_order.append(
                    _required_text(
                        value,
                        f"render series_order[{index}]",
                        maximum=512,
                    )
                )
            except ValueError:
                repair_reasons.append("render_series_order_invalid")
        if len(set(normalized_series_order)) != len(normalized_series_order):
            repair_reasons.append("render_series_order_not_unique")
    options_series_order = render_options.get("series_order")
    if (
        options_series_order is not None
        and json_safe(options_series_order) != normalized_series_order
    ):
        repair_reasons.append("render_series_order_binding_mismatch")

    explicit_keys = package.get("explicit_render_option_keys")
    if not isinstance(explicit_keys, list):
        repair_reasons.append("explicit_render_option_keys_invalid")
    else:
        normalized_explicit: list[str] = []
        for index, value in enumerate(explicit_keys):
            try:
                normalized_explicit.append(
                    _required_text(
                        value,
                        f"explicit render option[{index}]",
                        maximum=128,
                    )
                )
            except ValueError:
                repair_reasons.append("explicit_render_option_keys_invalid")
        if len(set(normalized_explicit)) != len(normalized_explicit):
            repair_reasons.append("explicit_render_option_keys_not_unique")
        if not set(normalized_explicit).issubset(render_options):
            repair_reasons.append("explicit_render_option_keys_unbound")

    certified_baseline = _certified_render_option_baseline(rule)
    for key, value in render_options.items():
        if key in VALIDATED_VISUAL_OVERRIDE_KEYS:
            continue
        if key not in certified_baseline or json_safe(value) != json_safe(
            certified_baseline[key]
        ):
            confirmation_reasons.append(f"render_option_requires_confirmation:{key}")

    try:
        contract = render_request_contract_payload(rule, package)
        _closed_object(
            contract,
            label="render request contract",
            expected=_RENDER_REQUEST_CONTRACT_FIELDS,
        )
    except ValueError:
        contract = None
        repair_reasons.append("render_request_contract_invalid")
    return (
        contract,
        list(dict.fromkeys(repair_reasons)),
        list(dict.fromkeys(confirmation_reasons)),
    )


def rule_contract_payload(rule: SemanticRule) -> dict[str, Any]:
    semantic = semantic_payload_from_rule(
        rule,
        confidence=100.0,
        reason=f"Validated-envelope contract for `{rule.rule_id}`.",
    )
    recognition = {
        field: deepcopy(json_safe(getattr(rule, field)))
        for field in _RECOGNITION_CONTRACT_FIELDS
    }
    for field, value in recognition.items():
        if not isinstance(value, list):
            raise ValueError(f"rule recognition contract {field} must be a list.")
    return {
        "version": RULE_CONTRACT_VERSION,
        "semantic": semantic_contract_payload(semantic),
        "recognition": recognition,
        "matcher": {
            "algorithm": "weighted_ready_rule_token_match",
            "version": 1,
            "automatic_scope": "ready_rules_only",
        },
        "render_request_policy": validated_render_request_policy_payload(rule),
    }


def semantic_contract_sha256(semantic: dict[str, Any]) -> str:
    return _canonical_sha256(semantic_contract_payload(semantic))


def rule_contract_sha256(rule: SemanticRule | str) -> str:
    resolved = get_rule(rule) if isinstance(rule, str) else rule
    return _canonical_sha256(rule_contract_payload(resolved))


def rule_semantic_contract_sha256(rule: SemanticRule | str) -> str:
    resolved = get_rule(rule) if isinstance(rule, str) else rule
    return _canonical_sha256(rule_contract_payload(resolved)["semantic"])


@dataclass(frozen=True)
class ValidatedRuleEnvelope:
    rule_id: str
    semantic_family: str
    contract_sha256: str
    semantic_contract_sha256: str
    accepted_manifest_sha256: str
    acceptance_generated_at: str
    evidence_tier: str
    evidence_strength: str
    real_data_evidence: bool
    authorization_status: str
    fixture_hash_status: str
    fixture_tree_sha256: str
    source_hash_status: str
    registered_source_hash_count: int
    unit_status: str
    lifecycle_status: str
    physical_size_status: str
    accepted_check_ids: tuple[str, ...]
    limitations: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "rule_id", _required_text(self.rule_id, "rule_id"))
        object.__setattr__(
            self,
            "semantic_family",
            _required_text(self.semantic_family, "semantic_family"),
        )
        object.__setattr__(
            self,
            "contract_sha256",
            _required_hash(self.contract_sha256, "contract_sha256"),
        )
        object.__setattr__(
            self,
            "semantic_contract_sha256",
            _required_hash(
                self.semantic_contract_sha256,
                "semantic_contract_sha256",
            ),
        )
        object.__setattr__(
            self,
            "accepted_manifest_sha256",
            _required_hash(
                self.accepted_manifest_sha256,
                "accepted_manifest_sha256",
            ),
        )
        object.__setattr__(
            self,
            "acceptance_generated_at",
            _timestamp(self.acceptance_generated_at, "acceptance_generated_at"),
        )
        object.__setattr__(
            self,
            "evidence_tier",
            _required_text(self.evidence_tier, "evidence_tier"),
        )
        strength = _required_text(self.evidence_strength, "evidence_strength")
        if strength not in EVIDENCE_STRENGTHS:
            raise ValueError(f"Unsupported evidence_strength `{strength}`.")
        object.__setattr__(self, "evidence_strength", strength)
        real_data_evidence = _required_bool(
            self.real_data_evidence,
            "real_data_evidence",
        )
        if not real_data_evidence:
            raise ValueError("Validated envelopes require real_data_evidence=true.")
        object.__setattr__(self, "real_data_evidence", real_data_evidence)
        authorization = _required_text(
            self.authorization_status,
            "authorization_status",
        )
        if authorization not in AUTHORIZATION_READY:
            raise ValueError(
                f"Envelope authorization_status is not accepted: `{authorization}`."
            )
        object.__setattr__(self, "authorization_status", authorization)
        fixture_status = _required_text(
            self.fixture_hash_status,
            "fixture_hash_status",
        )
        if fixture_status not in FIXTURE_HASH_ACCEPTED:
            raise ValueError(
                f"Envelope fixture_hash_status is not accepted: `{fixture_status}`."
            )
        object.__setattr__(self, "fixture_hash_status", fixture_status)
        object.__setattr__(
            self,
            "fixture_tree_sha256",
            _required_hash(self.fixture_tree_sha256, "fixture_tree_sha256"),
        )
        object.__setattr__(
            self,
            "source_hash_status",
            _required_text(self.source_hash_status, "source_hash_status"),
        )
        object.__setattr__(
            self,
            "registered_source_hash_count",
            _required_int(
                self.registered_source_hash_count,
                "registered_source_hash_count",
            ),
        )
        object.__setattr__(
            self,
            "unit_status",
            _required_text(self.unit_status, "unit_status"),
        )
        if self.lifecycle_status != "passed":
            raise ValueError("Validated envelopes require lifecycle_status=passed.")
        if self.physical_size_status != "passed":
            raise ValueError("Validated envelopes require physical_size_status=passed.")
        accepted_checks = tuple(
            _required_text(value, "accepted_check_id")
            for value in self.accepted_check_ids
        )
        if len(set(accepted_checks)) != len(accepted_checks):
            raise ValueError("accepted_check_ids must be unique.")
        if not REQUIRED_ACCEPTANCE_CHECKS.issubset(accepted_checks):
            missing = sorted(REQUIRED_ACCEPTANCE_CHECKS - set(accepted_checks))
            raise ValueError(
                "Validated envelope is missing acceptance checks: " + ", ".join(missing)
            )
        object.__setattr__(self, "accepted_check_ids", accepted_checks)
        object.__setattr__(
            self,
            "limitations",
            tuple(
                _required_text(value, "limitation", maximum=4096)
                for value in self.limitations
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "semantic_family": self.semantic_family,
            "contract_sha256": self.contract_sha256,
            "semantic_contract_sha256": self.semantic_contract_sha256,
            "accepted_manifest_sha256": self.accepted_manifest_sha256,
            "acceptance_generated_at": self.acceptance_generated_at,
            "evidence_tier": self.evidence_tier,
            "evidence_strength": self.evidence_strength,
            "real_data_evidence": self.real_data_evidence,
            "authorization_status": self.authorization_status,
            "fixture_hash_status": self.fixture_hash_status,
            "fixture_tree_sha256": self.fixture_tree_sha256,
            "source_hash_status": self.source_hash_status,
            "registered_source_hash_count": self.registered_source_hash_count,
            "unit_status": self.unit_status,
            "lifecycle_status": self.lifecycle_status,
            "physical_size_status": self.physical_size_status,
            "accepted_check_ids": list(self.accepted_check_ids),
            "limitations": list(self.limitations),
        }

    @classmethod
    def from_dict(cls, payload: object) -> ValidatedRuleEnvelope:
        parsed = _closed_object(
            payload,
            label="validated rule envelope",
            expected=frozenset(
                {
                    "rule_id",
                    "semantic_family",
                    "contract_sha256",
                    "semantic_contract_sha256",
                    "accepted_manifest_sha256",
                    "acceptance_generated_at",
                    "evidence_tier",
                    "evidence_strength",
                    "real_data_evidence",
                    "authorization_status",
                    "fixture_hash_status",
                    "fixture_tree_sha256",
                    "source_hash_status",
                    "registered_source_hash_count",
                    "unit_status",
                    "lifecycle_status",
                    "physical_size_status",
                    "accepted_check_ids",
                    "limitations",
                }
            ),
        )
        return cls(
            rule_id=parsed["rule_id"],
            semantic_family=parsed["semantic_family"],
            contract_sha256=parsed["contract_sha256"],
            semantic_contract_sha256=parsed["semantic_contract_sha256"],
            accepted_manifest_sha256=parsed["accepted_manifest_sha256"],
            acceptance_generated_at=parsed["acceptance_generated_at"],
            evidence_tier=parsed["evidence_tier"],
            evidence_strength=parsed["evidence_strength"],
            real_data_evidence=parsed["real_data_evidence"],
            authorization_status=parsed["authorization_status"],
            fixture_hash_status=parsed["fixture_hash_status"],
            fixture_tree_sha256=parsed["fixture_tree_sha256"],
            source_hash_status=parsed["source_hash_status"],
            registered_source_hash_count=parsed["registered_source_hash_count"],
            unit_status=parsed["unit_status"],
            lifecycle_status=parsed["lifecycle_status"],
            physical_size_status=parsed["physical_size_status"],
            accepted_check_ids=_text_list(
                parsed["accepted_check_ids"],
                "accepted_check_ids",
            ),
            limitations=_text_list(
                parsed["limitations"],
                "limitations",
                maximum_items=32,
                maximum_text=4096,
            ),
        )


@dataclass(frozen=True)
class ValidatedEnvelopeRegistry:
    generated_at: str
    source_acceptance: dict[str, Any]
    entries: tuple[ValidatedRuleEnvelope, ...]
    limitations: tuple[str, ...]
    kind: str = VALIDATED_ENVELOPE_REGISTRY_KIND
    version: int = VALIDATED_ENVELOPE_REGISTRY_VERSION

    def __post_init__(self) -> None:
        kind = _required_text(self.kind, "registry kind")
        if kind != VALIDATED_ENVELOPE_REGISTRY_KIND:
            raise ValueError("Not a SciPlot validated-envelope registry.")
        version = _required_int(self.version, "registry version", minimum=1)
        if version != VALIDATED_ENVELOPE_REGISTRY_VERSION:
            raise ValueError(
                f"Unsupported validated-envelope registry version {version}."
            )
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "version", version)
        object.__setattr__(
            self,
            "generated_at",
            _timestamp(self.generated_at, "registry generated_at"),
        )
        source = _closed_object(
            self.source_acceptance,
            label="source_acceptance",
            expected=frozenset(
                {
                    "kind",
                    "version",
                    "generated_at",
                    "summary_sha256",
                    "ready_rule_count",
                    "lifecycle_passed_count",
                    "physical_size_passed_count",
                    "real_data_lifecycle_passed_count",
                    "limitations",
                }
            ),
        )
        source["kind"] = _required_text(
            source["kind"],
            "source_acceptance kind",
        )
        if source["kind"] != "sciplot_ready_rule_acceptance":
            raise ValueError("source_acceptance kind is not supported.")
        source["version"] = _required_int(
            source["version"],
            "source_acceptance version",
            minimum=1,
        )
        if source["version"] != READY_RULE_ACCEPTANCE_VERSION:
            raise ValueError(
                "Unsupported source_acceptance version "
                f"{source['version']}; expected {READY_RULE_ACCEPTANCE_VERSION}."
            )
        source["generated_at"] = _timestamp(
            source["generated_at"],
            "source_acceptance generated_at",
        )
        source["summary_sha256"] = _required_hash(
            source["summary_sha256"],
            "source_acceptance summary_sha256",
        )
        for key in (
            "ready_rule_count",
            "lifecycle_passed_count",
            "physical_size_passed_count",
            "real_data_lifecycle_passed_count",
        ):
            source[key] = _required_int(source[key], f"source_acceptance {key}")
        source["limitations"] = list(
            _text_list(
                source["limitations"],
                "source_acceptance limitations",
                maximum_items=64,
                maximum_text=4096,
            )
        )
        object.__setattr__(self, "source_acceptance", source)
        entries = tuple(self.entries)
        ids = [entry.rule_id for entry in entries]
        if len(set(ids)) != len(ids):
            raise ValueError("Validated-envelope rule IDs must be unique.")
        for key in (
            "ready_rule_count",
            "lifecycle_passed_count",
            "physical_size_passed_count",
            "real_data_lifecycle_passed_count",
        ):
            if source[key] != len(entries):
                raise ValueError(
                    f"source_acceptance {key} must equal the envelope count."
                )
        object.__setattr__(
            self,
            "entries",
            tuple(sorted(entries, key=lambda item: item.rule_id)),
        )
        object.__setattr__(
            self,
            "limitations",
            tuple(
                _required_text(value, "registry limitation", maximum=4096)
                for value in self.limitations
            ),
        )

    def entry(self, rule_id: str) -> ValidatedRuleEnvelope | None:
        return next(
            (entry for entry in self.entries if entry.rule_id == rule_id),
            None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "version": self.version,
            "generated_at": self.generated_at,
            "source_acceptance": deepcopy(self.source_acceptance),
            "entries": [entry.to_dict() for entry in self.entries],
            "limitations": list(self.limitations),
        }

    @classmethod
    def from_dict(cls, payload: object) -> ValidatedEnvelopeRegistry:
        parsed = _closed_object(
            payload,
            label="validated-envelope registry",
            expected=frozenset(
                {
                    "kind",
                    "version",
                    "generated_at",
                    "source_acceptance",
                    "entries",
                    "limitations",
                }
            ),
        )
        if not isinstance(parsed["entries"], list):
            raise ValueError("validated-envelope entries must be a list.")
        if len(parsed["entries"]) > 512:
            raise ValueError("validated-envelope registry is too large.")
        return cls(
            kind=parsed["kind"],
            version=parsed["version"],
            generated_at=parsed["generated_at"],
            source_acceptance=parsed["source_acceptance"],
            entries=tuple(
                ValidatedRuleEnvelope.from_dict(entry) for entry in parsed["entries"]
            ),
            limitations=_text_list(
                parsed["limitations"],
                "registry limitations",
                maximum_items=64,
                maximum_text=4096,
            ),
        )


def load_validated_envelope_registry(
    path: Path | None = None,
) -> ValidatedEnvelopeRegistry:
    registry_path = (
        path.expanduser().resolve()
        if path is not None
        else DEFAULT_VALIDATED_ENVELOPE_REGISTRY
    )
    if not registry_path.is_file():
        raise FileNotFoundError(
            f"Validated-envelope registry not found: {registry_path}"
        )
    try:
        payload = json.loads(registry_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Validated-envelope registry is not valid JSON: {registry_path}"
        ) from exc
    return ValidatedEnvelopeRegistry.from_dict(payload)


def write_validated_envelope_registry(
    path: Path,
    registry: ValidatedEnvelopeRegistry,
) -> Path:
    return atomic_write_json(path.expanduser().resolve(), registry.to_dict())


def _evidence_strength(evidence: dict[str, Any]) -> str:
    fixture = str(evidence.get("fixture_hash_status") or "")
    source = str(evidence.get("source_hash_status") or "")
    units = str(evidence.get("unit_status") or "")
    if (
        fixture == "verified"
        and source == "registered"
        and units == "source_and_output_registered"
    ):
        return "registered_fixture_source_and_units"
    if fixture == "verified" and source == "registered":
        return "registered_fixture_and_source"
    if fixture == "verified":
        return "verified_fixture"
    return "computed_fixture_hash"


def _evidence_limitations(evidence: dict[str, Any]) -> tuple[str, ...]:
    limitations = [
        _required_text(value, "evidence limitation", maximum=4096)
        for value in evidence.get("limitations", [])
        if isinstance(value, str) and value.strip()
    ]
    if evidence.get("fixture_hash_status") == "computed_unregistered":
        limitations.append(
            "The accepted fixture hash was computed but was not registered in "
            "its provenance record."
        )
    if evidence.get("source_hash_status") != "registered":
        limitations.append(
            "The upstream source hash was not registered; the accepted fixture "
            "tree remains hash-bound."
        )
    if evidence.get("unit_status") == "canonical_contract_only":
        limitations.append(
            "Source-unit metadata was not registered; runtime parsing must still "
            "satisfy the rule's canonical axis contract."
        )
    return tuple(dict.fromkeys(limitations))


def _resolved_manifest_path(
    value: object,
    *,
    acceptance_root: Path,
) -> Path:
    text = _required_text(value, "acceptance manifest path", maximum=8192)
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = acceptance_root / path
    resolved = path.resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"Acceptance manifest not found: {resolved}")
    return resolved


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


def validated_envelope_status(
    registry: ValidatedEnvelopeRegistry | None = None,
    *,
    registry_path: Path | None = None,
) -> dict[str, Any]:
    resolved = registry or load_validated_envelope_registry(registry_path)
    current_rules = tuple(iter_public_rules())
    current_ids = {rule.rule_id for rule in current_rules}
    registered_ids = {entry.rule_id for entry in resolved.entries}
    records: list[dict[str, Any]] = []
    stale_ids: list[str] = []
    missing_ids: list[str] = []
    for rule in current_rules:
        entry = resolved.entry(rule.rule_id)
        current_hash = rule_contract_sha256(rule)
        current_semantic_hash = rule_semantic_contract_sha256(rule)
        if entry is None:
            status = "missing"
            certified_hash = None
            certified_semantic_hash = None
            evidence_strength = None
            limitations: list[str] = []
            missing_ids.append(rule.rule_id)
        else:
            certified_hash = entry.contract_sha256
            certified_semantic_hash = entry.semantic_contract_sha256
            status = (
                "current"
                if (
                    certified_hash == current_hash
                    and certified_semantic_hash == current_semantic_hash
                    and entry.semantic_family == rule.semantic_family
                )
                else "stale"
            )
            evidence_strength = entry.evidence_strength
            limitations = list(entry.limitations)
            if status == "stale":
                stale_ids.append(rule.rule_id)
        records.append(
            {
                "rule_id": rule.rule_id,
                "semantic_family": rule.semantic_family,
                "status": status,
                "current_contract_sha256": current_hash,
                "certified_contract_sha256": certified_hash,
                "current_semantic_contract_sha256": current_semantic_hash,
                "certified_semantic_contract_sha256": certified_semantic_hash,
                "evidence_strength": evidence_strength,
                "limitations": limitations,
            }
        )
    extra_ids = sorted(registered_ids - current_ids)
    ready = not stale_ids and not missing_ids and not extra_ids
    return {
        "kind": "sciplot_validated_envelope_status",
        "version": 1,
        "status": "ready" if ready else NEEDS_RULE_REPAIR,
        "ready_without_ai_rule_count": sum(
            record["status"] == "current" for record in records
        ),
        "current_ready_rule_count": len(current_rules),
        "missing_rule_ids": missing_ids,
        "stale_rule_ids": stale_ids,
        "extra_rule_ids": extra_ids,
        "source_acceptance": deepcopy(resolved.source_acceptance),
        "evidence_strength_counts": {
            strength: sum(record["evidence_strength"] == strength for record in records)
            for strength in sorted(EVIDENCE_STRENGTHS)
        },
        "records": records,
        "claims": {
            "current_rule_contracts_match_acceptance": ready,
            "real_data_lifecycle_certified": ready
            and len(resolved.entries) == len(current_rules)
            and all(entry.real_data_evidence for entry in resolved.entries),
            "journal_compliance_established": False,
            "human_daily_use_cutover_established": False,
            "human_daily_use_validation_established": False,
        },
        "limitations": list(resolved.limitations),
    }


def _confidence(payload: dict[str, Any]) -> float:
    value = payload.get("confidence")
    if isinstance(value, bool) or not isinstance(value, int | float):
        return 0.0
    result = float(value)
    return result if 0.0 <= result <= 100.0 else 0.0


def validated_envelope_evaluation_ready(
    payload: object,
    *,
    render_request: object,
) -> bool:
    """Return true only for a complete, strictly typed ready evaluation."""

    if not isinstance(payload, dict) or set(payload) != _EVALUATION_FIELDS:
        return False
    if payload.get("kind") != VALIDATED_ENVELOPE_EVALUATION_KIND:
        return False
    version = payload.get("version")
    if (
        isinstance(version, bool)
        or not isinstance(version, int)
        or version != VALIDATED_ENVELOPE_EVALUATION_VERSION
    ):
        return False
    if payload.get("state") != INSIDE_VALIDATED_ENVELOPE:
        return False
    if payload.get("ready_without_ai") is not True:
        return False
    if payload.get("contract_current") is not True:
        return False
    if payload.get("request_contract_current") is not True:
        return False
    if payload.get("repair_reasons") != []:
        return False
    if payload.get("confirmation_reasons") != []:
        return False

    try:
        evaluation_rule_id = _required_text(
            payload.get("rule_id"),
            "evaluation rule_id",
        )
        evaluation_semantic_family = _required_text(
            payload.get("semantic_family"),
            "evaluation semantic_family",
        )
        current_contract = _required_hash(
            payload.get("current_contract_sha256"),
            "evaluation current_contract_sha256",
        )
        certified_contract = _required_hash(
            payload.get("certified_contract_sha256"),
            "evaluation certified_contract_sha256",
        )
        presented_semantic = _required_hash(
            payload.get("presented_semantic_contract_sha256"),
            "evaluation presented_semantic_contract_sha256",
        )
        current_semantic = _required_hash(
            payload.get("current_semantic_contract_sha256"),
            "evaluation current_semantic_contract_sha256",
        )
        certified_semantic = _required_hash(
            payload.get("certified_semantic_contract_sha256"),
            "evaluation certified_semantic_contract_sha256",
        )
        presented_render_request = _required_hash(
            payload.get("presented_render_request_sha256"),
            "evaluation presented_render_request_sha256",
        )
        request_policy_version = _required_int(
            payload.get("request_policy_version"),
            "evaluation request_policy_version",
            minimum=1,
        )
        mapping_state = _required_text(
            payload.get("mapping_state"),
            "evaluation mapping_state",
        )
    except ValueError:
        return False
    if current_contract != certified_contract:
        return False
    if not (presented_semantic == current_semantic == certified_semantic):
        return False
    if request_policy_version != VALIDATED_RENDER_REQUEST_POLICY_VERSION:
        return False
    if mapping_state not in {"auto", "confirmed"}:
        return False
    try:
        current_rule = get_rule(evaluation_rule_id)
        registry = load_validated_envelope_registry()
    except (FileNotFoundError, ValueError):
        return False
    registry_entry = registry.entry(evaluation_rule_id)
    if (
        current_rule.fixture_status != "ready"
        or current_rule.semantic_family != evaluation_semantic_family
        or registry_entry is None
        or registry_entry.semantic_family != evaluation_semantic_family
        or current_contract != rule_contract_sha256(current_rule)
        or current_semantic != rule_semantic_contract_sha256(current_rule)
        or registry_entry.contract_sha256 != current_contract
        or registry_entry.semantic_contract_sha256 != current_semantic
    ):
        return False
    request_contract, request_repairs, request_confirmations = (
        _render_request_policy_evaluation(current_rule, render_request)
    )
    if (
        request_contract is None
        or request_repairs
        or request_confirmations
        or _canonical_sha256(request_contract) != presented_render_request
    ):
        return False

    confidence_value = payload.get("confidence")
    if isinstance(confidence_value, bool) or not isinstance(
        confidence_value,
        int | float,
    ):
        return False
    confidence = float(confidence_value)
    if not 0.0 <= confidence <= 100.0:
        return False
    if mapping_state == "auto" and confidence < HIGH_CONFIDENCE_THRESHOLD:
        return False
    if mapping_state == "confirmed" and confidence < MEDIUM_CONFIDENCE_THRESHOLD:
        return False

    evidence = payload.get("accepted_evidence")
    if not isinstance(evidence, dict) or set(evidence) != _EVALUATION_EVIDENCE_FIELDS:
        return False
    try:
        _required_text(evidence.get("tier"), "evaluation evidence tier")
        strength = _required_text(
            evidence.get("strength"),
            "evaluation evidence strength",
        )
        authorization = _required_text(
            evidence.get("authorization_status"),
            "evaluation authorization_status",
        )
        fixture_status = _required_text(
            evidence.get("fixture_hash_status"),
            "evaluation fixture_hash_status",
        )
        _required_text(
            evidence.get("source_hash_status"),
            "evaluation source_hash_status",
        )
        _required_text(evidence.get("unit_status"), "evaluation unit_status")
        _timestamp(
            evidence.get("acceptance_generated_at"),
            "evaluation acceptance_generated_at",
        )
        _required_hash(
            evidence.get("accepted_manifest_sha256"),
            "evaluation accepted_manifest_sha256",
        )
        _text_list(
            evidence.get("limitations"),
            "evaluation evidence limitations",
            maximum_items=32,
            maximum_text=4096,
        )
    except ValueError:
        return False
    if strength not in EVIDENCE_STRENGTHS:
        return False
    if authorization not in AUTHORIZATION_READY:
        return False
    if fixture_status not in FIXTURE_HASH_ACCEPTED:
        return False
    if (
        evidence["tier"] != registry_entry.evidence_tier
        or strength != registry_entry.evidence_strength
        or authorization != registry_entry.authorization_status
        or fixture_status != registry_entry.fixture_hash_status
        or evidence["source_hash_status"] != registry_entry.source_hash_status
        or evidence["unit_status"] != registry_entry.unit_status
        or evidence["acceptance_generated_at"] != registry_entry.acceptance_generated_at
        or evidence["accepted_manifest_sha256"]
        != registry_entry.accepted_manifest_sha256
        or evidence["limitations"] != list(registry_entry.limitations)
    ):
        return False

    authority = payload.get("authority")
    if (
        not isinstance(authority, dict)
        or set(authority) != _EVALUATION_AUTHORITY_FIELDS
    ):
        return False
    return all(authority[field] is True for field in _EVALUATION_AUTHORITY_FIELDS)


def evaluate_validated_envelope(
    *,
    semantic: dict[str, Any],
    source_package: dict[str, Any],
    mapping_package: dict[str, Any],
    render_request: dict[str, Any],
    registry: ValidatedEnvelopeRegistry | None = None,
) -> dict[str, Any]:
    """Evaluate a new input without trusting user- or provider-authored ready flags."""

    resolved = registry or load_validated_envelope_registry()
    rule_id = str(semantic.get("rule_id") or "").strip()
    mapping_rule_id = str(mapping_package.get("rule_id") or "").strip()
    source_rule_id = str(source_package.get("rule_id") or "").strip()
    repair_reasons: list[str] = []
    confirmation_reasons: list[str] = []

    rule: SemanticRule | None = None
    entry: ValidatedRuleEnvelope | None = None
    current_contract: str | None = None
    current_semantic_contract: str | None = None
    presented_semantic_contract: str | None = None
    presented_render_request: str | None = None
    request_contract_current = False
    if not rule_id:
        repair_reasons.append("semantic_rule_missing")
    else:
        try:
            rule = get_rule(rule_id)
        except ValueError:
            repair_reasons.append("semantic_rule_unknown")
        if rule is not None:
            current_contract = rule_contract_sha256(rule)
            current_semantic_contract = rule_semantic_contract_sha256(rule)
            entry = resolved.entry(rule.rule_id)
            if entry is None:
                repair_reasons.append("validated_envelope_missing")
            elif entry.contract_sha256 != current_contract:
                repair_reasons.append("validated_envelope_stale")
            if rule.fixture_status != "ready":
                repair_reasons.append("semantic_rule_not_ready")
            if semantic.get("semantic_family") != rule.semantic_family:
                repair_reasons.append("semantic_family_mismatch")
            if entry is not None and entry.semantic_family != rule.semantic_family:
                repair_reasons.append("certified_semantic_family_mismatch")
            if (
                entry is not None
                and entry.semantic_contract_sha256 != current_semantic_contract
            ):
                repair_reasons.append("validated_semantic_contract_stale")
            try:
                presented_semantic_contract = semantic_contract_sha256(semantic)
            except ValueError:
                repair_reasons.append("semantic_contract_invalid")
            else:
                if presented_semantic_contract != current_semantic_contract:
                    repair_reasons.append("semantic_contract_mismatch")

            request_contract, request_repairs, request_confirmations = (
                _render_request_policy_evaluation(rule, render_request)
            )
            repair_reasons.extend(request_repairs)
            confirmation_reasons.extend(request_confirmations)
            if request_contract is not None:
                presented_render_request = _canonical_sha256(request_contract)
                request_contract_current = not (
                    request_repairs or request_confirmations
                )

    if not mapping_rule_id or mapping_rule_id != rule_id:
        repair_reasons.append("mapping_rule_mismatch")
    if not source_rule_id or source_rule_id != rule_id:
        repair_reasons.append("source_rule_mismatch")
    if (
        source_package.get("kind") != "sciplot_source_package"
        or isinstance(source_package.get("version"), bool)
        or not isinstance(source_package.get("version"), int)
        or source_package.get("version") != 1
    ):
        repair_reasons.append("source_package_contract_invalid")
    if (
        mapping_package.get("kind") != "sciplot_mapping_package"
        or isinstance(mapping_package.get("version"), bool)
        or not isinstance(mapping_package.get("version"), int)
        or mapping_package.get("version") != 1
    ):
        repair_reasons.append("mapping_package_contract_invalid")
    semantic_family = str(semantic.get("semantic_family") or "").strip()
    if str(mapping_package.get("semantic_family") or "").strip() != semantic_family:
        repair_reasons.append("mapping_semantic_family_mismatch")
    if str(source_package.get("instrument_family") or "").strip() != semantic_family:
        repair_reasons.append("source_semantic_family_mismatch")
    if str(mapping_package.get("experiment_type") or "").strip() != rule_id:
        repair_reasons.append("mapping_experiment_type_mismatch")
    if semantic.get("needs_ai_intervention") is True:
        repair_reasons.append("semantic_requires_intervention")
    if semantic.get("production_status") != "ready":
        repair_reasons.append("semantic_production_not_ready")
    if semantic.get("rule_readiness") != "ready":
        repair_reasons.append("semantic_readiness_not_ready")

    mapping_state = str(mapping_package.get("status") or "")
    if mapping_state not in MAPPING_STATES:
        repair_reasons.append("mapping_state_invalid")
    elif mapping_state == NEEDS_RULE_REPAIR:
        repair_reasons.append("mapping_requires_rule_repair")
    elif mapping_state == NEEDS_HUMAN_CONFIRMATION:
        confirmation_reasons.append("mapping_requires_confirmation")

    semantic_confidence = _confidence(semantic)
    mapping_confidence = _confidence(mapping_package)
    source_confidence = _confidence(source_package)
    if (
        max(
            abs(semantic_confidence - mapping_confidence),
            abs(semantic_confidence - source_confidence),
        )
        > 1e-9
    ):
        repair_reasons.append("confidence_binding_mismatch")
    if semantic_confidence < MEDIUM_CONFIDENCE_THRESHOLD:
        repair_reasons.append("semantic_confidence_below_supported_floor")
    elif (
        semantic_confidence < HIGH_CONFIDENCE_THRESHOLD and mapping_state != "confirmed"
    ):
        confirmation_reasons.append("semantic_match_requires_confirmation")

    file_count = source_package.get("file_count")
    if (
        isinstance(file_count, bool)
        or not isinstance(file_count, int)
        or file_count < 1
    ):
        repair_reasons.append("source_package_empty")
    if source_package.get("source_kind") not in {"file", "directory"}:
        repair_reasons.append("source_kind_invalid")

    if repair_reasons:
        state = NEEDS_RULE_REPAIR
    elif confirmation_reasons:
        state = NEEDS_HUMAN_CONFIRMATION
    else:
        state = INSIDE_VALIDATED_ENVELOPE
    return {
        "kind": VALIDATED_ENVELOPE_EVALUATION_KIND,
        "version": VALIDATED_ENVELOPE_EVALUATION_VERSION,
        "state": state,
        "ready_without_ai": state == INSIDE_VALIDATED_ENVELOPE,
        "rule_id": rule_id or None,
        "semantic_family": semantic.get("semantic_family"),
        "current_contract_sha256": current_contract,
        "certified_contract_sha256": (
            entry.contract_sha256 if entry is not None else None
        ),
        "presented_semantic_contract_sha256": presented_semantic_contract,
        "current_semantic_contract_sha256": current_semantic_contract,
        "certified_semantic_contract_sha256": (
            entry.semantic_contract_sha256 if entry is not None else None
        ),
        "presented_render_request_sha256": presented_render_request,
        "request_policy_version": VALIDATED_RENDER_REQUEST_POLICY_VERSION,
        "request_contract_current": request_contract_current,
        "contract_current": bool(
            current_contract
            and entry is not None
            and current_contract == entry.contract_sha256
            and current_semantic_contract == entry.semantic_contract_sha256
            and presented_semantic_contract == current_semantic_contract
            and request_contract_current
        ),
        "mapping_state": mapping_state or None,
        "confidence": semantic_confidence,
        "repair_reasons": list(dict.fromkeys(repair_reasons)),
        "confirmation_reasons": list(dict.fromkeys(confirmation_reasons)),
        "accepted_evidence": (
            {
                "tier": entry.evidence_tier,
                "strength": entry.evidence_strength,
                "authorization_status": entry.authorization_status,
                "fixture_hash_status": entry.fixture_hash_status,
                "source_hash_status": entry.source_hash_status,
                "unit_status": entry.unit_status,
                "acceptance_generated_at": entry.acceptance_generated_at,
                "accepted_manifest_sha256": entry.accepted_manifest_sha256,
                "limitations": list(entry.limitations),
            }
            if entry is not None
            else None
        ),
        "authority": {
            "provider_ready_flags_are_ignored": True,
            "current_rule_contract_must_match_acceptance": True,
            "render_request_must_match_versioned_policy": True,
            "new_input_mapping_and_qa_still_required": True,
        },
    }


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
    "render_request_contract_payload",
    "rule_contract_payload",
    "rule_contract_sha256",
    "rule_semantic_contract_sha256",
    "semantic_contract_payload",
    "semantic_contract_sha256",
    "validated_envelope_evaluation_ready",
    "validated_envelope_status",
    "validated_render_request_policy_payload",
    "write_validated_envelope_registry",
]
