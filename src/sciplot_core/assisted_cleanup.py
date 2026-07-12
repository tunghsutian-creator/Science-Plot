from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sciplot_core._utils import json_safe, safe_filename, unique_path
from sciplot_core.operation_modes import assisted_cleanup_mode_payload

CLEANUP_REQUEST_FILENAME = "assisted_cleanup_request.json"
CLEANUP_RESULT_FILENAME = "cleanup_result.json"

_CLEANUP_REQUEST_PATCH_KEYS = {
    "column_confirmations",
    "recipe",
    "render_options",
    "replicate_mode",
    "rule_id",
    "series_order",
    "template",
    "y_metric",
}


def _timestamp() -> str:
    return datetime.now(UTC).isoformat()


def _path_payload(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    exists = resolved.exists()
    if resolved.is_file():
        kind = "file"
    elif resolved.is_dir():
        kind = "directory"
    else:
        kind = "missing"
    return {
        "path": str(resolved),
        "exists": exists,
        "kind": kind,
    }


def _confidence_payload(score: float | int | None) -> dict[str, Any]:
    if score is None:
        return {"score": None, "band": "unknown"}
    bounded = max(0.0, min(1.0, float(score)))
    if bounded >= 0.8:
        band = "high"
    elif bounded >= 0.6:
        band = "medium"
    else:
        band = "low"
    return {"score": bounded, "band": band}


def build_cleanup_request(
    *,
    input_path: str | Path,
    output_dir: str | Path,
    reason: str | None = None,
    semantic: dict[str, Any] | None = None,
    request: dict[str, Any] | None = None,
    intervention_request: str | Path | dict[str, Any] | None = None,
    provider: str = "codex",
) -> dict[str, Any]:
    category = reason or "input_cleanup_or_rule_repair"
    payload: dict[str, Any] = {
        "kind": "sciplot_assisted_cleanup_request",
        "version": 1,
        "created_at": _timestamp(),
        "operation_mode": assisted_cleanup_mode_payload(reason=category, provider=provider),
        "reason": category,
        "provider": provider,
        "raw_input": _path_payload(input_path),
        "output_dir": str(Path(output_dir).expanduser().resolve()),
        "semantic": json_safe(semantic or {}),
        "request": json_safe(request or {}),
        "required_result": {
            "filename": CLEANUP_RESULT_FILENAME,
            "mode_transition": "automatic_after_codex_or_assistant_result",
            "user_switch_required": False,
            "minimum_fields": [
                "cleaned_data",
                "mapping_proposal",
                "confidence",
                "human_confirmation",
            ],
            "raw_data_policy": "preserve_raw_inputs",
            "confirmation_required_before_render": True,
            "human_review_required_before_final_render": True,
        },
    }
    if intervention_request is not None:
        payload["intervention_request"] = (
            json_safe(intervention_request)
            if isinstance(intervention_request, dict)
            else str(Path(intervention_request).expanduser().resolve())
        )
    return payload


def write_cleanup_request(
    output_dir: str | Path,
    *,
    input_path: str | Path,
    reason: str | None = None,
    semantic: dict[str, Any] | None = None,
    request: dict[str, Any] | None = None,
    intervention_request: str | Path | dict[str, Any] | None = None,
    provider: str = "codex",
) -> dict[str, Any]:
    output_path = Path(output_dir).expanduser().resolve()
    output_path.mkdir(parents=True, exist_ok=True)
    payload = build_cleanup_request(
        input_path=input_path,
        output_dir=output_path,
        reason=reason,
        semantic=semantic,
        request=request,
        intervention_request=intervention_request,
        provider=provider,
    )
    request_path = output_path / CLEANUP_REQUEST_FILENAME
    payload["cleanup_request"] = str(request_path)
    request_path.write_text(json.dumps(json_safe(payload), indent=2, ensure_ascii=False), encoding="utf-8")
    return payload


def build_cleanup_result(
    *,
    cleaned_data: str | Path,
    mapping_proposal: dict[str, Any] | None = None,
    confidence: float | int | None = None,
    human_confirmed: bool = False,
    raw_inputs: list[str | Path] | None = None,
    notes: str | None = None,
    provider: str = "manual",
) -> dict[str, Any]:
    cleaned_payload = _path_payload(cleaned_data)
    confidence_payload = _confidence_payload(confidence)
    ready_for_normal_mode = bool(
        cleaned_payload["exists"]
        and human_confirmed
        and confidence_payload["score"] is not None
        and confidence_payload["score"] >= 0.6
    )
    return {
        "kind": "sciplot_assisted_cleanup_result",
        "version": 1,
        "created_at": _timestamp(),
        "operation_mode": assisted_cleanup_mode_payload(reason="cleanup_result", provider=provider),
        "provider": provider,
        "cleaned_data": cleaned_payload,
        "mapping_proposal": json_safe(mapping_proposal or {}),
        "confidence": confidence_payload,
        "human_confirmation": {
            "confirmed": bool(human_confirmed),
            "confirmed_at": _timestamp() if human_confirmed else None,
        },
        "raw_inputs": [_path_payload(path) for path in raw_inputs or []],
        "notes": notes or "",
        "ready_for_normal_mode": ready_for_normal_mode,
        "mode_transition": {
            "type": "automatic",
            "user_switch_required": False,
            "next_input": cleaned_payload["path"] if ready_for_normal_mode else None,
        },
        "next_step": (
            "SciPlot can use cleaned_data.path as the next normal input after review."
            if ready_for_normal_mode
            else "Review the cleaned data and mapping before final rendering."
        ),
    }


def write_cleanup_result(
    output_dir: str | Path,
    *,
    cleaned_data: str | Path,
    mapping_proposal: dict[str, Any] | None = None,
    confidence: float | int | None = None,
    human_confirmed: bool = False,
    raw_inputs: list[str | Path] | None = None,
    notes: str | None = None,
    provider: str = "manual",
) -> dict[str, Any]:
    output_path = Path(output_dir).expanduser().resolve()
    output_path.mkdir(parents=True, exist_ok=True)
    result_path = output_path / CLEANUP_RESULT_FILENAME
    payload = build_cleanup_result(
        cleaned_data=cleaned_data,
        mapping_proposal=mapping_proposal,
        confidence=confidence,
        human_confirmed=human_confirmed,
        raw_inputs=raw_inputs,
        notes=notes,
        provider=provider,
    )
    payload["cleanup_result"] = str(result_path)
    result_path.write_text(json.dumps(json_safe(payload), indent=2, ensure_ascii=False), encoding="utf-8")
    return payload


def load_cleanup_result(path_or_dir: str | Path) -> dict[str, Any]:
    path = Path(path_or_dir).expanduser()
    if path.is_dir():
        path = path / CLEANUP_RESULT_FILENAME
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"No cleanup result found at {path}.")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Cleanup result must be a JSON object: {path}")
    return payload


def _preserve_cleaned_data(cleaned_data: Path, *, output_dir: Path, payload: dict[str, Any]) -> Path:
    previous = payload.get("consumption") if isinstance(payload.get("consumption"), dict) else {}
    previous_input = previous.get("effective_input")
    if isinstance(previous_input, str) and previous_input.strip():
        previous_path = Path(previous_input).expanduser()
        if previous_path.exists():
            return previous_path.resolve()

    if not cleaned_data.exists():
        raise FileNotFoundError(f"Confirmed cleaned data no longer exists: {cleaned_data}")

    preserved_root = output_dir / "cleanup" / "cleaned_data"
    preserved_root.mkdir(parents=True, exist_ok=True)
    if cleaned_data.is_relative_to(preserved_root):
        return cleaned_data.resolve()

    destination = unique_path(preserved_root, safe_filename(cleaned_data.name or "cleaned_data"))
    if cleaned_data.is_dir():
        shutil.copytree(cleaned_data, destination)
    else:
        shutil.copy2(cleaned_data, destination)
    return destination.resolve()


def _cleanup_request_patch(mapping_proposal: dict[str, Any]) -> dict[str, Any]:
    nested = mapping_proposal.get("request_patch")
    candidates = dict(nested) if isinstance(nested, dict) else {}
    for key in _CLEANUP_REQUEST_PATCH_KEYS:
        if key in mapping_proposal and key not in candidates:
            candidates[key] = mapping_proposal[key]
    return {key: json_safe(value) for key, value in candidates.items() if key in _CLEANUP_REQUEST_PATCH_KEYS}


def consume_ready_cleanup_result(
    request: dict[str, Any],
    *,
    output_dir: str | Path,
    request_path: str | Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Apply a confirmed cleanup result to a deterministic rerun request.

    The cleaned input is copied under ``output/cleanup`` before managed run
    artifacts are cleared. This keeps the reviewed cleanup result and the exact
    consumed data stable across retries.
    """

    output_path = Path(output_dir).expanduser().resolve()
    result_path = output_path / CLEANUP_RESULT_FILENAME
    if not result_path.exists():
        return dict(request), None

    payload = load_cleanup_result(result_path)
    if payload.get("ready_for_normal_mode") is not True:
        return dict(request), None

    cleaned = payload.get("cleaned_data") if isinstance(payload.get("cleaned_data"), dict) else {}
    cleaned_value = cleaned.get("path")
    if not isinstance(cleaned_value, str) or not cleaned_value.strip():
        raise ValueError("A ready cleanup result must define cleaned_data.path.")
    cleaned_path = Path(cleaned_value).expanduser().resolve()

    preserved_input = _preserve_cleaned_data(cleaned_path, output_dir=output_path, payload=payload)
    mapping = payload.get("mapping_proposal") if isinstance(payload.get("mapping_proposal"), dict) else {}
    request_patch = _cleanup_request_patch(mapping)
    effective_request = dict(request)
    for key, value in request_patch.items():
        if key == "render_options" and isinstance(value, dict):
            current = effective_request.get("render_options")
            effective_request["render_options"] = {
                **(current if isinstance(current, dict) else {}),
                **value,
            }
        else:
            effective_request[key] = value
    original_input = effective_request.get("input")
    effective_request["input"] = str(preserved_input)
    effective_request["cleanup_result"] = str(result_path)
    effective_request["cleanup_mapping_proposal"] = json_safe(mapping)

    application = {
        "kind": "sciplot_cleanup_application",
        "version": 1,
        "status": "applied_to_request",
        "applied_at": _timestamp(),
        "cleanup_result": str(result_path),
        "request_path": str(Path(request_path).expanduser().resolve()) if request_path is not None else None,
        "original_input": str(original_input or ""),
        "cleaned_data_source": str(cleaned_path),
        "effective_input": str(preserved_input),
        "mapping_proposal": json_safe(mapping),
        "request_patch": json_safe(request_patch),
        "raw_inputs_preserved": True,
    }
    payload["consumption"] = application
    result_path.write_text(json.dumps(json_safe(payload), indent=2, ensure_ascii=False), encoding="utf-8")
    return effective_request, application


__all__ = [
    "CLEANUP_REQUEST_FILENAME",
    "CLEANUP_RESULT_FILENAME",
    "build_cleanup_request",
    "build_cleanup_result",
    "consume_ready_cleanup_result",
    "load_cleanup_result",
    "write_cleanup_request",
    "write_cleanup_result",
]
