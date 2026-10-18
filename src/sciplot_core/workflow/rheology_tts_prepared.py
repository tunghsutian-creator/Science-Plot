"""Plot an externally processed numerical plan without scientific calculations."""

from __future__ import annotations

import json
from pathlib import Path

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.studio_core.source_update_commit import reject_symlink_path
from sciplot_core.workflow.rheology_tts_contract import (
    rheology_capabilities,
    validate_creation_request,
    validate_prepared_plan_provenance,
)
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
    validate_prepared_plan_provenance(raw)
    sources = raw["source_binding"]["sources"]
    for source in sources:
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
