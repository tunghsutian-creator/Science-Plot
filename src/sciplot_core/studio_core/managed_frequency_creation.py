"""One source-bound Managed group, with the ordinary project delivery surface."""

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.foundation.json_io import atomic_write_json, read_json_object
from sciplot_core.foundation.project_session_lease import external_project_session
from sciplot_core.output_contract import REQUEST_DELIVERY_ROOT_KEY, UserOutputLayout
from sciplot_core.semantic import classify_source
from sciplot_core.study_model import study_model_from_request
from sciplot_core.workflow.frequency_managed_workflow import check_visible_frequency_documents, frequency_candidates
from sciplot_core.workflow.request_io import _managed_output_transaction
from sciplot_core.workflow.request_run import _run_request_in_managed_output
from sciplot_core.workflow.scientific_source_resolution import resolve_workflow_scientific_source

from .managed_frequency_query import frequency_roots, frequency_receipt, inspect_frequency_creation


_RULE = "rheology_frequency_sweep"


def create_frequency_project(source: Path, verified: dict[str, Any], layout: UserOutputLayout, *,
                             require_new: Any, owner: str) -> dict[str, Any] | None:
    """Return None only for unclaimed, unsupported original inputs."""
    if verified.get("rule_id") != _RULE or verified.get("template") != "point_line" or (
            "data_mapping" in verified or "source_options" in verified):
        return None
    record, output, authority = frequency_roots(layout)
    request = {"input": str(source), "rule_id": _RULE, "output": str(output),
               REQUEST_DELIVERY_ROOT_KEY: str(layout.delivery_root),
               "resolved_figure_plan": verified["resolved_figure_plan"]}
    if layout.workspace_root.exists() and not record.exists():
        return None
    expected = {"version": 1, "request": request, "owner": owner,
                "source_sha256": verified["preview_identity"]["source_tree_sha256"]}
    candidates = None
    if not record.exists():
        semantic = classify_source(source, requested_rule_id=_RULE)
        study = study_model_from_request(request=request, semantic=semantic, input_path=source)
        resolved, selected = resolve_workflow_scientific_source(
            input_path=source, rule_id=_RULE, template="point_line", study_model=study, request=request)
        if resolved is None or selected is None:
            return None
        candidates = frequency_candidates(resolved, authority=authority)
        if candidates is None:
            return None
        require_new(layout)
        layout.workspace_root.parent.mkdir(parents=True, exist_ok=True)
    with external_project_session(layout.workspace_root):
        if not record.exists():
            require_new(layout)
            with TemporaryDirectory(prefix=".frequency-creation-", dir=layout.workspace_root.parent) as temp:
                stage = Path(temp) / "workspace"
                atomic_write_json(stage / record.name, expected)
                atomic_write_json(stage / "plot_request.json", request)
                stage.rename(layout.workspace_root)
        if read_json_object(record) != expected:
            raise ValueError("This output belongs to a different source-bound Managed frequency project.")
        canonical_request = record.parent / "plot_request.json"
        if read_json_object(canonical_request) != request:
            raise ValueError("The saved Managed frequency plotting request changed; preserve it and choose a new output.")
        check_visible_frequency_documents(authority, request, output, delivery=layout.delivery_root)
        project = authority / canonical_json_sha256(request)
        prior_manifest = read_json_object(output / "manifest.json")
        if prior_manifest is not None and prior_manifest.get("ready_to_use") is True:
            current = inspect_frequency_creation(project)
            assert current is not None
            if current["ready_to_use"]:
                return frequency_receipt(canonical_request, output, prior_manifest)
            if not current["qa"]["current"]:
                raise ValueError("The saved Managed frequency figures changed; open them rather than rerunning creation.")
        with _managed_output_transaction(output):
            manifest = _run_request_in_managed_output(
                request_path=canonical_request, source_request=request, base_dir=record.parent, output_dir=output,
                classifier=classify_source, update_project=False, frequency_authority=authority,
                frequency_prepared=candidates, frequency_required=True)
        return frequency_receipt(canonical_request, output, manifest)


