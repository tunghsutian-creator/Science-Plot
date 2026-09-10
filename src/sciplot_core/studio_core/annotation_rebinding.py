"""Review fixed annotations and source-bound observed peaks against new data."""

from __future__ import annotations

from typing import Any
from copy import deepcopy

from sciplot_core.studio_core.annotation_contracts import annotation_records, normalize_annotation
from sciplot_core.studio_core.peak_evidence import peak_candidates_for_spec
from sciplot_core.studio_core.document_edit_state import value_digest


def _peak_choice(peak: dict[str, Any], series: dict[str, Any]) -> dict[str, Any]:
    record = {key: peak[key] for key in ("sample", "window", "polarity", "point_index", "x", "y", "x_unit", "y_unit", "method")}
    record["series_values_sha256"] = value_digest({key: series[key] for key in ("label", "x_values", "y_values")})
    record["candidate_id"] = value_digest(record)
    return record


def annotation_revision(
    before: dict[str, Any], after: dict[str, Any] | None, *, figure_id: str,
    document_sha256: str, decisions: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return factual differences and native operations; uncertain anchors need answers."""
    records, operations = [], []
    for original in annotation_records(before):
        identifier = original["id"]
        choices = [choice for choice in decisions if choice.get("figure_id") == figure_id and choice.get("id") == identifier]
        if len(choices) > 1:
            raise ValueError("An annotation revision repeats a decision.")
        decision = choices[0] if choices else None
        record: dict[str, Any] = {"figure_id": figure_id, "id": identifier,
            "binding": "observed_peak" if "peak_anchor" in original else "fixed",
            "before": original, "candidates": [], "requires_choice": False}
        candidates: dict[str, dict[str, Any]] = {}
        if after is None:
            record.update(status="figure_missing", requires_choice=True)
        elif "peak_anchor" not in original:
            try:
                normalize_annotation(after, original)
                record["status"] = "fixed_retained"
            except ValueError as exc:
                record.update(status="fixed_incompatible", requires_choice=True, reason=str(exc))
        else:
            old = original["peak_anchor"]
            series = [item for item in after["series"] if item["label"] == old["sample"]]
            if len(series) != 1:
                record.update(status="sample_missing" if not series else "sample_ambiguous", requires_choice=True)
            else:
                try:
                    peaks = peak_candidates_for_spec(after, object_path=f"/page1/graph1/{series[0]['name']}", window=old["window"], polarity=old["polarity"])
                    for peak in peaks:
                        if peak["x_unit"] != old["x_unit"] or peak["y_unit"] != old["y_unit"]:
                            raise ValueError("Peak units changed; this anchor cannot be rebound automatically.")
                        choice = _peak_choice(peak, series[0])
                        choice["preview_marker"] = f"P{len(records) + 1}.{len(record['candidates']) + 1}"
                        record["candidates"].append(choice)
                        candidates[choice["candidate_id"]] = peak
                    record.update(status=("missing" if not peaks else "ambiguous" if len(peaks) > 1 else
                        "unchanged" if (peaks[0]["x"], peaks[0]["y"]) == (old["x"], old["y"]) else "moved"), requires_choice=True)
                except ValueError as exc:
                    record.update(status="anchor_incompatible", requires_choice=True, reason=str(exc))
        operation = None
        if decision is not None:
            action = decision.get("action")
            common = {"figure_id", "id", "action"}
            if action == "remove" and set(decision) == common:
                record["resolution"] = "removed"
            elif action == "keep" and set(decision) == common and record["status"] == "fixed_retained":
                operation = original
                record["resolution"] = "kept"
            elif action == "rebind" and after is not None and set(decision) <= common | {"candidate_id", "text", "position"} and common | {"candidate_id", "text"} <= set(decision):
                peak = candidates.get(decision["candidate_id"])
                if peak is None:
                    raise ValueError("Select a current candidate for this exact sample and annotation.")
                operation = {"op": "add_peak_label", "id": identifier,
                    "candidate": {**peak, "document_sha256": document_sha256, "figure_id": figure_id},
                    "text": decision["text"]}
                if "position" in decision:
                    operation["position"] = decision["position"]
                elif "arrow_to" in original:
                    operation["position"] = original["position"]
                normalize_annotation(after, operation)
                record["resolution"] = "rebound"
            elif action == "replace" and after is not None and set(decision) == common | {"replacement"}:
                operation = decision["replacement"]
                if not isinstance(operation, dict) or operation.get("id") != identifier or operation.get("op") not in {"add_annotation", "add_reference_line"}:
                    raise ValueError("Replacement must be a fixed annotation with the same ID; use rebind for peaks.")
                normalize_annotation(after, operation)
                record["resolution"] = "replaced_with_fixed"
            else:
                raise ValueError("Invalid annotation revision action or fields.")
            record["decision"] = decision
            record["requires_choice"] = False
        elif record["status"] == "fixed_retained":
            operation = original
            record["resolution"] = "kept"
        if operation:
            operations.append(operation)
        elif record["requires_choice"] and after is not None:
            # Temporary review markers are ordinary native annotations. They
            # never enter a ready candidate or a committed project.
            for index, peak in enumerate(record["candidates"]):
                operations.append({"op": "add_annotation", "id": f"review_{len(records)}_{index}",
                    "parent_path": "/page1/graph1", "text": peak["preview_marker"],
                    "position": {"mode": "axes", **{key: peak[key] for key in ("x", "y", "x_unit", "y_unit")}}})
            if not record["candidates"]:
                operations.append({"op": "add_annotation", "id": f"review_{len(records)}_missing",
                    "parent_path": "/page1/graph1", "text": f"{identifier}: {record['status']}",
                    "position": {"mode": "relative", "x": 0.05, "y": max(0.05, 0.95 - 0.08 * len(records))}})
        records.append(record)
    return records, operations


def relocate_annotation_evidence(before: dict[str, Any], relocated: dict[str, Any]) -> dict[str, Any]:
    """Refresh only path-dependent peak signatures after candidate installation."""
    if not before.get("native_annotations"):
        return relocated
    annotation_records(before)
    for old, new in zip(before.get("series", []), relocated.get("series", []), strict=True):
        if {k: v for k, v in old.items() if k != "source_artifacts"} != {k: v for k, v in new.items() if k != "source_artifacts"}:
            raise ValueError("Relocating annotation evidence cannot change scientific series values.")
        if [item["sha256"] for item in old["source_artifacts"]] != [item["sha256"] for item in new["source_artifacts"]]:
            raise ValueError("Relocating annotation evidence cannot change scientific source hashes.")
    result = deepcopy(relocated)
    for item in result["native_annotations"]["items"]:
        if "peak_anchor" not in item:
            continue
        old = item["peak_anchor"]
        peaks = peak_candidates_for_spec(result, object_path=old["object_path"], window=old["window"], polarity=old["polarity"])
        keys = ("point_index", "sample", "x", "y", "x_unit", "y_unit")
        matches = [peak for peak in peaks if all(peak[key] == old[key] for key in keys)]
        if len(matches) != 1:
            raise ValueError("Relocated annotation no longer identifies the same reviewed observed point.")
        item["peak_anchor"] = matches[0]
    annotation_records(result)
    return result
