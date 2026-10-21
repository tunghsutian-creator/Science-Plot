"""Closed ordered selections for new ManagedPlot native-snapshot deliveries."""

from copy import deepcopy
from pathlib import Path
from typing import Any

from sciplot_core.plot_document.schema import IDENTIFIER, closed
from sciplot_core.plot_document.validation import validate_wire
from sciplot_core.plot_engine.errors import EngineError
from sciplot_core.studio_core.project_query_paths import canonical_path


def managed_delivery_schema() -> dict[str, Any]:
    text = {"type": "string", "minLength": 1, "maxLength": 200}
    path = {"type": "string", "minLength": 1, "pattern": "^/"}
    return closed({
        "idempotency_key": {"type": "string", "minLength": 1, "maxLength": 128},
        "out": path, "title": text,
        "mode": {"const": "native_snapshot"},
        "items": {"type": "array", "minItems": 1, "maxItems": 32, "items": closed({
            "plot": path, "plot_id": IDENTIFIER,
            "revision": {"type": "integer", "minimum": 0}, "label": text,
        })},
    })


def normalize_request(value: Any) -> dict[str, Any]:
    validate_wire(value, managed_delivery_schema(), code="managed_delivery_invalid_request")
    request = deepcopy(value)
    request["out"] = str(canonical_path(Path(request["out"])))
    plots = set()
    for item in request["items"]:
        item["plot"] = str(canonical_path(Path(item["plot"])))
        if item["plot"] in plots:
            raise EngineError("managed_delivery_duplicate_plot", "Select each ManagedPlot once.")
        plots.add(item["plot"])
    return dict(request)
