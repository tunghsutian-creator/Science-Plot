"""Continue the owning project from a delivery, or open an explicit portable copy."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from sciplot_core.foundation.file_hashing import existing_file_sha256
from sciplot_core.launchers.delivery_binding import (
    DeliveryBinding,
    delivery_binding_from_content,
)
from sciplot_core.launchers.delivery_inspection import (
    inspect_delivery_launcher_contract,
)
from sciplot_core.policy import DELIVERY_LAUNCHER, DELIVERY_PROJECT_DIR


def resolve_delivery_target(path: Path) -> dict[str, Any] | None:
    """Resolve a generated launcher without executing or trusting shell content."""
    launcher = path / DELIVERY_LAUNCHER if path.is_dir() else path
    if launcher.name != DELIVERY_LAUNCHER or not launcher.is_file():
        return None
    root = launcher.parent.resolve()
    # A project has its own identically named launcher; only visible packages
    # with editable copies belong to this resolver.
    if not (root / DELIVERY_PROJECT_DIR).is_dir():
        return None
    if inspect_delivery_launcher_contract(root).get("ready") is not True:
        raise ValueError(
            f"The delivery launcher is not a valid SciPlot launcher: {launcher}"
        )
    binding = delivery_binding_from_content(launcher.read_text(encoding="utf-8"))
    managed = _managed_project(root, binding) if binding is not None else None
    if managed is not None and binding is not None:
        changed = [
            str(root / DELIVERY_PROJECT_DIR / name)
            for name, expected in binding.documents
            if existing_file_sha256(root / DELIVERY_PROJECT_DIR / name) != expected
        ]
        actual = {item.name for item in (root / DELIVERY_PROJECT_DIR).glob("*.vsz")}
        if actual != dict(binding.documents).keys():
            changed.append(str(root / DELIVERY_PROJECT_DIR))
        if changed:
            raise ValueError(
                "The visible Veusz copy has changed; opening the managed project would "
                "skip these edits. All files were preserved: "
                + ", ".join(changed)
                + ". Preview recovery with studio DELIVERY --recover-delivery --preview-out PREVIEW.json, "
                "or use Recover visible edits in the managed Project dock."
            )
        return {
            "mode": "project",
            "project_dir": managed,
            "request": managed / "plot_request.json",
        }
    documents = sorted((root / DELIVERY_PROJECT_DIR).glob("*.vsz"))
    if not documents:
        raise FileNotFoundError(f"No portable Veusz documents exist in {root}")
    primary = (
        root / DELIVERY_PROJECT_DIR / binding.primary
        if binding is not None
        else documents[0]
    )
    if primary not in documents:
        primary = documents[0]
    print(
        f"Opening portable Veusz copy: {primary}. This copy does not update the original SciPlot project.",
        file=sys.stderr,
    )
    if len(documents) > 1:
        print(
            "Other portable figures: "
            + ", ".join(item.name for item in documents)
            + ". Pass a filename to Open_in_Veusz.command to choose another figure.",
            file=sys.stderr,
        )
    return {"mode": "vsz", "document": primary}


def _managed_project(root: Path, binding: DeliveryBinding) -> Path | None:
    if binding.root != str(root) or binding.request is None:
        return None
    request_path = Path(binding.request)
    if request_path.name != "plot_request.json" or not request_path.is_file():
        return None
    project = request_path.parent
    if not (project / "studio" / "document.vsz").is_file():
        return None
    try:
        request = json.loads(request_path.read_text(encoding="utf-8"))
        if not isinstance(request, dict):
            return None
        output = request.get("delivery_output")
        source = request.get("input")
        if not isinstance(output, str) or Path(output).expanduser().resolve() != root:
            return None
        if not isinstance(source, str) or not source.strip():
            return None
        source_path = Path(source).expanduser()
        if not source_path.is_absolute():
            source_path = project / source_path
        if str(source_path.resolve()) != binding.source:
            return None
    except (OSError, ValueError):
        return None
    return project
