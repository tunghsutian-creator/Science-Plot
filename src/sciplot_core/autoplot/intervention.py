"""Extract intervention and validated-envelope status."""

from __future__ import annotations

from typing import Any


def _intervention_package(
    one_step: dict[str, Any], manifest: dict[str, Any]
) -> dict[str, Any]:
    intervention = (
        one_step.get("intervention_package")
        if isinstance(one_step.get("intervention_package"), dict)
        else {}
    )
    if intervention:
        return intervention
    manifest_one_step = (
        manifest.get("one_step") if isinstance(manifest.get("one_step"), dict) else {}
    )
    intervention = (
        manifest_one_step.get("intervention_package")
        if isinstance(manifest_one_step.get("intervention_package"), dict)
        else {}
    )
    return intervention


def _validated_envelope(
    one_step: dict[str, Any],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    envelope = (
        one_step.get("validated_envelope")
        if isinstance(one_step.get("validated_envelope"), dict)
        else {}
    )
    if envelope:
        return envelope
    manifest_one_step = (
        manifest.get("one_step") if isinstance(manifest.get("one_step"), dict) else {}
    )
    envelope = manifest_one_step.get("validated_envelope")
    return envelope if isinstance(envelope, dict) else {}
