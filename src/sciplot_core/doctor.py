from __future__ import annotations

import ast
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

from sciplot_core._utils import json_safe
from sciplot_core.materials_rules import iter_rules
from sciplot_core.publication import (
    get_publication_profile,
    list_composite_layouts,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
VEUSZ_ROOT = REPO_ROOT / "third_party" / "veusz"


def _check(check_id: str, label: str, passed: bool, *, required: bool = True, detail: str = "") -> dict[str, Any]:
    return {
        "id": check_id,
        "label": label,
        "status": "passed" if passed else "failed",
        "required": required,
        "detail": detail,
    }


def _module_available(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


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
    studio_symbols = _top_level_symbols(REPO_ROOT / "src" / "sciplot_core" / "studio.py")
    delivery_symbols = _top_level_symbols(REPO_ROOT / "src" / "sciplot_core" / "delivery.py")
    return {
        "prepare_studio_document",
        "export_studio_document",
        "publish_studio_export_run",
        "_studio_document_state",
        "_archive_manual_document_if_needed",
    }.issubset(studio_symbols) and "build_delivery_package" in delivery_symbols


def _publication_foundation_available() -> bool:
    try:
        layouts = list_composite_layouts()
        profile = get_publication_profile("sciplot_composite_183_v1")
    except Exception:
        return False
    return (
        len(layouts) == 5
        and all(float(layout.get("geometry_total_mm") or 0.0) == 183.0 for layout in layouts)
        and profile.get("integrity", {}).get("scientific_outcome_agnostic") is True
        and profile.get("integrity", {}).get("significance_required") is False
    )


def _ready_rule_fixtures_exist(rules: list[Any]) -> tuple[bool, str]:
    missing = [
        rule.rule_id
        for rule in rules
        if rule.fixture_status == "ready"
        and (not rule.fixture_path or not (REPO_ROOT / str(rule.fixture_path)).exists())
    ]
    return not missing, ", ".join(missing) if missing else "all ready rules are fixture-backed"


def doctor_payload() -> dict[str, Any]:
    rules = list(iter_rules())
    ready_rules = [rule for rule in rules if rule.fixture_status == "ready"]
    pending_rules = [rule for rule in rules if rule.fixture_status != "ready"]
    fixtures_ok, fixture_detail = _ready_rule_fixtures_exist(rules)

    checks = [
        _check(
            "python_version",
            "Python 3.11+",
            sys.version_info >= (3, 11),
            detail=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        ),
        _check("repo_root", "SciPlot repo root", (REPO_ROOT / "pyproject.toml").exists(), detail=str(REPO_ROOT)),
        _check(
            "veusz_vendor",
            "Vendored Veusz runtime",
            (VEUSZ_ROOT / "veusz" / "__init__.py").exists(),
            detail=str(VEUSZ_ROOT),
        ),
        _check("pyqt6", "PyQt6 available", _module_available("PyQt6")),
        _check(
            "vsz_lifecycle",
            "VSZ authority, history, exact export, and delivery hash gate",
            _vsz_lifecycle_available(),
            detail="studio/document.vsz -> Veusz -> exact edited export",
        ),
        _check(
            "publication_foundation",
            "Publication intent, lineage, 183 mm composition, and artifact QA",
            _publication_foundation_available(),
            detail="183 mm canvas -> evidence/transform contracts -> PDF/TIFF publication QA",
        ),
        _check(
            "skill_wrapper",
            "Skill wrapper executable",
            (REPO_ROOT / "skill" / "scripts" / "sciplot").exists(),
            detail=str(REPO_ROOT / "skill" / "scripts" / "sciplot"),
        ),
        _check("ready_rules", "Ready material rules", len(ready_rules) >= 5, detail=str(len(ready_rules))),
        _check("ready_rule_fixtures", "Ready-rule fixtures", fixtures_ok, detail=fixture_detail),
    ]
    required_failures = [check for check in checks if check["required"] and check["status"] != "passed"]
    layouts = list_composite_layouts()
    return {
        "kind": "sciplot_doctor",
        "status": "ready" if not required_failures else "blocked",
        "repo_root": str(REPO_ROOT),
        "normal_mode": {
            "daily_entrypoint": "sciplot studio PATH --out outputs/projects --export pdf,tiff_300 --json",
            "frontend_default": "independent",
            "codex_required": False,
            "user_switch_required": False,
        },
        "vsz_lifecycle": {
            "canonical_artifact": "studio/document.vsz",
            "advanced_editor": "veusz",
            "open_preserves_document": True,
            "manual_edit_detection": "sha256",
            "archive_before_explicit_regeneration": True,
            "export_exact_current_document": True,
            "delivery_requires_matching_vsz_hash": True,
        },
        "publication_foundation": {
            "composite_canvas_width_mm": 183.0,
            "nominal_panel_widths_mm": [60.0, 90.0, 120.0, 180.0],
            "layout_ids": [layout["id"] for layout in layouts],
            "default_profile": "sciplot_single_panel_v1",
            "composite_profile": "sciplot_composite_183_v1",
            "official_profile": "nature_flagship_research_2026_v1",
            "scientific_outcome_agnostic": True,
            "silent_data_omission_allowed": False,
        },
        "rule_summary": {
            "total": len(rules),
            "ready": len(ready_rules),
            "pending": len(pending_rules),
            "automatic_match_scope": "ready_only",
        },
        "checks": checks,
        "next_actions": _next_actions(required_failures),
    }


def _next_actions(required_failures: list[dict[str, Any]]) -> list[str]:
    if not required_failures:
        return [
            "Use the Studio daily entrypoint for deterministic plotting and delivery.",
            "Open Open_in_Veusz.command only when advanced correction is needed.",
            "Use assisted repair only when the deterministic result reports a blocking state.",
        ]
    actions: list[str] = []
    failed_ids = {str(check["id"]) for check in required_failures}
    if {"pyqt6", "veusz_vendor"} & failed_ids:
        actions.append("Install the Studio dependencies and verify the vendored Veusz runtime.")
    if "python_version" in failed_ids:
        actions.append("Use Python 3.11 or newer.")
    if {"ready_rules", "ready_rule_fixtures"} & failed_ids:
        actions.append("Keep automatic plotting limited to fixture-backed ready material rules.")
    if "publication_foundation" in failed_ids:
        actions.append("Restore publication profiles, 183 mm layouts, lineage contracts, and artifact QA.")
    if not actions:
        actions.append("Fix the failed required checks before normal use.")
    return actions


def print_doctor(payload: dict[str, Any]) -> None:
    print(json.dumps(json_safe(payload), indent=2, ensure_ascii=False))


__all__ = ["doctor_payload", "print_doctor"]
