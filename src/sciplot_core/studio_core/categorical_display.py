"""One presentation overlay over unchanged ordinary categorical science."""
from copy import deepcopy
from typing import Any

from sciplot_core.plot_document.validation import validate_wire
from sciplot_core.studio_core.annotation_schema import AnnotationOperationError
from sciplot_core.studio_core.categorical_display_schema import operation_schemas, overlay_schema
from sciplot_core.studio_core.series_encoding_contract import series_encoding_from_spec, series_encoding_contract_payload

KEY = "presentation_categorical_display"
OPS = {"set_category_display_labels", "set_categorical_display_style"}


def require_categorical(spec: dict[str, Any]) -> dict[str, Any]:
    request = spec.get("source_request", {})
    binding = request.get("categorical_binding") if isinstance(request, dict) else None
    categorical = spec.get("categorical")
    if (not isinstance(binding, dict) or request.get("rule_id") is not None
            or spec.get("scalar_field") is not None or spec.get("performance_comparison") is not None
            or not isinstance(categorical, dict)
            or (binding.get("mode"), spec.get("template")) not in {
                ("given_values", "point_line"), ("mean_sample_sd", "bar"), ("mean_sample_sd_n", "bar")}):
        raise AnnotationOperationError("categorical_display_unsupported", "Use a source-bound ordinary categorical given-value or bar-summary figure without a scientific rule.")
    from sciplot_core.mapping_contract.categorical import validate_categorical_context

    validate_categorical_context(request)
    return binding


def category_ids(spec: dict[str, Any]) -> list[str]:
    binding = require_categorical(spec)
    labels = spec["axes"]["x"]["category_labels"]
    if binding.get("source_identity_version") == 1:
        from sciplot_core.mapping_contract.categorical_identity import validate_categorical_correspondence

        validate_categorical_correspondence(spec)
        return list(spec["source_category_ids"])
    inverse = {alias: source for source, alias in binding.get("category_aliases", {}).items()}
    ids = [inverse.get(label, label) for label in labels]
    if len(ids) != len(set(ids)) or any(binding.get("category_aliases", {}).get(source, source) != label
                                        for source, label in zip(ids, labels, strict=True)):
        raise AnnotationOperationError("categorical_display_identity", "Original category identities must remain unique and reproduce their declared creation labels.")
    return ids


def _series_style(spec: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    if spec["template"] == "bar":
        group = next(group for group in spec["categorical"]["groups"] if group["label"] == item["label"])
        return {"color": str(group["fill_color"])}
    encoding = series_encoding_from_spec(item, style=spec["style"])
    return {"color": str(encoding["line"]["color"]), "marker": str(encoding["marker"]["shape"]),
            "marker_fill_mode": "open" if encoding["marker"]["fill_color"] == "white" else "filled"}


def overlay(spec: dict[str, Any]) -> dict[str, Any]:
    require_categorical(spec)
    value = deepcopy(spec.get(KEY, {"version": 1, "aliases": {}, "styles": {}, "legend": {}}))
    validate_wire(value, overlay_schema(), code="categorical_display_invalid")
    ids = category_ids(spec)
    series = {item["name"]: item for item in spec["series"]}
    if not set(value["aliases"]) <= set(ids) or not set(value["styles"]) <= set(series):
        raise AnnotationOperationError("categorical_display_unknown_target", "Presentation must name retained original category and series IDs.")
    labels = [value["aliases"].get(source, label) for source, label in zip(ids, spec["axes"]["x"]["category_labels"], strict=True)]
    if len(set(labels)) != len(labels) or any(any(ord(char) < 32 for char in label) for label in labels):
        raise AnnotationOperationError("categorical_display_duplicate_label", "Displayed categories must have unique literal labels without control characters.")
    for name, style in value["styles"].items():
        if not style or not set(style) <= set(_series_style(spec, series[name])):
            raise AnnotationOperationError("categorical_display_style_scope", "Use only the advertised display channels for this retained series.")
    if value["legend"] and (spec["template"] != "point_line" or spec["legend"].get("native_key") is False
                             or spec["legend"].get("presentation_kind") in {"segmented_component", "factorized_curve"}):
        raise AnnotationOperationError("categorical_display_legend_scope", "Named corner and column edits require the represented given-value native key.")
    return dict(value)


def display_axes(spec: dict[str, Any]) -> dict[str, Any]:
    axes = deepcopy(spec["axes"])
    if KEY in spec:
        value = overlay(spec)
        axes["x"]["category_labels"] = [value["aliases"].get(source, label)
            for source, label in zip(category_ids(spec), axes["x"]["category_labels"], strict=True)]
    return dict(axes)


def context(spec: dict[str, Any], widgets: dict[str, Any] | None = None) -> dict[str, Any]:
    value = overlay(spec)
    targets = []
    binding = require_categorical(spec)
    for index, item in enumerate(spec["series"]):
        style = {**_series_style(spec, item), **value["styles"].get(item["name"], {})}
        selector: dict[str, Any] = {"source_label": item["label"]}
        if spec["template"] == "bar":
            group = next(group for group in spec["categorical"]["groups"] if group["label"] == item["label"])
            selector.update({field: group[field] for field in ("sample_label", "condition_label") if field in group})
        else:
            fields = binding["value_columns"]
            selector["value_column_index"] = fields[index % len(fields)]["column_index"]
            if binding.get("condition_column") is not None and len(fields) == 1:
                selector["condition_label"] = item["label"]
        targets.append({"series_id": item["name"], "source_selector": selector, "current_style": style,
                        "editable_fields": list(style)})
    result: dict[str, Any] = {"categories": [{"category_id": source, "label": label} for source, label in
                              zip(category_ids(spec), display_axes(spec)["x"]["category_labels"], strict=True)],
              "style_targets": targets, "legend": None}
    key = (widgets or {}).get("/page1/graph1/key1")
    if spec["template"] == "point_line" and key is not None:
        result["legend"] = {"current": {field: key["settings"][field] for field in ("columns", "horzPosn", "vertPosn")},
                            "positions": ["upper_left", "upper_right", "lower_left", "lower_right"], "columns": [1, 12]}
    return result


def compile_display(spec: dict[str, Any], operation: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    validate_wire(operation, {"oneOf": operation_schemas()}, code="categorical_display_invalid")
    before, value = context(spec), overlay(spec)
    touched: set[str] = set()
    if operation["op"] == "set_category_display_labels":
        current = {item["category_id"]: item["label"] for item in before["categories"]}
        for change in operation["changes"]:
            source = change["category_id"]
            if source in touched or source not in current or current[source] != change["expected_label"]:
                raise AnnotationOperationError("stale_category_display", "Use each current original category ID and expected display label once.")
            value["aliases"][source] = change["label"]
            touched.add(source)
    else:
        current = {item["series_id"]: item["current_style"] for item in before["style_targets"]}
        for change in operation.get("changes", []):
            name = change["series_id"]
            if name in touched or name not in current or current[name] != change["expected_style"]:
                raise AnnotationOperationError("stale_categorical_style", "Use each current source-bound series selector and its complete expected_style once.")
            value["styles"][name] = {**value["styles"].get(name, {}), **change["style"]}
            touched.add(name)
        if "legend" in operation:
            value["legend"] = {key: operation["legend"][key] for key in ("position", "columns")}
    result = {**deepcopy(spec), KEY: value}
    overlay(result)
    return result, {"op": operation["op"], "before": spec.get(KEY), "after": deepcopy(value),
                    "authorization": "explicit_categorical_presentation", "source_identity_preserved": True,
                    **({"expected_legend": operation["legend"]["expected"]} if "legend" in operation else {})}


def require_native_display_preconditions(
    spec: dict[str, Any], operations: list[dict[str, Any]], widgets: dict[str, Any],
) -> None:
    """Reject known stale expectations before admitting a native effect.

    Category and series expectations use the same compiler as the candidate.
    Legend placement is current native presentation, observed by the caller's
    exact-document inspection; generated spec defaults cannot attest it.
    """
    revised = spec
    for operation in operations:
        if operation.get("op") not in OPS:
            continue
        revised, change = compile_display(revised, operation)
        if "expected_legend" not in change:
            continue
        key = widgets.get("/page1/graph1/key1", {})
        settings = key.get("settings", {}) if isinstance(key, dict) else {}
        fields = ("columns", "horzPosn", "vertPosn")
        if not isinstance(settings, dict) or any(field not in settings for field in fields):
            raise AnnotationOperationError("stale_categorical_legend", "Inspect the complete current native legend before editing it.")
        legend = context(spec, widgets)["legend"]
        if legend is None or legend["current"] != change["expected_legend"]:
            raise AnnotationOperationError("stale_categorical_legend", "Use the current native legend's complete expected placement and columns.")


def effective_presentation(spec: dict[str, Any]) -> dict[str, Any]:
    if KEY not in spec:
        return spec
    value, result = overlay(spec), deepcopy(spec)
    for item in result["series"]:
        style = value["styles"].get(item["name"])
        if not style:
            continue
        encoding = series_encoding_from_spec(item, style=result["style"])
        current = {**_series_style(spec, item), **style}
        if result["template"] == "point_line":
            encoding["line"]["color"] = current["color"]
            encoding["marker"].update(shape=current["marker"], fill_color="white" if current["marker_fill_mode"] == "open" else current["color"], line_color=current["color"])
            if "marker" in style:
                encoding["marker"].update(fill_visible=current["marker"] != "none", line_visible=current["marker"] != "none")
            encoding["request_bound_fields"] = sorted(set(encoding["request_bound_fields"]) | {"line.color", "marker.shape", "marker.fill_color", "marker.line_color"})
            item["encoding"] = encoding
        else:
            group = next(group for group in result["categorical"]["groups"] if group["label"] == item["label"])
            group.update(fill_color=current["color"], keyline_color=current["color"])
    if result["template"] == "point_line":
        result["series_encoding_contract"] = series_encoding_contract_payload(result["series"])
    elif result["legend"].get("presentation_kind") == "segmented_component":
        for row in result["legend"]["rows"]:
            row["colors"] = [next(group["fill_color"] for group in result["categorical"]["groups"]
                                  if group["condition_label"] == row["label"] and group["sample_label"] == sample)
                             for sample in row["sample_labels"]]
    if value["legend"]:
        legend = value["legend"]
        result["legend"].update(columns=legend["columns"], horz_position="left" if legend["position"].endswith("left") else "right",
                                vert_position="top" if legend["position"].startswith("upper") else "bottom")
    return result
