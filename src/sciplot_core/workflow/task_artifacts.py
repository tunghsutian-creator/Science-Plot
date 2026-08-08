"""Install task-owned editable worker evidence and remap QA paths."""

from __future__ import annotations

from pathlib import Path
import shutil
from typing import Any

from sciplot_core.figure_plan.task import FigureTask


def install_task_worker_tree(
    payload: dict[str, Any],
    *,
    task: FigureTask,
    figures_dir: Path,
) -> tuple[list[str], list[str]]:
    """Install one task's editable document/spec tree under its stable stem."""

    target = figures_dir / "_veusz" / task.document_stem
    if target.exists():
        shutil.rmtree(target)
    documents = [
        Path(str(value))
        for value in payload.get("veusz_documents", [])
        if isinstance(value, str) and Path(value).is_file()
    ]
    specs = [
        Path(str(value))
        for value in payload.get("veusz_specs", [])
        if isinstance(value, str) and Path(value).is_file()
    ]
    source_worker = _common_worker_root(documents, specs)
    if source_worker is not None:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source_worker, target)
        return (
            _mapped_existing_paths(
                documents,
                source_worker=source_worker,
                target=target,
            ),
            _mapped_existing_paths(
                specs,
                source_worker=source_worker,
                target=target,
            ),
        )
    studio_dir = target / "studio"
    studio_dir.mkdir(parents=True, exist_ok=True)
    mapped_documents: list[str] = []
    mapped_specs: list[str] = []
    if len(documents) == 1:
        destination = studio_dir / "document.vsz"
        shutil.copy2(documents[0], destination)
        mapped_documents.append(str(destination))
    if len(specs) == 1:
        destination = studio_dir / "spec.json"
        shutil.copy2(specs[0], destination)
        mapped_specs.append(str(destination))
    return mapped_documents, mapped_specs


def task_qa_reports(
    payload: dict[str, Any],
    *,
    outputs: list[str],
    documents: list[str],
) -> list[dict[str, Any]]:
    """Remap task QA evidence to installed document and export paths."""

    reports: list[dict[str, Any]] = []
    for value in payload.get("qa_reports", []):
        if not isinstance(value, dict):
            continue
        report = dict(value)
        if isinstance(value.get("layout_summary"), dict):
            summary = dict(value["layout_summary"])
            if documents:
                summary["document"] = documents[0]
            summary["outputs"] = list(outputs)
            report["layout_summary"] = summary
        reports.append(report)
    return reports


def _common_worker_root(documents: list[Path], specs: list[Path]) -> Path | None:
    for path in [*documents, *specs]:
        for parent in path.parents:
            if parent.name == "_veusz" and parent.is_dir():
                return parent
    return None


def _mapped_existing_paths(
    paths: list[Path],
    *,
    source_worker: Path,
    target: Path,
) -> list[str]:
    mapped: list[str] = []
    for path in paths:
        try:
            destination = target / path.relative_to(source_worker)
        except ValueError:
            continue
        if destination.is_file():
            mapped.append(str(destination))
    return mapped


__all__ = ["install_task_worker_tree", "task_qa_reports"]
