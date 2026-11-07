"""One mechanical observation per operation, with fresh external boundaries."""

from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
from typing import Any

import pytest

from public_multitask_inputs import mechanical_source
from sciplot_core.figure_plan.mechanical_resolution import resolve_mechanical_plan
from sciplot_core.materials_rules import get_rule, semantic_payload_from_rule
from sciplot_core.mechanical_task_sources import build_mechanical_task_sources
from sciplot_core.semantic import prepare_semantic_source
from sciplot_core.semantic_sources import mechanical_facts
from sciplot_core.semantic_sources.mechanical_fact_models import MechanicalSourceFacts
from sciplot_core.studio_core.figure_task_evidence import figure_queue_from_plan
from sciplot_core.studio_core.mechanical_task_source_lifecycle import (
    manage_mechanical_task_source_lifecycle,
)
from sciplot_core.studio_core.source_bound_prepare import (
    bind_mechanical_task_sources,
    prepare_source_bound_figure_queue,
)
from sciplot_core.study_model import experiment_recommendation_payload
from sciplot_core.terminal_request import project_terminal_render_request
from sciplot_core.workflow import auto_split, request_rendering
from sciplot_core.workflow.mechanical_bundle import _render_veusz_mechanical_bundle
from sciplot_core.workflow.route_intent import resolve_workflow_route_intent
from sciplot_core.workflow.scientific_source_resolution import (
    resolve_workflow_scientific_source,
)
from tests.test_mechanical_workflow_bundle import _fake_renderer


def _resolve(source: Path, request: dict[str, Any]):
    rule = request["rule_id"]
    resolved, plan = resolve_workflow_scientific_source(
        input_path=source, rule_id=rule, template="curve", request=request,
        study_model=experiment_recommendation_payload(rule_id=rule),
    )
    assert resolved is not None and plan is not None
    return resolved, plan


def _prepare(source: Path, output: Path, request: dict[str, Any], resolved):
    return prepare_semantic_source(
        source, output_dir=output,
        semantic=semantic_payload_from_rule(get_rule(request["rule_id"]), confidence=1.0),
        series_order=request.get("series_order"),
        replicate_mode=request.get("replicate_mode"),
        resolved_scientific_source=resolved,
    )


@pytest.mark.parametrize("rule", ("tensile_curve", "compression_curve", "flexural_curve"))
@pytest.mark.parametrize("mode", ("representative", "individual"))
@pytest.mark.parametrize("route", ("workflow", "studio"))
def test_mechanical_operation_carries_one_observation_to_every_task(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rule: str, mode: str, route: str,
) -> None:
    source = mechanical_source(tmp_path / "raw", rule)
    original = {p: p.read_bytes() for p in (source.rglob("*") if source.is_dir() else (source,)) if p.is_file()}
    order = ["Cedar"] if mode == "representative" else [f"Cedar__repeat {n}" for n in (1, 2, 3)]
    request = {"rule_id": rule, "template": "curve", "series_order": order, "replicate_mode": mode}
    reads = []
    read = mechanical_facts._read_source

    def counted(*args, **kwargs):
        result = read(*args, **kwargs)
        reads.append(result)
        return result

    monkeypatch.setattr(mechanical_facts, "_read_source", counted)
    resolved, plan = _resolve(source, request)
    facts = resolved.require_domain(MechanicalSourceFacts)
    assert facts.replicate_counts == (("Cedar", 3),)
    assert len(facts.summary_rows) == 3
    assert facts.curve_sample_order(mode) == tuple(order)
    assert resolve_mechanical_plan(facts=facts, replicate_mode=mode) == plan
    if route == "workflow":
        seen = []

        def builder(*args, **kwargs):
            assert kwargs["facts"] is facts
            result = build_mechanical_task_sources(*args, **kwargs)
            seen.extend(result)
            return result

        def bundle(*args, **kwargs):
            assert kwargs["resolved_scientific_source"] is resolved
            def renderer(*args, **kwargs):
                payload = _fake_renderer(*args, **kwargs)
                payload["terminal_render_requests"] = [project_terminal_render_request(
                    request_context=kwargs["request_context"], template=kwargs["template"],
                    render_options=kwargs["options"],
                )]
                return payload
            return _render_veusz_mechanical_bundle(*args, **kwargs,
                _source_builder=builder, _renderer=renderer,
                _payload_validator=lambda *_a, **_k: None,
                _evidence_builder=lambda **_k: {})

        monkeypatch.setattr(auto_split, "_render_veusz_mechanical_bundle", bundle)
        rendered = request_rendering.execute_request_render(
            request={**request, "resolved_figure_plan": plan.to_payload()},
            route_intent=resolve_workflow_route_intent(request),
            semantic=semantic_payload_from_rule(get_rule(rule), confidence=1.0),
            study_model=experiment_recommendation_payload(rule_id=rule),
            input_path=source, output_dir=tmp_path / "workflow", base_dir=tmp_path,
            transform_steps=[], resolved_scientific_source=resolved,
            _resolved_figure_plan=plan,
        )
        assert rendered.result["resolved_figure_plan"]["complete"] is True
        assert tuple(item.task for item in seen) == plan.tasks
        assert all(item.binding.sample_order == item.task.sample_order for item in seen)
    else:
        from sciplot_core.studio_core import source_bound_prepare

        queue, attestation, steps = prepare_source_bound_figure_queue(
            figure_plan=plan, source_input=source, request=request, base_dir=tmp_path,
            resolved_scientific_source=resolved,
        )
        seen = []
        bind = source_bound_prepare.bind_mechanical_task_sources

        def binding(*args, **kwargs):
            assert kwargs["resolved_scientific_source"] is resolved
            result = bind(*args, **kwargs)
            seen.extend(result)
            return result

        monkeypatch.setattr(source_bound_prepare, "bind_mechanical_task_sources", binding)

        @manage_mechanical_task_source_lifecycle
        def transaction(**kwargs):
            return kwargs["queue_override"]

        output = transaction(project_dir=tmp_path, request=request, figure_plan=plan,
            prepared_source_attestation=attestation, queue_override=queue,
            preserve_existing=False, resolved_scientific_source=resolved)
        assert seen == output
        assert len(output) == len(plan.tasks)
        assert steps[0]["parameters"]["summary_raw_specimen_count"] == 3
        assert tuple(item["id"] for item in output) == plan.selected_figure_ids
    assert len(reads) == 1
    assert {p: p.read_bytes() for p in original} == original
    # A different operation really reads again; the envelope is not a cache.
    fresh, fresh_plan = _resolve(source, request)
    assert len(reads) == 2
    assert fresh.domain == facts and fresh_plan.plan_sha256 == plan.plan_sha256
    assert fresh.domain is not facts
    direct = _prepare(source, tmp_path / "raw_entry", request, None)
    assert len(reads) == 3
    direct["source_attestation"].verify_current(
        source_root=source, prepared_source=Path(direct["source"]),
    )


def test_mechanical_diagnostics_detach_inputs_and_refuse_mutation(tmp_path: Path) -> None:
    source = mechanical_source(tmp_path / "raw", "tensile_curve")
    facts = mechanical_facts.load_mechanical_source_facts(source, rule_id="tensile_curve")
    curve = facts.raw_series[0]
    original = {**curve.diagnostics, "reported_metric_headers": dict(curve.diagnostics["reported_metric_headers"])}
    supplied = replace(curve, diagnostics=original)
    closed = replace(facts, raw_series=(supplied,), individual_curve_series=(supplied,),
                     representative_curve_series=(supplied,))
    original["source_file"] = "caller mutation"
    original["reported_metric_headers"]["modulus_MPa"] = "wrong header"
    assert closed.raw_series[0].diagnostics["source_file"] == curve.diagnostics["source_file"]
    assert closed.raw_series[0].diagnostics["reported_metric_headers"] == curve.diagnostics["reported_metric_headers"]
    with pytest.raises(TypeError):
        closed.raw_series[0].diagnostics["source_file"] = "corrupt"
    with pytest.raises(TypeError):
        closed.raw_series[0].diagnostics["reported_metric_headers"]["modulus_MPa"] = "corrupt"
    assert closed.raw_series[0].points is supplied.points
    payload = facts.summary_records()
    payload[0]["sample"] = "caller mutation"
    assert facts.summary_rows[0].sample == "Cedar"
    # Published mechanical ledgers contain ordinary JSON, never proxy reprs.
    prepared = _prepare(source, tmp_path / "prepared", {"rule_id": "tensile_curve"}, _resolve(source, {"rule_id": "tensile_curve"})[0])
    encoded = json.dumps(prepared["transform_steps"], allow_nan=False)
    assert "mappingproxy" not in encoded
    assert json.loads(encoded)[0]["parameters"]["representative_selections"][0]["metrics"]["strength_MPa"] == 20.0


@pytest.mark.parametrize("mutation", ("same_metadata", "missing", "alias"))
def test_mechanical_snapshot_requires_current_physical_source_before_writes(tmp_path: Path, mutation: str) -> None:
    source = mechanical_source(tmp_path / "raw", "compression_curve")
    request = {"rule_id": "compression_curve"}
    resolved, _ = _resolve(source, request)
    before = source.stat()
    if mutation == "same_metadata":
        content = source.read_bytes()
        source.write_bytes(content.replace(b"10.0", b"90.0"))
        assert source.stat().st_size == before.st_size
        os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
    elif mutation == "missing":
        source.unlink()
    else:
        moved = source.with_name("other.csv")
        source.rename(moved)
        source.symlink_to(moved)
    with pytest.raises((ValueError, OSError)):
        _prepare(source, tmp_path / "rejected", request, resolved)
    assert not any(p.is_file() for p in (tmp_path / "rejected").rglob("*"))


@pytest.mark.parametrize("mutation", ("raw", "prepared", "attestation", "order", "foreign_source", "foreign_rule"))
def test_mechanical_task_materialization_rejects_divergent_boundary(tmp_path: Path, mutation: str) -> None:
    source = mechanical_source(tmp_path / "raw", "compression_curve")
    request = {"rule_id": "compression_curve"}
    resolved, plan = _resolve(source, request)
    prepared = _prepare(source, tmp_path / "prepared", request, resolved)
    table = Path(prepared["source"])
    attestation = prepared["source_attestation"]
    if mutation == "raw":
        source.write_bytes(source.read_bytes().replace(b"10.0", b"90.0"))
    elif mutation == "prepared":
        table.write_bytes(table.read_bytes().replace(b"MPa", b"kPa"))
    elif mutation == "attestation":
        attestation = replace(attestation, prepared_source=replace(attestation.prepared_source, sha256="0" * 64))
    elif mutation == "order":
        request["series_order"] = ["Cedar__repeat 3", "Cedar__repeat 1", "Cedar__repeat 2"]
    elif mutation == "foreign_source":
        source = mechanical_source(tmp_path / "other", "compression_curve")
    else:
        with pytest.raises(ValueError, match="rule identity"):
            replace(resolved, rule_id="flexural_curve")
        resolved = replace(resolved, domain=replace(resolved.domain, rule_id="flexural_curve"), rule_id="flexural_curve", figure_plan=None)
    target = tmp_path / "rejected"
    with pytest.raises((ValueError, OSError)):
        build_mechanical_task_sources(table, raw_source=source,
            facts=resolved.require_domain(MechanicalSourceFacts), source_attestation=attestation,
            figure_plan=plan, output_dir=target, request=request, options={})
    assert not target.exists()


@pytest.mark.parametrize("rule", ("compression_curve", "flexural_curve"))
def test_curated_representative_facts_do_not_invent_individual_curves(tmp_path: Path, rule: str) -> None:
    import pandas as pd

    source = tmp_path / "workbooks"
    source.mkdir()
    stress = "Compressive stress" if rule == "compression_curve" else "Flexural stress"
    with pd.ExcelWriter(source / "specimens.xlsx") as writer:
        pd.DataFrame([["Strain", stress], ["%", "MPa"], ["Foam", "Foam"],
                      [0., 0.], [1., 2.], [2., 3.]]).to_excel(
            writer, sheet_name="Representative_Curve", header=False, index=False)
        pd.DataFrame([["repeat 1", 2.], ["repeat 2", 4.], ["repeat 3", 6.]],
                     columns=["Specimen", "Strength (MPa)"]).to_excel(
            writer, sheet_name="All_Specimens", index=False)
        pd.DataFrame([["label", "Foam"]]).to_excel(
            writer, sheet_name="DataStudio_Metadata", header=False, index=False)
    request = {"rule_id": rule}
    resolved, plan = _resolve(source, request)
    facts = resolved.require_domain(MechanicalSourceFacts)
    assert facts.individual_curves_complete is False
    assert facts.replicate_counts == (("Foam", 3),)
    assert len(facts.representative_curve_series) == 1
    prepared = _prepare(source, tmp_path / "prepared", request, resolved)
    records = build_mechanical_task_sources(Path(prepared["source"]), raw_source=source,
        facts=facts, source_attestation=prepared["source_attestation"], figure_plan=plan,
        output_dir=tmp_path / "tasks", request=request, options={})
    assert records[1].groups[0].values == (2., 4., 6.)
    with pytest.raises(ValueError, match="not every specimen curve"):
        _prepare(source, tmp_path / "rejected", {**request, "replicate_mode": "individual"}, resolved)
    assert not any(p.is_file() for p in (tmp_path / "rejected").rglob("*"))


def test_mechanical_callback_source_drift_rejects_before_renderer_and_rolls_back(tmp_path: Path) -> None:
    source = mechanical_source(tmp_path / "raw", "compression_curve")
    request = {"rule_id": "compression_curve"}
    resolved, plan = _resolve(source, request)
    prepared = _prepare(source, tmp_path / "prepared", request, resolved)
    output = tmp_path / "output"
    figures = output / "figures"
    figures.mkdir(parents=True)
    sentinel = figures / "previous.txt"
    sentinel.write_bytes(b"prior complete figure set")

    def builder(*args, **kwargs):
        records = build_mechanical_task_sources(*args, **kwargs)
        source.write_bytes(source.read_bytes().replace(b"10.0", b"90.0"))
        return records

    with pytest.raises(ValueError, match="changed"):
        _render_veusz_mechanical_bundle(Path(prepared["source"]),
            resolved_scientific_source=resolved, source_input=source,
            source_attestation=prepared["source_attestation"], output_dir=output,
            options={}, export_formats=("pdf", "tiff_300"), request=request,
            _resolved_figure_plan=plan, _source_builder=builder,
            _renderer=lambda *_a, **_k: pytest.fail("drift reached renderer"))
    assert sentinel.read_bytes() == b"prior complete figure set"
    assert not list(output.glob(".sciplot-mechanical-stage-*"))
    assert not any((output / "processed").rglob("*.csv"))


def test_studio_missing_mechanical_envelope_is_not_a_reparse_fallback(tmp_path: Path) -> None:
    source = mechanical_source(tmp_path / "raw", "compression_curve")
    request = {"rule_id": "compression_curve"}
    resolved, plan = _resolve(source, request)
    prepared = _prepare(source, tmp_path / "prepared", request, resolved)
    with pytest.raises(ValueError, match="resolved scientific source"):
        bind_mechanical_task_sources(figure_queue_from_plan(plan, plan.rule_id),
            figure_plan=plan, source_attestation=prepared["source_attestation"],
            project_dir=tmp_path, request=request, resolved_scientific_source=None)
    assert not (tmp_path / "studio").exists()


def test_public_studio_generation_carries_facts_to_the_native_audit_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sciplot_core.studio import prepare_studio_document
    from sciplot_core.project_store import FileProjectStore
    from sciplot_core.studio_core import preparation_commands, veusz_document

    source = mechanical_source(tmp_path / "raw", "compression_curve")
    original = source.read_bytes()
    project = tmp_path / "project"
    project.mkdir()
    request = project / "plot_request.json"
    request.write_text(json.dumps({"input": str(source), "rule_id": "compression_curve",
        "template": "curve", "replicate_mode": "individual"}))
    request_before = request.read_bytes()
    store = FileProjectStore(project)
    before = store.snapshot(import_legacy=True)
    reads, specs = [], []
    read = mechanical_facts._read_source

    def counted(*args, **kwargs):
        result = read(*args, **kwargs)
        reads.append(result)
        return result

    def save(path, spec, *, spec_path=None):
        # Stop before real native save/audit. Source/plan/spec and private
        # transaction code is real, and no Store publication may occur.
        specs.append(spec)
        path.write_text("# generated test double; not a Veusz document\n")

    class AuditBoundary(Exception):
        pass

    audited = []

    def audit(candidate, payload):
        audited.append(payload)
        assert candidate.project_dir != project
        assert len(reads) == 1
        raise AuditBoundary("real native audit belongs to the integrated gate")

    monkeypatch.setattr(mechanical_facts, "_read_source", counted)
    monkeypatch.setattr(veusz_document, "_save_veusz_document_from_spec", save)
    monkeypatch.setattr(preparation_commands, "audit_studio_candidate", audit)
    with pytest.raises(AuditBoundary, match="real native audit"):
        prepare_studio_document(request)
    assert len(reads) == 1
    assert len(audited) == 1
    assert {spec["template"] for spec in specs} == {"curve", "box_strip"}
    assert audited[0]["figure_set"]["resolved_figure_plan"]["rule_id"] == "compression_curve"
    assert len(audited[0]["figure_set"]["resolved_figure_plan"]["tasks"]) == 2
    assert store.snapshot() == before
    assert request.read_bytes() == request_before
    assert source.read_bytes() == original
