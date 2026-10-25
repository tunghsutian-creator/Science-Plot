"""Original row identity through ordered builtins, without another durable ledger."""
from copy import deepcopy
from typing import Any

from sciplot_core.plot_document.errors import fail


def row_origins(dataset: dict[str, Any]) -> list[list[dict[str, Any]]]:
    """Resolve the last row-changing step; other steps preserve row positions."""
    count = len(next(iter(dataset["columns"].values()))["values"])
    for step in reversed(dataset["provenance"]["transforms"]):
        details = step["details"]
        if "row_origins" in details:
            origins = details["row_origins"]
            if len(origins) != count:
                fail("transform_row_lineage_invalid", "The selected row lineage does not match the output point count.", "/provenance", "exact_row_lineage")
            return deepcopy(origins)
        if details.get("protocol_version"):
            fail("transform_row_lineage_unknown", "An external executor has no declared original row correspondence.", "/provenance", "known_row_lineage")
    sources = dataset["provenance"]["sources"]
    if len(sources) != 1 or len(sources[0]["rows"]) != count:
        fail("transform_row_lineage_unknown", "Stage operations require an explicit original row correspondence.", "/provenance", "known_row_lineage")
    return [[{"source_id": sources[0]["source_id"], "row": row}] for row in sources[0]["rows"]]


def merge_provenance(sources: list[dict[str, Any]]) -> dict[str, Any]:
    """Retain each original source and shared ancestor once, rejecting conflicts."""
    originals: dict[str, Any] = {}
    history: dict[str, Any] = {}
    for dataset in sources:
        for source in dataset["provenance"]["sources"]:
            identifier = source["source_id"]
            if identifier in originals and originals[identifier] != source:
                fail("transform_source_identity_conflict", "One source identity cannot refer to different original tables.", "/inputs", "unique_source_binding", source_id=identifier)
            originals[identifier] = deepcopy(source)
        for step in dataset["provenance"]["transforms"]:
            identifier = step["node_id"]
            if identifier in history and history[identifier] != step:
                fail("transform_history_conflict", "One transform identity cannot refer to two executions.", "/inputs", "unique_transform_identity", node_id=identifier)
            history[identifier] = deepcopy(step)
    return {"sources": list(originals.values()), "transforms": list(history.values())}
