"""Keep private FigureTask sources aligned with a Studio transaction."""

from __future__ import annotations

import re
import shutil
from collections.abc import Callable
from functools import wraps
from pathlib import Path
from typing import Any, Literal, NoReturn, TypeVar

from sciplot_core.mechanical_figure_contract import MECHANICAL_RULE_IDS
from sciplot_core.studio_render.models import StudioPreparationBlocked


_MANAGED_DIRECTORY = re.compile(r"rfp_[0-9a-f]{16}_[0-9a-f]{32}")
_Result = TypeVar("_Result")
_SourceKind = Literal["impact_conditions", "mechanical_task_sources"]


def manage_mechanical_task_source_lifecycle(
    function: Callable[..., _Result],
) -> Callable[..., _Result]:
    """Roll back new task tables on failure and prune same-plan predecessors."""

    @wraps(function)
    def wrapped(*args: Any, **kwargs: Any) -> _Result:
        queue: object = kwargs.get("queue_override")
        plan = kwargs.get("figure_plan")
        rule_id = str(getattr(plan, "rule_id", "") or "")
        if rule_id in MECHANICAL_RULE_IDS:
            preserve_existing = kwargs.get("preserve_existing") is True
            if preserve_existing:
                if queue is not None:
                    raise StudioPreparationBlocked(
                        f"{rule_id}_figure_plan_source_mismatch",
                        f"{rule_id}: exact-current reuse cannot accept a new "
                        "mechanical task-source queue.",
                    )
            if not preserve_existing:
                from sciplot_core.studio_core.source_bound_prepare import (
                    bind_mechanical_task_sources,
                )

                internal_queue = _require_internal_queue(queue, rule_id=rule_id)
                try:
                    _private_figure_task_source_root(
                        kwargs["project_dir"],
                        source_kind="mechanical_task_sources",
                    )
                    queue = bind_mechanical_task_sources(
                        internal_queue,
                        figure_plan=kwargs.get("figure_plan"),
                        source_attestation=kwargs.get("prepared_source_attestation"),
                        project_dir=kwargs["project_dir"],
                        request=kwargs["request"],
                    )
                except StudioPreparationBlocked:
                    raise
                except ValueError as exc:
                    raise StudioPreparationBlocked(
                        f"{rule_id}_figure_plan_source_mismatch",
                        f"{rule_id}: mechanical Studio execution received a "
                        "malformed internal queue.",
                    ) from exc
                kwargs["queue_override"] = queue
        project_dir = kwargs.get("project_dir")
        project_root = (
            project_dir.expanduser().resolve()
            if isinstance(project_dir, Path)
            else None
        )
        active = _managed_directories(queue, project_root=project_root)
        try:
            result = function(*args, **kwargs)
        except BaseException:
            _remove_directories(active)
            raise
        _remove_same_plan_predecessors(active)
        return result

    return wrapped


def _require_internal_queue(
    value: object,
    *,
    rule_id: str,
) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        _reject_internal_queue(rule_id)
    queue: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            _reject_internal_queue(rule_id)
        narrowed: dict[str, Any] = {}
        for key, field in item.items():
            if not isinstance(key, str):
                _reject_internal_queue(rule_id)
            narrowed[key] = field
        queue.append(narrowed)
    return queue


def _private_figure_task_source_root(
    project_dir: Path,
    *,
    source_kind: _SourceKind,
) -> Path:
    """Return one project-owned ordinary directory or fail before a write."""

    project_root = project_dir.expanduser().resolve()
    studio_root = project_root / "studio"
    processed_root = studio_root / "processed"
    source_root = processed_root / source_kind
    components = (studio_root, processed_root, source_root)
    try:
        _require_ordinary_private_source_components(components)
        source_root.mkdir(parents=True, exist_ok=True)
        _require_ordinary_private_source_components(components)
        if source_root.resolve() != source_root:
            raise ValueError("private FigureTask source root escaped its project")
    except OSError as exc:
        raise ValueError(
            "private FigureTask source root must stay inside ordinary project "
            "directories"
        ) from exc
    return source_root


def _require_ordinary_private_source_components(
    components: tuple[Path, ...],
) -> None:
    if any(
        component.is_symlink() or (component.exists() and not component.is_dir())
        for component in components
    ):
        raise ValueError(
            "private FigureTask source root must not contain symbolic links"
        )


def _reject_internal_queue(rule_id: str) -> NoReturn:
    raise StudioPreparationBlocked(
        f"{rule_id}_figure_plan_source_mismatch",
        f"{rule_id}: mechanical Studio execution requires one "
        "non-empty internal list queue.",
    )


def _managed_directories(
    value: object,
    *,
    project_root: Path | None,
) -> tuple[Path, ...]:
    if not isinstance(value, list) or project_root is None:
        return ()
    from sciplot_core.mechanical_task_sources import MechanicalTaskSource

    directories: list[Path] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        record = item.get("_mechanical_task_source")
        if isinstance(record, MechanicalTaskSource):
            _append_managed_directory(
                directories,
                record.source.expanduser().resolve().parent,
                project_root=project_root,
                source_kind="mechanical_task_sources",
            )
        condition_source = item.get("condition_source")
        if isinstance(condition_source, str) and condition_source.strip():
            _append_managed_directory(
                directories,
                Path(condition_source).expanduser().resolve().parent,
                project_root=project_root,
                source_kind="impact_conditions",
            )
    return tuple(directories)


def _append_managed_directory(
    directories: list[Path],
    directory: Path,
    *,
    project_root: Path,
    source_kind: str,
) -> None:
    expected_parent = project_root / "studio" / "processed" / source_kind
    if (
        directory.parent == expected_parent
        and _MANAGED_DIRECTORY.fullmatch(directory.name)
        and directory not in directories
    ):
        directories.append(directory)


def _remove_same_plan_predecessors(active: tuple[Path, ...]) -> None:
    active_set = set(active)
    for directory in active:
        if directory.is_symlink() or not directory.parent.is_dir():
            continue
        prefix = f"{directory.name.rsplit('_', 1)[0]}_"
        try:
            candidates = tuple(directory.parent.iterdir())
        except OSError:
            continue
        for candidate in candidates:
            if (
                candidate not in active_set
                and candidate.is_dir()
                and not candidate.is_symlink()
                and candidate.name.startswith(prefix)
                and _MANAGED_DIRECTORY.fullmatch(candidate.name)
            ):
                try:
                    shutil.rmtree(candidate)
                except OSError:
                    # The figure-set transaction has already committed. An
                    # unreferenced predecessor is safer than reporting a false
                    # failure after the new registry became authoritative.
                    continue


def _remove_directories(directories: tuple[Path, ...]) -> None:
    for directory in directories:
        if directory.is_dir() and not directory.is_symlink():
            shutil.rmtree(directory)


__all__ = ["manage_mechanical_task_source_lifecycle"]
