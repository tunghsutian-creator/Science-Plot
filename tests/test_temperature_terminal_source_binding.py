from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from sciplot_core.render import render_to_dir
from sciplot_core.terminal_request import authoritative_terminal_render_request
from sciplot_core.terminal_source_binding import (
    MaterializedTerminalSourceBinding,
    SealedTerminalSourceBinding,
    TerminalSourceBindingError,
)
from sciplot_core.terminal_source_binding_wire import (
    TERMINAL_SOURCE_BINDING_ENV,
    consume_terminal_source_binding_environment,
    sealed_terminal_source_binding_from_payload,
)


RULE_ID = "rheology_temperature_sweep"
TEMPLATE = "point_line"
EXPECTED_SAMPLE_ORDER = ("PA-2", "D-PA", "SD-PA", "S-PA")


def _write_materialized_temperature_source(path: Path) -> dict[str, list[float]]:
    headers: list[object] = []
    samples: list[object] = []
    units: list[object] = []
    rows: list[list[object]] = []
    expected: dict[str, list[float]] = {}
    for sample_index, sample in enumerate(EXPECTED_SAMPLE_ORDER, start=1):
        headers.extend(["Temperature", "Loss Factor"])
        samples.extend([sample, sample])
        units.extend(["°C", "1"])
        x_values = [150.0, 175.0, 200.0]
        y_values = [
            round(sample_index / 10.0 + offset, 2) for offset in (0.0, 0.01, 0.02)
        ]
        expected[sample] = y_values
        while len(rows) < len(x_values):
            rows.append([])
        for row, x_value, y_value in zip(
            rows,
            x_values,
            y_values,
            strict=True,
        ):
            row.extend([x_value, y_value])
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([headers, samples, units, *rows]).to_csv(
        path,
        header=False,
        index=False,
    )
    return expected


def _binding_fixture(
    tmp_path: Path,
) -> tuple[MaterializedTerminalSourceBinding, Path, dict[str, list[float]]]:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    raw_sources: list[Path] = []
    for sample in EXPECTED_SAMPLE_ORDER:
        raw = raw_dir / f"{sample}.csv"
        raw.write_text(f"raw source for {sample}\n", encoding="utf-8")
        raw_sources.append(raw)
    prepared_source = tmp_path / "prepared" / "temperature_comparison.xlsx"
    prepared_source.parent.mkdir()
    prepared_source.write_bytes(b"prepared temperature comparison authority\n")
    terminal_source = tmp_path / "materialized" / "temp_loss_factor.csv"
    expected = _write_materialized_temperature_source(terminal_source)
    binding = MaterializedTerminalSourceBinding.create(
        task_key="tan_delta_vs_temperature",
        rule_id=RULE_ID,
        template=TEMPLATE,
        x_metric="temperature",
        y_metric="loss_factor",
        raw_sources=raw_sources,
        prepared_source=prepared_source,
        terminal_source=terminal_source,
        sample_order=EXPECTED_SAMPLE_ORDER,
        point_counts={sample: 3 for sample in EXPECTED_SAMPLE_ORDER},
    )
    return binding, terminal_source, expected


def _request_context(*, y_metric: str = "loss_factor") -> dict[str, Any]:
    return {
        "rule_id": RULE_ID,
        "template": TEMPLATE,
        "x_metric": "temperature",
        "y_metric": y_metric,
    }


def _sealed_binding_fixture(
    tmp_path: Path,
) -> tuple[SealedTerminalSourceBinding, Path, dict[str, Any]]:
    binding, source, _expected = _binding_fixture(tmp_path)
    request = {
        **_request_context(),
        "input": str(source.resolve()),
        "series_order": list(EXPECTED_SAMPLE_ORDER),
        "render_options": {
            "x_metric": "temperature",
            "y_metric": "loss_factor",
        },
    }
    request_path = tmp_path / "terminal_request.json"
    request_path.write_text(json.dumps(request), encoding="utf-8")
    return binding.seal(request_path, request), request_path, request


def _worker_request_for_spec(spec_path: Path) -> dict[str, Any]:
    request_path = spec_path.parent.parent / "plot_request.json"
    payload = json.loads(request_path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _assert_no_published_artifacts(output_dir: Path) -> None:
    assert not any(
        path.is_file() and path.suffix.casefold() in {".pdf", ".png", ".tiff", ".vsz"}
        for path in output_dir.rglob("*")
    )


@pytest.mark.parametrize(
    ("reserved_key", "reserved_value"),
    [
        ("_terminal_source_prepared", True),
        ("_terminal_source_binding", {"claimed": "public-json"}),
    ],
)
def test_public_request_cannot_claim_prepared_terminal_source(
    reserved_key: str,
    reserved_value: object,
) -> None:
    with pytest.raises(ValueError, match="reserved"):
        authoritative_terminal_render_request(
            {
                "template": TEMPLATE,
                reserved_key: reserved_value,
            }
        )


@pytest.mark.parametrize(
    "mutation", ["missing", "extra", "non_string_sample", "bool_version"]
)
def test_sealed_binding_payload_rejects_noncanonical_shape(
    tmp_path: Path,
    mutation: str,
) -> None:
    sealed, _request_path, _request = _sealed_binding_fixture(tmp_path)
    payload = sealed.to_payload()
    if mutation == "missing":
        payload.pop("task_key")
    elif mutation == "extra":
        payload["public_override"] = True
    elif mutation == "non_string_sample":
        payload["sample_order"][0] = 1
    else:
        payload["version"] = True

    with pytest.raises(TerminalSourceBindingError) as exc_info:
        sealed_terminal_source_binding_from_payload(payload)

    assert exc_info.value.reason_code == "terminal_source_binding_contract_mismatch"


def test_terminal_source_binding_environment_is_consumed_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sealed, request_path, request = _sealed_binding_fixture(tmp_path)
    monkeypatch.setenv(TERMINAL_SOURCE_BINDING_ENV, sealed.to_environment_value())

    assert consume_terminal_source_binding_environment(request_path) == sealed
    assert consume_terminal_source_binding_environment(request_path) is None


def test_binding_seal_rejects_dataclass_field_tamper(tmp_path: Path) -> None:
    binding, source, _expected = _binding_fixture(tmp_path)
    output = tmp_path / "out"

    with pytest.raises(TerminalSourceBindingError) as exc_info:
        tampered = replace(binding, y_metric="storage_modulus")
        render_to_dir(
            source,
            template=TEMPLATE,
            output_dir=output,
            options={"x_metric": "temperature", "y_metric": "loss_factor"},
            export_formats=("pdf",),
            request_context=_request_context(),
            _terminal_source_binding=tampered,
        )

    assert exc_info.value.reason_code == "terminal_source_binding_request_mismatch"
    _assert_no_published_artifacts(output)


def test_binding_rejects_terminal_source_byte_change(tmp_path: Path) -> None:
    binding, source, _expected = _binding_fixture(tmp_path)
    source.write_bytes(source.read_bytes() + b"\nsource drift")
    output = tmp_path / "out"

    with pytest.raises(TerminalSourceBindingError) as exc_info:
        render_to_dir(
            source,
            template=TEMPLATE,
            output_dir=output,
            options={"x_metric": "temperature", "y_metric": "loss_factor"},
            export_formats=("pdf",),
            request_context=_request_context(),
            _terminal_source_binding=binding,
        )

    assert exc_info.value.reason_code == "terminal_source_binding_source_changed"
    _assert_no_published_artifacts(output)


def test_binding_rejects_request_metric_mismatch(tmp_path: Path) -> None:
    binding, source, _expected = _binding_fixture(tmp_path)
    output = tmp_path / "out"

    with pytest.raises(TerminalSourceBindingError) as exc_info:
        render_to_dir(
            source,
            template=TEMPLATE,
            output_dir=output,
            options={"x_metric": "temperature", "y_metric": "storage_modulus"},
            export_formats=("pdf",),
            request_context=_request_context(y_metric="storage_modulus"),
            _terminal_source_binding=binding,
        )

    assert exc_info.value.reason_code == "terminal_source_binding_request_mismatch"
    _assert_no_published_artifacts(output)


def test_binding_accepts_existing_mechanical_canonical_metric_case(
    tmp_path: Path,
) -> None:
    binding, _source, _expected = _binding_fixture(tmp_path)

    mechanical = replace(
        binding,
        x_metric="sample",
        y_metric="strength_MPa",
    )

    assert mechanical.x_metric == "sample"
    assert mechanical.y_metric == "strength_MPa"


@pytest.mark.parametrize(
    "metric",
    ["", "Strength_MPa", "strength MPa", "strength-MPa"],
)
def test_binding_still_rejects_noncanonical_metric_tokens(
    tmp_path: Path,
    metric: str,
) -> None:
    binding, _source, _expected = _binding_fixture(tmp_path)

    with pytest.raises(TerminalSourceBindingError) as exc_info:
        replace(binding, y_metric=metric)

    assert exc_info.value.reason_code == "terminal_source_binding_contract_mismatch"


def test_binding_does_not_relax_rule_task_or_template_identity(tmp_path: Path) -> None:
    binding, _source, _expected = _binding_fixture(tmp_path)

    with pytest.raises(TerminalSourceBindingError) as exc_info:
        replace(binding, rule_id="Tensile_curve")

    assert exc_info.value.reason_code == "terminal_source_binding_contract_mismatch"


@pytest.mark.comprehensive
def test_bound_terminal_source_is_read_directly_without_second_semantic_prepare(
    tmp_path: Path,
) -> None:
    binding, source, expected = _binding_fixture(tmp_path)

    result = render_to_dir(
        source,
        template=TEMPLATE,
        output_dir=tmp_path / "bound",
        options={"x_metric": "temperature", "y_metric": "loss_factor"},
        export_formats=("pdf",),
        request_context=_request_context(),
        _terminal_source_binding=binding,
    )

    assert len(result["veusz_specs"]) == 1
    spec_path = Path(result["veusz_specs"][0])
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    assert [series["label"] for series in spec["series"]] == list(EXPECTED_SAMPLE_ORDER)
    assert all(len(series["x_values"]) == 3 for series in spec["series"])
    assert [series["y_values"] for series in spec["series"]] == [
        expected[sample] for sample in EXPECTED_SAMPLE_ORDER
    ]
    assert all(
        {Path(artifact["path"]).resolve() for artifact in series["source_artifacts"]}
        == {source.resolve()}
        for series in spec["series"]
    )
    terminal_request = result["terminal_render_requests"][0]
    assert terminal_request["x_metric"] == "temperature"
    assert terminal_request["y_metric"] == "loss_factor"
    assert "resolved_figure_task" not in terminal_request
    worker_request = _worker_request_for_spec(spec_path)
    assert not any(
        step.get("implementation_ref")
        == "sciplot_core.semantic.prepare_semantic_source"
        for step in worker_request.get("transform_ledger", {}).get("steps", [])
        if isinstance(step, dict)
    )
    assert not list(
        spec_path.parent.glob("processed/rheology_temperature_comparison.*")
    )


@pytest.mark.comprehensive
def test_unbound_metric_table_does_not_enter_trusted_direct_read_path(
    tmp_path: Path,
) -> None:
    _binding, source, _expected = _binding_fixture(tmp_path)

    result = render_to_dir(
        source,
        template=TEMPLATE,
        output_dir=tmp_path / "unbound",
        options={"x_metric": "temperature", "y_metric": "loss_factor"},
        export_formats=("pdf",),
        request_context=_request_context(),
    )

    spec_path = Path(result["veusz_specs"][0])
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    assert [series["label"] for series in spec["series"]] != list(EXPECTED_SAMPLE_ORDER)
    assert any(
        Path(artifact["path"]).resolve() != source.resolve()
        for series in spec["series"]
        for artifact in series["source_artifacts"]
    )
    worker_request = _worker_request_for_spec(spec_path)
    assert any(
        step.get("implementation_ref")
        == "sciplot_core.semantic.prepare_semantic_source"
        for step in worker_request.get("transform_ledger", {}).get("steps", [])
        if isinstance(step, dict)
    )
