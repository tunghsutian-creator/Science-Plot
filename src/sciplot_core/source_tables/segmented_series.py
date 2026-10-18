"""Read-only time-run candidates from an already source-bound table snapshot."""
from typing import Any

from sciplot_core.plot_document.errors import fail
from sciplot_core.plot_transforms.datasets import validate_dataset
from sciplot_core.plot_transforms.lineage import row_origins
from sciplot_core.plot_transforms.units import TIME_UNITS, canonical_unit_token


def segment_candidates(dataset: dict[str, Any], *, time_column: str) -> dict[str, Any]:
    """Time resets suggest boundaries, never phase identity or acquisition order."""
    dataset = validate_dataset(dataset)
    if time_column not in dataset["columns"]:
        fail("segment_time_column_missing", "Select one source-bound time column.", "/time_column", "existing_column")
    time = dataset["columns"][time_column]
    if canonical_unit_token(time["unit"]) not in TIME_UNITS:
        fail("segment_time_unit_required", "Stage candidates require an explicit time unit.", "/time_column", "known_time_unit", actual=time["unit"])
    values, origins = time["values"], row_origins(dataset)
    segments: list[dict[str, Any]] = []
    start: int | None = None
    reason = "source_start"

    def append(end: int) -> None:
        if start is not None:
            segments.append({"id": f"{dataset['id']}:stage:{len(segments)}", "dataset_id": dataset["id"],
                "start_index": start, "end_index": end, "time_start": values[start], "time_end": values[end - 1],
                "time_unit": time["unit"], "point_count": end - start, "reason": reason,
                "source_rows": [row[0]["row"] for row in origins[start:end]], "row_origins": origins[start:end]})

    unassigned = []
    for index, value in enumerate(values):
        if value is None:
            append(index)
            start = None
            reason = "after_missing_time"
            unassigned.append(index)
        elif start is None:
            start = index
        elif value <= values[index - 1]:
            append(index)
            start = index
            reason = "time_reset" if value < values[index - 1] else "repeated_time"
    append(len(values))
    questions = []
    if len(segments) > 1:
        questions = [{"field": "stage_order", "reason": "Time runs do not establish physical acquisition order.",
                      "candidates": [segment["id"] for segment in segments]},
                     {"field": "boundary", "reason": "Elapsed time at a reset needs an explicit boundary policy; both keep every point.",
                      "candidates": ["preserve_endpoint", "next_sample"]}]
    if unassigned:
        questions.append({"field": "missing_time_rows", "reason": "Missing-time rows cannot enter a monotone phase silently.", "indices": unassigned})
    return {"dataset_id": dataset["id"], "time_column": time_column, "segments": segments,
            "unassigned_indices": unassigned, "questions": questions, "automatic_selection": False}
