"""Rebind mapped outputs into study models and candidate render requests."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any
from sciplot_core.mapping_contract import (
    DataMappingProposal,
)
from sciplot_core.study_model import normalize_study_model

from sciplot_core.data_mapping.output_files import (
    _stable_id,
)


def _rebind_study_model(
    request: dict[str, Any],
    proposal: DataMappingProposal,
    *,
    source_root: Path,
) -> dict[str, Any] | None:
    existing = request.get("study_model")
    if not isinstance(existing, dict):
        return None
    model = normalize_study_model(existing)
    replicate_by_hash: dict[str, tuple[str, dict[str, Any]]] = {}
    for sample in model.get("samples", []):
        if not isinstance(sample, dict):
            continue
        sample_id = str(sample.get("id") or "")
        for replicate in sample.get("replicates", []):
            if not isinstance(replicate, dict):
                continue
            source_file = (
                replicate.get("source_file")
                if isinstance(replicate.get("source_file"), dict)
                else {}
            )
            digest = str(source_file.get("sha256") or "")
            if digest:
                replicate_by_hash[digest] = (
                    sample_id,
                    deepcopy(replicate),
                )

    grouped: dict[str, list[tuple[str | None, dict[str, Any]]]] = {}
    group_order: list[str] = []
    for reference in proposal.sources:
        label = (
            proposal.sample_labels.get(reference.source_id)
            or Path(reference.relative_path).stem
            or reference.source_id
        )
        if label not in grouped:
            grouped[label] = []
            group_order.append(label)
        matched = replicate_by_hash.get(reference.sha256)
        if matched is not None:
            grouped[label].append(matched)
            continue
        source_path = source_root / reference.relative_path
        grouped[label].append(
            (
                None,
                {
                    "id": "",
                    "name": source_path.stem,
                    "order": 0,
                    "source_file": {
                        "original_name": source_path.name,
                        "raw_path": str(source_path),
                        "source_path": str(source_path),
                        "size_bytes": source_path.stat().st_size,
                        "sha256": reference.sha256,
                    },
                },
            )
        )

    used_sample_ids: set[str] = set()
    used_replicate_ids: set[str] = set()
    old_to_new_sample: dict[str, str] = {}
    samples: list[dict[str, Any]] = []
    for order, label in enumerate(group_order, start=1):
        members = grouped[label]
        old_ids = [old_id for old_id, _replicate in members if old_id]
        if len(set(old_ids)) == 1:
            candidate = old_ids[0]
            sample_id = (
                candidate
                if candidate and candidate not in used_sample_ids
                else _stable_id("sample", label, used_sample_ids)
            )
            used_sample_ids.add(sample_id)
        else:
            sample_id = _stable_id("sample", label, used_sample_ids)
        for old_id in old_ids:
            old_to_new_sample[old_id] = sample_id
        replicates: list[dict[str, Any]] = []
        for replicate_order, (_old_id, replicate) in enumerate(members, start=1):
            item = deepcopy(replicate)
            replicate_id = str(item.get("id") or "")
            if not replicate_id or replicate_id in used_replicate_ids:
                replicate_id = _stable_id(
                    f"{sample_id}_replicate",
                    str(item.get("name") or replicate_order),
                    used_replicate_ids,
                )
            else:
                used_replicate_ids.add(replicate_id)
            item["id"] = replicate_id
            item["order"] = replicate_order
            replicates.append(item)
        samples.append(
            {
                "id": sample_id,
                "name": label,
                "order": order,
                "replicate_mode": str(
                    proposal.request_patch.get("replicate_mode")
                    or model.get("replicate_policy", {}).get("mode")
                    or "mean"
                ),
                "replicates": replicates,
            }
        )

    rebound = deepcopy(model)
    rebound["samples"] = samples
    rebound["sample_order"] = [sample["name"] for sample in samples]
    if "replicate_mode" in proposal.request_patch:
        rebound.setdefault("replicate_policy", {})["mode"] = proposal.request_patch[
            "replicate_mode"
        ]
    valid_source_refs = {
        str(replicate.get("id"))
        for sample in samples
        for replicate in sample.get("replicates", [])
        if isinstance(replicate, dict) and replicate.get("id")
    }
    valid_sample_refs = {str(sample["id"]) for sample in samples}
    for figure in rebound.get("figure_queue", []):
        if not isinstance(figure, dict):
            continue
        evidence = (
            figure.get("evidence_contract")
            if isinstance(figure.get("evidence_contract"), dict)
            else {}
        )
        old_source_refs = [
            str(item) for item in evidence.get("source_refs", []) if str(item)
        ]
        old_sample_refs = [
            str(item) for item in evidence.get("sample_refs", []) if str(item)
        ]
        evidence["source_refs"] = [
            item for item in old_source_refs if item in valid_source_refs
        ]
        translated_samples = [
            old_to_new_sample.get(item, item) for item in old_sample_refs
        ]
        evidence["sample_refs"] = list(
            dict.fromkeys(
                item for item in translated_samples if item in valid_sample_refs
            )
        )
        evidence["confirmation_status"] = (
            "confirmed_mapping"
            if evidence["source_refs"] or evidence["sample_refs"]
            else "pending"
        )
        figure["evidence_contract"] = evidence
    rebound["data_mapping"] = {
        "proposal_id": proposal.proposal_id,
        "provider": proposal.provider,
        "source_hashes": proposal.source_hashes,
        "raw_sources_preserved": True,
    }
    return normalize_study_model(rebound)


def _candidate_request(
    base_request: dict[str, Any],
    proposal: DataMappingProposal,
    *,
    source_root: Path,
    execution_path: Path,
    output_root: Path,
    transform_ledger: dict[str, Any],
    output_labels: list[str],
    superseded_ledger_path: Path | None,
) -> dict[str, Any]:
    request = deepcopy(base_request)
    request.update(deepcopy(proposal.request_patch))
    request["data_mapping_execution"] = str(execution_path)
    request["data_mapping_proposal_id"] = proposal.proposal_id
    request["output"] = str(output_root / "run")
    request["transform_ledger"] = deepcopy(transform_ledger)
    if superseded_ledger_path is not None:
        request["data_mapping_superseded_transform_ledger"] = str(
            superseded_ledger_path
        )
    if output_labels and "series_order" not in proposal.request_patch:
        request["series_order"] = list(output_labels)
    series_order = request.get("series_order")
    if isinstance(series_order, list):
        render_options = (
            deepcopy(request.get("render_options"))
            if isinstance(request.get("render_options"), dict)
            else {}
        )
        if "series_order" in render_options:
            render_options["series_order"] = list(series_order)
        if "series_include" in render_options:
            render_options["series_include"] = list(series_order)
        if render_options:
            request["render_options"] = render_options
    rebound = _rebind_study_model(request, proposal, source_root=source_root)
    if rebound is not None:
        request["study_model"] = rebound
    notes = (
        list(request.get("review_notes"))
        if isinstance(request.get("review_notes"), list)
        else []
    )
    note = (
        f"Confirmed DataMappingProposal {proposal.proposal_id} "
        f"from {proposal.provider}; raw input remains immutable."
    )
    if note not in notes:
        notes.append(note)
    request["review_notes"] = notes
    return request
