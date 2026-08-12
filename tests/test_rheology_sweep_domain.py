from __future__ import annotations

from pathlib import Path

import pytest

from sciplot_core.semantic_sources.rheology_sweep_domain import (
    FREQUENCY_RULE_ID,
    ResolvedRheologySweepDomain,
    RheologySweepDomainError,
    RheologySweepSourceFacts,
    resolve_rheology_frequency_domain,
)
from sciplot_core.semantic_sources.rheology_sweep_sources import (
    _read_rheology_frequency_comparison_samples,
)
from sciplot_core.semantic_sources.rheology_temperature_domain import (
    ResolvedRheologyTemperatureDomain,
    RheologyTemperatureDomainError,
    TemperatureSourceFacts,
)


def _write_frequency_source(
    path: Path,
    *,
    include_loss_modulus: bool = False,
    include_complex_modulus: bool = False,
) -> None:
    loss_header = ",Loss Modulus" if include_loss_modulus else ""
    loss_unit = ",Pa" if include_loss_modulus else ""
    first_loss = ",80" if include_loss_modulus else ""
    second_loss = ",70" if include_loss_modulus else ""
    complex_header = ",Complex Modulus" if include_complex_modulus else ""
    complex_unit = ",Pa" if include_complex_modulus else ""
    first_complex = ",128" if include_complex_modulus else ""
    second_complex = ",114" if include_complex_modulus else ""
    path.write_text(
        "Angular Frequency,Storage Modulus"
        f"{loss_header}{complex_header}\n"
        "rad/s,Pa"
        f"{loss_unit}{complex_unit}\n"
        "1,100"
        f"{first_loss}{first_complex}\n"
        "10,90"
        f"{second_loss}{second_complex}\n",
        encoding="utf-8",
    )


def _write_frequency_tsv(path: Path, responses: tuple[str, str]) -> None:
    path.write_text(
        "Angular Frequency\tStorage Modulus\n"
        "rad/s\tPa\n"
        f"1\t{responses[0]}\n"
        f"2\t{responses[1]}\n",
        encoding="utf-8",
    )


def test_frequency_reader_accepts_two_decimal_comma_values(tmp_path: Path) -> None:
    source = tmp_path / "decimal_comma.tsv"
    _write_frequency_tsv(source, ("0,5", "0,75"))

    sample = _read_rheology_frequency_comparison_samples(source)[0]

    assert sample.rows == (
        {"x": 1.0, "storage_modulus": 0.5},
        {"x": 2.0, "storage_modulus": 0.75},
    )


@pytest.mark.parametrize(
    ("responses", "expected"),
    [
        (("1,234.5", "2,345.5"), (1234.5, 2345.5)),
        (("1.234,5", "2.345,5"), (1234.5, 2345.5)),
    ],
)
def test_frequency_reader_uses_last_separator_when_grouping_is_explicit(
    tmp_path: Path,
    responses: tuple[str, str],
    expected: tuple[float, float],
) -> None:
    source = tmp_path / "explicit_grouping.tsv"
    _write_frequency_tsv(source, responses)

    sample = _read_rheology_frequency_comparison_samples(source)[0]

    assert tuple(row["storage_modulus"] for row in sample.rows) == expected


@pytest.mark.parametrize(
    ("responses", "message"),
    [
        (("0,5", "0.75"), "mix point-decimal and comma-decimal"),
        (("12,345", "13"), "ambiguous `12,345`-shaped values"),
    ],
)
def test_frequency_reader_rejects_mixed_or_ambiguous_separators(
    tmp_path: Path,
    responses: tuple[str, str],
    message: str,
) -> None:
    source = tmp_path / "unsupported_separator.tsv"
    _write_frequency_tsv(source, responses)

    with pytest.raises(ValueError, match=message):
        _read_rheology_frequency_comparison_samples(source)


def test_temperature_compatibility_names_share_one_sweep_schema() -> None:
    assert ResolvedRheologyTemperatureDomain is ResolvedRheologySweepDomain
    assert TemperatureSourceFacts is RheologySweepSourceFacts
    assert RheologyTemperatureDomainError is RheologySweepDomainError


def test_frequency_domain_uses_parser_selected_text_sources_only(
    tmp_path: Path,
) -> None:
    source = tmp_path / "frequency"
    source.mkdir()
    first = source / "sample_a.csv"
    second = source / "sample_b.csv"
    _write_frequency_source(first)
    _write_frequency_source(second)
    (source / "derived.xlsx").write_bytes(b"this derived workbook must not be read")

    domain = resolve_rheology_frequency_domain(source, request={})

    assert domain.rule_id == FREQUENCY_RULE_ID
    assert domain.selected_sources == (first.resolve(), second.resolve())
    assert domain.facts.available_metrics == ("storage_modulus",)
    assert all(
        "complex_modulus" not in row
        for sample in domain.prepared_samples
        for row in sample.rows
    )


def test_frequency_domain_declares_only_parser_retained_complex_modulus(
    tmp_path: Path,
) -> None:
    source = tmp_path / "frequency"
    source.mkdir()
    raw = source / "sample.csv"
    _write_frequency_source(raw, include_loss_modulus=True)

    domain = resolve_rheology_frequency_domain(source, request={})

    assert "complex_modulus" in domain.facts.available_metrics
    assert all(
        "complex_modulus" in row
        for sample in domain.prepared_samples
        for row in sample.rows
    )


def test_frequency_domain_preserves_explicit_complex_modulus(
    tmp_path: Path,
) -> None:
    source = tmp_path / "explicit_complex"
    source.mkdir()
    _write_frequency_source(
        source / "sample.csv",
        include_complex_modulus=True,
    )

    domain = resolve_rheology_frequency_domain(source, request={})

    assert "complex_modulus" in domain.facts.available_metrics
    assert tuple(
        row["complex_modulus"] for row in domain.prepared_samples[0].rows
    ) == (128.0, 114.0)


def test_frequency_domain_requires_a_metric_in_every_selected_sample(
    tmp_path: Path,
) -> None:
    source = tmp_path / "mixed_metrics"
    source.mkdir()
    _write_frequency_source(
        source / "sample_a.csv",
        include_complex_modulus=True,
    )
    _write_frequency_source(source / "sample_b.csv")

    domain = resolve_rheology_frequency_domain(source, request={})

    assert domain.facts.available_metrics == ("storage_modulus",)


def test_frequency_domain_uses_confirmed_columns_in_the_same_snapshot(
    tmp_path: Path,
) -> None:
    source = tmp_path / "confirmed_frequency"
    source.mkdir()
    raw = source / "opaque.csv"
    raw.write_text(
        "Opaque independent,Opaque elastic\n"
        "rad/s,Pa\n"
        "1,100\n"
        "10,90\n",
        encoding="utf-8",
    )
    confirmations = [
        {
            "file_name": raw.name,
            "source_path": str(raw),
            "columns": [
                {
                    "index": 0,
                    "name": "Angular Frequency",
                    "confirmed_type": "numeric",
                    "role": "x",
                },
                {
                    "index": 1,
                    "name": "Storage Modulus",
                    "confirmed_type": "numeric",
                    "role": "y",
                },
            ],
        }
    ]

    domain = resolve_rheology_frequency_domain(
        source,
        request={"column_confirmations": confirmations},
    )

    assert domain.selected_sources == (raw.resolve(),)
    assert domain.facts.available_metrics == ("storage_modulus",)
    assert domain.prepared_samples[0].rows == (
        {"x": 1.0, "storage_modulus": 100.0},
        {"x": 10.0, "storage_modulus": 90.0},
    )
