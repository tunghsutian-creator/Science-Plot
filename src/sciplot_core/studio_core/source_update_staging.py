"""Prepare a fresh source revision through the ordinary Intake/Studio owners."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.materials_rules import get_rule
from sciplot_core.output_contract import requested_delivery_root
from sciplot_core.source_coverage.managed_documents import (
    verify_managed_document_sources,
)
from sciplot_core.studio_core.prepare_generated import generate_studio_document
from sciplot_core.studio_core.source_update_review import project_figures
from sciplot_core.veusz_runtime import veusz_worker_environment


def verify_project_science(project: Path) -> dict[str, Any]:
    documents = [str(item[0]) for item in project_figures(project).values()]
    return verify_managed_document_sources(
        {
            "veusz_documents": documents,
            "data_snapshot_sources": [
                str(project / "source"),
                str(project / "studio" / "processed"),
            ],
        }
    )


def _worksheet_confirmation(
    source: Path, worksheet: str | None, rule_id: str
) -> list[dict[str, Any]]:
    from sciplot_core.intake.table_preview import preview_table_payload

    if not worksheet:
        return []
    if get_rule(rule_id).scientific_source_adapter != "registered_paired_curve":
        raise ValueError(
            f"{rule_id} owns its worksheet/condition interpretation; no worksheet can be silently omitted."
        )
    if not source.is_file() or source.suffix.casefold() not in {".xls", ".xlsx"}:
        raise ValueError("Explicit worksheet selection requires one Excel workbook.")
    table = preview_table_payload(
        name=source.name, source_path=source, selected_sheet=worksheet
    )
    return [
        {
            "file_name": source.name,
            "source_path": str(source),
            "source_sha256": file_sha256(source),
            "sheet": worksheet,
            "sheet_selected": True,
            "columns": [
                {
                    "index": c["index"],
                    "name": c["name"],
                    "role": c["suggested_role"],
                    "confirmed_type": c["inferred_type"],
                }
                for c in table["columns"]
            ],
        }
    ]


def prepare_candidate(
    project: Path,
    source: Path,
    temporary: Path,
    *,
    worksheet: str | None,
) -> tuple[Path, list[dict[str, Any]]]:
    # Intake's public package composes the Studio facade; load it only after
    # the facade is initialized, as the existing Studio intake route does.
    from sciplot_core.intake.project import create_intake_project_from_session
    from sciplot_core.intake.session import prepare_intake_session

    previous = json.loads((project / "plot_request.json").read_text())
    rule_id = str(previous.get("rule_id") or "")
    if (
        not rule_id
        or previous.get("data_mapping")
        or previous.get("data_mapping_application")
    ):
        raise ValueError(
            "This source needs a fresh explicit data mapping before it can replace the project source."
        )
    session = prepare_intake_session(
        source, output_root=temporary, requested_rule_id=rule_id
    )
    manifest_path = project / "intake_manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.is_file() else {}
    session["project_name"] = manifest.get("project_name") or project.name
    session["exports"] = previous.get("exports", ["pdf", "tiff_300"])
    session["replicate_mode"] = previous.get("replicate_mode") or session.get(
        "replicate_mode"
    )
    # Scientific labels, axis ranges, source selections, and transformations are
    # derived anew. Compatible native styling is transferred after preparation.
    presentation_options = {"size", "style_preset", "visual_theme_id", "palette_preset"}
    session["render_options"] = {
        **session.get("render_options", {}),
        **{
            k: v
            for k, v in previous.get("render_options", {}).items()
            if k in presentation_options
        },
    }
    confirmations = _worksheet_confirmation(source, worksheet, rule_id)
    session["column_confirmations"] = confirmations
    failure: list[Exception] = []

    def prepare_once(directory: Path) -> dict[str, Any]:
        try:
            return generate_studio_document(
                project_dir=directory,
                request_path=directory / "plot_request.json",
                rule_id=None,
                template=None,
                project_name=None,
            )
        except Exception as exc:
            failure.append(exc)
            raise

    result = create_intake_project_from_session(
        session,
        studio_preparer=prepare_once,
        template=previous.get("template"),
        delivery_root=requested_delivery_root(
            {"request": previous}, run_output=project
        ),
    )
    if failure:
        raise failure[0]
    candidate = Path(result["project_dir"]).resolve()
    if result.get("studio", {}).get("status") != "ready":
        raise ValueError(
            "The replacement source cannot produce a complete current figure set."
        )
    # Preserve the existing project identity and mirror names, not stale runs or
    # source facts. All current scientific facts come from the newly built project.
    new_manifest = json.loads((candidate / "intake_manifest.json").read_text())
    new_manifest["project_slug"] = manifest.get("project_slug") or project.name
    for mirror in candidate.glob("*.sciplot.json"):
        mirror.unlink()
    for target in [
        candidate / "intake_manifest.json",
        *[candidate / p.name for p in project.glob("*.sciplot.json")],
    ]:
        target.write_text(json.dumps(new_manifest, ensure_ascii=False, indent=2))
    verify_project_science(candidate)
    return candidate, confirmations


def transfer_project_styles(previous: Path, candidate: Path) -> list[dict[str, Any]]:
    before, after = project_figures(previous), project_figures(candidate)
    changes = []
    for identity, (document, spec) in after.items():
        if identity not in before:
            changes.append(
                {"figure_id": identity, "status": "new_figure", "applied": []}
            )
            continue
        old_document, old_spec = before[identity]
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "sciplot_core.veusz_worker",
                "transfer-styles",
                str(old_document),
                str(document),
                str(old_spec),
                str(spec),
            ],
            env=veusz_worker_environment(),
            text=True,
            capture_output=True,
            timeout=120,
            check=False,
        )
        if completed.returncode:
            detail = completed.stderr.strip().splitlines()
            raise ValueError(
                "Could not preserve compatible styles: "
                + (detail[-1] if detail else "worker failed")
            )
        payload = json.loads(completed.stdout)
        # Paths/hashes of freshly generated VSZs are temporary implementation
        # details, not choices the operator must approve on every regeneration.
        changes.append(
            {
                "figure_id": identity,
                "status": payload["status"],
                "applied": payload.get("applied", []),
                "skipped": payload.get("skipped", []),
                "reasons": payload.get("reasons", []),
            }
        )
    verify_project_science(candidate)
    return changes


__all__ = ["prepare_candidate", "transfer_project_styles", "verify_project_science"]
