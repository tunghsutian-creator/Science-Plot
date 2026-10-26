"""Re-read original replicate evidence before claiming audited n disclosure."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.source_coverage.file_snapshots import _assert_snapshot_current, _stable_file_snapshot


def verify_replicate_summary_request(request: dict[str, Any]) -> dict[str, Any] | None:
    """Close every disclosure field against the exact original, never a prepared CSV."""
    if request.get("summary_statistic") != "mean_sample_sd_n" and "replicate_summary_disclosure" not in request:
        return None
    categorical = "categorical_binding" in request
    if request.get("summary_statistic") != "mean_sample_sd_n" or request.get("template") != "bar" or (not categorical and request.get("rule_id") != "impact_metric"):
        raise ValueError("Replicate disclosure has no compatible closed original-source contract.")
    declaration = request.get("replicate_summary_disclosure")
    if not isinstance(declaration, dict):
        raise ValueError("Replicate disclosure requires a complete original-source declaration.")
    value = declaration.get("original_source")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Replicate disclosure requires its explicit original source input, independent of prepared tables.")
    source = Path(value).expanduser().resolve()
    expected_file_sha256 = None
    if categorical:
        from sciplot_core.mapping_contract.categorical import validate_categorical_context

        validate_categorical_context(request)
        if Path(str(request.get("input", ""))).expanduser().resolve() != source:
            raise ValueError("Categorical disclosure source differs from its bound original table input.")
        expected_file_sha256 = request["categorical_binding"]["source_sha256"]
    snapshot = (_stable_file_snapshot(source, label="original replicate disclosure source")
                if expected_file_sha256 is None else _stable_file_snapshot(
                    source, label="original replicate disclosure source", expected_sha256=expected_file_sha256))
    if categorical:
        from sciplot_core.categorical_disclosure import categorical_disclosure
        binding = request["categorical_binding"]
        if binding["mode"] != "mean_sample_sd_n":
            raise ValueError("Categorical valid-n disclosure requires its explicit replicate-summary mode.")
        disclosure = categorical_disclosure(source, binding, policy=declaration.get("missing_values"))
        if canonical_json_sha256(disclosure, allow_nan=False) != canonical_json_sha256(declaration, allow_nan=False):
            raise ValueError("Categorical disclosure differs from current original columns, rows, identities, units or missing cells.")
    else:
        from sciplot_core.semantic_sources.impact_replicate_disclosure import validate_replicate_disclosure

        disclosure = validate_replicate_disclosure(source, declaration)
    _assert_snapshot_current(snapshot, label="original replicate disclosure source", expected_sha256=snapshot["sha256"])
    return {"status": "passed", "original_source": str(source),
            "source_file_sha256": snapshot["sha256"], "source_sha256": disclosure["source_sha256"],
            "disclosure_sha256": canonical_json_sha256(disclosure, allow_nan=False)}


def verify_published_replicate_disclosures(request: dict[str, Any], documents: list[Path]) -> None:
    """Bind per-spec scientific declarations to the canonical publication request."""
    audited = verify_replicate_summary_request(request)
    if audited is not None and Path(str(request.get("input", ""))).expanduser().resolve() != Path(audited["original_source"]):
        raise ValueError("Replicate original source differs from the canonical publication input.")
    for document in documents:
        spec_path = document.with_name("spec.json") if document.name == "document.vsz" else document.with_suffix(".spec.json")
        canonical_categorical = request.get("categorical_binding")
        if audited is None and canonical_categorical is None and not spec_path.is_file():
            continue  # Existing non-disclosure routes retain their own spec validation.
        snapshot = _stable_file_snapshot(spec_path, label="replicate publication spec")
        spec = json.loads(snapshot["bytes"])
        source_request = spec.get("source_request", {})
        spec_categorical = source_request.get("categorical_binding") if isinstance(source_request, dict) else None
        if canonical_categorical is not None or spec_categorical is not None:
            from sciplot_core.mapping_contract.categorical import validate_categorical_context

            validate_categorical_context(request)
            if not isinstance(source_request, dict):
                raise ValueError("Categorical publication specification has no original-source request.")
            validate_categorical_context(source_request)
            if canonical_json_sha256(canonical_categorical, allow_nan=False) != canonical_json_sha256(spec_categorical, allow_nan=False):
                raise ValueError("Categorical specification binding differs from the canonical publication request.")
        spec_has_disclosure = isinstance(source_request, dict) and (
            source_request.get("summary_statistic") == "mean_sample_sd_n" or "replicate_summary_disclosure" in source_request)
        if audited is None and not spec_has_disclosure:
            continue
        if (audited is None or not isinstance(source_request, dict)
                or source_request.get("summary_statistic") != request.get("summary_statistic")
                or canonical_json_sha256(source_request.get("replicate_summary_disclosure"), allow_nan=False) != canonical_json_sha256(request.get("replicate_summary_disclosure"), allow_nan=False)):
            raise ValueError("Replicate specification disclosure differs from the canonical publication request.")
        verify_replicate_summary_request(source_request)
        _assert_snapshot_current(snapshot, label="replicate publication spec", expected_sha256=snapshot["sha256"])
