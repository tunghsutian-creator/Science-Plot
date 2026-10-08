"""Pinned house style resolution and trace; historical unbound revisions stay stable."""
from copy import deepcopy
from typing import Any

from sciplot_core.rendering_contract import contract_value, require_binding, resolved_style_defaults, resolved_style_provenance, load_contract
from sciplot_core.plot_document.errors import fail
from sciplot_core.rendering_contract.legacy_algorithms import require_legacy_algorithms
from .styles import resolve_style


class StyleResolver:
    def __init__(self, spec: dict[str, Any]) -> None:
        self.binding = spec.get("rendering_contract")
        self.trace: dict[str, Any] = {}
        if self.binding is not None:
            require_binding(self.binding)
            self.trace["rendering:algorithm_binding"] = require_legacy_semantics(self.binding)

    def resolve(self, identity: str, kind: str, scopes: list[dict[str, Any]], override: dict[str, Any],
                *, index: int = 0, scope_names: list[str] | None = None) -> dict[str, Any]:
        if self.binding is None:
            return resolve_style(kind, scopes, override)
        result = deepcopy(resolved_style_defaults(kind, series_index=index, binding=self.binding))
        trace = {key: {**record, "source": "RenderingStyleContract"}
                 for key, record in resolved_style_provenance(kind, series_index=index, binding=self.binding).items()}
        names = scope_names or ["project theme", "figure override", "view override", "layer override"]
        for number, scope in enumerate(scopes):
            for key, value in scope.get(kind, {}).items():
                result[key] = deepcopy(value)
                trace[key] = {"value": value, "source": names[number]}
        for key, value in override.items():
            result[key] = deepcopy(value)
            trace[key] = {"value": value, "source": "object override", "semantic_id": identity}
        for key, value in result.items():
            if "color" in key:
                result[key] = value.lower()
                trace[key]["value"] = result[key]
        self.trace[identity] = trace
        return result


def resolved_layout_input(spec: dict[str, Any]) -> tuple[dict[str, Any], dict[str, float] | None]:
    if "rendering_contract" not in spec:
        return spec["layout"], None
    binding = spec["rendering_contract"]
    def value(key: str) -> Any:
        return contract_value(key, binding=binding)
    multi = spec["composition"]["kind"] != "single"
    if multi and "composition_policy" not in spec:
        fail("figure_composition_policy_missing", "Multi-panel house figures require a separate composition policy.",
             "/composition_policy", "policy_identity")
    width, height = float(value("canvas.width_mm")), float(value("canvas.height_mm"))
    gap_x = gap_y = 0.0
    if multi:
        require_binding(spec["composition_policy"])
        gap_x = float(contract_value("gap_x_mm", spec["composition_policy"]))
        gap_y = float(contract_value("gap_y_mm", spec["composition_policy"]))
    # Every supplied number is an explicit layout override. Omission uses the
    # pinned house panel, never an unrecorded beautification heuristic.
    rows, columns = spec["composition"]["rows"], spec["composition"]["columns"]
    defaults: dict[str, Any] = {"width_mm": columns * width + (columns - 1) * gap_x,
        "height_mm": rows * height + (rows - 1) * gap_y,
        "gap_x_mm": gap_x, "gap_y_mm": gap_y,
        "outer_margins_mm": {side: 0.0 for side in ("left", "right", "top", "bottom")},
        "panel_min_height_mm": height, "panel_label_height_mm": 0.0}
    defaults.update(deepcopy(spec["layout"]))
    margins = {side: float(value("frame." + side + "_mm")) for side in ("left", "right", "top", "bottom")}
    return defaults, margins


def require_legacy_semantics(binding: dict[str, Any]) -> dict[str, Any]:
    try:
        return require_legacy_algorithms(binding)
    except ValueError as exc:
        fail("rendering_contract_algorithm_drift", "The pinned rendering algorithm or its policy changed; restore its reviewed runtime.",
             "/rendering_contract", "algorithm_content_identity", detail=str(exc)[:500])


def axis_flow(axis: dict[str, Any], scale: dict[str, Any], resolver: StyleResolver, *, explicit_labels: bool = False) -> None:
    # Shared old semantic tick preparation, independent of native paths/widgets.
    from sciplot_core.studio_render.value_parsing import _log_minor_ticks
    axis.update(text_layout="axis-metric-flow", tick_notation=axis["style"].get(
        "tick_notation", "power10" if scale["transform"] == "log" else "general"),
        minor_ticks=_log_minor_ticks(*scale["domain"], scale=scale["transform"], major_ticks=tuple(axis["ticks"])))
    if explicit_labels:
        axis["tick_notation"] = "labels"
        resolver.trace[axis["id"] + ":tick_labels"] = {"value": axis["tick_labels"], "source": "object override"}
    if "label_runs" in axis:
        resolver.trace[axis["id"] + ":label_runs"] = {"value": axis["label_runs"], "source": "object override"}
    trace = resolver.trace[axis["id"]]["minor_tick_count"]
    if scale["transform"] == "log" and trace["source"] == "RenderingStyleContract":
        axis["style"]["minor_tick_count"] = int(contract_value("axis.log_minor_tick_count", resolver.binding))
        trace.update(load_contract()["properties"]["axis.log_minor_tick_count"], contract_property="axis.log_minor_tick_count")
    resolver.trace[axis["id"] + ":tick_policy"] = {
        "tick_notation": axis["tick_notation"], "minor_ticks": axis["minor_ticks"],
        "source": resolver.trace[axis["id"]].get("tick_notation", {}).get("source", "scale notation policy"),
        "algorithm_binding": resolver.trace["rendering:algorithm_binding"],
    }
