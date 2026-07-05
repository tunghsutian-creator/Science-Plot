from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

from sciplot_core.materials_rules import iter_rules
from sciplot_core.render import json_safe
from sciplot_core.studio import VEUSZ_ROOT, _ensure_veusz_on_path

REPO_ROOT = Path(__file__).resolve().parents[2]


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


def doctor_payload() -> dict[str, Any]:
    rules = list(iter_rules())
    ready_rules = [rule for rule in rules if rule.fixture_status == "ready"]
    pending_rules = [rule for rule in rules if rule.fixture_status != "ready"]

    _ensure_veusz_on_path()
    checks = [
        _check(
            "python_version",
            "Python 3.11+",
            sys.version_info >= (3, 11),
            detail=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        ),
        _check("repo_root", "SciPlot repo root", (REPO_ROOT / "pyproject.toml").exists(), detail=str(REPO_ROOT)),
        _check("veusz_vendor", "Vendored Veusz runtime", VEUSZ_ROOT.exists(), detail=str(VEUSZ_ROOT)),
        _check("pyqt6", "PyQt6 available", _module_available("PyQt6")),
        _check("veusz_import", "Veusz importable", _module_available("veusz")),
        _check(
            "skill_wrapper",
            "Skill wrapper executable",
            (REPO_ROOT / "skill" / "scripts" / "sciplot").exists(),
            detail=str(REPO_ROOT / "skill" / "scripts" / "sciplot"),
        ),
        _check("ready_rules", "Ready material rules", len(ready_rules) >= 5, detail=str(len(ready_rules))),
    ]
    required_failures = [check for check in checks if check["required"] and check["status"] != "passed"]
    return {
        "kind": "sciplot_doctor",
        "status": "ready" if not required_failures else "blocked",
        "repo_root": str(REPO_ROOT),
        "normal_mode": {
            "daily_entrypoint": "sciplot studio PATH --out outputs/intake_projects",
            "frontend_default": "independent",
            "codex_required": False,
            "user_switch_required": False,
        },
        "rule_summary": {
            "total": len(rules),
            "ready": len(ready_rules),
            "pending": len(pending_rules),
        },
        "checks": checks,
        "next_actions": _next_actions(required_failures),
    }


def _next_actions(required_failures: list[dict[str, Any]]) -> list[str]:
    if not required_failures:
        return [
            "Open the frontend or Studio normally; it starts in independent mode.",
            "Use Codex assisted mode only by launching a Codex-controlled repair or plotting job.",
        ]
    actions: list[str] = []
    failed_ids = {str(check["id"]) for check in required_failures}
    if {"pyqt6", "veusz_import", "veusz_vendor"} & failed_ids:
        actions.append("Install the Studio extras and verify the vendored Veusz runtime before launching Studio.")
    if "python_version" in failed_ids:
        actions.append("Use Python 3.11 or newer.")
    if "ready_rules" in failed_ids:
        actions.append("Mark only fixture-backed material rules as ready before alpha use.")
    if not actions:
        actions.append("Fix the failed required checks before normal use.")
    return actions


def print_doctor(payload: dict[str, Any]) -> None:
    print(json.dumps(json_safe(payload), indent=2, ensure_ascii=False))


__all__ = ["doctor_payload", "print_doctor"]
