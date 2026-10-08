"""Reference, scientific scale and composition validation before any rendering."""
from copy import deepcopy
from typing import Any

from sciplot_core.plot_document.errors import fail
from sciplot_core.plot_document.validation import validate_wire
from sciplot_core.plot_transforms.datasets import validate_dataset

from .schema import figure_spec_schema, figure_layout_schema
from .styles import STYLE_FIELDS


def _check(condition: bool, code: str, message: str, path: str) -> None:
    if not condition:
        fail(code, message, path, code.removeprefix("figure_"))


def _identities(spec: dict[str, Any]) -> None:
    ids = [spec["id"]]
    ids += [item["id"] for item in spec["scales"] + spec["guides"] + spec["annotations"] + spec["composition"]["resolve"]]
    for view in spec["views"]:
        ids.append(view["id"])
        ids += [axis["id"] for axis in view["axes"]]
        for layer in view["layers"]:
            ids.append(layer["id"])
            ids += [mark["id"] for mark in layer["marks"]]
    _check(len(ids) == len(set(ids)), "figure_duplicate_id", "Every semantic identity must be unique across the figure.", "/")


def _composition(spec: dict[str, Any]) -> None:
    views = {view["id"]: view for view in spec["views"]}
    composition = spec["composition"]
    cells = composition["cells"]
    _check({cell["view_id"] for cell in cells} == set(views) and len(cells) == len(views),
        "figure_cell_membership", "Each view must occupy exactly one declared grid cell.", "/composition/cells")
    _check(len({(cell["row"], cell["column"]) for cell in cells}) == len(cells),
        "figure_cell_overlap", "Two views cannot occupy the same grid cell.", "/composition/cells")
    _check(all(cell["row"] < composition["rows"] and cell["column"] < composition["columns"] for cell in cells),
        "figure_cell_bounds", "Grid cell positions must be inside declared rows and columns.", "/composition/cells")
    _check(len(composition["row_weights"]) == composition["rows"] and len(composition["column_weights"]) == composition["columns"],
        "figure_grid_weights", "Each declared row and column requires one positive weight.", "/composition")
    kind = composition["kind"]
    _check(kind != "single" or len(views) == composition["rows"] == composition["columns"] == 1,
        "figure_single_composition", "Single composition has exactly one cell and view.", "/composition")
    _check(kind != "hconcat" or composition["rows"] == 1, "figure_concat_dimensions", "Horizontal concat has one row.", "/composition")
    _check(kind != "vconcat" or composition["columns"] == 1, "figure_concat_dimensions", "Vertical concat has one column.", "/composition")
    declared: dict[tuple[str, str, str], str] = {}
    for group in composition["resolve"]:
        _check(set(group["views"]) <= set(views), "figure_resolve_reference", "Resolve groups name existing views.", "/composition/resolve")
        for axis in ("x", "y"):
            sets = [{layer[axis + "_scale"] for layer in views[name]["layers"]} for name in group["views"]]
            if group[axis] == "shared":
                _check(all(item == sets[0] for item in sets), "figure_shared_scale_conflict",
                    "Shared scales require identical explicit scale IDs, dimensions, units and scientific quantities.", "/composition/resolve")
            else:
                _check(sum(map(len, sets)) == len(set.union(*sets)), "figure_independent_scale_conflict",
                    "Independent scale resolution cannot reference the same scale identity across views.", "/composition/resolve")
            for a in group["views"]:
                for b in group["views"]:
                    if a >= b:
                        continue
                    key = (axis, a, b)
                    _check(key not in declared or declared[key] == group[axis], "figure_resolve_conflict",
                        "Overlapping resolve groups cannot disagree.", "/composition/resolve")
                    declared[key] = group[axis]
    names = list(views)
    for axis in ("x", "y"):
        for index, a in enumerate(names):
            first = {layer[axis + "_scale"] for layer in views[a]["layers"]}
            for b in names[index + 1:]:
                second = {layer[axis + "_scale"] for layer in views[b]["layers"]}
                if first & second:
                    _check(declared.get((axis, *sorted((a, b)))) == "shared", "figure_shared_scale_undeclared",
                        "Sharing scale identity across views requires an explicit shared resolve group.", "/composition/resolve")


def _legend_resolution(spec: dict[str, Any], layers: dict[str, tuple[str, dict[str, Any]]]) -> None:
    """Resolution declares semantic membership; never merge equal-looking labels."""
    memberships = []
    for guide in spec["guides"]:
        if not guide["visible"]:
            continue
        eligible = {name for name, (view_id, layer) in layers.items() if layer["legend"]["visible"]
                    and (guide["scope"] == "figure" or guide["view_id"] == view_id)}
        selected = set(guide["layer_ids"]) if guide["layer_ids"] else eligible
        memberships.append((guide, selected, {layers[name][0] for name in selected}))
    declared: dict[tuple[str, str], str] = {}
    for group in spec["composition"]["resolve"]:
        views = set(group["views"])
        for a in views:
            for b in views:
                if a >= b:
                    continue
                _check((a, b) not in declared or declared[(a, b)] == group["legend"], "figure_legend_resolve_conflict",
                       "Overlapping groups cannot disagree on legend resolution.", "/composition/resolve")
                declared[(a, b)] = group["legend"]
        if group["legend"] == "independent":
            _check(all(len(owners & views) <= 1 for _, _, owners in memberships), "figure_independent_legend_conflict",
                   "Independent legends cannot combine layers from the declared view collection.", "/guides")
        else:
            expected = {name for name, (owner, layer) in layers.items() if owner in views and layer["legend"]["visible"]}
            touching = [(guide, selected) for guide, selected, _ in memberships if selected & expected]
            _check(not expected or len(touching) == 1 and touching[0][0]["scope"] == "figure"
                   and expected <= touching[0][1], "figure_shared_legend_conflict",
                   "Shared legend resolution requires one figure guide covering all eligible layers in the view collection.", "/guides")


def validate_axis_presentation(axis: dict[str, Any], scale: dict[str, Any], *, bound: bool) -> None:
    if "tick_labels" in axis:
        _check(bound and scale["transform"] == "linear" and len(axis["tick_labels"]) == len(axis["ticks"])
               and bool(axis["ticks"]) and "tick_notation" not in axis["style"],
               "figure_tick_labels", "Explicit category labels require a bound linear axis, one label per tick, and no numeric notation override.", "/views/axes/tick_labels")
    if "label_runs" in axis:
        _check(bound and "".join(run["text"] for run in axis["label_runs"]) == axis["label"],
               "figure_axis_label_runs", "Explicit axis label runs must reconstruct the exact plain label.", "/views/axes/label_runs")


def validate_figure_spec(value: Any) -> dict[str, Any]:
    validate_wire(value, figure_spec_schema(), code="figure_spec_invalid")
    assert isinstance(value, dict)
    spec = deepcopy(value)
    from sciplot_core.rendering_contract import require_binding
    for field in ("rendering_contract", "composition_policy"):
        if field in spec:
            require_binding(spec[field])
    _check("composition_policy" not in spec or "rendering_contract" in spec and spec["composition"]["kind"] != "single",
        "figure_composition_policy_scope", "Composition policy requires a managed house multi-panel figure.", "/composition_policy")
    if "rendering_contract" not in spec:
        layout_schema = figure_layout_schema()
        layout_schema["required"] = list(layout_schema["properties"])
        validate_wire(spec["layout"], layout_schema, code="figure_legacy_layout_invalid")
        def scope(value: dict[str, Any]) -> None:
            for kind, item in value.items():
                if kind in STYLE_FIELDS:
                    _check(set(item) <= set(STYLE_FIELDS[kind]), "figure_contract_required",
                           "Extended scoped visual settings require a pinned rendering contract.", "/style")
        for theme_scope in ("project", "figure"):
            scope(spec["theme"][theme_scope])
        def styles(value: Any) -> None:
            if isinstance(value, dict):
                if "style" in value and isinstance(value["style"], dict):
                    kind = value.get("type", "axis" if "scale_id" in value else "annotation" if "space" in value else None)
                    if kind in STYLE_FIELDS:
                        _check(set(value["style"]) <= set(STYLE_FIELDS[kind]), "figure_contract_required",
                               "Extended visual settings require a pinned rendering contract.", "/style")
                    else:
                        scope(value["style"])
                for item in value.values():
                    styles(item)
            elif isinstance(value, list):
                for item in value:
                    styles(item)
        styles(spec)
    _identities(spec)
    scales = {scale["id"]: scale for scale in spec["scales"]}
    views = {view["id"]: view for view in spec["views"]}
    used: set[str] = set()
    layers: dict[str, tuple[str, dict[str, Any]]] = {}
    for scale in scales.values():
        low, high = scale["domain"]
        _check(low < high and (scale["transform"] != "log" or low > 0), "figure_scale_domain",
            "Domains must increase; logarithmic bounds must both be positive. Direction is declared separately.", "/scales")
    for view in views.values():
        bound: set[str] = set()
        for layer in view["layers"]:
            layers[layer["id"]] = (view["id"], layer)
            for axis in ("x", "y"):
                name = layer[axis + "_scale"]
                _check(name in scales, "figure_scale_reference", "Layers must bind existing scale identities.", "/views/layers")
                scale = scales[name]
                _check(scale["dimension"] == axis and scale["quantity"] == layer["mapping_semantics"][axis],
                    "figure_scale_mapping_conflict", "Scale dimension and quantity must match the explicitly declared mapping semantics.", "/views/layers")
                used.add(name)
                bound.add(name)
            uncertainty = any(mark["type"] in {"errorbar", "band"} for mark in layer["marks"])
            _check(set(layer["mappings"]) == ({"x", "y", "y_low", "y_high"} if uncertainty else {"x", "y"}),
                "figure_mark_mappings", "Error bars and bands require absolute y_low and y_high columns; unused mappings are rejected.", "/views/layers/mappings")
        sides = [axis["side"] for axis in view["axes"]]
        _check(len(sides) == len(set(sides)), "figure_axis_stack_unsupported", "This grammar version supports one axis guide per view side.", "/views/axes")
        for axis in view["axes"]:
            _check(axis["scale_id"] in bound, "figure_axis_reference", "An axis guides a scale used by a layer in its view.", "/views/axes")
            scale = scales[axis["scale_id"]]
            validate_axis_presentation(axis, scale, bound="rendering_contract" in spec)
            dimension = "x" if axis["side"] in {"top", "bottom"} else "y"
            _check(scale["dimension"] == dimension, "figure_axis_dimension", "Axis guide side must match the scale dimension.", "/views/axes")
            low, high = scale["domain"]
            _check(all(low <= tick <= high for tick in axis["ticks"]), "figure_tick_domain", "All explicit ticks must lie inside their scale domain.", "/views/axes/ticks")
    _check(used == set(scales), "figure_unused_scale", "Each scale must be consumed by at least one scientific layer.", "/scales")
    _composition(spec)
    for guide in spec["guides"]:
        local = guide["scope"] == "view"
        _check(("view_id" in guide) == local and (not local or guide["view_id"] in views),
            "figure_guide_scope", "View guides require exactly one existing view; figure guides have no view owner.", "/guides")
        locations = {"top-right", "top-left", "bottom-right", "bottom-left", *({"inside-best"} if "rendering_contract" in spec else set())} if local else {"top", "bottom", "left", "right"}
        _check(guide["location"] in locations, "figure_guide_location", "Legend location must belong to its declared scope.", "/guides")
        eligible = {name for name, (view_id, layer) in layers.items() if layer["legend"]["visible"] and (not local or view_id == guide["view_id"])}
        selected = set(guide["layer_ids"]) if guide["layer_ids"] else eligible
        _check(selected <= eligible and set(guide["labels"]) <= selected,
            "figure_guide_membership", "Legend membership and labels must name eligible layers in the selected scope.", "/guides")
        _check(not guide["order"] or set(guide["order"]) == selected, "figure_guide_order",
            "Explicit legend order must include each selected layer exactly once.", "/guides/order")
    _legend_resolution(spec, layers)
    for annotation in spec["annotations"]:
        if annotation["space"] in {"data", "view"}:
            _check(annotation["view_id"] in views, "figure_annotation_reference", "Annotations require an existing view.", "/annotations")
        if annotation["space"] == "data":
            view = views[annotation["view_id"]]
            for dimension in ("x", "y"):
                names = {layer[dimension + "_scale"] for layer in view["layers"]}
                _check(annotation[dimension + "_scale"] in names, "figure_annotation_scale", "Data annotations bind explicit view scales.", "/annotations")
        else:
            _check(0 <= annotation["x"] <= 1 and 0 <= annotation["y"] <= 1,
                "figure_annotation_bounds", "View and figure anchors use normalized coordinates inside their declared frame.", "/annotations")
    return spec


def validate_bound_data(spec: dict[str, Any], datasets: dict[str, dict[str, Any]]) -> None:
    for key, dataset in datasets.items():
        validate_dataset(dataset)
        _check(key == dataset["id"], "figure_dataset_identity", "Dataset keys must equal their stable identities.", "/datasets")
    scales = {scale["id"]: scale for scale in spec["scales"]}
    for view in spec["views"]:
        for layer in view["layers"]:
            _check(layer["dataset_id"] in datasets, "figure_missing_data", "Every layer requires its declared immutable dataset.", "/views/layers/dataset_id")
            dataset = datasets[layer["dataset_id"]]
            for channel, column_id in layer["mappings"].items():
                _check(column_id in dataset["columns"], "figure_missing_mapped_data", "Mapped columns must exist in the immutable dataset.", "/views/layers/mappings")
                column = dataset["columns"][column_id]
                dimension = "x" if channel == "x" else "y"
                scale = scales[layer[dimension + "_scale"]]
                _check(column["unit"] == scale["unit"], "figure_shared_scale_unit_conflict",
                    "Mapped column units must match the scientific scale exactly; conversions need TransformNodes.", "/views/layers/mappings")
                if scale["transform"] == "log":
                    _check(all(value is None or value > 0 for value in column["values"]), "figure_log_data_domain",
                        "Logarithmic mappings cannot silently discard zero or negative measurements.", "/views/layers/mappings")
            if "y_low" in layer["mappings"]:
                low = dataset["columns"][layer["mappings"]["y_low"]]["values"]
                high = dataset["columns"][layer["mappings"]["y_high"]]["values"]
                _check(all(a is None or b is None or a <= b for a, b in zip(low, high, strict=True)),
                    "figure_uncertainty_bounds", "Absolute uncertainty bounds must be ordered for every original row.", "/views/layers/mappings")
                complete = [all(value is not None for value in row) for row in zip(
                    dataset["columns"][layer["mappings"]["x"]]["values"],
                    dataset["columns"][layer["mappings"]["y"]]["values"], low, high, strict=True)]
                _check(any(complete), "figure_empty_uncertainty", "Uncertainty marks require at least one complete paired interval.",
                       "/views/layers/mappings")
                if any(mark["type"] == "band" for mark in layer["marks"]):
                    _check(any(a and b for a, b in zip(complete, complete[1:], strict=False)), "figure_empty_band",
                           "A band requires two consecutive complete intervals; missing rows remain gaps.", "/views/layers/mappings")
