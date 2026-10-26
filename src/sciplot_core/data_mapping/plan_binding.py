"""Bind a public creation plan to one verified confirmed mapping execution."""

from __future__ import annotations

from sciplot_core.data_mapping.execution_directories import mapping_directory_path

from pathlib import Path
from copy import deepcopy
from typing import Any
from collections.abc import Callable

import pandas as pd

from sciplot_core.data_mapping.contracts import _read_json
from sciplot_core.data_mapping.execution_inputs import mapping_file_path, mapping_input_reads
from sciplot_core.data_mapping.curve_support import table_mapping_shape, supports_table_mapping
from sciplot_core.data_mapping.execution_loading import load_data_mapping_execution
from sciplot_core.data_mapping.request_resolution import resolve_data_mapping_request
from sciplot_core.data_mapping.source_projection import mapping_source_groups
from sciplot_core.foundation.source_tree import source_tree_sha256
from sciplot_core.materials_rules import get_rule
from sciplot_core.semantic_sources.impact_sources import _read_impact_source


def mapped_preview_request(seed: dict[str, Any], binding: dict[str, Any]) -> dict[str, Any]:
    """Project category order for FigureTask without rewriting physical group order."""
    request = deepcopy(seed)
    request.pop("data_mapping_execution", None)
    request.pop("data_mapping_proposal_id", None)
    request["input"] = binding["effective_input"]
    if binding.get("source_group_ids"):
        request["series_order"] = binding["expected_sample_labels"]
        if isinstance(request.get("render_options"), dict):
            request["render_options"]["series_order"] = binding["expected_sample_labels"]
    return request


def resolve_mapping_plan_request(
    source: Path, request: dict[str, Any], *,
    source_tree_reader: Callable[[Path], str | None] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    reference = request.get("data_mapping_execution")
    if not isinstance(reference, str) or not reference.strip():
        raise ValueError("A mapping plan requires its confirmed execution path.")
    with mapping_input_reads(reference, expected_source=source):
        return _resolve_mapping_plan_request(source, request, source_tree_reader=source_tree_reader)


def _resolve_mapping_plan_request(source: Path, request: dict[str, Any], *,
    source_tree_reader: Callable[[Path], str | None] | None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Recover scientific fields from the immutable receipt, never caller overrides."""

    source = source.expanduser().resolve()
    reference = request.get("data_mapping_execution")
    proposal_id = request.get("data_mapping_proposal_id")
    if not isinstance(reference, str) or not reference.strip():
        raise ValueError("A mapping plan requires its confirmed execution path.")
    if not isinstance(proposal_id, str) or not proposal_id.strip():
        raise ValueError("A mapping plan requires its exact proposal identity.")
    execution = load_data_mapping_execution(reference, expected_source=source)
    if execution.get("handoff_allowed") is not True:
        raise ValueError("A mapping plan requires a current path-bound confirmation.")
    if execution["proposal_id"] != proposal_id:
        raise ValueError("The mapping plan refers to another proposal.")
    seed = _read_json(Path(execution["request_seed"]))
    original = seed.get("input")
    if not isinstance(original, str) or Path(original).expanduser().resolve() != source:
        raise ValueError("The mapping request does not target the original task source.")
    outputs = execution.get("outputs") or []
    raw_hashes = set(execution["source_hashes"].values())
    if not outputs or len(raw_hashes) != 1 or not mapping_file_path(source, expected_sha256=next(iter(raw_hashes))).is_file():
        raise ValueError("Mapped creation requires one original source file and selected output tables.")
    recorded_sources = {
        (Path(execution["source_root"]) / output["source_relative_path"]).resolve()
        for output in outputs
    }
    if recorded_sources != {source} or len(execution["source_hashes"]) != 1:
        raise ValueError("The confirmed mapping does not cover exactly the task source.")
    for key in ("rule_id", "template"):
        selected = seed.get(key)
        if not isinstance(selected, str) or not selected:
            raise ValueError(f"The confirmed mapping request is missing {key}.")
        if key in request and request[key] != selected:
            raise ValueError(f"The mapping plan cannot override confirmed {key}.")
    if "xscale" in request and request["xscale"] != seed.get("xscale"):
        raise ValueError("The mapping plan cannot override confirmed xscale.")
    rule = get_rule(seed["rule_id"])
    proposal = _read_json(Path(execution["proposal"]))
    replicates = "replicates" in proposal.get("table_confirmation", {})
    if replicates:
        if table_mapping_shape(rule, summary_statistic=seed.get("summary_statistic")) != "replicates":
            raise ValueError("Confirmed replicate columns require the existing raw-only replicate adapter.")
        if "summary_statistic" in request and request["summary_statistic"] != "raw_only":
            raise ValueError("The mapping plan cannot override its confirmed raw-only choice.")
    elif not supports_table_mapping(rule):
        raise ValueError("This scientific adapter does not consume confirmed XY tables.")
    effective, application = resolve_data_mapping_request(
        seed, base_dir=Path(execution["request_seed"]).parent
    )
    if application is None:
        raise ValueError("The immutable mapping request lost its execution binding.")
    effective_input = Path(effective["input"]).expanduser().resolve()
    if source_tree_reader is None:
        original_hash = source_tree_sha256(source, expected_file_sha256=next(iter(raw_hashes)))
        actual_input = (mapping_directory_path(execution) if execution["effective_input"] == execution["data_dir"]
                        else mapping_file_path(effective_input))
        effective_hash = source_tree_sha256(actual_input)
    else:
        original_hash = source_tree_reader(source)
        effective_hash = source_tree_reader(effective_input)
    if original_hash is None or effective_hash is None:
        raise ValueError("A mapping plan source is unavailable.")
    binding = {
        "data_mapping_execution": str(Path(application["execution"]).resolve()),
        "data_mapping_proposal_id": proposal_id,
        "proposal_sha256": execution["proposal_sha256"],
        "confirmation_id": execution["confirmation_id"],
        "request_seed_sha256": execution["request_seed_sha256"],
        "original_input": str(source),
        "original_input_sha256": original_hash,
        "effective_input": str(effective_input),
        "effective_input_sha256": effective_hash,
        "expected_sample_labels": application["expected_sample_labels"],
        **({"source_group_ids": [group["source_id"] for group in application["source_groups"]]}
           if application.get("source_groups") else {}),
        **({"mapping_shape": "replicates"} if replicates else {}),
        **({"expected_series_points": application["expected_series_points"]}
           if execution["provider"] == "explicit_table_choice" and not replicates else {}),
    }
    return seed, binding


def verify_mapping_sample_identity(
    binding: dict[str, Any], scientific_transform: dict[str, Any] | None
) -> None:
    """File-safe output naming must never rename confirmed scientific samples."""

    if binding.get("mapping_shape") == "replicates":
        verify_replicate_projection(binding)
        return
    output = scientific_transform.get("output") if scientific_transform else None
    actual = output.get("series_order") if isinstance(output, dict) else None
    if actual != binding["expected_sample_labels"]:
        raise ValueError(
            "Mapped scientific sample labels do not match the confirmed labels: "
            f"expected {binding['expected_sample_labels']!r}, found {actual!r}."
        )
    if "expected_series_points" in binding:
        series = output.get("series", []) if isinstance(output, dict) else []
        stress = scientific_transform and scientific_transform.get("semantic_family") == "rheology_stress_relaxation"
        counts = {item["sample"]: item["source_point_count"] if stress else item["point_count"] for item in series}
        if counts != binding["expected_series_points"]:
            raise ValueError("Mapped scientific point counts do not match each confirmed source range.")


def verify_replicate_projection(binding: dict[str, Any]) -> None:
    """Check finite display membership against complete, source-verified domains."""
    with mapping_input_reads(binding["data_mapping_execution"], expected_source=Path(binding["original_input"])):
        _verify_replicate_projection(binding)


def _verify_replicate_projection(binding: dict[str, Any]) -> None:

    # This rebuilds every complete original region and verifies its output bytes,
    # including null positions. The finite projection cannot establish that domain.
    execution = load_data_mapping_execution(binding["data_mapping_execution"])
    groups = mapping_source_groups(execution)
    if groups and binding.get("source_group_ids") != [group["source_id"] for group in groups]:
        raise ValueError("Mapped raw group identity differs from its original physical domains.")
    expected = []
    for output in execution["outputs"]:
        frame = pd.read_csv(mapping_file_path(Path(output["path"]), expected_sha256=output["sha256"]), float_precision="round_trip")
        if list(frame.columns) != ["Impact strength"] or len(frame) != output["rows"]:
            raise ValueError("Mapped replicate domain no longer matches its confirmed output.")
        expected.append(tuple(float(value).hex() for value in frame.iloc[:, 0] if pd.notna(value)))
    if groups:
        # load_data_mapping_execution already reproduced each complete original
        # domain and the composite. A sample aggregate cannot prove membership
        # of several independent groups in the same category.
        return
    actual = _read_impact_source(Path(binding["effective_input"]))
    if list(actual.samples) != binding["expected_sample_labels"] or (
            tuple(tuple(float(value).hex() for value in values) for values in actual.values) != tuple(expected)):
        raise ValueError("Raw replicate display membership/order differs from the confirmed original domains.")

def project_replicate_binding(request: dict[str, Any]) -> dict[str, Any] | None:
    """Recover raw mode only from an existing immutable mapping and its science."""
    binding = request.get("data_mapping_plan_binding")
    if not isinstance(binding, dict) or binding.get("mapping_shape") != "replicates":
        return None

    seed, current = resolve_mapping_plan_request(Path(binding["original_input"]), {
        **binding, "rule_id": request.get("rule_id"), "template": request.get("template"),
    })
    if (current != binding or request.get("input") != binding["original_input"]
            or request.get("summary_statistic") != "raw_only"
            or (request.get("render_options") or {}).get("summary_statistic") != "raw_only"
            or request.get("data_mapping_execution") != seed["data_mapping_execution"]
            or request.get("data_mapping_proposal_id") != seed["data_mapping_proposal_id"]):
        raise ValueError("The project's immutable replicate binding and raw-only scientific presentation disagree.")
    verify_replicate_projection(current)
    return current

def verify_replicate_source_expansion(previous: dict[str, Any], source: Path,
                                      request: dict[str, Any], plan: dict[str, Any]) -> None:
    """An existing raw binding may gain groups without replacing old observations."""
    from sciplot_core.data_mapping.execution_inputs import without_mapping_inputs

    with without_mapping_inputs():
        old = project_replicate_binding(previous)
    if old is None:
        if (plan.get("data_mapping") or {}).get("mapping_shape") == "replicates":
            raise ValueError("Adding raw groups requires an existing immutable raw group binding.")
        return  # Existing non-replicate source revisions keep their own contracts.

    _, new = resolve_mapping_plan_request(source, request)
    if (new.get("mapping_shape") != "replicates" or old["original_input"] != new["original_input"]
            or old["original_input_sha256"] != new["original_input_sha256"]):
        raise ValueError("Adding raw groups requires the same unchanged original source; old source identity cannot be replaced.")
    labels = old.get("source_group_ids", old["expected_sample_labels"])
    new_labels = new.get("source_group_ids", new["expected_sample_labels"])
    if len(new_labels) <= len(labels) or new_labels[:len(labels)] != labels:
        raise ValueError("Select every existing raw group in its original order, followed by the added groups.")
    for key in ("primary_figure_id", "tasks"):
        before_plan = previous.get("resolved_figure_plan") or {}
        after_plan = plan.get("resolved_figure_plan") or {}
        if before_plan.get(key) != after_plan.get(key):
            raise ValueError("Adding raw groups must preserve the existing figure task identity.")
    with without_mapping_inputs(), mapping_input_reads(old["data_mapping_execution"], expected_source=source):
        before = load_data_mapping_execution(old["data_mapping_execution"])
        old_proposal = _read_json(Path(before["proposal"]))
    with mapping_input_reads(new["data_mapping_execution"], expected_source=source):
        after = load_data_mapping_execution(new["data_mapping_execution"])
        new_proposal = _read_json(Path(after["proposal"]))
    for index in range(len(labels)):
        source_id = old_proposal["sources"][index]["source_id"]
        if old_proposal.get("display_labels", {}).get(source_id) != new_proposal.get("display_labels", {}).get(source_id):
            raise ValueError("Adding groups must preserve an existing raw group's confirmed display label.")
        for key in ("sources", "columns"):
            if old_proposal[key][index] != new_proposal[key][index]:
                raise ValueError("An existing raw group's original sheet, rows, cells or column identity changed.")
        if any(before["outputs"][index][key] != after["outputs"][index][key]
               for key in ("source_id", "rows", "columns", "sample_label", "sha256")):
            raise ValueError("An existing raw group's complete row domain, mask or values changed.")


__all__ = ["resolve_mapping_plan_request", "verify_mapping_sample_identity",
           "verify_replicate_projection", "project_replicate_binding", "verify_replicate_source_expansion"]
