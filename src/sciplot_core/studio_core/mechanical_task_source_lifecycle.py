"""Keep private mechanical task tables aligned with a Studio transaction."""

from __future__ import annotations

import re
import shutil
from collections.abc import Callable
from functools import wraps
from pathlib import Path
from typing import Any, TypeVar

from sciplot_core.mechanical_figure_contract import MECHANICAL_RULE_IDS
from sciplot_core.studio_render.models import StudioPreparationBlocked


_MANAGED_DIRECTORY = re.compile(r"rfp_[0-9a-f]{16}_[0-9a-f]{32}")
_Result = TypeVar("_Result")


def manage_mechanical_task_source_lifecycle(
    function: Callable[..., _Result],
) -> Callable[..., _Result]:
    """Roll back new task tables on failure and prune same-plan predecessors."""

    @wraps(function)
    def wrapped(*args: Any, **kwargs: Any) -> _Result:
        queue = kwargs.get("queue_override")
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
            elif not isinstance(queue, list) or not queue:
                raise StudioPreparationBlocked(
                    f"{rule_id}_figure_plan_source_mismatch",
                    f"{rule_id}: mechanical Studio execution requires one "
                    "non-empty internal list queue.",
                )
            if not preserve_existing:
                from sciplot_core.studio_core.source_bound_prepare import (
                    bind_mechanical_task_sources,
                )

                queue = bind_mechanical_task_sources(
                    queue,
                    figure_plan=kwargs.get("figure_plan"),
                    source_attestation=kwargs.get("prepared_source_attestation"),
                    project_dir=kwargs["project_dir"],
                    request=kwargs["request"],
                )
                kwargs["queue_override"] = queue
        active = _managed_directories(queue)
        try:
            result = function(*args, **kwargs)
        except BaseException:
            _remove_directories(active)
            raise
        _remove_same_plan_predecessors(active)
        return result

    return wrapped


def _managed_directories(value: object) -> tuple[Path, ...]:
    if not isinstance(value, list):
        return ()
    from sciplot_core.mechanical_task_sources import MechanicalTaskSource

    directories: list[Path] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        record = item.get("_mechanical_task_source")
        if not isinstance(record, MechanicalTaskSource):
            continue
        directory = record.source.expanduser().absolute().parent
        if (
            directory.parent.name == "mechanical_task_sources"
            and directory.parent.parent.name == "processed"
            and directory.parent.parent.parent.name == "studio"
            and _MANAGED_DIRECTORY.fullmatch(directory.name)
            and directory not in directories
        ):
            directories.append(directory)
    return tuple(directories)


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
