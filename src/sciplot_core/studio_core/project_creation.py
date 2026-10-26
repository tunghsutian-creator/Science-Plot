"""Model-free creation and publication shared by CLI, tasks and MCP."""

from __future__ import annotations

from pathlib import Path
from collections.abc import Callable
from copy import deepcopy
from typing import Any

from sciplot_core.data_mapping.plan_binding import resolve_mapping_plan_request
from sciplot_core.foundation.json_io import atomic_write_json
from sciplot_core.source_tables.read_session import with_table_reads
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


@with_table_reads
def create_project(
    source: Path,
    *,
    expected_plan: dict[str, Any],
    output_dir: Path | None = None,
    on_prepared: Callable[[dict[str, Any]], None] | None = None,
    publish: bool = True,
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
    # Only initial namespace creation needs a separate claim. All recognized
    # project mutations use the short ProjectStore lease and observed baseline.
    layout.workspace_root.mkdir(mode=0o700, exist_ok=False)
    claimed = layout.workspace_root.lstat()
    if layout.delivery_root.exists():
        raise ValueError("The requested new delivery was occupied before project creation.")
    if "data_mapping" in verified or "source_options" in verified:
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
    canonical_path(layout.workspace_root)
    current = layout.workspace_root.lstat()
    if (current.st_dev, current.st_ino) != (claimed.st_dev, claimed.st_ino):
        raise ValueError("The new workspace namespace changed identity during preparation.")
    if not publish:
        return {"kind": "sciplot_project_prepared_result", "version": 1, "status": "prepared",
                **{key: payload[key] for key in ("project_dir", "document", "request")},
                "ready_to_use": False, "export_performed": False}
    if layout.delivery_root.exists():
        raise ValueError("The requested new delivery was occupied during private preparation.")
    return _publish(payload)


def _prepare_mapped_project(
    source: Path, *, verified: dict[str, Any], layout: UserOutputLayout
) -> dict[str, Any]:
    """Enter the existing canonical-request Studio route with confirmed lineage."""

    project = layout.workspace_root / "projects" / source.stem
    request = request_from_verified_plan(source, verified=verified, project_dir=project, delivery_root=layout.delivery_root)
    project.mkdir(parents=True, exist_ok=False)
    request_path = project / "plot_request.json"
    atomic_write_json(request_path, request)
    if verified["rule_id"] == "rheology_stress_relaxation":
        return prepare_studio_document(request_path, rule_id=verified["rule_id"], template=verified["template"])
    return prepare_studio_document(request_path, _new_creation=True)


def request_from_verified_plan(source: Path, *, verified: dict[str, Any], project_dir: Path,
                               delivery_root: Path) -> dict[str, Any]:
    """Recover confirmed scientific choices without allocating or writing a project."""

    current = None
    if "data_mapping" in verified:
        mapping = verified["data_mapping"]
        request, current = resolve_mapping_plan_request(
            source, {**mapping, "rule_id": verified["rule_id"], "template": verified["template"]},
        )
        if current != mapping:
            raise ValueError("The confirmed mapping changed after the expected plan.")
    else:
        request = {"input": str(source), "rule_id": verified["rule_id"], "template": verified["template"]}
    request.update(deepcopy(verified.get("source_options", {})))
    if request.get("summary_statistic") == "raw_only":
        request["render_options"] = {**request.get("render_options", {}), "summary_statistic": "raw_only"}
    request["output"] = str(project_dir / "runs" / "run_001")
    request[REQUEST_DELIVERY_ROOT_KEY] = str(delivery_root)
    request["resolved_figure_plan"] = deepcopy(verified["resolved_figure_plan"])
    if current is not None:
        request["data_mapping_plan_binding"] = current
    if verified["rule_id"] == "rheology_stress_relaxation":
        # The canonical-request route must reuse the rule-default owner just as
        # raw-source intake does. A top-level scientific choice alone is not a
        # render option and must never leave a log projection on a linear axis.
        scale = request.get("xscale", "log")
        request["render_options"] = {"xscale": scale,
            **({"x_tick_format": "Auto"} if scale == "linear" else {})}
    return request


@with_table_reads
def export_project(project: Path) -> dict[str, Any]:
    root = resolve_project_path(project)
    # resolve_project_path requires the saved canonical document. Export owns
    # its exact-current audit and native adoption; preparation would clone an
    # older generation or reject a legitimate manual native save beforehand.
    payload = {"project_dir": str(root), "request": str(root / "plot_request.json"),
               "document": str(root / "studio/document.vsz")}
    result = _publish(payload)
    return {
        **result, "kind": "sciplot_project_export_result",
        "status": "exported" if result["studio_run"]["ready_to_use"] else "blocked",
    }
