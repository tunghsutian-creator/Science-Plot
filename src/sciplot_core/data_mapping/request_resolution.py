"""Resolve the active confirmed mapping request for downstream rendering."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from sciplot_core.data_mapping.contracts import (
    DATA_MAPPING_APPLICATION_KIND,
    DATA_MAPPING_APPLICATION_VERSION,
    _read_json,
)

from sciplot_core.data_mapping.execution_loading import (
    load_data_mapping_execution,
)


def resolve_data_mapping_request(
    request: dict[str, Any],
    *,
    base_dir: str | Path,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    execution_value = request.get("data_mapping_execution")
    if not isinstance(execution_value, str) or not execution_value.strip():
        return deepcopy(request), None
    execution_path = Path(execution_value).expanduser()
    if not execution_path.is_absolute():
        execution_path = (
            Path(base_dir).expanduser().resolve() / execution_path
        ).resolve()
    execution = load_data_mapping_execution(execution_path)
    if execution.get("handoff_allowed") is not True:
        raise ValueError(
            "Mapped execution uses a path-unbound v1 confirmation; explicit "
            "v2 reconfirmation is required before rendering or handoff."
        )
    seed_payload = _read_json(Path(str(execution["request_seed"])).expanduser())
    if request.get("input") != seed_payload.get("input"):
        raise ValueError(
            "Mapped project raw input no longer matches its immutable request seed."
        )
    if request.get("data_mapping_proposal_id") != execution.get("proposal_id"):
        raise ValueError(
            "Mapped project proposal ID no longer matches its verified execution."
        )
    effective_input = Path(str(execution.get("effective_input") or "")).expanduser()
    if not effective_input.exists():
        raise FileNotFoundError(f"Mapped effective input not found: {effective_input}")
    effective = deepcopy(request)
    effective.update(deepcopy(execution.get("request_patch") or {}))
    original_input = effective.get("input")
    effective["input"] = str(effective_input)
    mapped_outputs = [
        {
            "source_id": str(output.get("source_id") or ""),
            "path": str(output.get("path") or ""),
            "sha256": str(output.get("sha256") or ""),
            "rows": int(output.get("rows") or 0),
            "columns": [str(column) for column in output.get("columns", [])],
            "sample_label": (
                str(output["sample_label"])
                if output.get("sample_label") is not None
                else None
            ),
        }
        for output in execution.get("outputs", [])
        if isinstance(output, dict)
    ]
    expected_labels = list(
        dict.fromkeys(
            str(output.get("sample_label") or "").strip()
            or Path(str(output.get("path") or "")).stem
            for output in mapped_outputs
        )
    )
    application = {
        "kind": DATA_MAPPING_APPLICATION_KIND,
        "version": DATA_MAPPING_APPLICATION_VERSION,
        "status": "validated",
        "execution": str(execution_path),
        "proposal_id": execution["proposal_id"],
        "proposal_sha256": execution["proposal_sha256"],
        "provider": execution["provider"],
        "confirmation_id": execution["confirmation_id"],
        "confirmed_by": execution["confirmed_by"],
        "original_input": str(original_input or ""),
        "effective_input": str(effective_input),
        "source_root": execution["source_root"],
        "source_hashes": deepcopy(execution["source_hashes"]),
        "mapped_outputs": mapped_outputs,
        "expected_sample_labels": expected_labels,
        "expected_series_count_min": len(expected_labels),
        "transform_steps": deepcopy(execution.get("transform_steps") or []),
        "transform_ledger": _read_json(
            Path(str(execution["transform_ledger"])).expanduser()
        ),
        "raw_inputs_preserved": True,
        "outputs_verified": True,
    }
    effective["transform_ledger"] = deepcopy(application["transform_ledger"])
    effective["data_mapping_application"] = deepcopy(application)
    return effective, application
