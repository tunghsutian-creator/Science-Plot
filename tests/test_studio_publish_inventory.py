from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sciplot_core.figure_plan import FigureOutcome, FigureTask, ResolvedFigurePlan
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
from sciplot_core.studio_core import publish_inventory as inventory_module
from sciplot_core.studio_core import rule_readiness as readiness_module
from sciplot_core.studio_core.figure_task_evidence import (
    figure_registry_projection_from_task,
)
from sciplot_core.studio_core.rule_contract_binding import (
    StudioRuleContractBinding,
)


def _current_binding() -> dict[str, Any]:
    rule = get_rule("swelling_curve")
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
            "rule_id": "swelling_curve",
            "template": "point_line",
            "studio_rule_contract_binding": _current_binding(),
        },
    )
    collected = _stub_inventory_ports(
        monkeypatch,
        document_path=document_path,
        document_hash=document_hash,
    )
    pending_rule = replace(get_rule("swelling_curve"), fixture_status="pending")
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

    assert calls == ["swelling_curve"]
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
        "Material rule `swelling_curve` is currently `pending` and is not ready "
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
        {"rule_id": "swelling_curve", "template": "point_line"},
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
        ["swelling_curve"] if str(request_payload.get("rule_id") or "").strip() else []
    )
    assert inventory.output_dir.is_dir()
