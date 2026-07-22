from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path
from typing import Any

from sciplot_core._paths import REPO_ROOT, VEUSZ_ROOT, resolve_fixture_path
from sciplot_core.materials_rules import iter_rules
from sciplot_core.publication import (
    get_publication_profile,
    list_composite_layouts,
)
from sciplot_core.readiness import validated_envelope_status
from sciplot_core.style_contract import audit_style_template_contract


def _check(
    check_id: str, label: str, passed: bool, *, required: bool = True, detail: str = ""
) -> dict[str, Any]:
    return {
        "id": check_id,
        "label": label,
        "status": "passed" if passed else "failed",
        "required": required,
        "detail": detail,
    }


def _module_available(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def _veusz_qt_runtime_status() -> tuple[bool, str]:
    if not _module_available("PyQt6"):
        return False, "PyQt6 is not importable."
    veusz_root = str(VEUSZ_ROOT)
    if veusz_root not in sys.path:
        sys.path.insert(0, veusz_root)
    try:
        from PyQt6 import QtCore, QtGui, QtWidgets  # noqa: F401
        from veusz.helpers import qtloops  # noqa: F401
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"
    return (
        True,
        f"PyQt {QtCore.PYQT_VERSION_STR}; Qt runtime {QtCore.qVersion()}; Veusz qtloops loaded",
    )


def _top_level_symbols(path: Path) -> set[str]:
    """Read a module contract without importing its GUI or renderer graph."""

    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, UnicodeError, SyntaxError):
        return set()
    return {
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
    }


def _vsz_lifecycle_available() -> bool:
    studio_symbols = _top_level_symbols(
        REPO_ROOT / "src" / "sciplot_core" / "studio.py"
    )
    delivery_symbols = _top_level_symbols(
        REPO_ROOT / "src" / "sciplot_core" / "delivery.py"
    )
    return {
        "prepare_studio_document",
        "export_studio_document",
        "publish_studio_export_run",
        "_studio_document_state",
        "_archive_manual_document_if_needed",
    }.issubset(studio_symbols) and "build_delivery_package" in delivery_symbols


def _publication_foundation_available() -> bool:
    """Check the active single-panel publication and QA contract."""

    try:
        profile = get_publication_profile("sciplot_single_panel_v1")
    except Exception:
        return False
    publication_symbols = _top_level_symbols(
        REPO_ROOT / "src" / "sciplot_core" / "publication.py"
    )
    qa_symbols = _top_level_symbols(
        REPO_ROOT / "src" / "sciplot_core" / "qa.py"
    )
    return (
        profile.get("id") == "sciplot_single_panel_v1"
        and profile.get("required_formats") == ["pdf", "tiff_300"]
        and profile.get("integrity", {}).get("scientific_outcome_agnostic") is True
        and profile.get("integrity", {}).get("significance_required") is False
        and {
            "build_publication_intent",
            "build_transform_ledger",
            "write_publication_artifacts",
        }.issubset(publication_symbols)
        and "run_qa" in qa_symbols
    )


def _publication_layout_inventory_available() -> bool:
    """Report deterministic figure-level layout metadata without a UI claim."""

    try:
        layouts = list_composite_layouts()
        profile = get_publication_profile("sciplot_composite_183_v1")
    except Exception:
        return False
    return (
        len(layouts) == 5
        and all(
            float(layout.get("geometry_total_mm") or 0.0) == 183.0
            for layout in layouts
        )
        and profile.get("integrity", {}).get("scientific_outcome_agnostic") is True
        and profile.get("integrity", {}).get("significance_required") is False
    )


def _ready_rule_fixtures_exist(rules: list[Any]) -> tuple[bool, str]:
    missing = [
        rule.rule_id
        for rule in rules
        if rule.fixture_status == "ready"
        and (
            not rule.fixture_path
            or not resolve_fixture_path(str(rule.fixture_path)).exists()
        )
    ]
    return not missing, ", ".join(
        missing
    ) if missing else "all local acceptance fixtures are available"


def _validated_envelope_summary() -> tuple[bool, str, dict[str, Any]]:
    try:
        payload = validated_envelope_status()
    except Exception as exc:
        return (
            False,
            f"{type(exc).__name__}: {exc}",
            {
                "status": "needs_rule_repair",
                "ready_without_ai_rule_count": 0,
                "current_ready_rule_count": 0,
            },
        )
    ready = payload.get("status") == "ready"
    detail = (
        f"{payload.get('ready_without_ai_rule_count', 0)}/"
        f"{payload.get('current_ready_rule_count', 0)} current rule contracts"
    )
    return ready, detail, payload


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
                "markers, and physical frame; explicit heatmap color contract"
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
                "sciplot studio PATH --out outputs/projects "
                "--export pdf,tiff_300 --json"
            ),
            "explicit_intent_entrypoint": (
                "sciplot studio PATH --rule RULE_ID --template TEMPLATE_ID "
                "--out outputs/projects"
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
                "headless": (
                    "sciplot studio PATH --export pdf,tiff_300 --json"
                ),
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
            "developer_validation_routes": ["smoke", "acceptance", "batch"],
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


def _next_actions(required_failures: list[dict[str, Any]]) -> list[str]:
    if not required_failures:
        return [
            "Use the Studio daily entrypoint for deterministic plotting and delivery.",
            "Use Open_in_Veusz.command when the generated document needs manual correction.",
            "Use assisted repair only when the deterministic result reports a blocking state.",
        ]
    actions: list[str] = []
    failed_ids = {str(check["id"]) for check in required_failures}
    if {"pyqt6", "veusz_vendor", "veusz_qt_runtime"} & failed_ids:
        actions.append(
            "Install the Studio dependencies and verify the vendored Veusz runtime."
        )
    if "python_version" in failed_ids:
        actions.append("Use Python 3.11 or newer.")
    if {"ready_rules", "ready_rule_fixtures"} & failed_ids:
        actions.append(
            "Keep automatic plotting limited to fixture-backed ready material rules."
        )
    if "validated_envelopes" in failed_ids:
        actions.append(
            "Re-run ready-rule real-data acceptance and certify the current "
            "deterministic rule contracts before returning ready_to_use."
        )
    if "publication_foundation" in failed_ids:
        actions.append(
            "Restore the single-panel publication profile, lineage contracts, "
            "and artifact QA."
        )
    if "style_template_contract" in failed_ids:
        actions.append(
            "Resolve template-private style or implementation drift before "
            "returning the runtime to daily use."
        )
    if not actions:
        actions.append("Fix the failed required checks before normal use.")
    return actions
__all__ = ["doctor_payload"]
