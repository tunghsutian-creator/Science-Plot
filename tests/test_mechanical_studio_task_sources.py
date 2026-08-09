from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

import sciplot_core.studio_core.mechanical_task_source_lifecycle as lifecycle
from sciplot_core._paths import resolve_fixture_path
from sciplot_core.figure_plan import ResolvedFigurePlan
from sciplot_core.materials_rules import get_rule
from sciplot_core.studio import prepare_studio_document
from sciplot_core.studio_core.figure_task_evidence import figure_queue_from_plan
from sciplot_core.studio_core.figure_set_prepare import _prepare_studio_figure_set
from sciplot_core.studio_core.prepare_generated import generate_studio_document
from sciplot_core.studio_core.source_bound_prepare import (
    bind_mechanical_task_sources,
)
from sciplot_core.studio_render.models import StudioPreparationBlocked


def _fixture(rule_id: str) -> Path:
    path = resolve_fixture_path(str(get_rule(rule_id).fixture_path or ""))
    assert path.exists()
    return path


def _project(tmp_path: Path, rule_id: str) -> tuple[Path, Path]:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    request_path = project_dir / "plot_request.json"
    request_path.write_text(
        json.dumps(
            {
                "input": str(_fixture(rule_id)),
                "rule_id": rule_id,
                "template": "curve",
                "explicit_template_selection": True,
                "explicit_render_option_keys": [],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return project_dir, request_path


def _generate(project_dir: Path, request_path: Path) -> None:
    generate_studio_document(
        project_dir=project_dir,
        request_path=request_path,
        rule_id=None,
        template=None,
        project_name=None,
    )


def _task_source_directories(project_dir: Path) -> list[Path]:
    root = project_dir / "studio" / "processed" / "mechanical_task_sources"
    return sorted(path for path in root.iterdir() if path.is_dir())


@pytest.mark.comprehensive
@pytest.mark.parametrize("failure_site", ["enumeration", "removal"])
def test_postcommit_task_source_gc_failure_does_not_report_a_false_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_site: str,
) -> None:
    project_dir, request_path = _project(tmp_path, "compression_curve")
    _generate(project_dir, request_path)
    predecessor = _task_source_directories(project_dir)[0]
    real_rmtree = shutil.rmtree

    def fail_only_for_predecessor(
        path: str | Path,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        if Path(str(path)).resolve() == predecessor.resolve():
            raise OSError("synthetic postcommit prune failure")
        real_rmtree(path, *args, **kwargs)

    real_iterdir = Path.iterdir

    def fail_only_for_task_source_root(path: Path) -> Any:
        if path.resolve() == predecessor.parent.resolve():
            raise PermissionError("synthetic postcommit enumeration failure")
        return real_iterdir(path)

    if failure_site == "removal":
        monkeypatch.setattr(lifecycle.shutil, "rmtree", fail_only_for_predecessor)
    else:
        monkeypatch.setattr(Path, "iterdir", fail_only_for_task_source_root)
    _generate(project_dir, request_path)
    if failure_site == "enumeration":
        monkeypatch.setattr(Path, "iterdir", real_iterdir)

    directories = _task_source_directories(project_dir)
    assert predecessor in directories
    assert len(directories) == 2
    registry = json.loads(
        (project_dir / "studio" / "figure_set.json").read_text(encoding="utf-8")
    )
    active_directories = {
        Path(
            json.loads(Path(item["spec"]).read_text(encoding="utf-8"))[
                "source_request"
            ]["input"]
        )
        .resolve()
        .parent
        for item in registry["figures"]
    }
    assert len(active_directories) == 1
    assert predecessor.resolve() not in active_directories


@pytest.mark.focused
@pytest.mark.parametrize("coverage", ["partial", "all"])
def test_prebound_private_mechanical_queue_is_rejected(
    tmp_path: Path,
    coverage: str,
) -> None:
    project_dir, request_path = _project(tmp_path, "compression_curve")
    _generate(project_dir, request_path)
    request = json.loads(request_path.read_text(encoding="utf-8"))
    plan = ResolvedFigurePlan.from_payload(request["resolved_figure_plan"])
    queue = figure_queue_from_plan(plan, plan.rule_id)
    selected = queue[:1] if coverage == "partial" else queue
    for item in selected:
        item["_mechanical_task_source"] = "forged private binding"

    with pytest.raises(
        StudioPreparationBlocked,
        match="fresh, complete mechanical task-source queue",
    ):
        bind_mechanical_task_sources(
            queue,
            figure_plan=plan,
            source_attestation=None,
            project_dir=project_dir,
            request=request,
        )


@pytest.mark.focused
@pytest.mark.parametrize("queue_kind", ["empty", "tuple"])
def test_mechanical_figure_set_rejects_a_non_internal_queue_shape(
    tmp_path: Path,
    queue_kind: str,
) -> None:
    project_dir, request_path = _project(tmp_path, "compression_curve")
    _generate(project_dir, request_path)
    request = json.loads(request_path.read_text(encoding="utf-8"))
    plan = ResolvedFigurePlan.from_payload(request["resolved_figure_plan"])
    queue = figure_queue_from_plan(plan, plan.rule_id)
    invalid_queue: Any = [] if queue_kind == "empty" else tuple(queue)

    with pytest.raises(
        StudioPreparationBlocked,
        match="non-empty internal list queue",
    ):
        _prepare_studio_figure_set(
            project_dir=project_dir,
            request_path=request_path,
            request=request,
            primary_document=project_dir / "studio" / "document.vsz",
            preserve_existing=False,
            queue_override=invalid_queue,
            figure_plan=plan,
        )


@pytest.mark.comprehensive
def test_exact_current_mechanical_studio_reuse_preserves_the_bound_figure_set(
    tmp_path: Path,
) -> None:
    project_dir, request_path = _project(tmp_path, "compression_curve")
    _generate(project_dir, request_path)
    registry_path = project_dir / "studio" / "figure_set.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    tracked = [
        registry_path,
        *(
            Path(value)
            for item in registry["figures"]
            for value in (item["document"], item["spec"])
        ),
    ]
    before = {path.resolve(): path.read_bytes() for path in tracked}
    source_dirs_before = _task_source_directories(project_dir)

    prepared = prepare_studio_document(project_dir)

    assert prepared["preserved_existing_document"] is True
    assert prepared["figure_set"] is not None
    assert _task_source_directories(project_dir) == source_dirs_before
    assert {path.resolve(): path.read_bytes() for path in tracked} == before
