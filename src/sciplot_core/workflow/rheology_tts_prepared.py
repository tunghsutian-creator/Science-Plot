"""Plot an externally processed numerical plan without scientific calculations."""

from __future__ import annotations

import json
from pathlib import Path

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.studio_core.source_update_commit import reject_symlink_path
from sciplot_core.workflow.rheology_tts_contract import rheology_capabilities, validate_creation_request
from sciplot_core.workflow.rheology_tts_suite import _check_sources, _output_paths


def plot_prepared_suite(request_path: Path, *, resume: bool = False) -> dict:
    """The AI owns all values and roles. This route only validates and draws them."""
    from sciplot_core.rheology_tts_spec import compile_tts_spec
    from sciplot_core.rheology_tts_style import prepare_tts_presentation
    from sciplot_core.workflow.rheology_tts_creation import create_prepared_suite

    request_path = request_path.expanduser()
    reject_symlink_path(request_path)
    request_path = request_path.resolve()
    request = json.loads(request_path.read_text(encoding="utf-8"))
    validate_creation_request(request, prepared=True)
    path = Path(request["prepared_plan"]).expanduser()
    reject_symlink_path(path)
    path = path.resolve()
    input_sha = file_sha256(path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Invalid prepared plan at prepared_plan: expected an object.")
    binding = raw.get("source_binding")
    if not isinstance(binding, dict):
        raise ValueError("Invalid prepared plan at source_binding: expected an object.")
    sources = binding.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("Invalid prepared plan at source_binding.sources: expected a non-empty array of original path and SHA256 bindings.")
    for index, source in enumerate(sources):
        location = f"source_binding.sources[{index}]"
        if not isinstance(source, dict):
            raise ValueError(f"Invalid prepared plan at {location}: expected an object with path and sha256.")
        if set(source) != {"path", "sha256"}:
            raise ValueError(f"Invalid prepared plan at {location}: requires exactly path and sha256.")
        for field in ("path", "sha256"):
            if not isinstance(source[field], str) or not source[field]:
                raise ValueError(f"Invalid prepared plan at {location}.{field}: expected a non-empty string.")
    if not raw.get("transform_ledger"):
        raise ValueError("The AI-prepared plan must disclose transformations, or explicitly declare none.")
    for index, source in enumerate(sources):
        if not Path(source["path"]).is_absolute():
            raise ValueError(f"Invalid prepared plan at source_binding.sources[{index}].path: original source paths must be absolute.")
        reject_symlink_path(Path(source["path"]))
    source = Path(sources[0]["path"]).resolve()
    requested_out = Path(request.get("out", source.parent / f"{source.stem}_Prepared_SciPlot")).expanduser()
    reject_symlink_path(requested_out)
    delivery, workspace = _output_paths(source, requested_out)
    try:
        _check_sources(sources)
        spec = prepare_tts_presentation(raw)
        spec["source_binding"]["prepared_plan"] = {"path": str(path), "sha256": input_sha,
            "authority": "External AI processing; local plotting preserves the supplied numeric coordinates."}
        # Complete validation precedes directory allocation and native side effects.
        compiled = compile_tts_spec(spec)
        if file_sha256(path) != input_sha:
            raise ValueError("Prepared numerical plan changed while reading.")
        return create_prepared_suite(request_path, request, spec, compiled, delivery, workspace,
                                     contract_sha256=rheology_capabilities()["contract_sha256"], resume=resume)
    except Exception as exc:
        from sciplot_core.workflow.rheology_tts_creation_repair import attach_creation_repair
        attach_creation_repair(exc, request_path, workspace)
        raise
