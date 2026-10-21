"""Original response-column and row identity for source-bound XY appends."""
from pathlib import Path
from typing import Any

from .append_target_lineage import coordinate_origin
from .errors import EngineError


def validate_append_identity(document: dict[str, Any], source: dict[str, Any], curves: list[dict[str, Any]],
                             *, region_proof: dict[str, Any] | None = None) -> None:
    """Do not clone observations by changing source ID, sample, alias or visibility."""
    path, region = Path(source["path"]).resolve(), source["table_selection"]
    same_file = [item for item in document["scientific"]["data_sources"] if Path(item["path"]).resolve() == path]
    if any(item["sha256"] != source["sha256"] for item in same_file):
        raise EngineError("managed_append_source_changed", "An already bound original file must retain its complete original SHA-256; use the source revision operation for changed bytes.")
    if not same_file:
        return
    if region_proof is None and not any(all(item["table_selection"].get(key) == region.get(key)
                                for key in ("sheet", "header_rows", "unit_row", "sample_row", "data_start_row"))
                             for item in same_file):
        raise EngineError("managed_append_region_conflict", "Same-file append requires an already bound original table region with its exact metadata rows and data start.")
    for mapping in document["scientific"]["mappings"].values():
        coordinate = mapping["y"]
        column = f"column:{coordinate['column_index']}" if "column_index" in coordinate else coordinate["column"]
        original, index, start, end = coordinate_origin(document, coordinate["source_id"], column, mapping["y_unit"])
        if (Path(original["path"]).resolve() == path and original["sha256"] == source["sha256"]
                and original["table_selection"]["sheet"] == region["sheet"]
                and index in {curve["y_column_index"] for curve in curves}
                and max(start, region["data_start_row"]) < min(end, region["data_end_row"])):
            raise EngineError("managed_append_duplicate_measurement", "This original response column and overlapping rows are already bound, including hidden curves. Sample text and display aliases cannot duplicate observations.")
