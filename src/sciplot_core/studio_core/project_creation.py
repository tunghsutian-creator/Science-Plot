"""Model-free creation and publication shared by CLI, tasks and MCP."""

from __future__ import annotations

from pathlib import Path
from collections.abc import Callable
from typing import Any

from sciplot_core.data_mapping.plan_binding import resolve_mapping_plan_request
from sciplot_core.foundation.json_io import atomic_write_json
from sciplot_core.output_contract import (
    REQUEST_DELIVERY_ROOT_KEY,
    UserOutputLayout,
    resolve_user_output_layout,
)
from sciplot_core.foundation.source_tree import source_tree_sha256
from sciplot_core.plan_preview import verify_expected_plan
from sciplot_core.studio_core.project_export import export_project_document
from sciplot_core.studio_core.project_query import resolve_project_path
from sciplot_core.studio_core.project_query_paths import canonical_path
from sciplot_core.studio_core.project_receipt import project_receipt
from sciplot_core.studio_core.project_session import external_project_session
from sciplot_core.studio_core.studio_prepare import prepare_studio_document


def require_new_layout(layout: UserOutputLayout) -> None:
    for path in (layout.delivery_root, layout.workspace_root):
        canonical_path(path)
        if path.exists():
            raise ValueError(
                f"Project creation requires a new delivery and workspace: {path}. "
                "Inspect an existing project or choose a new output directory."
            )


def _publish(payload: dict[str, Any]) -> dict[str, Any]:
    published = export_project_document(
        project_dir=Path(payload["project_dir"]),
        request_path=Path(payload["request"]),
        document_path=Path(payload["document"]),
        formats=["pdf", "tiff_300"],
    )
    payload = {**payload, "studio_run": published.run_payload}
    return project_receipt(payload, 0 if published.ready_to_use else 1)


def create_project(
    source: Path,
    *,
    expected_plan: dict[str, Any],
    output_dir: Path | None = None,
    on_prepared: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    source = canonical_path(source)
    if (expected_plan.get("rule_id") is not None
            and not isinstance(expected_plan["rule_id"], str)) or not isinstance(
                expected_plan.get("template"), str):
        raise ValueError("The expected plan has invalid rule/template identities.")
    verified = verify_expected_plan(
        source, expected_plan, rule_id=expected_plan.get("rule_id"),
        template=expected_plan.get("template"),
    )
    layout = resolve_user_output_layout(source, requested_delivery_root=output_dir)
    require_new_layout(layout)
    canonical_path(layout.workspace_root.parent)
    layout.workspace_root.parent.mkdir(parents=True, exist_ok=True)
    with external_project_session(layout.workspace_root):
        require_new_layout(layout)
        if "data_mapping" in verified:
            payload = _prepare_mapped_project(source, verified=verified, layout=layout)
        else:
            payload = prepare_studio_document(
                source, output_root=layout.workspace_root / "projects",
                delivery_root=layout.delivery_root, rule_id=verified["rule_id"],
                template=verified["template"],
            )
        if source_tree_sha256(source) != verified["preview_identity"]["source_tree_sha256"]:
            raise ValueError(
                "Source changed during project preparation. The candidate is preserved; "
                "no delivery was published. Start a new source-bound plan."
            )
        if on_prepared is not None:
            on_prepared({key: payload[key] for key in ("project_dir", "document", "request")})
        return _publish(payload)


def _prepare_mapped_project(
    source: Path, *, verified: dict[str, Any], layout: UserOutputLayout
) -> dict[str, Any]:
    """Enter the existing canonical-request Studio route with confirmed lineage."""

    mapping = verified["data_mapping"]
    request, current = resolve_mapping_plan_request(
        source,
        {**mapping, "rule_id": verified["rule_id"], "template": verified["template"]},
    )
    if current != mapping:
        raise ValueError("The confirmed mapping changed after the expected plan.")
    project = layout.workspace_root / "projects" / source.stem
    project.mkdir(parents=True, exist_ok=False)
    request["output"] = str(project / "runs" / "run_001")
    request[REQUEST_DELIVERY_ROOT_KEY] = str(layout.delivery_root)
    request["resolved_figure_plan"] = verified["resolved_figure_plan"]
    request["data_mapping_plan_binding"] = current
    request_path = project / "plot_request.json"
    atomic_write_json(request_path, request)
    return prepare_studio_document(request_path)


def export_project(project: Path) -> dict[str, Any]:
    root = resolve_project_path(project)
    with external_project_session(root):
        payload = prepare_studio_document(root)
        result = _publish(payload)
    return {
        **result, "kind": "sciplot_project_export_result",
        "status": "exported" if result["studio_run"]["ready_to_use"] else "blocked",
    }
