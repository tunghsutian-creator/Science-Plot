from __future__ import annotations

from dataclasses import replace
import json
import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import sciplot_core.studio_core.mechanical_task_source_lifecycle as lifecycle
import sciplot_core.studio_core.prepare_existing as prepare_existing
from sciplot_core._paths import resolve_fixture_path
from sciplot_core.figure_plan import (
    CartesianMetricBinding,
    FigureTask,
    ResolvedFigurePlan,
)
from sciplot_core.materials_rules import get_rule
from sciplot_core.mechanical_task_sources import MechanicalTaskSource
from sciplot_core.studio import prepare_studio_document
from sciplot_core.studio_core.figure_task_evidence import figure_queue_from_plan
from sciplot_core.studio_core.figure_set_prepare import _prepare_studio_figure_set
from sciplot_core.studio_core.figure_source_request import _mechanical_task_source
from sciplot_core.studio_core.prepare_generated import generate_studio_document
from sciplot_core.studio_core.source_bound_prepare import (
    bind_mechanical_task_sources,
)
from sciplot_core.studio_render.models import StudioPreparationBlocked
from sciplot_core.terminal_source_binding import (
    MaterializedTerminalSourceBinding,
    SourceArtifactBinding,
)


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


def _private_mechanical_source(
    tmp_path: Path,
) -> tuple[FigureTask, ResolvedFigurePlan, MechanicalTaskSource]:
    task = FigureTask.with_metric_binding(
        figure_id="compression_stress_strain",
        order=1,
        title="Compression stress-strain",
        metric_binding=CartesianMetricBinding(
            x_metric="strain",
            y_metric="stress",
        ),
        template="curve",
        artifact_stem="compression_stress_strain",
        document_stem="compression_stress_strain",
        sample_order=("E0", "E2"),
        replicate_counts=(("E0", 1), ("E2", 1)),
    )
    plan = ResolvedFigurePlan.planned(
        rule_id="compression_curve",
        selection_policy="mechanical_test",
        primary_figure_id=task.figure_id,
        tasks=(task,),
    )
    raw = tmp_path / "raw.csv"
    prepared = tmp_path / "prepared.csv"
    terminal = tmp_path / "terminal.csv"
    for path in (raw, prepared, terminal):
        path.write_text("x,E0,E2\ny,1,2\n", encoding="utf-8")
    binding = MaterializedTerminalSourceBinding.create(
        task_key=task.figure_id,
        rule_id=plan.rule_id,
        template=task.template,
        x_metric="strain",
        y_metric="stress",
        raw_sources=(raw,),
        prepared_source=prepared,
        terminal_source=terminal,
        sample_order=task.sample_order,
        point_counts={"E0": 1, "E2": 1},
    )
    record = MechanicalTaskSource(
        task=task,
        source=terminal.resolve(),
        render_options={"x_metric": "strain", "y_metric": "stress"},
        binding=binding,
        task_kind="curve",
        metric="stress",
        unit="MPa",
    )
    return task, plan, record


@pytest.mark.focused
@pytest.mark.parametrize(
    "split",
    [
        "task_key",
        "rule_id",
        "template",
        "metrics",
        "terminal_source",
        "sample_order",
        "render_options",
    ],
)
def test_mechanical_private_source_rejects_binding_identity_split(
    tmp_path: Path,
    split: str,
) -> None:
    task, plan, record = _private_mechanical_source(tmp_path)
    assert (
        _mechanical_task_source(
            {"_mechanical_task_source": record},
            expected_task=task,
            expected_plan=plan,
        )
        is record
    )
    binding = record.binding
    if split == "task_key":
        binding = replace(binding, task_key="forged_task")
    elif split == "rule_id":
        binding = replace(binding, rule_id="tensile_curve")
    elif split == "template":
        binding = replace(binding, template="point_line")
    elif split == "metrics":
        binding = replace(binding, x_metric="time")
    elif split == "terminal_source":
        alternate = tmp_path / "alternate.csv"
        alternate.write_text("x,E0,E2\ny,1,2\n", encoding="utf-8")
        binding = replace(
            binding,
            terminal_source=SourceArtifactBinding.create(alternate),
        )
    elif split == "sample_order":
        binding = replace(
            binding,
            sample_order=("E2", "E0"),
            point_counts=(("E2", 1), ("E0", 1)),
        )
    else:
        record = replace(
            record,
            render_options={"x_metric": "time", "y_metric": "stress"},
        )
    forged = replace(record, binding=binding)

    with pytest.raises(ValueError, match="studio_figure_task_mismatch"):
        _mechanical_task_source(
            {"_mechanical_task_source": forged},
            expected_task=task,
            expected_plan=plan,
        )


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
@pytest.mark.parametrize(
    "queue_kind",
    ["empty", "tuple", "non_mapping", "non_string_key", "empty_mapping"],
)
def test_mechanical_figure_set_rejects_a_non_internal_queue_shape(
    tmp_path: Path,
    queue_kind: str,
) -> None:
    project_dir, request_path = _project(tmp_path, "compression_curve")
    _generate(project_dir, request_path)
    request = json.loads(request_path.read_text(encoding="utf-8"))
    plan = ResolvedFigurePlan.from_payload(request["resolved_figure_plan"])
    queue = figure_queue_from_plan(plan, plan.rule_id)
    if queue_kind == "empty":
        invalid_queue: Any = []
    elif queue_kind == "tuple":
        invalid_queue = tuple(queue)
    elif queue_kind == "non_mapping":
        invalid_queue = [object()]
    elif queue_kind == "non_string_key":
        invalid_queue = [{**queue[0], 1: "forged"}, *queue[1:]]
    else:
        invalid_queue = [{}]

    with pytest.raises(
        StudioPreparationBlocked,
        match="non-empty internal list queue|malformed internal queue",
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


@pytest.mark.focused
def test_impact_private_source_directory_rolls_back_with_figure_set_failure(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "project"
    directory = (
        project_dir
        / "studio"
        / "processed"
        / "impact_conditions"
        / f"rfp_{'a' * 16}_{'b' * 32}"
    )
    directory.mkdir(parents=True)
    source = directory / "impact_2mm.csv"
    source.write_text("source", encoding="utf-8")

    @lifecycle.manage_mechanical_task_source_lifecycle
    def fail_transaction(**_kwargs: object) -> None:
        raise RuntimeError("synthetic figure-set failure")

    with pytest.raises(RuntimeError, match="synthetic figure-set failure"):
        fail_transaction(
            project_dir=project_dir,
            figure_plan=SimpleNamespace(rule_id="impact_metric"),
            queue_override=[{"condition_source": str(source)}],
        )

    assert not directory.exists()


@pytest.mark.focused
def test_mechanical_private_source_rejects_symlink_root_before_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_dir = tmp_path / "project"
    processed = project_dir / "studio" / "processed"
    processed.mkdir(parents=True)
    external = tmp_path / "external"
    external.mkdir()
    unsafe_root = processed / "mechanical_task_sources"
    unsafe_root.symlink_to(external, target_is_directory=True)
    binding_calls = 0

    def forbidden_binding(*_args: object, **_kwargs: object) -> object:
        nonlocal binding_calls
        binding_calls += 1
        raise AssertionError("binding must not run through a symlink root")

    monkeypatch.setattr(
        "sciplot_core.studio_core.source_bound_prepare.bind_mechanical_task_sources",
        forbidden_binding,
    )

    @lifecycle.manage_mechanical_task_source_lifecycle
    def transaction(**_kwargs: object) -> None:
        raise AssertionError("transaction must not start")

    with pytest.raises(
        StudioPreparationBlocked,
        match="malformed internal queue",
    ):
        transaction(
            project_dir=project_dir,
            figure_plan=SimpleNamespace(rule_id="compression_curve"),
            queue_override=[{}],
            preserve_existing=False,
            request={},
            prepared_source_attestation=None,
        )

    assert binding_calls == 0
    assert unsafe_root.is_symlink()
    assert list(external.iterdir()) == []


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


@pytest.mark.comprehensive
@pytest.mark.parametrize("missing_artifact", ["document", "spec"])
def test_exact_current_mechanical_reuse_rejects_missing_ready_secondary_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    missing_artifact: str,
) -> None:
    project_dir, request_path = _project(tmp_path, "compression_curve")
    _generate(project_dir, request_path)
    registry = json.loads(
        (project_dir / "studio" / "figure_set.json").read_text(encoding="utf-8")
    )
    secondary = next(
        item
        for item in registry["figures"]
        if item["figure_id"] != registry["primary_figure_id"]
    )
    Path(secondary[missing_artifact]).unlink()
    request_before = request_path.read_bytes()
    metadata_writes: list[str] = []

    def record_launcher(*_args: object, **_kwargs: object) -> Path:
        metadata_writes.append("launcher")
        return project_dir / "unexpected-launcher"

    def record_registration(*_args: object, **_kwargs: object) -> None:
        metadata_writes.append("registration")

    monkeypatch.setattr(prepare_existing, "_write_studio_launcher", record_launcher)
    monkeypatch.setattr(prepare_existing, "_write_veusz_launcher", record_launcher)
    monkeypatch.setattr(
        prepare_existing,
        "_write_export_edited_launcher",
        record_launcher,
    )
    monkeypatch.setattr(
        prepare_existing,
        "_register_studio_block",
        record_registration,
    )

    with pytest.raises(StudioPreparationBlocked) as exc_info:
        prepare_studio_document(project_dir)

    assert exc_info.value.reason_code == "studio_figure_set_mismatch"
    assert metadata_writes == []
    assert request_path.read_bytes() == request_before
