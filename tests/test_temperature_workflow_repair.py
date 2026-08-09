from __future__ import annotations

import json
import shutil
from dataclasses import replace
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

import sciplot_core.workflow.rheology_task_sources as rheology_task_source_module
from sciplot_core._paths import resolve_fixture_path
from sciplot_core.materials_rules import get_rule, semantic_payload_from_rule
from sciplot_core.preparation_source_attestation import (
    PreparationSourceAttestationError,
)
from sciplot_core.figure_plan.temperature_resolution import resolve_temperature_plan
from sciplot_core.figure_plan import request_for_figure_task
from sciplot_core.render import render_to_dir
from sciplot_core.semantic import (
    _read_rheology_temperature_comparison_samples,
    prepare_semantic_source,
)
from sciplot_core.workflow.rheology_bundle import _render_veusz_sweep_bundle
from sciplot_core.workflow.rheology_task_sources import (
    RheologyTaskSource,
    build_rheology_task_sources,
)
from sciplot_core.terminal_request import project_terminal_render_request


RULE_ID = "rheology_temperature_sweep"
TEMPLATE = "point_line"
EXPECTED_SAMPLE_ORDER = ("PA-2", "D-PA", "SD-PA", "S-PA")
EXPECTED_METRICS = (
    ("temp_storage_modulus", "storage_modulus", "storage_modulus_vs_temperature"),
    ("temp_loss_factor", "loss_factor", "tan_delta_vs_temperature"),
)


def _temperature_request(source: Path) -> dict[str, Any]:
    base: dict[str, Any] = {"rule_id": RULE_ID, "template": TEMPLATE}
    plan = resolve_temperature_plan(input_path=source, request=base)
    return {**base, "resolved_figure_plan": plan.to_payload()}


def _real_temperature_fixture() -> Path:
    rule = get_rule(RULE_ID)
    fixture = resolve_fixture_path(str(rule.fixture_path or ""))
    assert fixture.is_dir(), f"ready real fixture is unavailable: {fixture}"
    return fixture


def _prepare_real_temperature_comparison(
    tmp_path: Path,
    *,
    copy_raw_source: bool = False,
) -> tuple[Path, Path, object]:
    fixture = _real_temperature_fixture()
    if copy_raw_source:
        fixture = Path(shutil.copytree(fixture, tmp_path / "mutable_raw"))
    rule = get_rule(RULE_ID)
    prepared = prepare_semantic_source(
        fixture,
        output_dir=tmp_path / "upstream",
        semantic=semantic_payload_from_rule(rule, confidence=1.0),
    )
    prepared_source = Path(str(prepared["processed_source"]))
    source_attestation = prepared.get("source_attestation")
    assert prepared_source.is_file()
    assert source_attestation is not None
    return fixture, prepared_source, source_attestation


def _build_real_temperature_task_sources(
    tmp_path: Path,
) -> tuple[Path, Path, Path, object, list[RheologyTaskSource]]:
    fixture, prepared_source, source_attestation = _prepare_real_temperature_comparison(
        tmp_path
    )
    bundle_root = tmp_path / "bundle"
    records = build_rheology_task_sources(
        prepared_source,
        request=_temperature_request(fixture),
        output_dir=bundle_root,
        raw_source=fixture,
        source_attestation=source_attestation,
    )
    return fixture, prepared_source, bundle_root, source_attestation, records


def _read_spec(result: dict[str, Any]) -> dict[str, Any]:
    specs = result.get("veusz_specs", [])
    assert isinstance(specs, list) and len(specs) == 1
    payload = json.loads(Path(str(specs[0])).read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_real_temperature_task_sources_keep_default_four_sample_contract(
    tmp_path: Path,
) -> None:
    fixture, prepared_source, bundle_root, _source_attestation, records = (
        _build_real_temperature_task_sources(tmp_path)
    )

    prepared_table = pd.read_excel(prepared_source, sheet_name=0, header=None)
    assert prepared_table.shape == (124, 20)
    assert tuple(prepared_table.iloc[1, 0::5].tolist()) == EXPECTED_SAMPLE_ORDER
    assert [record.metric_id for record in records] == [
        metric_id for metric_id, _y_metric, _task_key in EXPECTED_METRICS
    ]

    for record, (metric_id, y_metric, task_key) in zip(
        records,
        EXPECTED_METRICS,
        strict=True,
    ):
        assert record.metric_id == metric_id
        assert record.binding is not None
        assert record.binding.task_key == task_key
        assert record.binding.rule_id == RULE_ID
        assert record.binding.template == TEMPLATE
        assert record.binding.x_metric == "temperature"
        assert record.binding.y_metric == y_metric
        assert tuple(record.binding.sample_order) == EXPECTED_SAMPLE_ORDER
        assert dict(record.binding.point_counts) == {
            sample: 121 for sample in EXPECTED_SAMPLE_ORDER
        }
        assert record.render_options["x_metric"] == "temperature"
        assert record.render_options["y_metric"] == y_metric

        table = pd.read_csv(record.source, header=None)
        assert table.shape == (124, 8)
        assert tuple(table.iloc[1, 0::2].tolist()) == EXPECTED_SAMPLE_ORDER
        assert tuple(table.iloc[1, 1::2].tolist()) == EXPECTED_SAMPLE_ORDER
        for column in range(8):
            numeric = pd.to_numeric(table.iloc[3:, column], errors="coerce")
            assert numeric.notna().sum() == 121

    bound_raw_paths = {
        Path(artifact.path).resolve()
        for record in records
        if record.binding is not None
        for artifact in record.binding.raw_sources
    }
    assert bound_raw_paths == {
        path.resolve() for path in fixture.iterdir() if path.is_file()
    }
    assert not list(bundle_root.rglob("rheology_temperature_comparison.xlsx"))


@pytest.mark.comprehensive
def test_real_temperature_terminal_workers_render_both_bound_metrics_directly(
    tmp_path: Path,
) -> None:
    fixture, _prepared_source, _bundle_root, _source_attestation, records = (
        _build_real_temperature_task_sources(tmp_path)
    )
    source_samples = _read_rheology_temperature_comparison_samples(fixture)
    assert tuple(sample.sample for sample in source_samples) == EXPECTED_SAMPLE_ORDER
    source_by_sample = {sample.sample: sample for sample in source_samples}
    plan = resolve_temperature_plan(
        input_path=fixture,
        request={"rule_id": RULE_ID, "template": TEMPLATE},
    )

    for record, task, (_metric_id, y_metric, _task_key) in zip(
        records,
        plan.tasks,
        EXPECTED_METRICS,
        strict=True,
    ):
        assert record.binding is not None
        result = render_to_dir(
            record.source,
            template=TEMPLATE,
            output_dir=tmp_path / "workers" / record.metric_id,
            options=record.render_options,
            export_formats=("pdf",),
            request_context=request_for_figure_task(
                _temperature_request(fixture),
                task,
            ),
            _terminal_source_binding=record.binding,
        )

        spec = _read_spec(result)
        assert [series["label"] for series in spec["series"]] == list(
            EXPECTED_SAMPLE_ORDER
        )
        for series in spec["series"]:
            source_sample = source_by_sample[series["label"]]
            assert series["x_values"] == [row["x"] for row in source_sample.rows]
            assert series["y_values"] == [row[y_metric] for row in source_sample.rows]
        terminal_requests = result["terminal_render_requests"]
        assert len(terminal_requests) == 1
        assert terminal_requests[0]["x_metric"] == "temperature"
        assert terminal_requests[0]["y_metric"] == y_metric
        assert terminal_requests[0]["resolved_figure_task"] == task.to_payload()
        assert all(
            {
                Path(artifact["path"]).resolve()
                for artifact in series["source_artifacts"]
            }
            == {record.source.resolve()}
            for series in spec["series"]
        )
        worker_root = Path(str(result["veusz_specs"][0])).parent.parent
        assert not list(worker_root.rglob("rheology_temperature_comparison.xlsx"))


@pytest.mark.comprehensive
def test_real_temperature_bundle_publishes_exact_two_metric_workers(
    tmp_path: Path,
) -> None:
    fixture, prepared_source, source_attestation = _prepare_real_temperature_comparison(
        tmp_path
    )
    output_dir = tmp_path / "published_bundle"

    result = _render_veusz_sweep_bundle(
        prepared_source,
        source_input=fixture,
        output_dir=output_dir,
        options={},
        export_formats=("pdf", "tiff"),
        request=_temperature_request(fixture),
        source_attestation=source_attestation,
    )

    assert result is not None
    figures_dir = output_dir / "figures"
    assert sorted(path.name for path in figures_dir.glob("*.pdf")) == [
        "temp_loss_factor.pdf",
        "temp_storage_modulus.pdf",
    ]
    assert sorted(path.name for path in figures_dir.glob("*.tiff")) == [
        "temp_loss_factor_300dpi.tiff",
        "temp_storage_modulus_300dpi.tiff",
    ]
    document_paths = [Path(value) for value in result["veusz_documents"]]
    spec_paths = [Path(value) for value in result["veusz_specs"]]
    assert len(document_paths) == 2
    assert len(spec_paths) == 2
    assert all(path.is_file() and path.suffix == ".vsz" for path in document_paths)
    assert all(path.is_file() and path.name == "spec.json" for path in spec_paths)
    assert all(
        path.is_relative_to(figures_dir) for path in [*document_paths, *spec_paths]
    )

    expected_y_metric = {
        "temp_storage_modulus": "storage_modulus",
        "temp_loss_factor": "loss_factor",
    }
    for spec_path in spec_paths:
        metric_id = next(
            metric for metric in expected_y_metric if metric in spec_path.parts
        )
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        assert spec["source_request"]["x_metric"] == "temperature"
        assert spec["source_request"]["y_metric"] == expected_y_metric[metric_id]
        assert [series["label"] for series in spec["series"]] == list(
            EXPECTED_SAMPLE_ORDER
        )
        assert all(len(series["x_values"]) == 121 for series in spec["series"])
        assert all(len(series["y_values"]) == 121 for series in spec["series"])

    assert [item["y_metric"] for item in result["terminal_render_requests"]] == [
        "storage_modulus",
        "loss_factor",
    ]
    assert [
        item["resolved_figure_task"]["figure_id"]
        for item in result["terminal_render_requests"]
    ] == [
        "storage_modulus_vs_temperature",
        "tan_delta_vs_temperature",
    ]
    assert result["resolved_figure_plan"]["status"] == "ready"
    assert [
        item["status"] for item in result["resolved_figure_plan"]["outcomes"]
    ] == [
        "ready",
        "ready",
    ]
    assert "figure_outcomes" not in result
    assert all(
        item["source"] == item["path"] and Path(item["source"]).is_file()
        for item in result["exports"]
    )
    assert not list(output_dir.rglob("rheology_temperature_comparison.xlsx"))
    assert not list(output_dir.rglob("_temp_*_render"))
    _assert_no_rheology_stage(output_dir)


def test_temperature_bundle_requires_exact_figure_plan_before_materialization(
    tmp_path: Path,
) -> None:
    fixture, prepared_source, source_attestation = _prepare_real_temperature_comparison(
        tmp_path
    )
    source_builder_calls: list[Path] = []

    def source_builder(source: Path, **_kwargs: Any) -> list[RheologyTaskSource]:
        source_builder_calls.append(source)
        return []

    with pytest.raises(ValueError, match="temperature_figure_plan_required"):
        _render_veusz_sweep_bundle(
            prepared_source,
            source_input=fixture,
            output_dir=tmp_path / "planless_bundle",
            options={},
            export_formats=("pdf",),
            request={"rule_id": RULE_ID, "template": TEMPLATE},
            source_attestation=source_attestation,
            _source_builder=source_builder,
        )

    assert source_builder_calls == []


def _fake_temperature_terminal_request(
    binding: object,
    kwargs: dict[str, Any],
) -> dict[str, Any]:
    return project_terminal_render_request(
        template=binding.template,
        render_options=dict(kwargs.get("options") or {}),
        request_context=kwargs.get("request_context"),
    )


def _fake_temperature_pdf_only_payload(
    source: Path,
    **kwargs: Any,
) -> dict[str, Any]:
    binding = kwargs["_terminal_source_binding"]
    render_dir = Path(kwargs["output_dir"])
    render_dir.mkdir(parents=True, exist_ok=True)
    export = render_dir / f"{source.stem}.pdf"
    export.write_bytes(b"synthetic rendered figure")
    return {
        "export_formats": ["pdf"],
        "exports": [{"path": str(export), "format": "pdf"}],
        "outputs": [str(export)],
        "qa_reports": [],
        "veusz_documents": [],
        "veusz_specs": [],
        "terminal_render_requests": [
            _fake_temperature_terminal_request(binding, kwargs)
        ],
    }


def _fake_complete_temperature_render_payload(
    source: Path,
    **kwargs: Any,
) -> dict[str, Any]:
    binding = kwargs["_terminal_source_binding"]
    render_dir = Path(kwargs["output_dir"])
    render_dir.mkdir(parents=True, exist_ok=True)
    export = render_dir / f"{source.stem}.pdf"
    export.write_bytes(b"synthetic rendered figure")

    studio_dir = render_dir / "_veusz" / "single" / "studio"
    studio_dir.mkdir(parents=True, exist_ok=True)
    document = studio_dir / "document.vsz"
    document.write_bytes(b"synthetic editable Veusz document")
    spec_path = studio_dir / "spec.json"
    table = pd.read_csv(source, header=None)
    series: list[dict[str, Any]] = []
    for index, sample in enumerate(binding.sample_order):
        pair = table.iloc[3:, [index * 2, index * 2 + 1]].apply(
            pd.to_numeric,
            errors="coerce",
        )
        pair = pair.dropna()
        series.append(
            {
                "label": sample,
                "x_values": [float(value) for value in pair.iloc[:, 0]],
                "y_values": [float(value) for value in pair.iloc[:, 1]],
                "source_artifacts": [
                    {
                        "path": binding.terminal_source.path,
                        "sha256": binding.terminal_source.sha256,
                    }
                ],
            }
        )
    source_request = _fake_temperature_terminal_request(binding, kwargs)
    spec_path.write_text(
        json.dumps(
            {
                "kind": "sciplot_veusz_spec",
                "template": binding.template,
                "size_mm": [60.0, 55.0],
                "source_request": source_request,
                "series": series,
                "axes": {"x": {}, "y": {}},
                "style": {},
                "legend": {},
                "layout_issues": [],
                "autofixes_applied": [],
            }
        ),
        encoding="utf-8",
    )
    request_path = render_dir / "_veusz" / "single" / "plot_request.json"
    request_path.write_text(
        json.dumps(
            {
                **source_request,
                "input": str(source.resolve()),
                "render_options": {
                    "x_metric": binding.x_metric,
                    "y_metric": binding.y_metric,
                },
                "transform_ledger": {"steps": []},
            }
        ),
        encoding="utf-8",
    )
    qa_report = {
        "kind": "sciplot_veusz_qa_report",
        "engine": "veusz",
        "issues": [],
        "layout_summary": {
            "kind": "sciplot_veusz_layout_summary",
            "render_engine": "veusz",
            "qa_target": "veusz_export",
            "template": binding.template,
            "document": str(document),
            "outputs": [str(export)],
            "series_count": len(series),
        },
    }
    return {
        "export_formats": ["pdf"],
        "exports": [{"path": str(export), "format": "pdf"}],
        "outputs": [str(export)],
        "qa_reports": [qa_report],
        "veusz_documents": [str(document)],
        "veusz_specs": [str(spec_path)],
        "terminal_render_requests": [source_request],
    }


def _assert_no_rheology_stage(output_dir: Path) -> None:
    assert not list(output_dir.glob(".sciplot-rheology-sweep-stage-*"))


def test_temperature_bundle_rejects_source_binding_mismatch_before_renderer(
    tmp_path: Path,
) -> None:
    fixture, prepared_source, _bundle_root, source_attestation, records = (
        _build_real_temperature_task_sources(tmp_path)
    )
    mismatched_source = tmp_path / "mismatched_terminal_source.csv"
    mismatched_source.write_bytes(records[0].source.read_bytes())
    mismatched_records = [replace(records[0], source=mismatched_source), records[1]]
    renderer_calls: list[Path] = []

    def renderer_spy(source: Path, **_kwargs: Any) -> dict[str, Any]:
        renderer_calls.append(source)
        return {}

    output_dir = tmp_path / "mismatch_publish"
    with pytest.raises(ValueError, match="terminal_source_binding_mismatch"):
        _render_veusz_sweep_bundle(
            prepared_source,
            source_input=fixture,
            output_dir=output_dir,
            options={},
            export_formats=("pdf",),
            request=_temperature_request(fixture),
            source_attestation=source_attestation,
            _source_builder=lambda *_args, **_kwargs: mismatched_records,
            _renderer=renderer_spy,
        )

    assert renderer_calls == []
    assert not (output_dir / "figures").exists()
    _assert_no_rheology_stage(output_dir)


def test_temperature_task_sources_consume_preparation_attestation_without_rediscovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture, prepared_source, source_attestation = _prepare_real_temperature_comparison(
        tmp_path, copy_raw_source=True
    )

    def reject_downstream_rediscovery(_source: Path) -> tuple[Path, ...]:
        raise AssertionError("task-source builder rediscovered the raw inventory")

    monkeypatch.setattr(
        rheology_task_source_module,
        "selected_rheology_sweep_source_files",
        reject_downstream_rediscovery,
        raising=False,
    )
    records = build_rheology_task_sources(
        prepared_source,
        request=_temperature_request(fixture),
        output_dir=tmp_path / "attested_sources",
        raw_source=fixture,
        source_attestation=source_attestation,
    )

    assert [record.metric_id for record in records] == [
        "temp_storage_modulus",
        "temp_loss_factor",
    ]


@pytest.mark.parametrize("mutation", ["added", "modified"])
def test_temperature_raw_drift_after_prepare_fails_before_renderer(
    tmp_path: Path,
    mutation: str,
) -> None:
    fixture, prepared_source, source_attestation = _prepare_real_temperature_comparison(
        tmp_path, copy_raw_source=True
    )
    request = _temperature_request(fixture)
    if mutation == "added":
        (fixture / "late_added_invalid.txt").write_text(
            "not a rheology export",
            encoding="utf-8",
        )
    else:
        selected = next(
            path
            for path in sorted(fixture.iterdir())
            if path.is_file() and path.suffix.casefold() in {".csv", ".tsv", ".txt"}
        )
        selected.write_bytes(selected.read_bytes() + b"\nraw source drift")

    with pytest.raises(PreparationSourceAttestationError) as task_error:
        build_rheology_task_sources(
            prepared_source,
            request=request,
            output_dir=tmp_path / "rejected_task_sources",
            raw_source=fixture,
            source_attestation=source_attestation,
        )
    assert task_error.value.reason_code == "semantic_preparation_source_changed"

    renderer_calls: list[Path] = []

    def renderer_spy(source: Path, **_kwargs: Any) -> dict[str, Any]:
        renderer_calls.append(source)
        return {}

    output_dir = tmp_path / "rejected_bundle"
    with pytest.raises(PreparationSourceAttestationError) as bundle_error:
        _render_veusz_sweep_bundle(
            prepared_source,
            source_input=fixture,
            output_dir=output_dir,
            options={},
            export_formats=("pdf",),
            request=request,
            source_attestation=source_attestation,
            _renderer=renderer_spy,
        )
    assert bundle_error.value.reason_code == "semantic_preparation_source_changed"

    assert renderer_calls == []
    assert not (output_dir / "figures").exists()
    _assert_no_rheology_stage(output_dir)


def test_temperature_prepared_workbook_drift_fails_before_task_materialization(
    tmp_path: Path,
) -> None:
    fixture, prepared_source, source_attestation = _prepare_real_temperature_comparison(
        tmp_path, copy_raw_source=True
    )
    request = _temperature_request(fixture)
    prepared_source.write_bytes(prepared_source.read_bytes() + b"prepared drift")

    with pytest.raises(PreparationSourceAttestationError) as exc_info:
        build_rheology_task_sources(
            prepared_source,
            request=request,
            output_dir=tmp_path / "rejected_prepared_source",
            raw_source=fixture,
            source_attestation=source_attestation,
        )

    assert exc_info.value.reason_code == "semantic_preparation_source_changed"
    assert not (tmp_path / "rejected_prepared_source").exists()


def test_frequency_bundle_rejects_injected_private_binding_before_renderer(
    tmp_path: Path,
) -> None:
    fixture, prepared_source, _bundle_root, _source_attestation, records = (
        _build_real_temperature_task_sources(tmp_path)
    )
    injected = replace(records[0], metric_id="freq_storage_modulus")
    renderer_calls: list[Path] = []

    def renderer_spy(source: Path, **_kwargs: Any) -> dict[str, Any]:
        renderer_calls.append(source)
        return {}

    output_dir = tmp_path / "frequency_binding_rejected"
    with pytest.raises(
        ValueError,
        match="rheology_private_terminal_binding_scope_mismatch",
    ):
        _render_veusz_sweep_bundle(
            prepared_source,
            source_input=fixture,
            output_dir=output_dir,
            options={},
            export_formats=("pdf",),
            request={"rule_id": "rheology_frequency_sweep", "template": TEMPLATE},
            _source_builder=lambda *_args, **_kwargs: [injected],
            _renderer=renderer_spy,
        )

    assert renderer_calls == []
    assert not (output_dir / "figures").exists()
    _assert_no_rheology_stage(output_dir)


def test_temperature_bundle_rejects_pdf_only_renderer_payload(
    tmp_path: Path,
) -> None:
    fixture, prepared_source, _bundle_root, source_attestation, records = (
        _build_real_temperature_task_sources(tmp_path)
    )
    renderer_calls: list[Path] = []

    def pdf_only_renderer(source: Path, **kwargs: Any) -> dict[str, Any]:
        renderer_calls.append(source)
        return _fake_temperature_pdf_only_payload(source, **kwargs)

    output_dir = tmp_path / "incomplete_payload_rejected"
    with pytest.raises(
        ValueError,
        match="temperature_terminal_source_binding_mismatch.*Veusz document",
    ):
        _render_veusz_sweep_bundle(
            prepared_source,
            source_input=fixture,
            output_dir=output_dir,
            options={},
            export_formats=("pdf",),
            request=_temperature_request(fixture),
            source_attestation=source_attestation,
            _source_builder=lambda *_args, **_kwargs: records,
            _renderer=pdf_only_renderer,
        )

    assert renderer_calls == [records[0].source]
    assert not (output_dir / "figures").exists()
    _assert_no_rheology_stage(output_dir)


def test_temperature_bundle_second_renderer_failure_publishes_nothing(
    tmp_path: Path,
) -> None:
    fixture, prepared_source, _bundle_root, source_attestation, records = (
        _build_real_temperature_task_sources(tmp_path)
    )
    renderer_calls: list[Path] = []

    def fail_second_renderer(source: Path, **kwargs: Any) -> dict[str, Any]:
        renderer_calls.append(source)
        if len(renderer_calls) == 2:
            raise RuntimeError("synthetic temperature second renderer failure")
        return _fake_complete_temperature_render_payload(source, **kwargs)

    output_dir = tmp_path / "failure_publish"
    with pytest.raises(RuntimeError, match="second renderer failure"):
        _render_veusz_sweep_bundle(
            prepared_source,
            source_input=fixture,
            output_dir=output_dir,
            options={},
            export_formats=("pdf",),
            request=_temperature_request(fixture),
            source_attestation=source_attestation,
            _source_builder=lambda *_args, **_kwargs: records,
            _renderer=fail_second_renderer,
        )

    assert renderer_calls == [record.source for record in records]
    assert not (output_dir / "figures").exists()
    _assert_no_rheology_stage(output_dir)
