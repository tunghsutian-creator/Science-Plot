"""Ready-rule intake catalog and managed scientific review notes."""

from __future__ import annotations

from typing import Any
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.materials_rules import get_rule

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
                "label": "拉伸（曲线与重复测量汇总）",
                "rule_id": "tensile_curve",
            },
            {
                "id": "compression_curve",
                "label": "压缩（曲线与重复测量汇总）",
                "rule_id": "compression_curve",
            },
            {
                "id": "flexural_curve",
                "label": "弯曲（曲线与重复测量汇总）",
                "rule_id": "flexural_curve",
            },
            {
                "id": "torque_curve",
                "label": "转矩曲线",
                "rule_id": "torque_curve",
            },
            {
                "id": "impact_metric",
                "label": "冲击",
                "rule_id": "impact_metric",
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


def _catalog_rule_items() -> dict[str, tuple[dict[str, Any], dict[str, Any]]]:
    """Index navigation entries while rejecting ambiguous rule identities."""

    indexed: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for data_type in INTAKE_CATALOG:
        for experiment in data_type["experiments"]:
            rule_id = experiment.get("rule_id")
            if not isinstance(rule_id, str) or not rule_id.strip():
                continue
            normalized = rule_id.strip()
            if normalized in indexed:
                first = indexed[normalized][1]
                raise ValueError(
                    "Intake catalog rule ids must be unique; "
                    f"`{normalized}` is assigned to both `{first['id']}` and "
                    f"`{experiment['id']}`."
                )
            indexed[normalized] = (data_type, experiment)
    return indexed


def _project_experiment(
    experiment: dict[str, Any], *, include_render_options: bool
) -> dict[str, Any]:
    """Project canonical rule capabilities onto one navigation entry."""

    projected = dict(experiment)
    rule_id = experiment.get("rule_id")
    if not isinstance(rule_id, str) or not rule_id.strip():
        return projected
    rule_payload = get_rule(rule_id.strip()).to_payload()
    template = str(rule_payload["template"])
    recommendation = rule_payload["experiment_recommendation"]
    projected.update(
        {
            "template": template,
            "chart": template,
            "presentation_contract": dict(rule_payload["presentation_contract"]),
            "default_replicate_mode": recommendation["default_replicate_mode"],
        }
    )
    if include_render_options:
        projected["render_options"] = dict(rule_payload["render_options"])
    return projected


def _project_data_type(
    data_type: dict[str, Any], *, include_render_options: bool
) -> dict[str, Any]:
    return {
        **data_type,
        "experiments": tuple(
            _project_experiment(
                experiment, include_render_options=include_render_options
            )
            for experiment in data_type["experiments"]
        ),
    }


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
    _catalog_rule_items()
    if include_pending:
        return tuple(
            _project_data_type(data_type, include_render_options=True)
            for data_type in INTAKE_CATALOG
        )
    data_types: list[dict[str, Any]] = []
    for data_type in INTAKE_CATALOG:
        experiments = [
            _project_experiment(experiment, include_render_options=True)
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
    _catalog_rule_items()
    for data_type in INTAKE_CATALOG:
        if data_type["id"] != data_type_id:
            continue
        for experiment in data_type["experiments"]:
            if experiment["id"] == experiment_type_id:
                return (
                    _project_data_type(data_type, include_render_options=False),
                    _project_experiment(experiment, include_render_options=False),
                )
        raise ValueError(
            f"Unknown experiment type `{experiment_type_id}` for data type `{data_type_id}`."
        )
    raise ValueError(f"Unknown data type `{data_type_id}`.")


def _catalog_item_for_rule(
    rule_id: str | None,
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    if not rule_id:
        return None
    matched = _catalog_rule_items().get(rule_id)
    if matched is None:
        return None
    data_type, experiment = matched
    return (
        _project_data_type(data_type, include_render_options=False),
        _project_experiment(experiment, include_render_options=False),
    )
