"""Resolve only supported scientific choices; retain fresh source-bound plans."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pandas as pd

from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.foundation.json_io import atomic_write_json
from sciplot_core.foundation.source_tree import source_tree_sha256
from sciplot_core.materials_rules.catalog import iter_public_rules
from sciplot_core.plan_preview import build_plan_preview
from sciplot_core.render import inspect_payload
from sciplot_core.semantic import classify_source
from sciplot_core.source_tables import read_raw_table
from sciplot_core.studio_core.project_query_paths import canonical_path
from sciplot_core.task_contract import TaskControlError


def assert_source_current(state: dict[str, Any]) -> Path:
    source = canonical_path(Path(state["request"]["source"]))
    digest = source_tree_sha256(source)
    if digest is None or digest != state["source_sha256"]:
        raise TaskControlError(
            "source_changed", "原始文件已变化。请用当前文件开始新任务，原任务不会覆盖数据。",
        )
    return source


def _profile_signature(source: Path, rule: str) -> dict[str, Any]:
    # An explicitly requested rule returns rule defaults without reading the
    # source. It therefore cannot establish whether a saved profile applies.
    if not source.is_file() or source.suffix.casefold() not in {".csv", ".tsv", ".txt", ".xlsx", ".xlsm"}:
        raise TaskControlError("profile_unavailable", "目前仅规范三行表头的单文件配对曲线支持保存配置；目录和专用仪器格式仍使用新计划。")
    worksheet: str | None = None
    if source.suffix.casefold() in {".xlsx", ".xlsm"}:
        with pd.ExcelFile(source) as workbook:
            if len(workbook.sheet_names) != 1:
                raise TaskControlError("profile_unavailable", "多工作表来源不能自动复用此配置，请明确本次实验。")
            worksheet = str(workbook.sheet_names[0])
    raw = read_raw_table(source, preserve_na_tokens=True)
    if raw.shape[0] < 4 or raw.shape[1] < 2 or raw.shape[1] % 2:
        raise TaskControlError("profile_unavailable", "配置需要列名、单位、样品三行元数据及明确的配对数据列。")
    rows = [[str(raw.iat[row, col]).strip() for col in range(raw.shape[1])] for row in range(3)]
    for row in rows:
        for text in row:
            if not text or text.casefold() in {"nan", "none"}:
                raise TaskControlError("profile_unavailable", "缺失表头或单位时不能自动复用配置。")
            try:
                float(text)
            except ValueError:
                continue
            raise TaskControlError("profile_unavailable", "未找到完整三行文字元数据，不能把数值当作导入配置。")
    pairs = [(rows[0][col:col + 2], rows[1][col:col + 2]) for col in range(0, raw.shape[1], 2)]
    if any(pair != pairs[0] for pair in pairs) or any(rows[2][col] != rows[2][col + 1] for col in range(0, raw.shape[1], 2)):
        raise TaskControlError("profile_unavailable", "仅列名及单位一致、样品成对对应的规范曲线可保存此配置。")
    try:
        starts_with_data = all(math.isfinite(float(str(raw.iat[3, col]))) for col in range(raw.shape[1]))
    except (TypeError, ValueError):
        starts_with_data = False
    if not starts_with_data:
        raise TaskControlError("profile_unavailable", "三行表头后不是明确的数值数据，不能自动复用配置。")
    semantics = classify_source(source)
    if semantics.get("rule_id") != rule:
        raise TaskControlError("profile_not_applicable", "当前来源的独立识别结果与保存的实验规则不一致，必须重新确认。")
    return {
        "source_type": source.suffix.casefold(), "worksheet": worksheet,
        "layout": "paired_columns_with_three_metadata_rows",
        "rule_id": semantics["rule_id"],
        "column_names": pairs[0][0], "declared_units": pairs[0][1],
    }


def _profile_selection(source: Path, path: Path) -> dict[str, Any]:
    profile = json.loads(canonical_path(path).read_text())
    if (
        not isinstance(profile, dict)
        or profile.get("kind") != "sciplot_task_profile"
        or profile.get("version") != 2
        or set(profile) != {"kind", "version", "selection", "signature", "sha256"}
    ):
        raise TaskControlError("invalid_profile", "配置文件格式不匹配。")
    if canonical_json_sha256(
        {key: value for key, value in profile.items() if key != "sha256"},
        allow_nan=False,
    ) != profile["sha256"]:
        raise TaskControlError("profile_changed", "保存的配置发生变化，请重新选择。")
    selected = profile["selection"]
    if (
        not isinstance(selected, dict)
        or set(selected) != {"rule_id", "template"}
        or not all(isinstance(value, str) and value for value in selected.values())
    ):
        raise TaskControlError("invalid_profile", "配置缺少规则与模板。")
    if _profile_signature(source, selected["rule_id"]) != profile["signature"]:
        raise TaskControlError("profile_not_applicable", "当前文件不适用此配置，请重新确认实验。")
    return dict(selected)


def _needs_rule_choice(
    state: dict[str, Any], *, reason_code: str, message: str,
    evidence: str | None = None,
) -> None:
    state.pop("blocker", None)
    state.update({
        "status": "needs_input", "phase": "scientific_choice",
        "question": {
            "reason_code": reason_code, "message": message,
            "field": "rule_id", "evidence": evidence,
            "choices": [{"rule_id": rule.rule_id, "x": rule.x_axis.display_label,
                         "y": rule.y_axis.display_label,
                         "templates": list(rule.presentation_templates)}
                        for rule in iter_public_rules()],
        },
    })


def plan_task(root: Path, state: dict[str, Any]) -> dict[str, Any] | None:
    source = assert_source_current(state)
    request = state["request"]
    selected = dict(state.get("selection") or {
        key: request[key] for key in ("rule_id", "template") if key in request
    })
    if not selected and request.get("profile"):
        try:
            selected = _profile_selection(source, Path(request["profile"]))
        except (TaskControlError, OSError, ValueError) as exc:
            _needs_rule_choice(state, reason_code=getattr(exc, "reason_code", "invalid_profile"),
                               message=f"此配置不能用于当前来源：{exc} 请重新确认实验规则。")
            return None
    if "rule_id" not in selected:
        try:
            inspection = inspect_payload(source)
        except (OSError, ValueError, TypeError) as exc:
            inspection = {"inspection_error": str(exc)}
        resolution = inspection.get("inspection_resolution") or {}
        if resolution.get("status") == "ready_rule_authoritative":
            selected["rule_id"] = resolution["rule_id"]
        else:
            atomic_write_json(root / "inspection.json", inspection)
            _needs_rule_choice(state, reason_code="rule_selection_required",
                message="尚不能确定实验类型。请选择与原始数据实际含义一致的实验。",
                evidence=str(root / "inspection.json"))
            return None
    plan = dict(build_plan_preview(source, request=selected))
    atomic_write_json(root / "plan.json", plan)
    state["selection"] = {"rule_id": plan["rule_id"], "template": plan["template"]}
    if plan["status"] == "blocked":
        blocker_value = plan["blocker"]
        blocker = blocker_value if isinstance(blocker_value, dict) else {}
        reason = str(blocker.get("reason_code", "plan_blocked"))
        if reason in {"plan_rule_invalid", "plan_rule_unknown", "plan_template_unsupported"} or (
            "question" in state and reason.endswith("_transform_invalid")
        ):
            _needs_rule_choice(state, reason_code=reason,
                message=f"当前选择无法用于此来源：{blocker.get('message', '')} 请更正实验规则或模板。",
                evidence=str(root / "plan.json"))
            return None
        state.update({"status": "blocked", "phase": "planning", "blocker": plan["blocker"]})
        return None
    state.pop("question", None)
    return plan


def save_profile(root: Path, state: dict[str, Any]) -> None:
    source = assert_source_current(state)
    selection = state["selection"]
    if not isinstance(selection.get("rule_id"), str):
        return
    try:
        signature = _profile_signature(source, selection["rule_id"])
    except (TaskControlError, OSError, ValueError) as exc:
        state["profile"] = None
        state["profile_unavailable"] = {"reason_code": getattr(exc, "reason_code", "profile_unavailable"), "message": str(exc)}
        return
    profile = {
        "kind": "sciplot_task_profile", "version": 2,
        "selection": selection,
        "signature": signature,
    }
    profile["sha256"] = canonical_json_sha256(profile, allow_nan=False)
    atomic_write_json(root / "profile.json", profile)
    state.pop("profile_unavailable", None)
    state["profile"] = str(root / "profile.json")
