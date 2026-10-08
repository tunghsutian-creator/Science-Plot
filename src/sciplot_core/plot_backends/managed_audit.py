"""Exact native numerical audit and closed-state comparison against resolved IR."""

from decimal import Decimal
import re
import hashlib
import json
import math
from typing import Any

from sciplot_core.plot_backends.managed_plan import dataset_name, native_datasets, native_name
from sciplot_core.veusz_worker.numeric_evidence import _dataset_evidence, _numeric_digest


def _value(value: Any) -> Any:
    if hasattr(value, "tolist"):
        value = value.tolist()
    if isinstance(value, (tuple, list)):
        return [_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _value(item) for key, item in value.items()}
    if isinstance(value, float) and not math.isfinite(value):
        return {"nonfinite": str(value)}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def content_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def native_state(loaded: Any) -> dict[str, Any]:
    nodes: dict[str, Any] = {}
    bindings: dict[str, Any] = {}

    def normalized(item: Any, value: Any) -> Any:
        if str(getattr(item, "typename", "")).startswith("distance") and isinstance(value, str):
            match = re.fullmatch(r"([+\-]?[\d.]+(?:[eE][+\-]?\d+)?)(pt|mm|cm|in)", value)
            if match:
                return f"{Decimal(match.group(1)).normalize():f}{match.group(2)}"
        return _value(value)

    def settings(group: Any, prefix: str = "") -> dict[str, Any]:
        result: dict[str, Any] = {}
        for name, item in group.setdict.items():
            path = f"{prefix}/{name}" if prefix else name
            if hasattr(item, "setdict"):
                result.update(settings(item, path))
            else:
                try:
                    result[path] = normalized(item, item.get())
                except ValueError:
                    # Some unused upstream stylesheet aliases point at settings
                    # absent from that widget type. Preserve the alias itself.
                    result[path] = {"unresolved_alias": str(getattr(item, "relpath", "")),
                                    "value": _value(getattr(item, "_val", None))}
                if item.isReference():
                    ref = item.getReference()
                    bindings[f"{group_path}/{path}"] = {"kind": type(ref).__name__, "paths": ref.getPaths()}
                elif getattr(item, "relpath", None) is not None:
                    bindings[f"{group_path}/{path}"] = {"kind": "forward", "path": item.relpath}
        return result

    group_path = ""

    def collect(path: str, widget: Any) -> None:
        nonlocal group_path
        group_path = str(path)
        nodes[str(path)] = {"type": str(widget.typename), "settings": settings(widget.settings),
                            "children": [child.name for child in widget.children]}

    loaded.walkNodes(collect, nodetypes=("widget",))
    datasets = {name: {"class": f"{type(data).__module__}.{type(data).__name__}",
                       "linked": getattr(data, "linked", None) is not None,
                       "tags": sorted(getattr(data, "tags", set())),
                       "dimensions": int(data.dimensions), "data": _value(data.data),
                       "serr": _value(getattr(data, "serr", None)),
                       "perr": _value(getattr(data, "perr", None)),
                       "nerr": _value(getattr(data, "nerr", None))}
                for name, data in loaded.data.items()}
    return {"widgets": nodes, "setting_bindings": bindings, "datasets": datasets, "customs": {name: _value(getattr(loaded.evaluate, name)) for name in
            ("def_imports", "def_definitions", "def_colors", "def_colormaps")}}


def scientific_audit(ir: dict[str, Any], loaded: Any) -> dict[str, Any]:
    if ir.get("schema_version") == 2:
        from sciplot_core.plot_backends.figure_audit import scientific_audit as audit_figure
        return audit_figure(ir, loaded)
    # The managed compiler always writes full binary64; no legacy rounding waiver.
    loaded._sciplot_exact_1d = True
    for dataset in loaded.data.values():
        if (type(dataset).__module__, type(dataset).__name__) != ("veusz.datasets.oned", "Dataset") or getattr(dataset, "linked", None) is not None:
            raise ValueError("Managed datasets must be plain embedded numeric arrays without expressions or links.")
    datasets = [_dataset_evidence(loaded, dataset_name=name, expected_values=values, dimensions=1)
                for name, values in native_datasets(ir).items()]
    expected_names = set(native_datasets(ir))
    if set(loaded.data) != expected_names:
        raise ValueError("Managed native document contains undeclared datasets.")
    series = []
    for record in ir["series"]:
        path = f"/page1/graph1/{native_name('series', record['id'])}"
        widget = loaded.resolveWidgetPath(None, path)
        x_name = dataset_name(record["dataset_id"], record["x_column"])
        y_name = dataset_name(record["dataset_id"], record["y_column"])
        for setting, expected in (("xData", x_name), ("yData", y_name), ("xAxis", "x"), ("yAxis", "y")):
            if widget.settings.get(setting).get() != expected:
                raise ValueError(f"Managed series {record['id']} has a changed scientific binding.")
        series.append({"id": record["id"], "dataset_id": record["dataset_id"],
                       "x_column": record["x_column"], "y_column": record["y_column"],
                       "point_count": len(record["x"]),
                       "x_values_hash": _numeric_digest(loaded.data[x_name].data),
                       "y_values_hash": _numeric_digest(loaded.data[y_name].data)})
    return {"kind": "sciplot_managed_native_audit", "status": "passed",
            "scientific_hash": ir["scientific_hash"], "ir_hash": ir["ir_hash"],
            "datasets": datasets, "series": series}


def compare_native(ir: dict[str, Any], expected: Any, actual: Any) -> dict[str, Any]:
    reference, current = native_state(expected), native_state(actual)
    differences: list[dict[str, Any]] = []
    semantic: list[dict[str, Any]] = []
    known: dict[tuple[str, str], tuple[str, str]] = {}
    for series in ir.get("series", []):
        path = f"/page1/graph1/{native_name('series', series['id'])}"
        known[(path, "PlotLine/width")] = (series["id"], "style.line.width")
        known[(path, "PlotLine/color")] = (series["id"], "style.line.color")
    opaque = any(reference[key] != current[key] for key in ("datasets", "customs", "setting_bindings"))
    for path in sorted(set(reference["widgets"]) | set(current["widgets"])):
        old, new = reference["widgets"].get(path), current["widgets"].get(path)
        if old is None or new is None or old["type"] != new["type"] or old["children"] != new["children"]:
            differences.append({"path": path, "kind": "structure"})
            opaque = True
            continue
        for setting in sorted(set(old["settings"]) | set(new["settings"])):
            before, after = old["settings"].get(setting), new["settings"].get(setting)
            if before == after:
                continue
            differences.append({"path": path, "setting": setting, "before": before, "after": after})
            mapping = known.get((path, setting))
            if mapping:
                target, property_name = mapping
                semantic.append({"target": target, "property": property_name, "before": before, "after": after})
            else:
                opaque = True
    return {"status": "unchanged" if reference == current else "external_mutation",
            "semantic_diff": semantic, "opaque_native_change": opaque,
            "native_differences": differences, "native_state_hash": content_hash(current),
            "expected_native_state_hash": content_hash(reference)}
