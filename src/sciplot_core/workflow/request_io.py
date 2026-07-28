"""Load requests, resolve paths, archive inputs, and bind runtime lineage."""

from __future__ import annotations

import json
import shutil
from copy import deepcopy
from pathlib import Path
from typing import Any
from sciplot_core.foundation.path_names import (
    unique_path,
)
from sciplot_core.assisted_cleanup import (
    CLEANUP_REQUEST_FILENAME,
)
from sciplot_core.managed_output import managed_output_transaction
from sciplot_core.policy import (
    DELIVERY_DIR,
)
from sciplot_core.source_coverage import (
    verify_rendered_mapping_source_coverage,
)


_MANAGED_OUTPUT_DIRECTORIES = (
    "processed",
    "figures",
    "tables",
    "raw",
    DELIVERY_DIR,
)


_MANAGED_OUTPUT_FILES = (
    "request_snapshot.json",
    "manifest.json",
    "analysis_report.md",
    "revision_brief.md",
    "review.html",
    "intervention_request.json",
    CLEANUP_REQUEST_FILENAME,
    "publication_intent.json",
    "transform_ledger.json",
    "journal_profile.json",
    "publication_qa.json",
    "one_step_status.json",
    "autoplot_summary.json",
)


def _load_request(request_path: Path) -> dict[str, Any]:
    if request_path.suffix.lower() != ".json":
        raise ValueError(
            "Plot requests currently support JSON files. Use a .json request file."
        )
    payload = json.loads(request_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Plot request must be a JSON object.")
    return payload


def _resolve_request_path(value: object, *, base_dir: Path, field: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Plot request must define a non-empty `{field}` path.")
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path


def _resolve_optional_request_path(value: object, *, base_dir: Path) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path


def _bind_result_data_snapshots(
    result: dict[str, Any],
    *,
    plotted_source: Path,
    mapping_application: dict[str, Any] | None,
    request: dict[str, Any],
) -> dict[str, Any]:
    resolved_source = plotted_source.expanduser().resolve()
    snapshot_paths = [resolved_source]
    if mapping_application is not None:
        effective_input = (
            Path(str(mapping_application.get("effective_input") or ""))
            .expanduser()
            .resolve()
        )
        if resolved_source == effective_input and resolved_source.is_dir():
            snapshot_paths = sorted(
                {
                    Path(str(record.get("path") or "")).expanduser().resolve()
                    for record in mapping_application.get("mapped_outputs", [])
                    if isinstance(record, dict)
                    and isinstance(record.get("path"), str)
                    and str(record["path"]).strip()
                },
                key=str,
            )
            if not snapshot_paths:
                raise ValueError(
                    "A mapped directory render has no concrete plotted tables."
                )
            for path in snapshot_paths:
                try:
                    path.relative_to(resolved_source)
                except ValueError as exc:
                    raise ValueError(
                        "A mapped plotted table is outside the effective input "
                        "directory."
                    ) from exc
                if not path.is_file():
                    raise FileNotFoundError(f"Mapped plotted table not found: {path}")
    result["data_snapshot_sources"] = [str(path) for path in snapshot_paths]
    if len(snapshot_paths) == 1:
        result["data_snapshot_source"] = str(snapshot_paths[0])
    else:
        result.pop("data_snapshot_source", None)
    if mapping_application is not None:
        result["rendered_source_coverage"] = verify_rendered_mapping_source_coverage(
            result,
            mapping_application=mapping_application,
            request=request,
        )
    return result


def _extend_runtime_transform_steps(
    target: list[dict[str, Any]],
    steps: object,
) -> None:
    """Merge terminal runtime lineage without duplicating step identities."""

    if not isinstance(steps, list):
        return
    for step in steps:
        if not isinstance(step, dict):
            continue
        candidate = deepcopy(step)
        if candidate in target:
            continue
        step_id = str(candidate.get("id") or "").strip()
        same_id = next(
            (
                (index, existing)
                for index, existing in enumerate(target)
                if step_id and str(existing.get("id") or "").strip() == step_id
            ),
            None,
        )
        if same_id is None:
            target.append(candidate)
            continue
        index, existing = same_id
        candidate_operation = str(candidate.get("operation") or "").strip()
        existing_operation = str(existing.get("operation") or "").strip()
        if candidate_operation == "identity":
            # Terminal compilation commonly confirms that an already prepared
            # table is plot-ready. The upstream non-identity preparation
            # remains the authoritative step for that shared id.
            continue
        if existing_operation == "identity":
            target[index] = candidate
            continue
        raise ValueError(
            "Conflicting runtime transform steps share the id "
            f"`{step_id}`; terminal lineage cannot be merged silently."
        )


def _managed_output_transaction(output_dir: Path):
    return managed_output_transaction(
        output_dir,
        managed_names=(*_MANAGED_OUTPUT_DIRECTORIES, *_MANAGED_OUTPUT_FILES),
    )


def _request_options(request: dict[str, Any]) -> dict[str, Any]:
    options: dict[str, Any] = {}
    if "template" in request:
        options["template"] = request["template"]
    if "render_options" in request:
        options["render_options"] = request["render_options"]
    if "exports" in request:
        options["exports"] = request["exports"]
    return options


def _archive_raw_input(input_path: Path, output_dir: Path) -> dict[str, Any]:
    raw_dir = output_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    destination = unique_path(raw_dir, input_path.name)
    if input_path.is_dir():
        shutil.copytree(input_path, destination)
        kind = "directory"
    else:
        shutil.copy2(input_path, destination)
        kind = "file"
    return {
        "kind": kind,
        "source": str(input_path),
        "path": str(destination),
    }


def _figures_from_result(result: dict[str, Any]) -> list[str]:
    figures = result.get("figures") or result.get("outputs") or []
    return [str(path) for path in figures]
