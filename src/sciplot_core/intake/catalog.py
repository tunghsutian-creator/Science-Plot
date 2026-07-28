"""Ready-rule intake catalog and managed scientific review notes."""

from __future__ import annotations

from typing import Any
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.materials_rules import get_rule
from sciplot_core.policy import (
    FTIR_SPECTRUM_RENDER_OPTIONS,
    TORQUE_OFFSET_STACK_RENDER_OPTIONS,
)

from .config import (
    APPROVED_INTAKE_SIZE_PRESETS,
    SAXS_SCALING_REVIEW_NOTE,
    _LEGACY_SAXS_SCALING_REVIEW_NOTE_PREFIX,
)


def converge_material_review_notes(request: dict[str, Any]) -> bool:
    """Converge managed scientific review notes from the final rule id."""

    original = (
        list(request.get("review_notes"))
        if isinstance(request.get("review_notes"), list)
        else []
    )
    notes = [
        str(value)
        for value in original
        if str(value) != SAXS_SCALING_REVIEW_NOTE
        and not str(value).startswith(_LEGACY_SAXS_SCALING_REVIEW_NOTE_PREFIX)
    ]
    if str(request.get("rule_id") or "").strip() == "saxs_profile":
        notes.append(SAXS_SCALING_REVIEW_NOTE)
    request["review_notes"] = notes
    return notes != original


INTAKE_CATALOG: tuple[dict[str, Any], ...] = (
    {
        "id": "rheology_dma",
        "label": "流变 / DMA",
        "icon": "curves",
        "experiments": (
            {
                "id": "rheology_frequency_sweep",
                "label": "频率扫描",
                "rule_id": "rheology_frequency_sweep",
            },
            {
                "id": "rheology_temperature_sweep",
                "label": "温度扫描",
                "rule_id": "rheology_temperature_sweep",
            },
            {
                "id": "rheology_stress_relaxation",
                "label": "应力松弛",
                "rule_id": "rheology_stress_relaxation",
            },
            {"id": "rheology_creep", "label": "蠕变", "rule_id": "rheology_creep"},
            {
                "id": "rheology_time_sweep",
                "label": "时间扫描",
                "rule_id": "rheology_time_sweep",
            },
            {
                "id": "rheology_strain_sweep",
                "label": "应变扫描",
                "rule_id": "rheology_strain_sweep",
            },
            {
                "id": "rheology_stress_sweep",
                "label": "应力扫描",
                "rule_id": "rheology_stress_sweep",
            },
            {
                "id": "dma_temperature_sweep",
                "label": "DMA 温扫",
                "rule_id": "dma_temperature_sweep",
            },
            {
                "id": "dma_frequency_sweep",
                "label": "DMA 频扫",
                "rule_id": "dma_frequency_sweep",
            },
            {"id": "unknown_rheology", "label": "未知流变", "rule_id": None},
        ),
    },
    {
        "id": "mechanical",
        "label": "力学",
        "icon": "tensile",
        "experiments": (
            {
                "id": "tensile_curve",
                "label": "拉伸曲线",
                "rule_id": "tensile_curve",
                "default_replicate_mode": "representative",
            },
            {
                "id": "tensile_strength",
                "label": "拉伸强度",
                "rule_id": "tensile_curve",
                "chart": "box_strip",
                "template": "box_strip",
            },
            {
                "id": "elongation_at_break",
                "label": "断裂伸长率",
                "rule_id": "tensile_curve",
                "chart": "box_strip",
                "template": "box_strip",
            },
            {
                "id": "youngs_modulus",
                "label": "杨氏模量",
                "rule_id": "tensile_curve",
                "chart": "box_strip",
                "template": "box_strip",
            },
            {
                "id": "compression_curve",
                "label": "压缩",
                "rule_id": "compression_curve",
            },
            {"id": "flexural_curve", "label": "弯曲", "rule_id": "flexural_curve"},
            {
                "id": "torque_curve",
                "label": "转矩曲线",
                "rule_id": "torque_curve",
                "chart": "curve",
            },
            {
                "id": "torque_offset_stack",
                "label": "转矩偏移堆积",
                "rule_id": "torque_curve",
                "chart": "stacked_curve",
                "template": "stacked_curve",
                "render_options": dict(TORQUE_OFFSET_STACK_RENDER_OPTIONS),
            },
            {
                "id": "impact_metric",
                "label": "冲击",
                "rule_id": "impact_metric",
                "chart": "box_strip",
                "template": "box_strip",
                "default_replicate_mode": "individual",
            },
            {"id": "unknown_mechanical", "label": "未知力学", "rule_id": None},
        ),
    },
    {
        "id": "thermal",
        "label": "热分析",
        "icon": "thermal",
        "experiments": (
            {
                "id": "dsc_curve",
                "label": "DSC",
                "rule_id": "dsc_curve",
                "chart": "stacked_curve",
            },
            {"id": "tga_curve", "label": "TGA", "rule_id": "tga_curve"},
            {"id": "dtg_curve", "label": "DTG", "rule_id": "dtg_curve"},
            {"id": "unknown_thermal", "label": "未知热分析", "rule_id": None},
        ),
    },
    {
        "id": "spectroscopy",
        "label": "光谱",
        "icon": "spectrum",
        "experiments": (
            {
                "id": "ftir_spectrum",
                "label": "FTIR",
                "rule_id": "ftir_spectrum",
                "chart": "stacked_curve",
                "template": "stacked_curve",
                "render_options": dict(FTIR_SPECTRUM_RENDER_OPTIONS),
            },
            {"id": "uvvis_spectrum", "label": "UV-vis", "rule_id": "uvvis_spectrum"},
            {"id": "unknown_spectroscopy", "label": "未知光谱", "rule_id": None},
        ),
    },
    {
        "id": "scattering",
        "label": "衍射 / 散射",
        "icon": "scattering",
        "experiments": (
            {"id": "xrd_pattern", "label": "XRD", "rule_id": "xrd_pattern"},
            {"id": "saxs_profile", "label": "SAXS", "rule_id": "saxs_profile"},
            {"id": "unknown_scattering", "label": "未知散射", "rule_id": None},
        ),
    },
    {
        "id": "chromatography",
        "label": "色谱 / 分子量",
        "icon": "chromatography",
        "experiments": (
            {
                "id": "gpc_sec_chromatogram",
                "label": "GPC / SEC",
                "rule_id": "gpc_sec_chromatogram",
            },
            {"id": "unknown_chromatography", "label": "未知色谱", "rule_id": None},
        ),
    },
    {
        "id": "metrics_time",
        "label": "指标 / 时序",
        "icon": "metrics",
        "experiments": (
            {"id": "swelling_curve", "label": "溶胀", "rule_id": "swelling_curve"},
            {
                "id": "performance_comparison",
                "label": "材料性能对比",
                "rule_id": "performance_comparison",
                "chart": "scatter",
                "template": "scatter",
                "render_options": {"size": "120x55"},
            },
            {"id": "unknown_metrics", "label": "未知指标", "rule_id": None},
        ),
    },
    {
        "id": "unknown",
        "label": "未知",
        "icon": "unknown",
        "experiments": ({"id": "unknown", "label": "未知", "rule_id": None},),
    },
)


def _rule_is_ready_for_public_catalog(rule_id: str | None) -> bool:
    if not rule_id:
        return True
    try:
        return get_rule(rule_id).fixture_status == "ready"
    except ValueError:
        return False


def _public_intake_catalog(
    *, include_pending: bool = False
) -> tuple[dict[str, Any], ...]:
    if include_pending:
        return INTAKE_CATALOG
    data_types: list[dict[str, Any]] = []
    for data_type in INTAKE_CATALOG:
        experiments = [
            experiment
            for experiment in data_type["experiments"]
            if _rule_is_ready_for_public_catalog(experiment.get("rule_id"))
        ]
        if not experiments:
            continue
        data_types.append({**data_type, "experiments": tuple(experiments)})
    return tuple(data_types)


def intake_catalog_payload(*, include_pending: bool = False) -> dict[str, Any]:
    catalog = _public_intake_catalog(include_pending=include_pending)
    visible_rules = {
        str(experiment.get("rule_id"))
        for data_type in catalog
        for experiment in data_type["experiments"]
        if experiment.get("rule_id")
    }
    return {
        "kind": "sciplot_intake_catalog",
        "visibility": "all" if include_pending else "ready",
        "ready_rule_ids": sorted(visible_rules),
        "data_types": json_safe(catalog),
        "figure_size_presets": list(APPROVED_INTAKE_SIZE_PRESETS),
    }


def _catalog_item(
    data_type_id: str, experiment_type_id: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    for data_type in INTAKE_CATALOG:
        if data_type["id"] != data_type_id:
            continue
        for experiment in data_type["experiments"]:
            if experiment["id"] == experiment_type_id:
                return data_type, experiment
        raise ValueError(
            f"Unknown experiment type `{experiment_type_id}` for data type `{data_type_id}`."
        )
    raise ValueError(f"Unknown data type `{data_type_id}`.")


def _catalog_item_for_rule(
    rule_id: str | None,
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    if not rule_id:
        return None
    for data_type in INTAKE_CATALOG:
        for experiment in data_type["experiments"]:
            if experiment.get("rule_id") == rule_id:
                return data_type, experiment
    return None
