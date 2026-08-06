"""Declare the visible delivery package contract and canonical project name."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from sciplot_core.foundation.path_names import slug


PUBLICATION_ARTIFACT_FILENAMES = (
    "publication_intent.json",
    "transform_ledger.json",
    "journal_profile.json",
    "publication_qa.json",
)


PUBLICATION_ARTIFACT_KINDS = {
    "publication_intent.json": "sciplot_publication_intent",
    "transform_ledger.json": "sciplot_transform_ledger",
    "journal_profile.json": "sciplot_publication_profile",
    "publication_qa.json": "sciplot_publication_qa",
}


DELIVERY_PACKAGE_CONTRACT_VERSION = 6
DELIVERY_BINDING_POLICY_LEGACY = "legacy_unplanned"
DELIVERY_BINDING_POLICY_RESOLVED_PLAN = "resolved_figure_plan_v1"


def _project_slug(output_dir: Path, manifest: dict[str, Any]) -> str:
    request_path = manifest.get("request_path")
    if isinstance(request_path, str) and request_path.strip():
        parent = Path(request_path).expanduser().parent
        if parent.name and parent.name not in {".", ".."}:
            return slug(parent.name)
    input_path = manifest.get("input")
    if isinstance(input_path, str) and input_path.strip():
        return slug(Path(input_path).stem)
    return slug(output_dir.name)
