"""Preview and explicitly apply revisions through the Studio command family."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sciplot_core.cli.value_io import _print_json
from sciplot_core.foundation.json_io import atomic_write_json
from sciplot_core.launchers.delivery_binding import delivery_binding_from_content
from sciplot_core.launchers.delivery_inspection import (
    inspect_delivery_launcher_contract,
)
from sciplot_core.policy import DELIVERY_LAUNCHER
from sciplot_core.studio_core.delivery_target import _managed_project
from sciplot_core.studio_core.delivery_recovery import (
    preview_delivery_recovery,
    apply_delivery_recovery,
)
from sciplot_core.studio_core.source_update import (
    preview_project_source_update,
    apply_project_source_update,
)
from sciplot_core.studio_core.project_session import external_project_session


def revision_project(target: Path) -> Path:
    path = target.expanduser().resolve()
    if path.name == "plot_request.json":
        path = path.parent
    if path.is_dir() and (path / "plot_request.json").is_file():
        return path
    launcher = path / DELIVERY_LAUNCHER if path.is_dir() else path
    if launcher.name == DELIVERY_LAUNCHER and launcher.is_file():
        root = launcher.parent
        if inspect_delivery_launcher_contract(root).get("ready") is True:
            binding = delivery_binding_from_content(
                launcher.read_text(encoding="utf-8")
            )
            project = _managed_project(root, binding) if binding is not None else None
            if project is not None:
                return project
    raise ValueError(
        "Select an existing project or its still-associated visible delivery for this revision."
    )


def dispatch_project_revision(args: Any) -> int | None:
    requested = args.recover_delivery or args.update_source or args.apply_revision
    if not requested:
        if args.preview_out or args.worksheet:
            raise ValueError(
                "--preview-out and --worksheet require a revision preview action."
            )
        return None
    if args.target is None:
        raise ValueError(
            "A revision requires an existing project or associated delivery target."
        )
    if any(
        (
            args.new,
            args.out,
            args.rule,
            args.template,
            args.name,
            args.export,
            args.prepare_only,
            args.qt_smoke,
        )
    ):
        raise ValueError(
            "Review or apply the project revision separately; then use normal Studio Save and Export."
        )
    if args.worksheet and not args.update_source:
        raise ValueError("--worksheet is only valid with --update-source.")
    if args.preview_out and args.apply_revision:
        raise ValueError(
            "--preview-out is only valid when creating a revision preview."
        )
    project = revision_project(args.target)
    if args.apply_revision:
        preview = json.loads(
            args.apply_revision.expanduser().read_text(encoding="utf-8")
        )
        if not isinstance(preview, dict):
            raise ValueError("The reviewed preview must be a JSON object.")
        kind = preview.get("kind")
        with external_project_session(project):
            if kind == "sciplot_delivery_recovery_preview":
                payload = apply_delivery_recovery(project, preview)
            elif kind == "sciplot_project_source_update":
                payload = apply_project_source_update(project, preview)
            else:
                raise ValueError("The file is not a supported project revision preview.")
    else:
        payload = (
            preview_project_source_update(
                project, args.update_source, worksheet=args.worksheet
            )
            if args.update_source
            else preview_delivery_recovery(project)
        )
        if args.preview_out:
            output = args.preview_out.expanduser().resolve()
            # Preview files are review artifacts, never project data replacements.
            source = (
                args.update_source.expanduser().resolve()
                if args.update_source
                else None
            )
            if (
                output.exists()
                or output.is_relative_to(project)
                or (
                    source is not None
                    and (output == source or output.is_relative_to(source))
                )
            ):
                raise ValueError(
                    "Choose a new preview JSON path outside the project and selected source."
                )
            atomic_write_json(output, payload)
    _print_json(payload)
    return 1 if payload.get("status") == "blocked" else 0
