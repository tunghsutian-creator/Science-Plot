"""Validate and relocate one persisted Studio figure-set snapshot."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from sciplot_core.figure_plan import FigureOutcome, ResolvedFigurePlan
from sciplot_core.figure_plan.task import FigureTask
from sciplot_core.studio_figure_set_contract import STUDIO_FIGURE_SET_TASK_VERSION

from sciplot_core.studio_core.figure_task_evidence import (
    validate_veusz_spec_figure_task,
)
from sciplot_core.studio_core.json_files import _read_json


def normalize_studio_figure_set_snapshot(
    payload: dict[str, Any],
    *,
    figures: list[Any],
    project_dir: Path,
    registry_path: Path,
    version: int,
    registry_plan: ResolvedFigurePlan | None,
    require_ready_artifacts: bool,
) -> dict[str, Any]:
    """Return one path-safe snapshot or raise for invalid persisted state."""

    normalized, persisted_root = _normalize_registry_paths(
        payload,
        figures=figures,
        project_dir=project_dir,
        registry_path=registry_path,
        version=version,
        require_bindings=require_ready_artifacts,
    )
    if registry_plan is not None:
        normalized_plan = _validate_v2_registry_state(
            normalized,
            plan=registry_plan,
            persisted_root=persisted_root,
            require_ready_artifacts=require_ready_artifacts,
        )
        normalized["resolved_figure_plan"] = normalized_plan.to_payload()
    return normalized


def _normalize_registry_paths(
    payload: dict[str, Any],
    *,
    figures: list[Any],
    project_dir: Path,
    registry_path: Path,
    version: int,
    require_bindings: bool,
) -> tuple[dict[str, Any], Path]:
    current_root = project_dir.expanduser().resolve()
    persisted_root = (
        _persisted_registry_root(
            payload,
            current_root=current_root,
            require_bindings=require_bindings,
        )
        if version == STUDIO_FIGURE_SET_TASK_VERSION
        else current_root
    )
    if require_bindings:
        _resolved_current_member(
            current_root,
            Path("studio") / "figure_set.json",
            label="figure-set registry",
        )
    primary_id = str(payload.get("primary_figure_id") or "").strip()
    normalized_figures: list[dict[str, Any]] = []
    for value in figures:
        if not isinstance(value, dict):
            if version == STUDIO_FIGURE_SET_TASK_VERSION:
                raise ValueError("A v2 figure-set entry must be an object.")
            continue
        figure_id = str(value.get("figure_id") or "").strip()
        if not re.fullmatch(r"[a-z0-9][a-z0-9_]*", figure_id):
            if version == STUDIO_FIGURE_SET_TASK_VERSION:
                raise ValueError("A v2 figure-set entry has an invalid ID.")
            continue
        document_stem = str(value.get("document_stem") or figure_id).strip()
        if not re.fullmatch(
            r"[A-Za-z0-9\u4e00-\u9fff][A-Za-z0-9._\-\u4e00-\u9fff]*",
            document_stem,
        ):
            if version == STUDIO_FIGURE_SET_TASK_VERSION:
                raise ValueError("A v2 figure-set entry has an invalid document stem.")
            continue
        relative_document, relative_spec = _relative_figure_paths(
            figure_id=figure_id,
            primary_id=primary_id,
            document_stem=document_stem,
        )
        current_document = current_root / relative_document
        current_spec = current_root / relative_spec
        if version == STUDIO_FIGURE_SET_TASK_VERSION:
            _require_canonical_persisted_path(
                value.get("document"),
                expected=persisted_root / relative_document,
                label=f"figure `{figure_id}` document",
                required=require_bindings,
            )
            _require_canonical_persisted_path(
                value.get("spec"),
                expected=persisted_root / relative_spec,
                label=f"figure `{figure_id}` spec",
                required=require_bindings,
            )
            if require_bindings:
                current_document = _resolved_current_member(
                    current_root,
                    relative_document,
                    label=f"figure `{figure_id}` document",
                )
                current_spec = _resolved_current_member(
                    current_root,
                    relative_spec,
                    label=f"figure `{figure_id}` spec",
                )
        normalized_figures.append(
            {
                **value,
                "document": str(current_document.resolve()),
                "spec": str(current_spec.resolve()),
            }
        )
    normalized = {
        **payload,
        "figures": normalized_figures,
        "primary_document": str((current_root / "studio" / "document.vsz").resolve()),
        "generated_from": str((current_root / "plot_request.json").resolve()),
        "registry_path": str(registry_path.expanduser().resolve()),
    }
    return normalized, persisted_root


def _resolved_current_member(root: Path, relative: Path, *, label: str) -> Path:
    """Resolve one canonical member without following an in-tree symlink."""

    member = root
    for part in relative.parts:
        member /= part
        if member.is_symlink():
            raise ValueError(f"The v2 {label} cannot be a symlink.")
    resolved = member.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"The v2 {label} escapes its project root.") from exc
    return resolved


def _persisted_registry_root(
    payload: dict[str, Any],
    *,
    current_root: Path,
    require_bindings: bool,
) -> Path:
    bindings = (
        ("registry_path", ("studio", "figure_set.json")),
        ("generated_from", ("plot_request.json",)),
        ("primary_document", ("studio", "document.vsz")),
    )
    roots: list[Path] = []
    for field, suffix in bindings:
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            if require_bindings:
                raise ValueError(f"The v2 figure-set is missing `{field}`.")
            continue
        path = _absolute_persisted_path(value, label=field)
        root = path
        for _part in suffix:
            root = root.parent
        if path != root.joinpath(*suffix).resolve():
            raise ValueError(f"The v2 figure-set `{field}` path is not canonical.")
        roots.append(root)
    if roots and any(root != roots[0] for root in roots[1:]):
        raise ValueError("The v2 figure-set persisted project roots disagree.")
    return roots[0] if roots else current_root


def _absolute_persisted_path(value: str, *, label: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError(f"The v2 figure-set `{label}` path must be absolute.")
    return path.resolve()


def _require_canonical_persisted_path(
    value: object,
    *,
    expected: Path,
    label: str,
    required: bool,
) -> None:
    if not isinstance(value, str) or not value.strip():
        if required:
            raise ValueError(f"The v2 figure-set {label} path is missing.")
        return
    if _absolute_persisted_path(value, label=label) != expected.resolve():
        raise ValueError(f"The v2 figure-set {label} path is not canonical.")


def _relative_figure_paths(
    *,
    figure_id: str,
    primary_id: str,
    document_stem: str,
) -> tuple[Path, Path]:
    document = (
        Path("studio") / "document.vsz"
        if figure_id == primary_id
        else Path("studio") / "figures" / f"{document_stem}.vsz"
    )
    spec = (
        Path("studio") / "spec.json"
        if figure_id == primary_id
        else document.with_suffix(".spec.json")
    )
    return document, spec


def _validate_v2_registry_state(
    registry: dict[str, Any],
    *,
    plan: ResolvedFigurePlan,
    persisted_root: Path,
    require_ready_artifacts: bool,
) -> ResolvedFigurePlan:
    figures = registry["figures"]
    if len(figures) != len(plan.outcomes):
        raise ValueError("The v2 figure-set outcome count does not match its entries.")
    normalized_outcomes: list[FigureOutcome] = []
    entry_statuses: list[str] = []
    for entry, task, outcome in zip(figures, plan.tasks, plan.outcomes, strict=True):
        status = entry.get("status")
        if status not in {"ready", "unavailable"}:
            raise ValueError("The v2 figure-set contains an unsupported entry status.")
        if require_ready_artifacts and status == "ready":
            _validate_document_hash_projection(entry)
        entry_statuses.append(status)
        expected_outcome_status = "editable" if status == "ready" else "unavailable"
        if outcome.status != expected_outcome_status:
            raise ValueError("The v2 figure-set entry and outcome statuses disagree.")
        document = Path(entry["document"]).expanduser().resolve()
        spec = Path(entry["spec"]).expanduser().resolve()
        relative_document, relative_spec = _relative_figure_paths(
            figure_id=task.figure_id,
            primary_id=plan.primary_figure_id,
            document_stem=task.document_stem,
        )
        artifact_paths = {
            (persisted_root / relative_document).resolve(): str(document),
            (persisted_root / relative_spec).resolve(): str(spec),
        }
        normalized_artifacts: list[str] = []
        for value in outcome.artifacts:
            artifact = _absolute_persisted_path(
                value,
                label=f"figure `{task.figure_id}` outcome artifact",
            )
            normalized = artifact_paths.get(artifact)
            if normalized is None:
                raise ValueError(
                    "The v2 figure-set outcome binds a noncanonical artifact."
                )
            normalized_artifacts.append(normalized)
        if require_ready_artifacts and status == "ready":
            _validate_ready_artifacts(
                document=document,
                spec=spec,
                normalized_artifacts=normalized_artifacts,
                task=task,
            )
        if require_ready_artifacts and status == "unavailable":
            _validate_unavailable_evidence(entry, outcome=outcome)
        normalized_outcomes.append(
            FigureOutcome(
                figure_id=outcome.figure_id,
                status=outcome.status,
                artifacts=tuple(normalized_artifacts),
                reason_code=outcome.reason_code,
                message=outcome.message,
            )
        )
    expected_registry_status = (
        "ready"
        if all(status == "ready" for status in entry_statuses)
        else "partially_available"
    )
    registry_status = registry.get("status")
    if require_ready_artifacts and registry_status != expected_registry_status:
        raise ValueError("The v2 figure-set aggregate status is inconsistent.")
    if registry_status is not None and registry_status != expected_registry_status:
        raise ValueError("The v2 figure-set aggregate status is inconsistent.")
    return ResolvedFigurePlan(
        rule_id=plan.rule_id,
        selection_policy=plan.selection_policy,
        primary_figure_id=plan.primary_figure_id,
        tasks=plan.tasks,
        outcomes=tuple(normalized_outcomes),
        source_sha256=plan.source_sha256,
    )


def _validate_document_hash_projection(entry: dict[str, Any]) -> None:
    state = entry.get("document_state")
    if not isinstance(state, dict) or state.get("kind") != "sciplot_vsz_document_state":
        raise ValueError("A v2 figure-set entry needs canonical document state.")
    if "generated_hash" not in state:
        raise ValueError(
            "A v2 figure-set document state is missing its generated hash."
        )
    generated_hash = entry.get("generated_hash")
    if generated_hash != state.get("generated_hash"):
        raise ValueError(
            "A v2 figure-set entry and document state generated hashes disagree."
        )
    for label, value in (
        ("generated", generated_hash),
        ("current", state.get("current_hash")),
    ):
        if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
            raise ValueError(
                f"A v2 figure-set document state has an invalid {label} hash."
            )


def _validate_ready_artifacts(
    *,
    document: Path,
    spec: Path,
    normalized_artifacts: list[str],
    task: FigureTask,
) -> None:
    if not document.is_file() or not spec.is_file():
        raise ValueError("A ready v2 figure-set entry is missing its document or spec.")
    if normalized_artifacts != [str(document), str(spec)]:
        raise ValueError(
            "A ready v2 figure-set outcome must bind its document and spec."
        )
    validate_veusz_spec_figure_task(
        _read_json(spec),
        expected=task,
        source=f"Studio figure `{task.figure_id}` Veusz spec",
    )


def _validate_unavailable_evidence(
    entry: dict[str, Any],
    *,
    outcome: FigureOutcome,
) -> None:
    unavailable = entry.get("unavailable")
    if not isinstance(unavailable, dict):
        raise ValueError("An unavailable v2 figure-set entry needs explicit evidence.")
    if (
        str(unavailable.get("reason_code") or "").strip() != outcome.reason_code
        or str(unavailable.get("message") or "").strip() != outcome.message
    ):
        raise ValueError(
            "The v2 figure-set unavailable evidence disagrees with its outcome."
        )


__all__ = ["normalize_studio_figure_set_snapshot"]
