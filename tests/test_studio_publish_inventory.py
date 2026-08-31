from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import sciplot_core.studio_core.figure_set_state as figure_set_state_module
from sciplot_core.figure_plan import (
    CartesianMetricBinding,
    FigureOutcome,
    FigureTask,
    OrderedMetricsBinding,
    ResolvedFigurePlan,
    editable_figure_plan,
    request_for_figure_task,
)
from sciplot_core.foundation.file_hashing import existing_file_sha256
from sciplot_core.materials_rules import get_rule
from sciplot_core.readiness import load_validated_envelope_registry
from sciplot_core.readiness.rule_certification import (
    current_certified_rule_contract_snapshot,
)
from sciplot_core.studio_figure_set_contract import (
    STUDIO_FIGURE_SET_KIND,
    STUDIO_FIGURE_SET_LEGACY_VERSION,
    STUDIO_FIGURE_SET_TASK_VERSION,
)
from sciplot_core.studio_core import publish_finalize as publish_finalize_module
from sciplot_core.studio_core import publish_inventory as inventory_module
from sciplot_core.studio_core import rule_readiness as readiness_module
from sciplot_core.studio_core.figure_registry_entry import _figure_registry_entry
from sciplot_core.studio_core.figure_set_registry import (
    build_studio_figure_set_registry,
)
from sciplot_core.studio_core.figure_task_evidence import (
    figure_queue_item_from_task,
    figure_registry_projection_from_task,
)
from sciplot_core.studio_core.rule_contract_binding import (
    StudioRuleContractBinding,
)


UNPLANNED_RULE_ID = "rheology_strain_sweep"


def _current_binding(rule_id: str = "swelling_curve") -> dict[str, Any]:
    rule = get_rule(rule_id)
    return StudioRuleContractBinding.from_snapshot(
        current_certified_rule_contract_snapshot(
            rule=rule,
            registry=load_validated_envelope_registry(),
        )
    ).to_payload()


@pytest.mark.parametrize(
    (
        "request_payload",
        "fixture_status",
        "expected_rule_id",
        "expected_persisted",
        "expected_pending",
        "expected_blockers",
        "expected_lookup_count",
    ),
    [
        ({}, None, None, False, False, [], 0),
        ({"rule_id": None}, None, None, False, False, [], 0),
        ({"rule_id": "   "}, None, None, False, False, [], 0),
        (
            {"pending_rule_review": True},
            None,
            None,
            True,
            True,
            ["persisted_pending_rule_review"],
            0,
        ),
        (
            {
                "rule_id": "swelling_curve",
                "studio_rule_contract_binding": _current_binding(),
            },
            "ready",
            "swelling_curve",
            False,
            False,
            [],
            1,
        ),
        (
            {
                "rule_id": "swelling_curve",
                "pending_rule_review": True,
                "studio_rule_contract_binding": _current_binding(),
            },
            "ready",
            "swelling_curve",
            True,
            True,
            ["persisted_pending_rule_review"],
            1,
        ),
        (
            {
                "rule_id": "swelling_curve",
                "studio_rule_contract_binding": _current_binding(),
            },
            "pending",
            "swelling_curve",
            False,
            True,
            [
                "current_rule_not_ready",
                "current_rule_certification_stale",
                "prepared_rule_contract_binding_stale",
            ],
            1,
        ),
        (
            {
                "rule_id": "swelling_curve",
                "pending_rule_review": True,
                "studio_rule_contract_binding": _current_binding(),
            },
            "disabled",
            "swelling_curve",
            True,
            True,
            [
                "persisted_pending_rule_review",
                "current_rule_not_ready",
                "current_rule_certification_stale",
                "prepared_rule_contract_binding_stale",
            ],
            1,
        ),
    ],
)
def test_rule_publication_readiness_truth_table_is_pure(
    monkeypatch: pytest.MonkeyPatch,
    request_payload: dict[str, Any],
    fixture_status: str | None,
    expected_rule_id: str | None,
    expected_persisted: bool,
    expected_pending: bool,
    expected_blockers: list[str],
    expected_lookup_count: int,
) -> None:
    original = deepcopy(request_payload)
    base_rule = get_rule("swelling_curve")
    calls: list[str] = []

    def lookup(rule_id: str) -> Any:
        calls.append(rule_id)
        assert fixture_status is not None
        return replace(base_rule, fixture_status=fixture_status)

    monkeypatch.setattr(readiness_module, "get_rule", lookup)

    readiness = readiness_module.resolve_studio_rule_publication_readiness(
        request_payload
    )

    assert request_payload == original
    assert readiness.rule_id == expected_rule_id
    assert readiness.persisted_pending_rule_review is expected_persisted
    assert readiness.pending_rule_review is expected_pending
    assert len(calls) == expected_lookup_count
    payload = readiness.to_payload()
    assert payload["kind"] == "sciplot_studio_rule_publication_readiness"
    assert payload["version"] == 2
    assert payload["rule_id"] == expected_rule_id
    assert payload["persisted_pending_rule_review"] is expected_persisted
    assert payload["current_rule_readiness"] == fixture_status
    assert payload["pending_rule_review"] is expected_pending
    assert payload["publication_blocked"] is bool(expected_blockers)
    assert payload["blockers"] == expected_blockers
    assert payload["rule_contract_evidence"]["status"] == (
        "not_applicable"
        if expected_rule_id is None
        else "blocked"
        if "current_rule_certification_stale" in expected_blockers
        else "current"
    )


@pytest.mark.parametrize("rule_id", [True, 1, [], {}])
def test_rule_publication_readiness_rejects_non_string_rule_ids_before_lookup(
    monkeypatch: pytest.MonkeyPatch,
    rule_id: object,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        readiness_module,
        "get_rule",
        lambda value: calls.append(value),
    )

    with pytest.raises(
        ValueError,
        match=r"Studio request `rule_id` must be a string, null, or omitted\.",
    ):
        readiness_module.resolve_studio_rule_publication_readiness({"rule_id": rule_id})

    assert calls == []


@pytest.mark.parametrize("pending", [None, 0, 1, "true", [], {}])
def test_rule_publication_readiness_rejects_non_boolean_pending_before_lookup(
    monkeypatch: pytest.MonkeyPatch,
    pending: object,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        readiness_module,
        "get_rule",
        lambda value: calls.append(value),
    )

    with pytest.raises(
        ValueError,
        match=r"Studio request `pending_rule_review` must be a boolean\.",
    ):
        readiness_module.resolve_studio_rule_publication_readiness(
            {
                "rule_id": "swelling_curve",
                "pending_rule_review": pending,
            }
        )

    assert calls == []


@pytest.mark.parametrize("persisted_pending", [False, True])
def test_unknown_rule_never_short_circuits_catalog_validation(
    monkeypatch: pytest.MonkeyPatch,
    persisted_pending: bool,
) -> None:
    calls: list[str] = []
    real_get_rule = get_rule

    def lookup(rule_id: str) -> Any:
        calls.append(rule_id)
        return real_get_rule(rule_id)

    monkeypatch.setattr(readiness_module, "get_rule", lookup)

    with pytest.raises(
        ValueError,
        match=r"Unknown material rule `not_a_rule`\.",
    ):
        readiness_module.resolve_studio_rule_publication_readiness(
            {
                "rule_id": "not_a_rule",
                "pending_rule_review": persisted_pending,
            }
        )

    assert calls == ["not_a_rule"]


def test_rule_readiness_failure_reason_distinguishes_current_and_sticky_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_rule = get_rule("swelling_curve")

    monkeypatch.setattr(
        readiness_module,
        "get_rule",
        lambda _rule_id: replace(base_rule, fixture_status="pending"),
    )
    current_pending = readiness_module.resolve_studio_rule_publication_readiness(
        {"rule_id": "swelling_curve"}
    )
    assert current_pending.failure_reason == (
        "Material rule `swelling_curve` is currently `pending` and is not ready "
        "for production publication. Repair and revalidate the central rule, "
        "then reprepare this Studio project before handoff."
    )

    monkeypatch.setattr(
        readiness_module,
        "get_rule",
        lambda _rule_id: base_rule,
    )
    sticky_ready = readiness_module.resolve_studio_rule_publication_readiness(
        {
            "rule_id": "swelling_curve",
            "pending_rule_review": True,
            "studio_rule_contract_binding": _current_binding(),
        }
    )
    assert sticky_ready.failure_reason == (
        "This Studio project retains preparation-time rule-review evidence. "
        "Reprepare it with the current ready rule before handoff."
    )

    ruleless_sticky = readiness_module.resolve_studio_rule_publication_readiness(
        {"pending_rule_review": True}
    )
    assert ruleless_sticky.failure_reason == (
        "This Studio project retains rule-review evidence but has no canonical "
        "request rule. Reprepare it with an explicit ready rule before handoff."
    )


def _minimal_project(
    tmp_path: Path,
    request: dict[str, Any],
) -> tuple[Path, Path, Path, str]:
    project_dir = tmp_path / "project"
    request_path = project_dir / "plot_request.json"
    document_path = project_dir / "studio" / "document.vsz"
    document_path.parent.mkdir(parents=True)
    request_path.write_text(
        json.dumps(request, ensure_ascii=False),
        encoding="utf-8",
    )
    document_path.write_text("Add('page')\n", encoding="utf-8")
    document_hash = existing_file_sha256(document_path)
    assert document_hash is not None
    return project_dir, request_path, document_path, document_hash


def _selected_performance_plan(
    *,
    figure_id: str = "performance_scatter",
) -> ResolvedFigurePlan:
    task = FigureTask(
        figure_id=figure_id,
        order=1,
        title="Performance comparison scatter",
        x_metric="density",
        y_metric="specific_impact_strength",
        template="scatter",
        artifact_stem=figure_id,
        document_stem=figure_id,
    )
    return ResolvedFigurePlan.planned(
        rule_id="performance_comparison",
        selection_policy="explicit_supported_template",
        primary_figure_id=task.figure_id,
        tasks=(task,),
        source_sha256="a" * 64,
    )


def _write_task_registry(
    project_dir: Path,
    *,
    plan: ResolvedFigurePlan,
) -> None:
    task = plan.tasks[0]
    registry_path = project_dir / "studio" / "figure_set.json"
    registry_path.write_text(
        json.dumps(
            {
                "kind": STUDIO_FIGURE_SET_KIND,
                "version": STUDIO_FIGURE_SET_TASK_VERSION,
                "rule_id": plan.rule_id,
                "primary_figure_id": plan.primary_figure_id,
                "figures": [
                    {
                        **figure_registry_projection_from_task(task),
                        "status": "ready",
                    }
                ],
                "resolved_figure_plan": plan.to_payload(),
                "plan_id": plan.plan_id,
                "plan_sha256": plan.plan_sha256,
            }
        ),
        encoding="utf-8",
    )


def _required_publish_plan() -> ResolvedFigurePlan:
    scatter = FigureTask.with_metric_binding(
        figure_id="performance_scatter",
        order=1,
        title="Performance scatter",
        metric_binding=CartesianMetricBinding(
            x_metric="density",
            y_metric="specific_impact_strength",
        ),
        template="scatter",
        artifact_stem="performance_scatter",
        document_stem="performance_scatter",
    )
    polar = FigureTask.with_metric_binding(
        figure_id="performance_polar",
        order=2,
        title="Performance polar curve",
        metric_binding=OrderedMetricsBinding(
            metric_ids=(
                "density",
                "specific_impact_strength",
                "tensile_strength",
            )
        ),
        template="polar_curve",
        artifact_stem="performance_polar",
        document_stem="performance_polar",
    )
    return ResolvedFigurePlan.planned(
        rule_id="performance_comparison",
        selection_policy="test_required_publish_snapshot",
        primary_figure_id=scatter.figure_id,
        tasks=(scatter, polar),
        source_sha256="a" * 64,
    )


def _write_required_publish_project(tmp_path: Path) -> SimpleNamespace:
    project_dir = tmp_path / "required_publish_project"
    studio_dir = project_dir / "studio"
    request_path = project_dir / "plot_request.json"
    source_path = project_dir / "source.csv"
    plan = _required_publish_plan()
    source_path.parent.mkdir(parents=True)
    source_path.write_text("metric,value\n", encoding="utf-8")
    request = {
        "input": str(source_path),
        "rule_id": plan.rule_id,
        "template": "scatter",
        "resolved_figure_plan": plan.to_payload(),
        "studio_rule_contract_binding": _current_binding(plan.rule_id),
    }
    request_path.write_text(json.dumps(request), encoding="utf-8")

    entries: list[dict[str, Any]] = []
    documents: dict[str, Path] = {}
    specs: dict[str, Path] = {}
    generated_hashes: dict[str, str] = {}
    for task in plan.tasks:
        document = (
            studio_dir / "document.vsz"
            if task.figure_id == plan.primary_figure_id
            else studio_dir / "figures" / f"{task.document_stem}.vsz"
        )
        spec = (
            studio_dir / "spec.json"
            if task.figure_id == plan.primary_figure_id
            else document.with_suffix(".spec.json")
        )
        document.parent.mkdir(parents=True, exist_ok=True)
        document.write_text(f"Add('page') # {task.figure_id}\n", encoding="utf-8")
        spec.write_text(
            json.dumps(
                {
                    "kind": "sciplot_veusz_plot_spec",
                    "version": 1,
                    "template": task.template,
                    "source_request": request_for_figure_task(request, task),
                    "size_mm": [60.0, 55.0],
                }
            ),
            encoding="utf-8",
        )
        generated_hash = existing_file_sha256(document)
        assert generated_hash is not None
        entries.append(
            _figure_registry_entry(
                figure=figure_queue_item_from_task(task),
                document_path=document,
                generated_hash=generated_hash,
                series_count=1,
            )
        )
        documents[task.figure_id] = document
        specs[task.figure_id] = spec
        generated_hashes[task.figure_id] = generated_hash

    registry_plan = editable_figure_plan(plan, entries)
    registry = build_studio_figure_set_registry(
        project_dir=project_dir,
        request_path=request_path,
        request=request,
        primary_figure_id=plan.primary_figure_id,
        primary_document=documents[plan.primary_figure_id],
        entries=entries,
        resolved_plan=registry_plan,
    )
    registry_path = studio_dir / "figure_set.json"
    registry_path.write_text(json.dumps(registry), encoding="utf-8")
    return SimpleNamespace(
        project_dir=project_dir,
        request_path=request_path,
        source_path=source_path,
        plan=plan,
        registry_path=registry_path,
        document_path=documents[plan.primary_figure_id],
        document_hash=generated_hashes[plan.primary_figure_id],
        primary_generated_hash=generated_hashes[plan.primary_figure_id],
        secondary_document=documents[plan.tasks[1].figure_id],
        secondary_spec=specs[plan.tasks[1].figure_id],
    )


def _stub_required_publish_ports(
    monkeypatch: pytest.MonkeyPatch,
    project: SimpleNamespace,
) -> tuple[list[dict[str, Any]], list[Path]]:
    secondary_exports: list[dict[str, Any]] = []
    allocations: list[Path] = []
    monkeypatch.setattr(
        inventory_module,
        "_verify_exact_current_export_binding",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        inventory_module,
        "resolve_current_figure_plan",
        lambda **_kwargs: project.plan,
    )
    monkeypatch.setattr(
        inventory_module,
        "resolve_data_mapping_request",
        lambda request, *, base_dir: (dict(request), None),
    )
    monkeypatch.setattr(
        inventory_module,
        "_resolve_request_input",
        lambda _request, *, base_dir: project.source_path,
    )

    def export_secondary(**kwargs: Any) -> dict[str, Any]:
        secondary_exports.append(kwargs)
        entry = kwargs["registry_entry"]
        assert isinstance(entry, dict)
        document = Path(str(entry["document"]))
        return {
            "figure_id": str(kwargs["figure_id"]),
            "document": str(document),
            "document_sha256": existing_file_sha256(document) or ("0" * 64),
            "exports": [],
        }

    monkeypatch.setattr(
        inventory_module,
        "_export_secondary_figure",
        export_secondary,
    )

    def allocate(project_dir: Path) -> Path:
        allocations.append(project_dir)
        return project_dir / "runs" / "studio_001"

    monkeypatch.setattr(inventory_module, "_next_studio_run_dir", allocate)
    return secondary_exports, allocations


@pytest.mark.parametrize(
    "registry_state",
    ["missing", "damaged", "legacy_v1", "mismatched_v2"],
)
def test_selected_supported_plan_requires_matching_task_registry_before_run_allocation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    registry_state: str,
) -> None:
    plan = _selected_performance_plan()
    project_dir, request_path, document_path, document_hash = _minimal_project(
        tmp_path,
        {
            "rule_id": plan.rule_id,
            "template": "scatter",
            "resolved_figure_plan": plan.to_payload(),
        },
    )
    registry_path = project_dir / "studio" / "figure_set.json"
    if registry_state == "damaged":
        registry_path.write_text("{not-json", encoding="utf-8")
    elif registry_state == "legacy_v1":
        registry_path.write_text(
            json.dumps(
                {
                    "kind": STUDIO_FIGURE_SET_KIND,
                    "version": STUDIO_FIGURE_SET_LEGACY_VERSION,
                    "rule_id": plan.rule_id,
                    "primary_figure_id": plan.primary_figure_id,
                    "figures": [],
                }
            ),
            encoding="utf-8",
        )
    elif registry_state == "mismatched_v2":
        _write_task_registry(
            project_dir,
            plan=_selected_performance_plan(figure_id="different_performance_scatter"),
        )

    monkeypatch.setattr(
        inventory_module,
        "_verify_exact_current_export_binding",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        inventory_module,
        "resolve_current_figure_plan",
        lambda **_kwargs: plan,
    )
    monkeypatch.setattr(
        inventory_module,
        "validate_prepared_studio_presentation",
        lambda **_kwargs: None,
    )
    collection_calls: list[bool] = []
    allocation_calls: list[Path] = []
    monkeypatch.setattr(
        inventory_module,
        "_collect_figure_documents",
        lambda **_kwargs: collection_calls.append(True),
    )
    monkeypatch.setattr(
        inventory_module,
        "_next_studio_run_dir",
        lambda project: allocation_calls.append(project),
    )

    with pytest.raises(
        RuntimeError,
        match="matching task-aware v2 Studio figure-set registry",
    ):
        inventory_module.prepare_studio_export_inventory(
            project_dir=project_dir,
            request_path=request_path,
            document_path=document_path,
            exports=[],
            export_document_sha256=document_hash,
        )

    assert collection_calls == []
    assert allocation_calls == []
    assert not (project_dir / "runs").exists()


def test_planless_legacy_request_does_not_require_a_figure_set_registry(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    assert (
        inventory_module._validated_figure_set_scope(
            project_dir,
            request={"rule_id": "swelling_curve", "template": "point_line"},
        )
        is None
    )


def test_matching_task_registry_establishes_supported_plan_export_scope(
    tmp_path: Path,
) -> None:
    plan = _selected_performance_plan()
    project_dir = tmp_path / "project"
    document = project_dir / "studio" / "document.vsz"
    spec = project_dir / "studio" / "spec.json"
    document.parent.mkdir(parents=True)
    document.write_text("Add('page')\n", encoding="utf-8")
    spec.write_text(
        json.dumps(
            {
                "kind": "sciplot_veusz_plot_spec",
                "version": 1,
                "template": "scatter",
            }
        ),
        encoding="utf-8",
    )
    registry_plan = ResolvedFigurePlan(
        rule_id=plan.rule_id,
        selection_policy=plan.selection_policy,
        primary_figure_id=plan.primary_figure_id,
        tasks=plan.tasks,
        outcomes=(
            FigureOutcome(
                figure_id=plan.primary_figure_id,
                status="editable",
                artifacts=(str(document), str(spec)),
            ),
        ),
        source_sha256=plan.source_sha256,
    )
    _write_task_registry(project_dir, plan=registry_plan)

    scope = inventory_module._validated_figure_set_scope(
        project_dir,
        request={
            "rule_id": plan.rule_id,
            "template": "scatter",
            "resolved_figure_plan": plan.to_payload(),
        },
    )

    assert scope is not None
    assert scope["status"] == "full_figure_set_exact_current"
    assert scope["primary_figure_id"] == plan.primary_figure_id
    assert scope["supported_figure_ids"] == list(plan.selected_figure_ids)
    assert scope["plan_sha256"] == plan.plan_sha256


def test_required_plan_publish_reads_one_strict_figure_set_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _write_required_publish_project(tmp_path)
    secondary_exports, allocations = _stub_required_publish_ports(
        monkeypatch,
        project,
    )
    registry_reads: list[Path] = []
    real_read_json = figure_set_state_module._read_json

    def count_registry_read(path: Path) -> dict[str, Any]:
        if path.expanduser().resolve() == project.registry_path.resolve():
            registry_reads.append(path)
        return real_read_json(path)

    monkeypatch.setattr(figure_set_state_module, "_read_json", count_registry_read)

    inventory = inventory_module.prepare_studio_export_inventory(
        project_dir=project.project_dir,
        request_path=project.request_path,
        document_path=project.document_path,
        exports=[],
        export_document_sha256=project.document_hash,
    )

    assert registry_reads == [project.registry_path]
    assert inventory.figure_set_export_scope is not None
    assert inventory.figure_set_export_scope["supported_figure_ids"] == list(
        project.plan.selected_figure_ids
    )
    assert [call["figure_id"] for call in secondary_exports] == [
        project.plan.tasks[1].figure_id
    ]
    assert allocations == [project.project_dir]


@pytest.mark.parametrize("missing_member", ["document", "spec"])
def test_required_plan_publish_rejects_missing_secondary_artifact_before_ports(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    missing_member: str,
) -> None:
    project = _write_required_publish_project(tmp_path)
    missing_path = (
        project.secondary_document
        if missing_member == "document"
        else project.secondary_spec
    )
    missing_path.unlink()
    secondary_exports, allocations = _stub_required_publish_ports(
        monkeypatch,
        project,
    )

    with pytest.raises(RuntimeError):
        inventory_module.prepare_studio_export_inventory(
            project_dir=project.project_dir,
            request_path=project.request_path,
            document_path=project.document_path,
            exports=[],
            export_document_sha256=project.document_hash,
        )

    assert secondary_exports == []
    assert allocations == []
    assert not (project.project_dir / "runs").exists()


@pytest.mark.parametrize("linked_member", ["document", "spec"])
def test_required_plan_publish_rejects_external_secondary_symlink_before_ports(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    linked_member: str,
) -> None:
    project = _write_required_publish_project(tmp_path)
    linked_path = (
        project.secondary_document
        if linked_member == "document"
        else project.secondary_spec
    )
    external_path = project.project_dir / "external" / linked_path.name
    external_path.parent.mkdir()
    linked_path.replace(external_path)
    linked_path.symlink_to(external_path)
    secondary_exports, allocations = _stub_required_publish_ports(
        monkeypatch,
        project,
    )

    with pytest.raises(RuntimeError):
        inventory_module.prepare_studio_export_inventory(
            project_dir=project.project_dir,
            request_path=project.request_path,
            document_path=project.document_path,
            exports=[],
            export_document_sha256=project.document_hash,
        )

    assert secondary_exports == []
    assert allocations == []
    assert not (project.project_dir / "runs").exists()


def test_required_plan_publish_rejects_split_generated_hash_before_ports(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _write_required_publish_project(tmp_path)
    registry = json.loads(project.registry_path.read_text(encoding="utf-8"))
    primary = next(
        entry
        for entry in registry["figures"]
        if entry["figure_id"] == project.plan.primary_figure_id
    )
    assert primary["document_state"]["generated_hash"] == primary["generated_hash"]
    primary["generated_hash"] = "f" * 64
    project.registry_path.write_text(json.dumps(registry), encoding="utf-8")
    secondary_exports, allocations = _stub_required_publish_ports(
        monkeypatch,
        project,
    )

    with pytest.raises(RuntimeError):
        inventory_module.prepare_studio_export_inventory(
            project_dir=project.project_dir,
            request_path=project.request_path,
            document_path=project.document_path,
            exports=[],
            export_document_sha256=project.document_hash,
        )

    assert secondary_exports == []
    assert allocations == []
    assert not (project.project_dir / "runs").exists()


def test_required_plan_publish_uses_snapshot_primary_generated_hash_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _write_required_publish_project(tmp_path)
    project.document_path.write_text(
        "Add('page') # manually edited primary\n",
        encoding="utf-8",
    )
    edited_hash = existing_file_sha256(project.document_path)
    assert edited_hash is not None
    assert edited_hash != project.primary_generated_hash
    secondary_exports, allocations = _stub_required_publish_ports(
        monkeypatch,
        project,
    )
    legacy_hash_calls: list[Path] = []

    def legacy_generated_hash(project_dir: Path) -> str:
        legacy_hash_calls.append(project_dir)
        return "e" * 64

    monkeypatch.setattr(
        inventory_module,
        "_registered_generated_hash",
        legacy_generated_hash,
    )

    inventory = inventory_module.prepare_studio_export_inventory(
        project_dir=project.project_dir,
        request_path=project.request_path,
        document_path=project.document_path,
        exports=[],
        export_document_sha256=edited_hash,
    )

    assert legacy_hash_calls == []
    assert inventory.document_state["generated_hash"] == project.primary_generated_hash
    assert inventory.document_state["current_hash"] == edited_hash
    assert inventory.document_state["authority"] == "veusz_manual"
    assert inventory.document_state["manual_edit_detected"] is True
    assert len(secondary_exports) == 1
    assert allocations == [project.project_dir]


def test_required_plan_publish_rejects_missing_primary_current_hash_before_ports(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _write_required_publish_project(tmp_path)
    registry = json.loads(project.registry_path.read_text(encoding="utf-8"))
    primary = next(
        entry
        for entry in registry["figures"]
        if entry["figure_id"] == project.plan.primary_figure_id
    )
    primary["document_state"].pop("current_hash")
    project.registry_path.write_text(json.dumps(registry), encoding="utf-8")
    secondary_exports, allocations = _stub_required_publish_ports(
        monkeypatch,
        project,
    )

    with pytest.raises(RuntimeError):
        inventory_module.prepare_studio_export_inventory(
            project_dir=project.project_dir,
            request_path=project.request_path,
            document_path=project.document_path,
            exports=[],
            export_document_sha256=project.document_hash,
        )

    assert secondary_exports == []
    assert allocations == []
    assert not (project.project_dir / "runs").exists()


def test_required_plan_primary_drift_after_presentation_blocks_before_ports(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _write_required_publish_project(tmp_path)
    secondary_exports, allocations = _stub_required_publish_ports(
        monkeypatch,
        project,
    )
    validate_presentation = inventory_module.validate_prepared_studio_presentation

    def validate_then_drift(**kwargs: Any) -> None:
        validate_presentation(**kwargs)
        project.document_path.write_text(
            "Add('page') # drifted after presentation\n",
            encoding="utf-8",
        )

    monkeypatch.setattr(
        inventory_module,
        "validate_prepared_studio_presentation",
        validate_then_drift,
    )

    with pytest.raises(RuntimeError, match="document changed before the project run"):
        inventory_module.prepare_studio_export_inventory(
            project_dir=project.project_dir,
            request_path=project.request_path,
            document_path=project.document_path,
            exports=[],
            export_document_sha256=project.document_hash,
        )

    assert secondary_exports == []
    assert allocations == []
    assert not (project.project_dir / "runs").exists()


def test_required_plan_primary_drift_during_secondary_port_blocks_before_allocation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _write_required_publish_project(tmp_path)
    secondary_exports, allocations = _stub_required_publish_ports(
        monkeypatch,
        project,
    )
    export_secondary = inventory_module._export_secondary_figure

    def export_secondary_then_drift(**kwargs: Any) -> dict[str, Any]:
        result = export_secondary(**kwargs)
        project.document_path.write_text(
            "Add('page') # drifted during secondary export\n",
            encoding="utf-8",
        )
        return result

    monkeypatch.setattr(
        inventory_module,
        "_export_secondary_figure",
        export_secondary_then_drift,
    )

    with pytest.raises(RuntimeError):
        inventory_module.prepare_studio_export_inventory(
            project_dir=project.project_dir,
            request_path=project.request_path,
            document_path=project.document_path,
            exports=[],
            export_document_sha256=project.document_hash,
        )

    assert len(secondary_exports) == 1
    assert allocations == []
    assert not (project.project_dir / "runs").exists()


def test_run_snapshot_writes_validated_inventory_registry_after_source_tamper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _write_required_publish_project(tmp_path)
    _stub_required_publish_ports(monkeypatch, project)
    inventory = inventory_module.prepare_studio_export_inventory(
        project_dir=project.project_dir,
        request_path=project.request_path,
        document_path=project.document_path,
        exports=[],
        export_document_sha256=project.document_hash,
    )
    assert inventory.figure_set is not None
    project.registry_path.write_text(
        json.dumps({"tampered_after_inventory": True}),
        encoding="utf-8",
    )
    destination = inventory.output_dir / "studio"

    publish_finalize_module._snapshot_studio_directory(
        source=project.document_path.parent,
        destination=destination,
        figure_set=inventory.figure_set,
        verified_spec_hashes=inventory.figure_set_spec_hashes,
    )

    assert json.loads(
        (destination / "figure_set.json").read_text(encoding="utf-8")
    ) == (inventory.figure_set)
    assert json.loads(project.registry_path.read_text(encoding="utf-8")) == {
        "tampered_after_inventory": True
    }


def test_run_snapshot_rejects_post_inventory_spec_drift_and_cleans_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _write_required_publish_project(tmp_path)
    _stub_required_publish_ports(monkeypatch, project)
    inventory = inventory_module.prepare_studio_export_inventory(
        project_dir=project.project_dir,
        request_path=project.request_path,
        document_path=project.document_path,
        exports=[],
        export_document_sha256=project.document_hash,
    )
    project.secondary_spec.write_text(
        project.secondary_spec.read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
    )
    destination = inventory.output_dir / "studio"

    with pytest.raises(RuntimeError, match="spec changed before its run snapshot"):
        publish_finalize_module._snapshot_studio_directory(
            source=project.document_path.parent,
            destination=destination,
            figure_set=inventory.figure_set,
            verified_spec_hashes=inventory.figure_set_spec_hashes,
        )

    assert not destination.exists()


def test_run_snapshot_rejects_external_verified_spec_before_replacing_destination(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source" / "studio"
    source.mkdir(parents=True)
    (source / "document.vsz").write_text("Add('page')\n", encoding="utf-8")
    external_spec = tmp_path / "external" / "figure.spec.json"
    external_spec.parent.mkdir()
    external_spec.write_text("{}\n", encoding="utf-8")
    external_hash = existing_file_sha256(external_spec)
    assert external_hash is not None
    destination = tmp_path / "run" / "studio"
    destination.mkdir(parents=True)
    marker = destination / "existing-marker.txt"
    marker.write_text("preserve me\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="outside its snapshot root"):
        publish_finalize_module._snapshot_studio_directory(
            source=source,
            destination=destination,
            verified_spec_hashes=((str(external_spec), external_hash),),
        )

    assert marker.read_text(encoding="utf-8") == "preserve me\n"


def _stub_inventory_ports(
    monkeypatch: pytest.MonkeyPatch,
    *,
    document_path: Path,
    document_hash: str,
) -> list[dict[str, Any]]:
    collected: list[dict[str, Any]] = []
    monkeypatch.setattr(
        inventory_module,
        "_verify_exact_current_export_binding",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        inventory_module,
        "resolve_current_figure_plan",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        inventory_module,
        "_validated_figure_set_scope",
        lambda *_args, **_kwargs: None,
    )

    def collect(**kwargs: Any) -> list[dict[str, Any]]:
        collected.append(kwargs)
        return [
            {
                "figure_id": "primary",
                "document": str(document_path),
                "document_sha256": document_hash,
                "exports": [],
            }
        ]

    monkeypatch.setattr(inventory_module, "_collect_figure_documents", collect)
    monkeypatch.setattr(
        inventory_module,
        "resolve_data_mapping_request",
        lambda request, *, base_dir: (dict(request), None),
    )
    monkeypatch.setattr(
        inventory_module,
        "_registered_generated_hash",
        lambda _project_dir: None,
    )
    monkeypatch.setattr(
        inventory_module,
        "_studio_document_state",
        lambda _document_path, *, generated_hash: {
            "authority": "generated_current",
            "manual_edit_detected": False,
            "current_hash": document_hash,
        },
    )
    return collected


def test_publish_inventory_revalidates_a_currently_downgraded_rule_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_dir, request_path, document_path, document_hash = _minimal_project(
        tmp_path,
        {
            "rule_id": UNPLANNED_RULE_ID,
            "template": "point_line",
            "studio_rule_contract_binding": _current_binding(UNPLANNED_RULE_ID),
        },
    )
    collected = _stub_inventory_ports(
        monkeypatch,
        document_path=document_path,
        document_hash=document_hash,
    )
    pending_rule = replace(get_rule(UNPLANNED_RULE_ID), fixture_status="pending")
    calls: list[str] = []

    def lookup(rule_id: str) -> Any:
        calls.append(rule_id)
        return pending_rule

    monkeypatch.setattr(readiness_module, "get_rule", lookup)

    inventory = inventory_module.prepare_studio_export_inventory(
        project_dir=project_dir,
        request_path=request_path,
        document_path=document_path,
        exports=[],
        export_document_sha256=document_hash,
    )

    assert calls == [UNPLANNED_RULE_ID]
    assert inventory.rule_readiness.current_rule is pending_rule
    assert inventory.rule_readiness.persisted_pending_rule_review is False
    assert inventory.pending_rule_review is True
    assert inventory.output_dir == project_dir / "runs" / "studio_001"
    assert inventory.output_dir.is_dir()
    assert len(collected) == 1

    import sciplot_core.studio_core.publish_finalize as finalize_module

    monkeypatch.setattr(
        finalize_module,
        "_write_studio_revision_brief",
        lambda *_args, **_kwargs: "revision_brief.md",
    )
    monkeypatch.setattr(
        finalize_module,
        "_write_studio_review_html",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        finalize_module,
        "_write_json_atomic",
        lambda *_args, **_kwargs: None,
    )

    def finalize_contracts(**kwargs: object) -> None:
        manifest = kwargs["manifest"]
        assert isinstance(manifest, dict)
        manifest["package_contract"] = {"complete": True}
        manifest["delivery_package"] = {"complete": True}
        manifest["delivery_verification"] = {"passed": True}

    monkeypatch.setattr(
        finalize_module,
        "_finalize_delivery_contracts",
        finalize_contracts,
    )
    registered: list[dict[str, Any]] = []
    monkeypatch.setattr(
        finalize_module,
        "_register_studio_run",
        lambda _project, _manifest, *, studio_run: registered.append(studio_run),
    )
    canonical_rule_readiness = inventory.rule_readiness.to_payload()
    presentation_identity = inventory.presentation_identity.to_payload()
    manifest = {
        "result": {
            "exports": [],
            "template": inventory.presentation_identity.template,
            "presentation_identity": presentation_identity,
            "rule_readiness": canonical_rule_readiness,
            "pending_rule_review": True,
            "publication_rule_blocked": True,
            "autonomous_rule_ready": False,
        },
        "semantic": {
            "presentation_identity": presentation_identity,
            "studio_rule_publication_readiness": canonical_rule_readiness,
            "publication_rule_ready": False,
        },
        "template": inventory.presentation_identity.template,
        "presentation_identity": presentation_identity,
        "studio": {"presentation_identity": presentation_identity},
        "scope": "project_delivery",
        "rule_readiness": canonical_rule_readiness,
        "pending_rule_review": True,
        "publication_rule_blocked": True,
        "autonomous_rule_ready": False,
    }
    payload = finalize_module.finalize_studio_run(
        inventory=inventory,
        evidence=SimpleNamespace(qa={"status": "passed"}),
        manifest=manifest,
        copied_exports=[],
        figures=[],
    )

    assert payload["state"] == "needs_rule_repair"
    assert payload["ready_to_use"] is False
    assert payload["failure_stage"] == "rule_readiness_gate"
    assert payload["failure_reason"] == (
        f"Material rule `{UNPLANNED_RULE_ID}` is currently `pending` and is not ready "
        "for production publication. Repair and revalidate the central rule, "
        "then reprepare this Studio project before handoff."
    )
    assert payload["rule_readiness"] == canonical_rule_readiness
    assert payload["rule_readiness"]["blockers"] == [
        "current_rule_not_ready",
        "current_rule_certification_stale",
        "prepared_rule_contract_binding_stale",
    ]
    assert (
        manifest["result"]["rule_readiness"]
        == manifest["rule_readiness"]
        == payload["rule_readiness"]
        == registered[0]["rule_readiness"]
        == canonical_rule_readiness
    )
    assert registered == [payload]


@pytest.mark.parametrize(
    ("request_payload", "message"),
    [
        (
            {"rule_id": True, "template": "curve"},
            r"Studio request `rule_id` must be a string",
        ),
        (
            {
                "rule_id": "swelling_curve",
                "template": "point_line",
                "pending_rule_review": None,
            },
            r"Studio request `pending_rule_review` must be a boolean",
        ),
        (
            {"rule_id": "not_a_rule", "template": "curve"},
            r"Unknown material rule `not_a_rule`",
        ),
    ],
)
def test_invalid_rule_state_fails_before_collecting_figures_or_allocating_a_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    request_payload: dict[str, Any],
    message: str,
) -> None:
    project_dir, request_path, document_path, document_hash = _minimal_project(
        tmp_path,
        request_payload,
    )
    collected = _stub_inventory_ports(
        monkeypatch,
        document_path=document_path,
        document_hash=document_hash,
    )

    with pytest.raises(ValueError, match=message):
        inventory_module.prepare_studio_export_inventory(
            project_dir=project_dir,
            request_path=request_path,
            document_path=document_path,
            exports=[],
            export_document_sha256=document_hash,
        )

    assert collected == []
    assert not (project_dir / "runs").exists()


@pytest.mark.parametrize(
    "request_payload",
    [
        {"rule_id": UNPLANNED_RULE_ID, "template": "point_line"},
        {"rule_id": "   ", "template": "curve"},
    ],
)
def test_ready_and_blank_rule_inventory_controls_remain_publishable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    request_payload: dict[str, Any],
) -> None:
    project_dir, request_path, document_path, document_hash = _minimal_project(
        tmp_path,
        request_payload,
    )
    _stub_inventory_ports(
        monkeypatch,
        document_path=document_path,
        document_hash=document_hash,
    )
    real_get_rule = get_rule
    calls: list[str] = []

    def lookup(rule_id: str) -> Any:
        calls.append(rule_id)
        return real_get_rule(rule_id)

    monkeypatch.setattr(readiness_module, "get_rule", lookup)

    inventory = inventory_module.prepare_studio_export_inventory(
        project_dir=project_dir,
        request_path=request_path,
        document_path=document_path,
        exports=[],
        export_document_sha256=document_hash,
    )

    assert inventory.pending_rule_review is False
    assert calls == (
        [UNPLANNED_RULE_ID] if str(request_payload.get("rule_id") or "").strip() else []
    )
    assert inventory.output_dir.is_dir()
