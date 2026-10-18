"""Explicit acquisition-stage slicing and cumulative-time concatenation."""
from copy import deepcopy
import math
from typing import Any

from sciplot_core.plot_document.errors import fail

from .lineage import merge_provenance, row_origins
from .units import TIME_UNITS, canonical_unit_token


def run_series_builtin(node: dict[str, Any], sources: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    params = node["parameters"]
    result = deepcopy(sources[0])
    if node["kind"] == "row_slice":
        count = len(next(iter(result["columns"].values()))["values"])
        start, end = params["start"], params["end"]
        if not 0 <= start < end <= count:
            fail("transform_row_range_invalid", "Stage rows must be a nonempty in-bounds interval; end is exclusive.", "/parameters", "bounded_row_interval", point_count=count)
        origins = row_origins(result)[start:end]
        for column in result["columns"].values():
            column["values"] = column["values"][start:end]
        details = {"start": start, "end": end, "input_point_count": count,
                   "excluded_point_count": count - (end - start), "row_origins": origins, "row_order": "preserved"}
    else:
        name = params["time_column"]
        columns = result["columns"]
        if name not in columns:
            fail("transform_column_missing", "The cumulative-time column is absent.", "/parameters/time_column", "existing_column")
        if canonical_unit_token(columns[name]["unit"]) not in TIME_UNITS:
            fail("transform_time_unit_required", "Time concatenation requires an explicit supported time unit.", "/parameters/time_column", "known_time_unit", actual=columns[name]["unit"])
        for source in sources:
            if set(source["columns"]) != set(columns) or any(
                (source["columns"][key]["label"], source["columns"][key]["unit"]) != (column["label"], column["unit"])
                for key, column in columns.items()
            ):
                fail("transform_stage_columns_conflict", "Stages require identical declared column IDs, labels and units; rename or convert explicitly first.", "/inputs", "same_column_contract", dataset_id=source["id"])
        offsets: list[float] = []
        origins = []
        joined: dict[str, list[Any]] = {key: [] for key in columns}
        previous_end = None
        for source in sources:
            times = source["columns"][name]["values"]
            if not times or any(value is None for value in times) or any(a >= b for a, b in zip(times, times[1:], strict=False)):
                fail("transform_stage_time_invalid", "Each selected stage requires finite strictly increasing measured time; split resets or resolve missing rows explicitly.", "/inputs", "strict_stage_time", dataset_id=source["id"])
            offset = -times[0] if previous_end is None and params["first_origin"] == "zero" else 0
            if previous_end is not None:
                increment = 0
                if params["boundary"] == "next_sample":
                    if len(times) < 2:
                        fail("transform_boundary_interval_missing", "next_sample needs the incoming stage's first measured positive interval.", "/parameters/boundary", "measured_interval", dataset_id=source["id"])
                    increment = times[1] - times[0]
                offset = previous_end + increment - times[0]
            transformed = [value + offset for value in times]
            if any(not math.isfinite(value) for value in transformed):
                fail("transform_nonfinite_result", "Cumulative time overflows the finite numeric domain.", "/parameters", "finite_result")
            offsets.append(offset)
            previous_end = transformed[-1]
            for key in columns:
                joined[key].extend(transformed if key == name else source["columns"][key]["values"])
            origins.extend(row_origins(source))
        for key, values in joined.items():
            columns[key]["values"] = values
        result["provenance"] = merge_provenance(sources)
        details = {"time_column": name, "unit": columns[name]["unit"], "boundary": params["boundary"],
                   "first_origin": params["first_origin"], "offsets": offsets,
                   "input_order": [source["id"] for source in sources],
                   "input_point_counts": [len(source["columns"][name]["values"]) for source in sources],
                   "point_policy": "preserve_every_input_point", "row_origins": origins, "row_order": "input_order"}
    result["id"] = node["output"]
    return result, details
