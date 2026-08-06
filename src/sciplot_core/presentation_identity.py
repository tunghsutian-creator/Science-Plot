"""Resolve and validate the selected presentation independently of semantics."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from typing import Any

from sciplot_core.materials_rules.models import SemanticRule
from sciplot_core.materials_rules.catalog import resolve_rule_template
from sciplot_core.style_contract.template_validation import (
    validate_veusz_template_id,
)


PRESENTATION_IDENTITY_KIND = "sciplot_selected_presentation_identity"
PRESENTATION_IDENTITY_VERSION = 1


@dataclass(frozen=True, slots=True)
class SelectedPresentationIdentity:
    """The rule/template pair selected for one concrete plot request."""

    rule_id: str | None
    template: str

    def __post_init__(self) -> None:
        if self.rule_id is not None and (
            not isinstance(self.rule_id, str) or not self.rule_id.strip()
        ):
            raise ValueError("presentation identity rule_id must be non-empty text.")
        if not isinstance(self.template, str) or not self.template.strip():
            raise ValueError("presentation identity template must be non-empty text.")
        object.__setattr__(
            self,
            "rule_id",
            self.rule_id.strip() if self.rule_id is not None else None,
        )
        object.__setattr__(self, "template", self.template.strip())

    def to_payload(self) -> dict[str, Any]:
        return {
            "kind": PRESENTATION_IDENTITY_KIND,
            "version": PRESENTATION_IDENTITY_VERSION,
            "rule_id": self.rule_id,
            "template": self.template,
        }

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, Any],
    ) -> SelectedPresentationIdentity:
        if not isinstance(payload, Mapping):
            raise ValueError("presentation identity must be an object.")
        if payload.get("kind") != PRESENTATION_IDENTITY_KIND:
            raise ValueError("presentation identity kind is unsupported.")
        if (
            type(payload.get("version")) is not int
            or payload["version"] != PRESENTATION_IDENTITY_VERSION
        ):
            raise ValueError("presentation identity version is unsupported.")
        if set(payload) != {"kind", "version", "rule_id", "template"}:
            raise ValueError("presentation identity fields are unsupported.")
        rule_id = payload.get("rule_id")
        if rule_id is not None and not isinstance(rule_id, str):
            raise ValueError("presentation identity rule_id must be text or null.")
        template = payload.get("template")
        if not isinstance(template, str):
            raise ValueError("presentation identity template must be text.")
        return cls(rule_id=rule_id, template=template)


def resolve_selected_presentation_identity(
    request: Mapping[str, Any],
    *,
    current_rule: SemanticRule | None,
) -> SelectedPresentationIdentity:
    """Resolve one strict identity without consulting recognition history."""

    raw_rule_id = request.get("rule_id")
    if raw_rule_id is not None and not isinstance(raw_rule_id, str):
        raise ValueError(
            "presentation_identity_invalid: request rule_id must be text when present."
        )
    request_rule_id = (
        raw_rule_id.strip() or None if isinstance(raw_rule_id, str) else None
    )
    if (
        current_rule is not None
        and request_rule_id is not None
        and request_rule_id != current_rule.rule_id
    ):
        raise ValueError(
            "presentation_identity_mismatch: canonical request rule_id does not "
            "match the resolved current rule."
        )

    requested_template: str | None = None
    if "template" in request:
        raw_template = request["template"]
        if not isinstance(raw_template, str) or not raw_template.strip():
            raise ValueError(
                "presentation_identity_invalid: request template must be "
                "non-empty text when present."
            )
        requested_template = raw_template.strip()

    if current_rule is not None:
        selected_template = resolve_rule_template(
            current_rule,
            requested_template,
        )
        rule_id = current_rule.rule_id
    else:
        selected_template = validate_veusz_template_id(requested_template or "curve")
        rule_id = request_rule_id
    return SelectedPresentationIdentity(
        rule_id=rule_id,
        template=selected_template,
    )


def project_selected_presentation_to_request(
    request: MutableMapping[str, Any],
    identity: SelectedPresentationIdentity,
) -> bool:
    """Materialize the selected template and synchronize its Study Model view."""

    changed = request.get("template") != identity.template
    request["template"] = identity.template
    study_model = request.get("study_model")
    if not isinstance(study_model, dict):
        return changed
    experiment = study_model.get("experiment")
    if not isinstance(experiment, dict):
        return changed
    if (
        experiment.get("template") != identity.template
        or experiment.get("chart") != identity.template
    ):
        experiment["template"] = identity.template
        experiment["chart"] = identity.template
        changed = True
    return changed


def require_selected_presentation_payload(
    value: object,
    *,
    expected: SelectedPresentationIdentity,
    source: str,
) -> None:
    """Reject a malformed or different persisted presentation projection."""

    if not isinstance(value, Mapping):
        raise RuntimeError(
            f"presentation_identity_mismatch: {source} does not contain a valid "
            "selected presentation identity."
        )
    try:
        actual = SelectedPresentationIdentity.from_payload(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            f"presentation_identity_mismatch: {source} does not contain a valid "
            "selected presentation identity."
        ) from exc
    if actual != expected:
        raise RuntimeError(
            f"presentation_identity_mismatch: {source} does not match the "
            "canonical selected presentation identity."
        )


def require_selected_template(
    value: object,
    *,
    expected: SelectedPresentationIdentity,
    source: str,
) -> None:
    """Reject a legacy template projection that differs from the identity."""

    if not isinstance(value, str) or value.strip() != expected.template:
        raise RuntimeError(
            f"presentation_identity_mismatch: {source} template does not match "
            "the canonical selected presentation identity."
        )
