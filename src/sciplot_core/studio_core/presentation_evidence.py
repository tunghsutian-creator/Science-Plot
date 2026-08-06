"""Validate prepared Studio plan and spec presentation projections."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sciplot_core.figure_plan.plan import ResolvedFigurePlan
from sciplot_core.figure_plan.task import FigureTask
from sciplot_core.presentation_identity import (
    SelectedPresentationIdentity,
    require_selected_template,
)

from sciplot_core.studio_core.figure_set_state import _read_studio_figure_set
from sciplot_core.studio_core.figure_task_evidence import (
    figure_task_from_registry_entry,
    primary_figure_task,
    validate_veusz_spec_figure_task,
)
from sciplot_core.studio_core.json_files import _read_json
from sciplot_core.studio_core.registry_state import _veusz_spec_path


def validate_veusz_spec_presentation(
    spec: dict[str, Any],
    *,
    expected: SelectedPresentationIdentity,
    source: str,
) -> None:
    """Require an existing generated spec to project the selected template."""

    require_selected_template(
        spec.get("template"),
        expected=expected,
        source=source,
    )
    source_request = spec.get("source_request")
    if isinstance(source_request, dict) and "template" in source_request:
        require_selected_template(
            source_request.get("template"),
            expected=expected,
            source=f"{source} source request",
        )


def validate_prepared_studio_presentation(
    *,
    project_dir: Path,
    document_path: Path,
    identity: SelectedPresentationIdentity,
    figure_plan: ResolvedFigurePlan | None,
) -> None:
    """Reject request/plan/spec splits before export or run allocation."""

    expected_by_figure_id: dict[str, FigureTask] = {}
    primary_task: FigureTask | None = None
    if figure_plan is not None:
        if identity.rule_id is not None and figure_plan.rule_id != identity.rule_id:
            raise RuntimeError(
                "presentation_identity_mismatch: resolved FigurePlan rule does "
                "not match the canonical selected presentation identity."
            )
        primary_task = primary_figure_task(figure_plan)
        require_selected_template(
            primary_task.template,
            expected=identity,
            source=f"resolved FigurePlan primary task `{primary_task.figure_id}`",
        )
        expected_by_figure_id = {task.figure_id: task for task in figure_plan.tasks}

    checked_specs: set[Path] = set()
    _validate_existing_spec(
        _veusz_spec_path(document_path),
        expected=identity,
        expected_task=primary_task,
        source="primary Veusz spec",
        checked=checked_specs,
    )

    registry = _read_studio_figure_set(project_dir)
    if registry is None:
        return
    registry_rule_id = str(registry.get("rule_id") or "").strip() or None
    if registry_rule_id != identity.rule_id:
        raise RuntimeError(
            "presentation_identity_mismatch: Studio figure-set rule does not "
            "match the canonical selected presentation identity."
        )
    for value in registry.get("figures", []):
        if not isinstance(value, dict) or value.get("status") == "unavailable":
            continue
        figure_id = str(value.get("figure_id") or "").strip()
        expected_task = expected_by_figure_id.get(figure_id)
        if figure_plan is not None:
            if expected_task is None:
                raise RuntimeError(
                    "studio_figure_task_mismatch: Studio registry contains "
                    f"unselected figure `{figure_id or 'unknown'}`."
                )
            try:
                registry_task = figure_task_from_registry_entry(
                    value,
                    required=True,
                )
            except (TypeError, ValueError) as exc:
                raise RuntimeError(str(exc)) from exc
            if registry_task != expected_task:
                raise RuntimeError(
                    "studio_figure_task_mismatch: Studio registry figure "
                    f"`{figure_id}` does not match its selected FigureTask."
                )
        spec_value = value.get("spec")
        document_value = value.get("document")
        spec_path = (
            Path(spec_value).expanduser()
            if isinstance(spec_value, str) and spec_value.strip()
            else _veusz_spec_path(Path(document_value).expanduser())
            if isinstance(document_value, str) and document_value.strip()
            else None
        )
        if spec_path is not None:
            _validate_existing_spec(
                spec_path,
                expected=identity if expected_task is None else None,
                expected_task=expected_task,
                source=f"Studio figure `{figure_id or 'unknown'}` Veusz spec",
                checked=checked_specs,
            )


def _validate_existing_spec(
    spec_path: Path,
    *,
    expected: SelectedPresentationIdentity | None,
    expected_task: FigureTask | None = None,
    source: str,
    checked: set[Path],
) -> None:
    resolved = spec_path.expanduser().resolve()
    if resolved in checked or not resolved.is_file():
        return
    checked.add(resolved)
    spec = _read_json(resolved)
    if expected is not None:
        validate_veusz_spec_presentation(
            spec,
            expected=expected,
            source=source,
        )
    if expected_task is not None:
        validate_veusz_spec_figure_task(
            spec,
            expected=expected_task,
            source=source,
        )
