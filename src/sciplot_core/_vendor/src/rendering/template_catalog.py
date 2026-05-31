from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from src.plot_contract import template_contract, template_names
from src.rendering.dataset_models import DataShape, RoleKey
from src.rendering.template_lifecycle import template_identity


@dataclass(frozen=True)
class TemplateSpec:
    id: str
    label: str
    supported_shapes: tuple[DataShape, ...]
    required_roles: tuple[RoleKey, ...]
    optional_roles: tuple[RoleKey, ...]
    preview_priority: int
    scientific_tags: tuple[str, ...]
    family: str
    canonical_id: str
    role: str
    lifecycle_policy: str
    implementation_id: str


class TemplateCatalog(Protocol):
    def list_templates(self) -> tuple[TemplateSpec, ...]: ...

    def get(self, template_id: str) -> TemplateSpec: ...


def _supported_shapes(template_id: str) -> tuple[DataShape, ...]:
    if template_id in {
        "curve",
        "function_curve",
        "point_line",
        "area_curve",
        "step_line",
        "stacked_area",
        "scatter",
        "bubble_scatter",
        "scatter_fit",
        "mean_band",
        "stacked_curve",
        "segmented_stacked_curve",
    }:
        return ("curve_like",)
    if template_id in {
        "bar",
        "box",
        "box_strip",
        "violin",
        "violin_box",
        "point_error",
        "lollipop_error",
        "density_area",
    }:
        return ("replicate_table", "distribution")
    if template_id == "histogram_density":
        return ("replicate_table", "distribution")
    if template_id in {"heatmap", "annotated_heatmap"}:
        return ("matrix",)
    if template_id == "contour_field":
        return ("matrix", "scalar_field")
    if template_id == "polar_curve":
        return ("curve_like", "polar")
    if template_id == "table_figure":
        return ("table",)
    return ()


def _scientific_tags(template_id: str) -> tuple[str, ...]:
    if template_id in {
        "curve",
        "function_curve",
        "point_line",
        "area_curve",
        "step_line",
        "stacked_area",
        "scatter",
        "bubble_scatter",
        "scatter_fit",
        "mean_band",
        "stacked_curve",
        "segmented_stacked_curve",
    }:
        return ("curve", "spectra")
    if template_id in {
        "bar",
        "box",
        "box_strip",
        "violin",
        "violin_box",
        "point_error",
        "lollipop_error",
        "histogram_density",
        "density_area",
    }:
        return ("distribution", "statistics")
    if template_id in {"heatmap", "annotated_heatmap"}:
        return ("matrix", "heatmap")
    if template_id == "contour_field":
        return ("matrix", "contour")
    if template_id == "polar_curve":
        return ("curve", "polar")
    if template_id == "table_figure":
        return ("table",)
    return ()


def _family(template_id: str) -> str:
    if template_id in {
        "curve",
        "function_curve",
        "point_line",
        "area_curve",
        "step_line",
        "stacked_area",
        "scatter",
        "bubble_scatter",
        "scatter_fit",
        "mean_band",
        "stacked_curve",
        "segmented_stacked_curve",
    }:
        return "curve"
    if template_id in {
        "bar",
        "box",
        "box_strip",
        "violin",
        "violin_box",
        "point_error",
        "lollipop_error",
        "histogram_density",
        "density_area",
    }:
        return "statistics"
    if template_id in {"heatmap", "annotated_heatmap"}:
        return "heatmap"
    if template_id == "contour_field":
        return "heatmap"
    if template_id == "polar_curve":
        return "curve"
    if template_id == "table_figure":
        return "table"
    return "other"


def _preview_priority(template_id: str) -> int:
    if template_id == "curve":
        return 100
    if template_id == "function_curve":
        return 76
    if template_id == "area_curve":
        return 94
    if template_id == "point_line":
        return 95
    if template_id == "step_line":
        return 88
    if template_id == "stacked_area":
        return 82
    if template_id == "mean_band":
        return 91
    if template_id == "scatter_fit":
        return 87
    if template_id == "scatter":
        return 80
    if template_id == "bubble_scatter":
        return 79
    if template_id == "annotated_heatmap":
        return 91
    if template_id == "heatmap":
        return 90
    if template_id == "contour_field":
        return 86
    if template_id == "polar_curve":
        return 75
    if template_id == "table_figure":
        return 65
    if template_id == "box_strip":
        return 84
    if template_id == "violin_box":
        return 83
    if template_id == "point_error":
        return 81
    if template_id == "lollipop_error":
        return 80
    if template_id == "histogram_density":
        return 78
    if template_id == "density_area":
        return 79
    if template_id in {"bar", "box", "violin"}:
        return 70
    return 60


class ContractTemplateCatalog:
    def list_templates(self) -> tuple[TemplateSpec, ...]:
        specs: list[TemplateSpec] = []
        for template_id in template_names():
            contract = template_contract(template_id)
            identity = template_identity(template_id)
            specs.append(
                TemplateSpec(
                    id=template_id,
                    label=contract.label,
                    supported_shapes=_supported_shapes(template_id),
                    required_roles=(),
                    optional_roles=tuple(contract.editable_options),
                    preview_priority=_preview_priority(template_id),
                    scientific_tags=_scientific_tags(template_id),
                    family=_family(template_id),
                    canonical_id=identity.canonical_id,
                    role=identity.role,
                    lifecycle_policy=identity.lifecycle_policy,
                    implementation_id=identity.implementation_id,
                )
            )
        return tuple(specs)

    def get(self, template_id: str) -> TemplateSpec:
        for spec in self.list_templates():
            if spec.id == template_id:
                return spec
        raise ValueError(f"Unknown template: {template_id}")


DEFAULT_TEMPLATE_CATALOG = ContractTemplateCatalog()


__all__ = [
    "ContractTemplateCatalog",
    "DEFAULT_TEMPLATE_CATALOG",
    "TemplateCatalog",
    "TemplateSpec",
]
