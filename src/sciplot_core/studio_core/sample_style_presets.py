"""Portable, explicitly applied sample styles; no data or scientific settings."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import Any

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.json_io import atomic_write_json
from sciplot_core.studio_core.annotation_schema import AnnotationOperationError, validate_operation_batch
from sciplot_core.studio_core.document_edit_policy import SAMPLE_STYLE_FIELDS
from sciplot_core.studio_core.document_edit_state import audit_edited_document, new_preview_directory
from sciplot_core.studio_core.project_query import inspect_project, resolve_project_figure
from sciplot_core.studio_core.project_query_paths import canonical_path
from sciplot_core.studio_core.sample_style import sample_style_targets


def _selected_samples(spec: dict[str, Any], samples: list[str] | None) -> list[str]:
    targets = {item["sample"]: item for item in sample_style_targets(spec)}
    selected = list(targets) if samples is None else samples
    if (not isinstance(selected, list) or not 1 <= len(selected) <= 100
            or not all(isinstance(sample, str) and sample.strip() for sample in selected)
            or len(set(selected)) != len(selected)):
        raise AnnotationOperationError("invalid_preset_samples", "Choose 1–100 unique exact ordinary-curve sample labels.")
    for sample in selected:
        if sample not in targets or not targets[sample]["unique"]:
            raise AnnotationOperationError("ambiguous_preset_sample", f"No unique ordinary curve for sample {sample!r}; inspect sample_styles.")
    return selected


def capture_sample_style_preset(
    project: Path, *, output_dir: Path, figure_id: str | None = None,
    samples: list[str] | None = None,
) -> dict[str, Any]:
    selected = resolve_project_figure(project, figure_id)
    query = inspect_project(project, figure_id=selected["figure_id"])
    figure = query["selected_figure"]
    document, spec_path = Path(figure["document"]), Path(figure["spec"])
    raw = spec_path.read_bytes()
    if sha256(raw).hexdigest() != figure["spec_sha256"]:
        raise AnnotationOperationError("stale_revision", "The sample mapping changed; inspect again.")
    labels = _selected_samples(json.loads(raw), samples)
    targets = {item["sample"]: item for item in figure["sample_styles"]}
    styles = []
    for label in labels:
        path = targets[label]["object_paths"][0]
        fields = {item["setting_path"]: item["current_value"]
                  for item in figure["objects"][path]["editable_fields"]}
        style = {}
        for key, suffix in SAMPLE_STYLE_FIELDS.items():
            setting = path + "/" + suffix
            if setting not in fields:
                raise AnnotationOperationError("unsupported_preset_style", f"The source does not advertise {setting}.")
            style[key] = fields[setting]
        styles.append({"sample": label, "style": style})
    validate_operation_batch([{"op": "set_sample_style", "samples": [item["sample"]], "style": item["style"]}
                              for item in styles])
    audit = audit_edited_document(document, spec_path)
    current = resolve_project_figure(project, figure["figure_id"])
    if (current["document_sha256"] != figure["document_sha256"]
            or current["spec_sha256"] != figure["spec_sha256"]):
        raise AnnotationOperationError("stale_revision", "The source figure changed while capturing its styles.")
    preset = {"kind": "sciplot_sample_style_preset", "version": 1, "styles": styles,
              "origin": {"project": query["project"], "figure_id": figure["figure_id"],
                         "document_sha256": figure["document_sha256"], "spec_sha256": figure["spec_sha256"]}}
    output = new_preview_directory(Path(query["project"]), output_dir)
    path = output / "sample-styles.json"
    atomic_write_json(path, preset)
    return {"kind": "sciplot_sample_style_preset_result", "version": 1, "status": "saved",
            "preset": str(path), "preset_sha256": file_sha256(path), "samples": labels,
            "styles": styles, "origin": preset["origin"], "scientific_audit": audit,
            "scope": "Ordinary sample color and line width; color also follows bound direct labels and markers. No data, axes, fonts or annotation content.",
            "ready_to_use": None, "readiness_evaluated": False}


def _load_preset(path: Path, expected_sha256: str) -> dict[str, dict[str, Any]]:
    path = canonical_path(path)
    if path.stat().st_size > 1024 * 1024:
        raise AnnotationOperationError("invalid_style_preset", "The sample style preset exceeds 1 MiB.")
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != expected_sha256:
        raise AnnotationOperationError("style_preset_changed", "The style preset changed; use its reviewed current fingerprint.")
    value = json.loads(raw)
    if (not isinstance(value, dict) or set(value) != {"kind", "version", "styles", "origin"}
            or value["kind"] != "sciplot_sample_style_preset" or type(value["version"]) is not int
            or value["version"] != 1 or not isinstance(value["origin"], dict)
            or not isinstance(value["styles"], list) or not 1 <= len(value["styles"]) <= 100):
        raise AnnotationOperationError("invalid_style_preset", "Expected a version 1 sample style preset.")
    styles = {}
    for item in value["styles"]:
        if (not isinstance(item, dict) or set(item) != {"sample", "style"}
                or not isinstance(item["sample"], str) or not item["sample"].strip()
                or item["sample"] in styles):
            raise AnnotationOperationError("invalid_style_preset", "Preset samples must be unique exact labels.")
        validate_operation_batch([{"op": "set_sample_style", "samples": [item["sample"]], "style": item["style"]}])
        styles[item["sample"]] = dict(item["style"])
    return styles


def expand_style_presets(spec: dict[str, Any], operations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Freeze matched preferences into ordinary operations before signing a review."""
    expanded = []
    for operation in operations:
        if operation["op"] != "apply_sample_style_preset":
            expanded.append(operation)
            continue
        styles = _load_preset(Path(operation["preset"]), operation["expected_preset_sha256"])
        labels = _selected_samples(spec, operation.get("samples"))
        missing = [label for label in labels if label not in styles]
        if missing:
            raise AnnotationOperationError("preset_samples_missing", f"Preset has no styles for {missing!r}; select an explicit covered subset or capture another preset.")
        expanded.extend({"op": "set_sample_style", "samples": [label], "style": styles[label]} for label in labels)
    return expanded
