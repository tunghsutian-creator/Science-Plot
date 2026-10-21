"""Validate the source-to-series categorical correspondence projection."""

from typing import Any

from sciplot_core.mapping_contract.source_identity import scientific_group_binding


def category_ids_from_bindings(bindings: list[dict[str, Any]]) -> list[str]:
    identities = [scientific_group_binding(binding) for binding in bindings]
    return list(dict.fromkeys(category for binding in identities for category in (
        binding["categories"] if binding["version"] == 2 else [binding["category"]])))


def validate_categorical_correspondence(spec: dict[str, Any]) -> None:
    series = spec.get("series", [])
    bindings = [item.get("source_binding") for item in series]
    if not any(binding is not None for binding in bindings):
        if "source_category_ids" in spec:
            raise ValueError("Category source IDs require complete structured series bindings.")
        return
    if spec.get("categorical") is None:
        if "source_category_ids" in spec:
            raise ValueError("XY scientific groups cannot declare categorical axis identities.")
        for binding in bindings:
            scientific_group_binding(binding)
        return
    originals = spec.get("source_category_ids")
    if (not isinstance(originals, list) or not originals
            or any(not isinstance(value, str) or not value.strip() for value in originals)
            or len(originals) != len(set(originals))):
        raise ValueError("Original categorical source identities must be nonempty and unique.")
    categories: list[str] = []
    by_y = {}
    for item, binding in zip(series, bindings, strict=True):
        current = scientific_group_binding(binding)
        by_y[item["y_name"]] = current
        if current["version"] == 2:
            if current["categories"] != originals:
                raise ValueError("Categorical series changed its original category membership/order.")
        elif current["category"] not in categories:
            categories.append(current["category"])
    if categories and categories != originals:
        raise ValueError("Categorical groups changed their original category membership/order.")
    groups = (spec.get("categorical") or {}).get("groups", [])
    if any("categories" in binding for binding in bindings):
        if [group.get("source_category_id") for group in groups] != originals:
            raise ValueError("Categorical axis slots differ from their original category identities.")
        return
    for group in groups:
        binding = group.get("source_binding")
        if binding != by_y.get(group["y_name"]):
            raise ValueError("Categorical group and series source correspondence differ.")
        if group.get("sample_label") != binding["sample"] or group.get("condition_label") != binding["condition"]:
            raise ValueError("Categorical sample/condition facts differ from their source binding.")
