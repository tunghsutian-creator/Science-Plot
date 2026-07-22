from __future__ import annotations

import html
import json
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any

from sciplot_core.autoplot import build_autoplot_summary
from sciplot_core._utils import atomic_write_json, existing_file_sha256
from sciplot_core.delivery import DELIVERY_PACKAGE_CONTRACT_VERSION
from sciplot_core.launchers import (
    inspect_delivery_launcher_contract,
    write_delivery_launcher,
)
from sciplot_core.materials_rules import get_rule, semantic_payload_from_rule
from sciplot_core.one_step import (
    _readiness,
    build_mapping_package,
    build_render_request_package,
)
from sciplot_core.publish_state import build_publish_state
from sciplot_core.policy import (
    DELIVERY_DATA_DIR,
    DELIVERY_PDF_DIR,
    DELIVERY_PROJECT_DIR,
    DELIVERY_TIFF_DIR,
)
from sciplot_core.study_model import build_output_package_contract
from sciplot_core.readiness import (
    INSIDE_VALIDATED_ENVELOPE,
    NEEDS_HUMAN_CONFIRMATION,
    NEEDS_RULE_REPAIR,
    ValidatedEnvelopeRegistry,
    evaluate_validated_envelope,
    load_validated_envelope_registry,
    rule_contract_payload,
    validated_envelope_status,
    write_validated_envelope_registry,
)

READINESS_PROBE_KIND = "sciplot_readiness_probe"
READINESS_PROBE_VERSION = 1


def _check(
    check_id: str,
    label: str,
    passed: bool,
    *,
    detail: object = None,
) -> dict[str, Any]:
    return {
        "id": check_id,
        "label": label,
        "status": "passed" if passed else "failed",
        "detail": detail,
    }


def _write_probe_delivery(root: Path) -> dict[str, Any]:
    data_dir = root / DELIVERY_DATA_DIR
    pdf_dir = root / DELIVERY_PDF_DIR
    tiff_dir = root / DELIVERY_TIFF_DIR
    project_dir = root / DELIVERY_PROJECT_DIR
    for directory in {data_dir, pdf_dir, tiff_dir, project_dir}:
        directory.mkdir(parents=True, exist_ok=True)
    data = data_dir / "probe_plot_data.csv"
    pdf = pdf_dir / "probe.pdf"
    tiff = tiff_dir / "probe_300dpi.tiff"
    project = project_dir / "probe.vsz"
    data.write_text("x,y\n1,2\n", encoding="utf-8")
    pdf.write_bytes(b"pdf")
    tiff.write_bytes(b"tiff")
    project.write_text("# Veusz saved document\n", encoding="utf-8")
    launcher = write_delivery_launcher(root)
    launcher_contract = inspect_delivery_launcher_contract(root)
    return {
        "kind": "sciplot_user_delivery_package",
        "version": DELIVERY_PACKAGE_CONTRACT_VERSION,
        "path": str(root),
        "data_csvs": [
            {"path": str(data), "sha256": existing_file_sha256(data)}
        ],
        "figures": [
            {"path": str(pdf), "delivery_sha256": existing_file_sha256(pdf)},
            {"path": str(tiff), "delivery_sha256": existing_file_sha256(tiff)},
        ],
        "project_documents": [
            {
                "path": str(project),
                "delivery_sha256": existing_file_sha256(project),
            }
        ],
        "open_in_veusz": str(launcher),
        "open_in_veusz_sha256": launcher_contract["content_sha256"],
        "launcher_contract": launcher_contract,
        "artifacts": [
            {"id": "data", "path": str(data_dir), "exists": True},
            {"id": "pdf", "path": str(pdf_dir), "exists": True},
            {"id": "tiff", "path": str(tiff_dir), "exists": True},
            {"id": "project", "path": str(project_dir), "exists": True},
            {"id": "launcher", "path": str(launcher), "exists": True},
        ],
        "complete": True,
    }


def _semantic(
    *,
    confidence: float,
    provider_ready_flag: bool | None = None,
) -> dict[str, Any]:
    rule = get_rule("ftir_spectrum")
    payload = semantic_payload_from_rule(
        rule,
        confidence=confidence,
        reason="Readiness probe deterministic FTIR contract.",
    )
    if provider_ready_flag is not None:
        payload["ready_to_use"] = provider_ready_flag
    return payload


def _packages(
    semantic: dict[str, Any],
    *,
    mapping_state: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    confidence = float(semantic["confidence"])
    source = {
        "kind": "sciplot_source_package",
        "version": 1,
        "source": "redacted",
        "source_kind": "file",
        "file_count": 1,
        "folder_count": 0,
        "instrument_family": semantic["semantic_family"],
        "rule_id": semantic["rule_id"],
        "confidence": confidence,
        "confidence_band": "high" if confidence >= 80 else "medium",
        "raw_archive": {},
    }
    mapping = {
        "kind": "sciplot_mapping_package",
        "version": 1,
        "status": mapping_state,
        "experiment_type": semantic["rule_id"],
        "semantic_family": semantic["semantic_family"],
        "rule_id": semantic["rule_id"],
        "confidence": confidence,
        "confidence_band": "high" if confidence >= 80 else "medium",
        "reason": semantic.get("reason") or "",
        "sample_order": [],
        "column_confirmations": [],
    }
    return source, mapping


def _render_request(
    semantic: dict[str, Any],
    *,
    request_patch: dict[str, Any] | None = None,
) -> dict[str, Any]:
    request = {
        "recipe": "auto",
        "rule_id": semantic["rule_id"],
        "exports": ["pdf", "tiff_300"],
        "render_options": {"size": "60x55"},
    }
    if request_patch:
        request.update(deepcopy(request_patch))
    return build_render_request_package(
        request_path=Path("redacted_plot_request.json"),
        request=request,
    )


def _evaluate(
    registry: ValidatedEnvelopeRegistry,
    *,
    confidence: float,
    mapping_state: str,
    provider_ready_flag: bool | None = None,
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
]:
    semantic = _semantic(
        confidence=confidence,
        provider_ready_flag=provider_ready_flag,
    )
    source, mapping = _packages(semantic, mapping_state=mapping_state)
    render_request = _render_request(semantic)
    evaluation = evaluate_validated_envelope(
        semantic=semantic,
        source_package=source,
        mapping_package=mapping,
        render_request=render_request,
        registry=registry,
    )
    return evaluation, source, mapping, render_request


def _write_report(path: Path, payload: dict[str, Any]) -> Path:
    rows = "\n".join(
        "<tr>"
        f"<td><code>{html.escape(str(check['id']))}</code></td>"
        f"<td>{html.escape(str(check['label']))}</td>"
        f"<td>{html.escape(str(check['status']))}</td>"
        "</tr>"
        for check in payload["checks"]
    )
    document = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>SciPlot readiness probe</title>
  <style>
    body {{ font: 14px/1.45 -apple-system, BlinkMacSystemFont, sans-serif; margin: 32px; color: #17202a; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border-bottom: 1px solid #d8dee6; padding: 8px; text-align: left; }}
    code {{ font-family: ui-monospace, SFMono-Regular, monospace; }}
  </style>
</head>
<body>
  <h1>SciPlot readiness probe</h1>
  <p>Status: <strong>{html.escape(str(payload["status"]))}</strong> ·
  {payload["passed_count"]}/{payload["check_count"]} passed.</p>
  <table>
    <thead><tr><th>Gate</th><th>Contract</th><th>Status</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</body>
</html>
"""
    path.write_text(document, encoding="utf-8")
    return path


def run_readiness_probe(*, output_root: Path) -> dict[str, Any]:
    output_root = output_root.expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    run_root = Path(
        tempfile.mkdtemp(prefix="readiness_probe_", dir=str(output_root))
    ).resolve()
    registry = load_validated_envelope_registry()
    status = validated_envelope_status(registry)

    roundtrip_path = run_root / "validated_envelopes.json"
    write_validated_envelope_registry(roundtrip_path, registry)
    roundtrip = load_validated_envelope_registry(roundtrip_path)

    tampered_payload = registry.to_dict()
    tampered_entry = next(
        entry
        for entry in tampered_payload["entries"]
        if entry["rule_id"] == "ftir_spectrum"
    )
    tampered_entry["contract_sha256"] = "0" * 64
    stale_registry = ValidatedEnvelopeRegistry.from_dict(tampered_payload)
    stale_status = validated_envelope_status(stale_registry)

    extra_field_rejected = False
    extra_payload = registry.to_dict()
    extra_payload["unexpected"] = True
    try:
        ValidatedEnvelopeRegistry.from_dict(extra_payload)
    except ValueError:
        extra_field_rejected = True

    duplicate_rejected = False
    duplicate_payload = registry.to_dict()
    duplicate_payload["entries"].append(deepcopy(duplicate_payload["entries"][0]))
    try:
        ValidatedEnvelopeRegistry.from_dict(duplicate_payload)
    except ValueError:
        duplicate_rejected = True

    non_real_evidence_rejected = False
    non_real_payload = registry.to_dict()
    non_real_payload["entries"][0]["real_data_evidence"] = False
    try:
        ValidatedEnvelopeRegistry.from_dict(non_real_payload)
    except ValueError:
        non_real_evidence_rejected = True

    future_acceptance_version_rejected = False
    future_version_payload = registry.to_dict()
    future_version_payload["source_acceptance"]["version"] = 4
    try:
        ValidatedEnvelopeRegistry.from_dict(future_version_payload)
    except ValueError:
        future_acceptance_version_rejected = True

    boolean_registry_version_rejected = False
    boolean_version_payload = registry.to_dict()
    boolean_version_payload["version"] = True
    try:
        ValidatedEnvelopeRegistry.from_dict(boolean_version_payload)
    except ValueError:
        boolean_registry_version_rejected = True

    missing_contract_check_rejected = False
    missing_contract_check_payload = registry.to_dict()
    missing_contract_check_payload["entries"][0]["accepted_check_ids"].remove(
        "validated_rule_contract_current"
    )
    try:
        ValidatedEnvelopeRegistry.from_dict(missing_contract_check_payload)
    except ValueError:
        missing_contract_check_rejected = True

    semantic_metadata_payload = registry.to_dict()
    semantic_metadata_payload["entries"][0]["semantic_family"] = "tampered_family"
    semantic_metadata_registry = ValidatedEnvelopeRegistry.from_dict(
        semantic_metadata_payload
    )
    semantic_metadata_status = validated_envelope_status(semantic_metadata_registry)

    ready, ready_source, ready_mapping, ready_render_request = _evaluate(
        registry,
        confidence=95.0,
        mapping_state="auto",
        provider_ready_flag=False,
    )
    medium, medium_source, medium_mapping, medium_render_request = _evaluate(
        registry,
        confidence=75.0,
        mapping_state="auto",
    )
    (
        confirmed,
        _confirmed_source,
        _confirmed_mapping,
        _confirmed_render_request,
    ) = _evaluate(
        registry,
        confidence=75.0,
        mapping_state="confirmed",
    )
    medium_semantic = _semantic(confidence=75.0)
    template_only_mapping = build_mapping_package(
        request={"template": "curve"},
        semantic=medium_semantic,
    )
    explicit_rule_mapping = build_mapping_package(
        request={"rule_id": "ftir_spectrum", "template": "curve"},
        semantic=medium_semantic,
    )
    (
        unsupported,
        _unsupported_source,
        _unsupported_mapping,
        _unsupported_render_request,
    ) = _evaluate(
        registry,
        confidence=50.0,
        mapping_state=NEEDS_RULE_REPAIR,
        provider_ready_flag=True,
    )
    stale, stale_source, stale_mapping, stale_render_request = _evaluate(
        stale_registry,
        confidence=95.0,
        mapping_state="auto",
        provider_ready_flag=True,
    )
    mismatch_semantic = _semantic(confidence=95.0)
    mismatch_source, mismatch_mapping = _packages(
        mismatch_semantic,
        mapping_state="auto",
    )
    mismatch_source["rule_id"] = "xrd_pattern"
    mismatch_mapping["kind"] = "provider_authored_mapping"
    mismatch = evaluate_validated_envelope(
        semantic=mismatch_semantic,
        source_package=mismatch_source,
        mapping_package=mismatch_mapping,
        render_request=_render_request(mismatch_semantic),
        registry=registry,
    )
    typed_source = deepcopy(ready_source)
    typed_mapping = deepcopy(ready_mapping)
    typed_source["version"] = True
    typed_mapping["version"] = True
    typed_mismatch = evaluate_validated_envelope(
        semantic=_semantic(confidence=95.0),
        source_package=typed_source,
        mapping_package=typed_mapping,
        render_request=ready_render_request,
        registry=registry,
    )
    tampered_semantic = _semantic(confidence=95.0, provider_ready_flag=True)
    tampered_semantic["render_options"]["x_min"] = 123.0
    tampered_source, tampered_mapping = _packages(
        tampered_semantic,
        mapping_state="auto",
    )
    tampered_evaluation = evaluate_validated_envelope(
        semantic=tampered_semantic,
        source_package=tampered_source,
        mapping_package=tampered_mapping,
        render_request=_render_request(tampered_semantic),
        registry=registry,
    )
    safe_visual_render_request = _render_request(
        _semantic(confidence=95.0),
        request_patch={
            "render_options": {
                "size": "120x55",
                "palette_preset": "tol_bright",
            }
        },
    )
    safe_visual_evaluation = evaluate_validated_envelope(
        semantic=_semantic(confidence=95.0),
        source_package=ready_source,
        mapping_package=ready_mapping,
        render_request=safe_visual_render_request,
        registry=registry,
    )
    hard_style_render_request = _render_request(
        _semantic(confidence=95.0),
        request_patch={
            "render_options": {
                "size": "60x55",
                "line_width_pt": 1.2,
            }
        },
    )
    hard_style_evaluation = evaluate_validated_envelope(
        semantic=_semantic(confidence=95.0),
        source_package=ready_source,
        mapping_package=ready_mapping,
        render_request=hard_style_render_request,
        registry=registry,
    )
    unsafe_axis_render_request = _render_request(
        _semantic(confidence=95.0),
        request_patch={"render_options": {"size": "60x55", "x_min": 123.0}},
    )
    unsafe_axis_evaluation = evaluate_validated_envelope(
        semantic=_semantic(confidence=95.0),
        source_package=ready_source,
        mapping_package=ready_mapping,
        render_request=unsafe_axis_render_request,
        registry=registry,
    )
    changed_template_render_request = _render_request(
        _semantic(confidence=95.0),
        request_patch={"template": "curve"},
    )
    changed_template_evaluation = evaluate_validated_envelope(
        semantic=_semantic(confidence=95.0),
        source_package=ready_source,
        mapping_package=ready_mapping,
        render_request=changed_template_render_request,
        registry=registry,
    )
    direct_recipe_render_request = _render_request(
        _semantic(confidence=95.0),
        request_patch={"recipe": "spectroscopy"},
    )
    direct_recipe_evaluation = evaluate_validated_envelope(
        semantic=_semantic(confidence=95.0),
        source_package=ready_source,
        mapping_package=ready_mapping,
        render_request=direct_recipe_render_request,
        registry=registry,
    )
    incomplete_exports_render_request = _render_request(
        _semantic(confidence=95.0),
        request_patch={"exports": ["pdf"]},
    )
    incomplete_exports_evaluation = evaluate_validated_envelope(
        semantic=_semantic(confidence=95.0),
        source_package=ready_source,
        mapping_package=ready_mapping,
        render_request=incomplete_exports_render_request,
        registry=registry,
    )
    mismatched_series_order_render_request = _render_request(
        _semantic(confidence=95.0),
        request_patch={
            "series_order": [],
            "render_options": {
                "size": "60x55",
                "series_order": ["presented_only_in_render_options"],
            },
        },
    )
    mismatched_series_order_evaluation = evaluate_validated_envelope(
        semantic=_semantic(confidence=95.0),
        source_package=ready_source,
        mapping_package=ready_mapping,
        render_request=mismatched_series_order_render_request,
        registry=registry,
    )

    passing_qa = {
        "status": "passed",
        "needs_ai_intervention": False,
        "qa_status": "passed",
        "delivery_complete": True,
    }
    ready_state, ready_reasons = _readiness(
        source_package=ready_source,
        mapping_package=ready_mapping,
        render_request=ready_render_request,
        figure_qa_report=passing_qa,
        validated_envelope=ready,
    )
    medium_state, medium_reasons = _readiness(
        source_package=medium_source,
        mapping_package=medium_mapping,
        render_request=medium_render_request,
        figure_qa_report=passing_qa,
        validated_envelope=medium,
    )
    stale_state, stale_reasons = _readiness(
        source_package=stale_source,
        mapping_package=stale_mapping,
        render_request=stale_render_request,
        figure_qa_report=passing_qa,
        validated_envelope=stale,
    )
    unknown_qa_state, unknown_qa_reasons = _readiness(
        source_package=ready_source,
        mapping_package=ready_mapping,
        render_request=ready_render_request,
        figure_qa_report={
            "status": "failed",
            "needs_ai_intervention": False,
            "qa_status": "unknown",
            "delivery_complete": True,
        },
        validated_envelope=ready,
    )
    incomplete_envelope = deepcopy(ready)
    incomplete_envelope.pop("repair_reasons")
    incomplete_state, incomplete_reasons = _readiness(
        source_package=ready_source,
        mapping_package=ready_mapping,
        render_request=ready_render_request,
        figure_qa_report=passing_qa,
        validated_envelope=incomplete_envelope,
    )
    valid_autoplot_run = run_root / "valid_autoplot"
    valid_autoplot_run.mkdir(parents=True, exist_ok=True)
    valid_autoplot_delivery = valid_autoplot_run / "delivery"
    valid_autoplot_delivery_record = _write_probe_delivery(
        valid_autoplot_delivery
    )
    valid_autoplot_one_step = {
        "state": "ready",
        "delivery_package": valid_autoplot_delivery_record,
        "figure_qa_report": passing_qa,
        "render_request": ready_render_request,
        "validated_envelope": ready,
    }
    valid_autoplot_qa = {"status": "passed"}
    atomic_write_json(valid_autoplot_run / "request_snapshot.json", {})
    atomic_write_json(valid_autoplot_run / "manifest.json", {})
    (valid_autoplot_run / "review.html").write_text(
        "<html></html>\n", encoding="utf-8"
    )
    (valid_autoplot_run / "revision_brief.md").write_text(
        "# Ready\n", encoding="utf-8"
    )
    valid_autoplot_manifest_seed = {
        "figures": [
            str(item["path"])
            for item in valid_autoplot_delivery_record["figures"]
            if isinstance(item, dict)
        ],
        "qa": valid_autoplot_qa,
        "result": {},
    }
    valid_autoplot_package = build_output_package_contract(
        valid_autoplot_run,
        manifest=valid_autoplot_manifest_seed,
    )
    valid_autoplot_publish = build_publish_state(
        qa=valid_autoplot_qa,
        package_contract=valid_autoplot_package,
        delivery_package=valid_autoplot_one_step["delivery_package"],
        prerequisite_state=valid_autoplot_one_step["state"],
    )
    atomic_write_json(
        valid_autoplot_run / "manifest.json",
        {
            "kind": "sciplot_run",
            **valid_autoplot_manifest_seed,
            "qa": valid_autoplot_qa,
            "package_contract": valid_autoplot_package,
            "delivery_package": valid_autoplot_one_step["delivery_package"],
            "one_step": valid_autoplot_one_step,
            **valid_autoplot_publish,
        },
    )
    atomic_write_json(
        valid_autoplot_run / "one_step_status.json", valid_autoplot_one_step
    )
    valid_autoplot = build_autoplot_summary(
        {
            "status": "ready",
            "run_output": str(valid_autoplot_run),
            "project_dir": str(run_root / "valid_project"),
            "one_step": valid_autoplot_one_step,
        }
    )
    forged_envelope = deepcopy(ready)
    forged_envelope["state"] = NEEDS_RULE_REPAIR
    forged_envelope["ready_without_ai"] = True
    forged_envelope["contract_current"] = False
    forged_autoplot = build_autoplot_summary(
        {
            "status": "ready",
            "run_output": str(run_root / "forged_autoplot"),
            "project_dir": str(run_root / "forged_project"),
            "one_step": {
                "state": "ready",
                "delivery_package": {
                    "complete": True,
                    "path": str(run_root / "forged_delivery"),
                },
                "figure_qa_report": passing_qa,
                "render_request": ready_render_request,
                "validated_envelope": forged_envelope,
            },
        }
    )
    request_forged_autoplot = build_autoplot_summary(
        {
            "status": "ready",
            "run_output": str(run_root / "request_forged_autoplot"),
            "project_dir": str(run_root / "request_forged_project"),
            "one_step": {
                "state": "ready",
                "delivery_package": {
                    "complete": True,
                    "path": str(run_root / "request_forged_delivery"),
                },
                "figure_qa_report": passing_qa,
                "render_request": unsafe_axis_render_request,
                "validated_envelope": ready,
            },
        }
    )
    boolean_version_envelope = deepcopy(ready)
    boolean_version_envelope["version"] = True
    identity_forged_envelope = deepcopy(ready)
    identity_forged_envelope["rule_id"] = "xrd_pattern"
    identity_forged_envelope["semantic_family"] = "xrd_pattern"
    incomplete_autoplot = build_autoplot_summary(
        {
            "status": "ready",
            "run_output": str(run_root / "incomplete_autoplot"),
            "project_dir": str(run_root / "incomplete_project"),
            "one_step": {
                "state": "ready",
                "delivery_package": {
                    "complete": 1,
                    "path": str(run_root / "incomplete_delivery"),
                },
                "figure_qa_report": passing_qa,
                "render_request": ready_render_request,
                "validated_envelope": incomplete_envelope,
            },
        }
    )
    boolean_version_autoplot = build_autoplot_summary(
        {
            "status": "ready",
            "run_output": str(run_root / "boolean_version_autoplot"),
            "project_dir": str(run_root / "boolean_version_project"),
            "one_step": {
                "state": "ready",
                "delivery_package": {
                    "complete": True,
                    "path": str(run_root / "boolean_version_delivery"),
                },
                "figure_qa_report": passing_qa,
                "render_request": ready_render_request,
                "validated_envelope": boolean_version_envelope,
            },
        }
    )
    identity_forged_autoplot = build_autoplot_summary(
        {
            "status": "ready",
            "run_output": str(run_root / "identity_forged_autoplot"),
            "project_dir": str(run_root / "identity_forged_project"),
            "one_step": {
                "state": "ready",
                "delivery_package": {
                    "complete": True,
                    "path": str(run_root / "identity_forged_delivery"),
                },
                "figure_qa_report": passing_qa,
                "render_request": ready_render_request,
                "validated_envelope": identity_forged_envelope,
            },
        }
    )
    persisted_repair_status = deepcopy(valid_autoplot_one_step)
    persisted_repair_status["state"] = NEEDS_RULE_REPAIR
    atomic_write_json(
        valid_autoplot_run / "one_step_status.json",
        persisted_repair_status,
    )
    mismatched_autoplot = build_autoplot_summary(
        {
            "status": "ready",
            "run_output": str(valid_autoplot_run),
            "project_dir": str(run_root / "valid_project"),
            "one_step": valid_autoplot_one_step,
        }
    )
    atomic_write_json(
        valid_autoplot_run / "one_step_status.json",
        valid_autoplot_one_step,
    )

    serialized = json.dumps(registry.to_dict(), ensure_ascii=False)
    rule_contract = rule_contract_payload(get_rule("ftir_spectrum"))
    checks = [
        _check(
            "registry_covers_current_ready_rules",
            "Every current ready rule has a current accepted contract",
            status["status"] == "ready"
            and status["ready_without_ai_rule_count"] == 23
            and not status["missing_rule_ids"]
            and not status["stale_rule_ids"],
            detail={
                "status": status["status"],
                "ready_without_ai_rule_count": status["ready_without_ai_rule_count"],
                "evidence_strength_counts": status["evidence_strength_counts"],
            },
        ),
        _check(
            "registry_roundtrip",
            "The closed source-controlled registry round-trips exactly",
            roundtrip.to_dict() == registry.to_dict(),
        ),
        _check(
            "registry_schema_is_closed",
            "Undeclared registry fields are rejected",
            extra_field_rejected,
        ),
        _check(
            "registry_rule_ids_are_unique",
            "Duplicate validated rule IDs are rejected",
            duplicate_rejected,
        ),
        _check(
            "real_data_evidence_is_required",
            "A certificate cannot relabel non-real evidence as validated",
            non_real_evidence_rejected,
        ),
        _check(
            "registry_versions_are_exact",
            "Boolean or unknown future registry/acceptance versions are rejected",
            boolean_registry_version_rejected and future_acceptance_version_rejected,
        ),
        _check(
            "registry_requires_current_contract_check",
            "Every certificate retains the accepted current-contract lifecycle gate",
            missing_contract_check_rejected,
        ),
        _check(
            "semantic_metadata_drift_invalidates_registry",
            "Tampered envelope semantic metadata makes the registry stale",
            semantic_metadata_status["status"] == NEEDS_RULE_REPAIR
            and bool(semantic_metadata_status["stale_rule_ids"]),
            detail=semantic_metadata_status["stale_rule_ids"],
        ),
        _check(
            "rule_contract_drift_invalidates_envelope",
            "A changed full rule contract becomes stale before a new input can be ready",
            stale_status["status"] == NEEDS_RULE_REPAIR
            and bool(stale_status["stale_rule_ids"]),
            detail=stale_status["stale_rule_ids"],
        ),
        _check(
            "rule_contract_binds_recognition",
            "The accepted rule contract includes declarative recognition inputs",
            rule_contract.get("version") == 3
            and rule_contract.get("matcher", {}).get("version") == 1
            and set(rule_contract.get("recognition", {}))
            == {
                "keywords",
                "path_keywords",
                "column_aliases",
                "vendor_models",
                "experiment_families",
            },
            detail=rule_contract.get("recognition"),
        ),
        _check(
            "rule_contract_binds_render_request_policy",
            "The full rule certificate binds a closed runtime render-request policy",
            rule_contract.get("render_request_policy", {}).get("version") == 1
            and rule_contract.get("render_request_policy", {}).get("template_policy")
            == "exact_rule_template"
            and rule_contract.get("render_request_policy", {}).get("split_policy")
            == "empty_only"
            and {"pdf", "tiff_300"}
            <= set(
                rule_contract.get("render_request_policy", {}).get(
                    "required_exports",
                    [],
                )
            )
            and "x_min"
            in rule_contract.get("render_request_policy", {}).get(
                "exact_certified_value_keys",
                [],
            )
            and "size"
            in rule_contract.get("render_request_policy", {}).get(
                "visual_override_keys",
                [],
            )
            and "line_width_pt"
            not in rule_contract.get("render_request_policy", {}).get(
                "visual_override_keys",
                [],
            ),
            detail=rule_contract.get("render_request_policy"),
        ),
        _check(
            "high_confidence_auto_input_is_inside",
            "A high-confidence deterministic match enters the accepted envelope",
            ready["state"] == INSIDE_VALIDATED_ENVELOPE
            and ready["ready_without_ai"] is True,
            detail=ready,
        ),
        _check(
            "medium_auto_input_requires_confirmation",
            "A medium-confidence automatic match cannot self-promote to ready",
            medium["state"] == NEEDS_HUMAN_CONFIRMATION
            and medium["ready_without_ai"] is False,
            detail=medium,
        ),
        _check(
            "explicit_confirmation_can_bind_medium_match",
            "An explicit host-side confirmation admits a supported medium match",
            confirmed["state"] == INSIDE_VALIDATED_ENVELOPE,
            detail=confirmed,
        ),
        _check(
            "visual_intent_cannot_confirm_scientific_semantics",
            "A template choice cannot confirm a medium-confidence experiment mapping",
            template_only_mapping["status"] == NEEDS_HUMAN_CONFIRMATION
            and explicit_rule_mapping["status"] == "confirmed",
            detail={
                "template_only": template_only_mapping["status"],
                "explicit_rule": explicit_rule_mapping["status"],
            },
        ),
        _check(
            "unsupported_input_requires_rule_repair",
            "Unsupported semantics stop at needs_rule_repair",
            unsupported["state"] == NEEDS_RULE_REPAIR
            and unsupported["ready_without_ai"] is False,
            detail=unsupported,
        ),
        _check(
            "provider_ready_flag_has_no_authority",
            "Provider-authored ready flags cannot override stale, tampered, or failed contracts",
            stale["state"] == NEEDS_RULE_REPAIR
            and unsupported["state"] == NEEDS_RULE_REPAIR
            and tampered_evaluation["state"] == NEEDS_RULE_REPAIR,
            detail={
                "stale": stale["repair_reasons"],
                "unsupported": unsupported["repair_reasons"],
                "tampered_semantic": tampered_evaluation["repair_reasons"],
            },
        ),
        _check(
            "presented_semantic_contract_is_bound",
            "A same-rule payload with changed render semantics cannot enter the envelope",
            tampered_evaluation["state"] == NEEDS_RULE_REPAIR
            and "semantic_contract_mismatch" in tampered_evaluation["repair_reasons"],
            detail=tampered_evaluation,
        ),
        _check(
            "safe_visual_overrides_remain_inside",
            "Whitelisted presentation-only changes retain deterministic ready authority",
            safe_visual_evaluation["state"] == INSIDE_VALIDATED_ENVELOPE
            and safe_visual_evaluation["request_contract_current"] is True,
            detail=safe_visual_evaluation,
        ),
        _check(
            "unified_style_overrides_cannot_claim_ready",
            "Project-wide typography and stroke settings cannot bypass the unified style contract",
            hard_style_evaluation["state"] == NEEDS_RULE_REPAIR
            and hard_style_evaluation["ready_without_ai"] is False
            and "render_options_not_canonical"
            in hard_style_evaluation["repair_reasons"],
            detail=hard_style_evaluation,
        ),
        _check(
            "scientific_render_overrides_require_confirmation",
            "Axis-domain changes cannot borrow the accepted default rule certificate",
            unsafe_axis_evaluation["state"] == NEEDS_HUMAN_CONFIRMATION
            and unsafe_axis_evaluation["ready_without_ai"] is False
            and "render_option_requires_confirmation:x_min"
            in unsafe_axis_evaluation["confirmation_reasons"],
            detail=unsafe_axis_evaluation,
        ),
        _check(
            "render_route_and_template_are_certificate_bound",
            "Changed templates or direct recipe routes leave the automatic envelope",
            changed_template_evaluation["state"] == NEEDS_HUMAN_CONFIRMATION
            and direct_recipe_evaluation["state"] == NEEDS_HUMAN_CONFIRMATION,
            detail={
                "changed_template": changed_template_evaluation,
                "direct_recipe": direct_recipe_evaluation,
            },
        ),
        _check(
            "canonical_exports_are_request_bound",
            "A request without the canonical PDF/TIFF pair cannot become ready",
            incomplete_exports_evaluation["state"] == NEEDS_RULE_REPAIR
            and "canonical_pdf_tiff_exports_missing"
            in incomplete_exports_evaluation["repair_reasons"],
            detail=incomplete_exports_evaluation,
        ),
        _check(
            "series_order_representations_are_bound",
            "Top-level and render-option series order cannot disagree",
            mismatched_series_order_evaluation["state"] == NEEDS_RULE_REPAIR
            and "render_series_order_binding_mismatch"
            in mismatched_series_order_evaluation["repair_reasons"],
            detail=mismatched_series_order_evaluation,
        ),
        _check(
            "source_mapping_binding_is_required",
            "A source/rule identity mismatch cannot enter a validated envelope",
            mismatch["state"] == NEEDS_RULE_REPAIR
            and "source_rule_mismatch" in mismatch["repair_reasons"]
            and "mapping_package_contract_invalid" in mismatch["repair_reasons"]
            and typed_mismatch["state"] == NEEDS_RULE_REPAIR
            and "source_package_contract_invalid" in typed_mismatch["repair_reasons"]
            and "mapping_package_contract_invalid" in typed_mismatch["repair_reasons"],
            detail={
                "identity_mismatch": mismatch,
                "typed_version_mismatch": typed_mismatch,
            },
        ),
        _check(
            "one_step_ready_gate_is_envelope_bound",
            "One-step returns ready only for a current inside-envelope evaluation",
            ready_state == "ready"
            and medium_state == NEEDS_HUMAN_CONFIRMATION
            and stale_state == NEEDS_RULE_REPAIR
            and unknown_qa_state == NEEDS_RULE_REPAIR
            and incomplete_state == NEEDS_RULE_REPAIR
            and "validated_envelope_invalid" in incomplete_reasons,
            detail={
                "ready": [ready_state, ready_reasons],
                "medium": [medium_state, medium_reasons],
                "stale": [stale_state, stale_reasons],
                "unknown_qa": [unknown_qa_state, unknown_qa_reasons],
                "incomplete_envelope": [incomplete_state, incomplete_reasons],
            },
        ),
        _check(
            "autoplot_ready_gate_is_closed",
            "Autoplot requires a passed QA report and the complete host evaluation",
            valid_autoplot["ready_to_use"] is True
            and forged_autoplot["ready_to_use"] is False
            and "validated_envelope_invalid" in forged_autoplot["integrity"]["reasons"]
            and incomplete_autoplot["ready_to_use"] is False
            and incomplete_autoplot["delivery_complete"] is False
            and boolean_version_autoplot["ready_to_use"] is False
            and request_forged_autoplot["ready_to_use"] is False
            and "validated_envelope_invalid"
            in request_forged_autoplot["integrity"]["reasons"],
            detail={
                "valid": valid_autoplot["integrity"],
                "forged": forged_autoplot["integrity"],
                "request_forged": request_forged_autoplot["integrity"],
                "incomplete": incomplete_autoplot["integrity"],
                "boolean_version": boolean_version_autoplot["integrity"],
            },
        ),
        _check(
            "autoplot_state_mismatch_is_rejected",
            "A reported ready state cannot override a persisted repair state",
            mismatched_autoplot["ready_to_use"] is False
            and mismatched_autoplot["state"] == NEEDS_RULE_REPAIR
            and "one_step_state_mismatch"
            in mismatched_autoplot["integrity"]["reasons"],
            detail=mismatched_autoplot["integrity"],
        ),
        _check(
            "persisted_evaluation_identity_is_registry_bound",
            "Copied hashes cannot be relabeled as another validated rule",
            identity_forged_autoplot["ready_to_use"] is False
            and "validated_envelope_invalid"
            in identity_forged_autoplot["integrity"]["reasons"],
            detail=identity_forged_autoplot["integrity"],
        ),
        _check(
            "registry_contains_no_local_source_paths",
            "Portable certificates contain hashes and evidence metadata, not local source paths",
            "/Users/" not in serialized
            and "/private/" not in serialized
            and "fixture_path" not in serialized
            and "manifest_path" not in serialized,
        ),
    ]
    passed_count = sum(check["status"] == "passed" for check in checks)
    payload = {
        "kind": READINESS_PROBE_KIND,
        "version": READINESS_PROBE_VERSION,
        "status": "passed" if passed_count == len(checks) else "failed",
        "check_count": len(checks),
        "passed_count": passed_count,
        "checks": checks,
        "registry_status": status,
        "limitations": [
            "This probe validates certificate authority and runtime gating; it "
            "does not replace the underlying authorized real-data acceptance.",
            "It does not count as Veusz-first human daily-use validation.",
        ],
    }
    summary_path = atomic_write_json(run_root / "readiness_probe.json", payload)
    report_path = _write_report(run_root / "readiness_probe.html", payload)
    payload["artifacts"] = {
        "root": str(run_root),
        "summary": str(summary_path),
        "report": str(report_path),
        "registry_roundtrip": str(roundtrip_path),
    }
    atomic_write_json(summary_path, payload)
    return payload


__all__ = [
    "READINESS_PROBE_KIND",
    "READINESS_PROBE_VERSION",
    "run_readiness_probe",
]
