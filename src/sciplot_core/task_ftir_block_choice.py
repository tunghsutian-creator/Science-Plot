"""One opted-in paired FTIR selection, through the semantic task owner."""

from pathlib import Path
from typing import Any

from sciplot_core.task_errors import TaskControlError


def _unsupported() -> TaskControlError:
    return TaskControlError(
        "ftir_block_choice_unsupported",
        "Raw-overlay sample selection needs one CSV or TSV with a single observed table of named FTIR pairs, explicit matching units, and no missing coordinates.",
    )


def normalize_ftir_block_request(request: dict[str, Any]) -> dict[str, Any]:
    """Translate only the typed raw FTIR column-choice entry, before allocation."""
    if (request.get("action"), request.get("rule_id"), request.get("choose_columns"), request.get("curve_display")) != (
        "create", "ftir_spectrum", True, "raw_overlay"
    ) or set(request) - {"version", "action", "rule_id", "source", "out", "choose_columns", "curve_display", "summary_statistic"}:
        return request
    source = Path(request["source"]).expanduser().resolve()
    _require_file(source)
    from sciplot_core.semantic_sources.ftir_sources import resolve_ftir_scientific_transform

    try:
        observed = resolve_ftir_scientific_transform(source)
    except ValueError as exc:
        raise _unsupported() from exc
    mode = observed.contract.output.get("response_mode")
    if mode not in {"transmittance", "absorbance"}:
        raise _unsupported()

    return {
        **{key: request[key] for key in ("version", "action", "out", "choose_columns", "curve_display", "summary_statistic") if key in request},
        "sources": [str(source)],
        "intent": {
            "rule_id": "ftir_spectrum",
            "x": {"quantity": "wavenumber", "unit": "cm^-1", "direction": "descending"},
            "y": {"quantity": mode, "unit": "%" if mode == "transmittance" else "a.u."},
        },
    }


def _require_file(source: Path) -> None:
    if source.suffix.casefold() not in {".csv", ".tsv"}:
        raise _unsupported()
    if not source.is_file():
        raise TaskControlError("source_is_directory" if source.is_dir() else "source_not_found",
                               "Select the exact original FTIR CSV or TSV file before choosing samples.")


def advertise_ftir_blocks(plan: dict[str, Any], source_hashes: dict[str, str]) -> None:
    """Use already-resolved exact table evidence, not a new mapping format."""
    source, = plan["sources"]
    _require_file(Path(source["path"]))
    if source_hashes.get(source["path"]) != source["sha256"]:
        raise TaskControlError("source_changed", "The original attachment changed while preparing its source-bound question.")
    available = plan["selection"]["available"]
    bindings = plan.get("resolved_bindings", [])
    if plan["decisions"] or not 2 <= len(available) == len(bindings) or len({b.get("sample") for b in available}) != len(available):
        raise _unsupported()
    tables = source["candidates"]
    if len(tables) != 1 or tables[0].get("format") != "sample_column_blocks":
        raise _unsupported()
    mode = plan["intent"]["y"]["quantity"]
    units = ("cm^-1", "%" if mode == "transmittance" else "a.u.")
    blocks_by_id = {block["block_id"]: block for block in tables[0]["blocks"]}
    for binding in bindings:
        region, coordinates = binding["table_selection"], binding["coordinates"]
        block = blocks_by_id[binding["block_id"]]
        if "unit_row" not in region or "sample_row" not in region:
            raise _unsupported()
        for role, quantity, unit in zip(("x", "y"), ("wavenumber", mode), units, strict=True):
            actual = coordinates[role]
            observed, = (col for col in block["columns"] if col["column_id"] == actual["column_id"])
            numeric = observed["numeric"]
            if (
                actual["observed_quantity"] != quantity or actual["observed_unit"] != unit
                or actual["unit"] != unit or actual["unit_relation"]["kind"] != "identity"
                or numeric["point_count"] < 2 or numeric["point_count"] != region["data_end_row"] - region["data_start_row"]
            ):
                raise _unsupported()
    from sciplot_core.task_semantic_selection import block_reference

    plan["selection"].update(mode="pending_blocks", selected=[])
    plan["decisions"] = [{
        "field": "blocks", "options": [block_reference(block) for block in available],
        "message": "Which original FTIR samples should be overlaid? Choose only their exact listed blocks; unselected spectra will not be drawn.",
    }]
