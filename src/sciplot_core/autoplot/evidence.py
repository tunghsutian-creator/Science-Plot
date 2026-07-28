"""Load and expose the persisted evidence consumed by an autoplot summary."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sciplot_core.automation_states import is_automation_state


def _json_object(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _read_json_object_if_exists(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return _json_object(payload)


def _truthy_path(value: object) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return Path(value).expanduser()


def _state(value: object) -> str:
    return str(value or "").strip()


@dataclass(frozen=True)
class AutoplotRunEvidence:
    """Typed aggregate over reported, persisted, and manifest run evidence."""

    reported_result: dict[str, Any]
    run_output: Path
    project_dir: Path
    status_path: Path
    manifest_path: Path
    reported_one_step: dict[str, Any]
    persisted_status: dict[str, Any]
    manifest: dict[str, Any]
    manifest_one_step: dict[str, Any]

    @classmethod
    def load(cls, reported_result: dict[str, Any]) -> AutoplotRunEvidence:
        run_output = _truthy_path(reported_result.get("run_output")) or Path(".")
        project_dir = (
            _truthy_path(reported_result.get("project_dir")) or run_output.parent
        )
        status_path = run_output / "one_step_status.json"
        manifest_path = run_output / "manifest.json"
        manifest = _read_json_object_if_exists(manifest_path)
        return cls(
            reported_result=reported_result,
            run_output=run_output,
            project_dir=project_dir,
            status_path=status_path,
            manifest_path=manifest_path,
            reported_one_step=_json_object(reported_result.get("one_step")),
            persisted_status=_read_json_object_if_exists(status_path),
            manifest=manifest,
            manifest_one_step=_json_object(manifest.get("one_step")),
        )

    @property
    def reported_state(self) -> str:
        return _state(self.reported_result.get("status"))

    @property
    def reported_payload_state(self) -> str:
        return _state(self.reported_one_step.get("state"))

    @property
    def persisted_state(self) -> str:
        return _state(self.persisted_status.get("state"))

    @property
    def manifest_one_step_state(self) -> str:
        return _state(self.manifest_one_step.get("state"))

    @property
    def manifest_state(self) -> str:
        return _state(self.manifest.get("state"))

    @property
    def status_valid(self) -> bool:
        return is_automation_state(self.persisted_state)

    @property
    def manifest_valid(self) -> bool:
        return bool(
            self.manifest.get("kind") == "sciplot_run"
            and is_automation_state(self.manifest_one_step_state)
            and is_automation_state(self.manifest_state)
        )

    @property
    def effective_one_step(self) -> dict[str, Any]:
        if self.status_valid:
            return self.persisted_status
        return self.reported_one_step or self.manifest_one_step

    @property
    def preparation_state_claims(self) -> tuple[str, ...]:
        return tuple(
            state
            for state in (
                self.reported_payload_state,
                self.persisted_state,
                self.manifest_one_step_state,
            )
            if state
        )

    @property
    def publish_state_claims(self) -> tuple[str, ...]:
        return tuple(
            state for state in (self.reported_state, self.manifest_state) if state
        )

    def _one_step_payload(self, key: str) -> dict[str, Any]:
        payload = _json_object(self.effective_one_step.get(key))
        if payload:
            return payload
        return _json_object(self.manifest_one_step.get(key))

    @property
    def delivery_package(self) -> dict[str, Any]:
        payload = _json_object(self.effective_one_step.get("delivery_package"))
        return payload or _json_object(self.manifest.get("delivery_package"))

    @property
    def manifest_delivery_package(self) -> dict[str, Any]:
        return _json_object(self.manifest.get("delivery_package"))

    @property
    def figure_qa(self) -> dict[str, Any]:
        return self._one_step_payload("figure_qa_report")

    @property
    def intervention(self) -> dict[str, Any]:
        return self._one_step_payload("intervention_package")

    @property
    def validated_envelope(self) -> dict[str, Any]:
        return self._one_step_payload("validated_envelope")

    @property
    def render_request(self) -> dict[str, Any]:
        return _json_object(self.effective_one_step.get("render_request"))

    def route_package(self) -> dict[str, Any]:
        source = _json_object(self.effective_one_step.get("source_package"))
        mapping = _json_object(self.effective_one_step.get("mapping_package"))
        semantic = _json_object(self.manifest.get("semantic"))
        result = _json_object(self.manifest.get("result"))
        return {
            "mode": "one_step",
            "source_kind": source.get("source_kind") or "unknown",
            "semantic_family": mapping.get("semantic_family")
            or semantic.get("semantic_family")
            or "unknown",
            "rule_id": mapping.get("rule_id") or semantic.get("rule_id"),
            "confidence_band": source.get("confidence_band")
            or mapping.get("confidence_band")
            or "unknown",
            "recipe": self.render_request.get("recipe"),
            "template": self.render_request.get("template") or result.get("template"),
            "figure_size": self.render_request.get("figure_size"),
            "exports": self.render_request.get("exports") or [],
        }


__all__ = ["AutoplotRunEvidence"]
