"""Build the complete doctor diagnostic payload."""

from __future__ import annotations

import sys
from typing import Any
from sciplot_core._paths import REPO_ROOT, VEUSZ_ROOT
from sciplot_core.materials_rules import iter_rules
from sciplot_core.publication import (
    list_composite_layouts,
)
from sciplot_core.style_contract import audit_style_template_contract

from sciplot_core.doctor.runtime_checks import (
    _check,
    _module_available,
    _veusz_qt_runtime_status,
    _vsz_lifecycle_available,
    _publication_foundation_available,
)

from sciplot_core.doctor.readiness_checks import (
    _publication_layout_inventory_available,
    _ready_rule_fixtures_exist,
    _validated_envelope_summary,
)

from sciplot_core.doctor.actions import (
    _next_actions,
)


def doctor_payload() -> dict[str, Any]:
    rules = list(iter_rules())
    ready_rules = [rule for rule in rules if rule.fixture_status == "ready"]
    pending_rules = [rule for rule in rules if rule.fixture_status != "ready"]
    fixtures_ok, fixture_detail = _ready_rule_fixtures_exist(rules)
    veusz_qt_ok, veusz_qt_detail = _veusz_qt_runtime_status()
    envelope_ok, envelope_detail, envelope_payload = _validated_envelope_summary()
    style_audit = audit_style_template_contract()

    checks = [
        _check(
            "python_version",
            "Python 3.11+",
            sys.version_info >= (3, 11),
            detail=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        ),
        _check(
            "repo_root",
            "SciPlot repo root",
            (REPO_ROOT / "pyproject.toml").exists(),
            detail=str(REPO_ROOT),
        ),
        _check(
            "veusz_vendor",
            "Vendored Veusz runtime",
            (VEUSZ_ROOT / "veusz" / "__init__.py").exists(),
            detail=str(VEUSZ_ROOT),
        ),
        _check("pyqt6", "PyQt6 available", _module_available("PyQt6")),
        _check(
            "veusz_qt_runtime",
            "Veusz Qt helper runtime",
            veusz_qt_ok,
            detail=veusz_qt_detail,
        ),
        _check(
            "vsz_lifecycle",
            "VSZ authority, history, exact export, and delivery hash gate",
            _vsz_lifecycle_available(),
            detail="studio/document.vsz -> Veusz -> exact edited export",
        ),
        _check(
            "publication_foundation",
            "Single-panel publication intent, lineage, and artifact QA",
            _publication_foundation_available(),
            detail=(
                "60/120/180 mm single-panel contract -> evidence/transform "
                "lineage -> PDF/TIFF publication QA"
            ),
        ),
        _check(
            "style_template_contract",
            "Global style and implemented-template contract",
            style_audit.get("status") == "passed",
            detail=(
                f"{len(style_audit.get('implemented_veusz_templates') or [])} "
                "production Veusz templates; unified typography, strokes, "
                "markers, physical frame, and negative-exponent unit "
                "expressions; explicit heatmap color contract"
            ),
        ),
        _check(
            "publication_layout_inventory",
            "Optional figure-level publication layout inventory",
            _publication_layout_inventory_available(),
            required=False,
            detail=(
                "Deterministic 183 mm layout metadata only; no standalone "
                "layout editor is part of daily readiness."
            ),
        ),
        _check(
            "skill_wrapper",
            "Skill wrapper executable",
            (REPO_ROOT / "skill" / "scripts" / "sciplot").exists(),
            detail=str(REPO_ROOT / "skill" / "scripts" / "sciplot"),
        ),
        _check(
            "ready_rules",
            "Ready material rules",
            len(ready_rules) >= 5,
            detail=str(len(ready_rules)),
        ),
        _check(
            "validated_envelopes",
            "Ready rules match accepted real-data lifecycle contracts",
            envelope_ok,
            detail=envelope_detail,
        ),
        _check(
            "ready_rule_fixtures",
            "Optional local acceptance fixtures",
            fixtures_ok,
            required=False,
            detail=(
                fixture_detail
                if fixtures_ok
                else f"not distributed on GitHub by policy; missing locally: {fixture_detail}"
            ),
        ),
    ]
    required_failures = [
        check for check in checks if check["required"] and check["status"] != "passed"
    ]
    try:
        layouts = list_composite_layouts()
    except Exception:
        layouts = []
    return {
        "kind": "sciplot_doctor",
        "status": "ready" if not required_failures else "blocked",
        "repo_root": str(REPO_ROOT),
        "normal_mode": {
            "daily_entrypoint": "sciplot studio PATH",
            "interactive_entrypoint": "sciplot studio PATH",
            "headless_export_entrypoint": (
                "sciplot studio PATH --out /path/to/Visible_Figure_Project "
                "--export pdf,tiff_300 --json"
            ),
            "explicit_intent_entrypoint": (
                "sciplot studio PATH --rule RULE_ID --template TEMPLATE_ID "
                "--out /path/to/Visible_Figure_Project"
            ),
            "frontend_default": "veusz_mainwindow",
            "assistant_default": "independent",
            "assistant_visibility_default": "hidden",
            "codex_required": False,
            "user_switch_required": False,
            "automatic_recognition_required": False,
        },
        "command_surface": {
            "interactive_family": {
                "command": "studio",
                "interactive": "sciplot studio PATH",
                "headless": ("sciplot studio PATH --export pdf,tiff_300 --json"),
                "role": "project preparation, native Veusz editing, exact-current export, QA, and delivery",
            },
            "automation_family": {
                "command": "autoplot",
                "role": "public automated project, QA, and delivery orchestration over the internal request and one-step status pipeline",
                "separate_renderer": False,
            },
            "request_replay": {
                "command": "run",
                "role": "repeat an already confirmed plot_request.json",
            },
            "browser_confirmation": {
                "command": "app",
                "role": "pre-render data confirmation and read-only result review",
                "drawing_frontend": False,
            },
            "developer_primitives": ["render", "recipe"],
            "developer_validation_routes": [
                "verify",
                "smoke",
                "acceptance",
                "batch",
            ],
            "internal_models": ["one_step"],
        },
        "vsz_lifecycle": {
            "canonical_artifact": "studio/document.vsz",
            "editor": "veusz_mainwindow",
            "open_preserves_document": True,
            "manual_edit_detection": "sha256",
            "archive_before_explicit_regeneration": True,
            "export_exact_current_document": True,
            "delivery_requires_matching_vsz_hash": True,
        },
        "publication_foundation": {
            "ordinary_widths_mm": [60.0, 120.0, 180.0],
            "default_profile": "sciplot_single_panel_v1",
            "official_profile": "nature_flagship_research_2026_v1",
            "scientific_outcome_agnostic": True,
            "silent_data_omission_allowed": False,
        },
        "optional_capabilities": {
            "publication_layout_inventory": {
                "required_for_daily_readiness": False,
                "available": _publication_layout_inventory_available(),
                "figure_width_mm": 183.0,
                "layout_ids": [layout["id"] for layout in layouts],
                "profile": "sciplot_composite_183_v1",
            },
        },
        "style_template_contract": {
            "status": style_audit.get("status"),
            "implemented_veusz_templates": style_audit.get(
                "implemented_veusz_templates"
            )
            or [],
            "ordinary_palette_contract": style_audit.get("ordinary_palette_contract")
            or {},
            "unit_expression_contract": style_audit.get("unit_expression_contract")
            or {},
            "issues": style_audit.get("issues") or [],
        },
        "rule_summary": {
            "total": len(rules),
            "ready": len(ready_rules),
            "pending": len(pending_rules),
            "automatic_match_scope": "ready_only",
        },
        "validated_envelopes": {
            "status": envelope_payload.get("status"),
            "ready_without_ai_rule_count": envelope_payload.get(
                "ready_without_ai_rule_count",
            ),
            "current_ready_rule_count": envelope_payload.get(
                "current_ready_rule_count",
            ),
            "stale_rule_ids": envelope_payload.get("stale_rule_ids") or [],
            "missing_rule_ids": envelope_payload.get("missing_rule_ids") or [],
            "evidence_strength_counts": envelope_payload.get(
                "evidence_strength_counts",
            )
            or {},
            "claims": envelope_payload.get("claims") or {},
        },
        "checks": checks,
        "next_actions": _next_actions(required_failures),
    }
