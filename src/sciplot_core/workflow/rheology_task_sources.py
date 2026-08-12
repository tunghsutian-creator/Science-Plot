"""Materialize source-bound terminal tables for rheology sweep figures."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from sciplot_core.figure_plan.plan import (
    ResolvedFigurePlan,
    resolved_figure_plan_from_payload,
)
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.preparation_source_attestation import PreparationSourceAttestation
from sciplot_core.policy import (
    RHEOLOGY_METRIC_AXIS_LABELS,
    anchored_log_decade_ticks,
)
from sciplot_core.terminal_source_binding import MaterializedTerminalSourceBinding
from sciplot_core.workflow.bundle_exports import _metric_token
from sciplot_core.workflow.rheology_task_plan import (
    TEMPERATURE_METRICS,
    TEMPERATURE_RULE_ID,
    TEMPERATURE_TASK_KEYS,
    selected_frequency_metric_keys,
    sweep_prefix_for_request,
    temperature_plan_metric_keys,
)


RHEOLOGY_METRIC_LABELS = {
    "storage_modulus": "Storage Modulus",
    "loss_modulus": "Loss Modulus",
    "loss_factor": "Loss Factor",
    "tan_delta": "Loss Factor",
    "complex_modulus": "Complex Modulus",
    "complex_viscosity": "Complex Viscosity",
}


@dataclass(frozen=True, slots=True)
class RheologyTaskSource:
    """One adapter-owned metric table and its private terminal attestation."""

    metric_id: str
    source: Path
    render_options: dict[str, Any]
    binding: MaterializedTerminalSourceBinding | None


def build_rheology_task_sources(
    source: Path,
    *,
    request: dict[str, Any],
    output_dir: Path,
    raw_source: Path | None = None,
    source_attestation: PreparationSourceAttestation | None = None,
    _resolved_figure_plan: ResolvedFigurePlan | None = None,
) -> list[RheologyTaskSource]:
    """Build ordered metric tables from one prepared comparison workbook."""

    prepared_source = source.expanduser().resolve()
    prefix = sweep_prefix_for_request(request)
    rule_id = str(request.get("rule_id") or "").strip()
    if prefix is None or prepared_source.suffix.casefold() not in {".xlsx", ".xls"}:
        return []

    figure_plan = _resolved_figure_plan
    if figure_plan is None and request.get("resolved_figure_plan") is not None:
        figure_plan = resolved_figure_plan_from_payload(
            request["resolved_figure_plan"]
        )
    if prefix == "temp" and figure_plan is None:
        raise ValueError(
            "temperature_figure_plan_required: temperature task sources require "
            "one exact resolved FigurePlan."
        )

    template = str(request.get("template") or "point_line").strip()
    if rule_id == TEMPERATURE_RULE_ID and template != "point_line":
        raise ValueError(
            "temperature_terminal_source_binding_mismatch: rheology temperature "
            "task sources require the point_line template."
        )

    if prefix == "temp" and (
        raw_source is None
        or not isinstance(source_attestation, PreparationSourceAttestation)
    ):
        raise ValueError(
            "temperature_terminal_source_binding_mismatch: the prepare-time "
            "source attestation is required and cannot be rediscovered downstream."
        )
    if prefix == "temp":
        assert raw_source is not None and source_attestation is not None
        if source_attestation.rule_id != TEMPERATURE_RULE_ID:
            raise ValueError(
                "temperature_terminal_source_binding_mismatch: prepare-time "
                "source attestation belongs to another rule."
            )
        source_attestation.verify_current(
            source_root=raw_source,
            prepared_source=prepared_source,
        )
        assert figure_plan is not None
        metric_keys = temperature_plan_metric_keys(
            figure_plan,
            source_attestation=source_attestation,
        )
        raw_sources = tuple(
            Path(item.path) for item in source_attestation.selected_sources
        )
    else:
        if source_attestation is not None:
            raise ValueError(
                "rheology_private_terminal_binding_scope_mismatch: preparation "
                "source attestation is temperature-only."
            )
        raw_sources = ()
    prepared_hash_before = file_sha256(prepared_source)

    frame = pd.read_excel(prepared_source, sheet_name=0, header=None)
    if frame.shape[0] < 4:
        if rule_id == TEMPERATURE_RULE_ID:
            raise ValueError(
                "temperature_metric_source_unavailable: the prepared comparison "
                "workbook has no plottable data rows."
            )
        return []

    headers = [_cell_text(item) for item in frame.iloc[0].tolist()]
    samples = [_cell_text(item) for item in frame.iloc[1].tolist()]
    units = [_cell_text(item) for item in frame.iloc[2].tolist()]
    x_tokens = (
        {"temperature"} if prefix == "temp" else {"angularfrequency", "frequency"}
    )
    x_columns = [
        index for index, label in enumerate(headers) if _metric_token(label) in x_tokens
    ]
    if not x_columns:
        if rule_id == TEMPERATURE_RULE_ID:
            raise ValueError(
                "temperature_metric_source_unavailable: the prepared comparison "
                "workbook has no temperature columns."
            )
        return []

    available_metrics = [
        key
        for key, label in RHEOLOGY_METRIC_LABELS.items()
        if key != "tan_delta"
        and any(_metric_token(header) == _metric_token(label) for header in headers)
    ]
    if prefix != "temp":
        metric_keys = selected_frequency_metric_keys(
            available_metrics,
            request=request,
            _resolved_figure_plan=figure_plan,
        )
    metric_keys = [metric for metric in metric_keys if metric in available_metrics]
    if prefix == "temp" and tuple(metric_keys) != TEMPERATURE_METRICS:
        missing = [
            metric for metric in TEMPERATURE_METRICS if metric not in metric_keys
        ]
        raise ValueError(
            "temperature_metric_source_unavailable: the prepared comparison "
            f"workbook is missing required metrics: {missing}."
        )

    sources_dir = output_dir / "processed" / "veusz_metric_sources"
    sources_dir.mkdir(parents=True, exist_ok=True)
    records: list[RheologyTaskSource] = []
    temperature_sample_order: tuple[str, ...] | None = None
    for metric_key in metric_keys:
        table, sample_order, point_counts = _metric_table(
            frame,
            headers=headers,
            samples=samples,
            units=units,
            x_columns=x_columns,
            metric_key=metric_key,
            strict=(prefix == "temp"),
        )
        if table is None:
            continue
        if prefix == "temp":
            if temperature_sample_order is None:
                temperature_sample_order = sample_order
            elif temperature_sample_order != sample_order:
                raise ValueError(
                    "temperature_terminal_source_binding_mismatch: required "
                    "metric tables do not preserve one sample order."
                )

        metric_id = f"{prefix}_{metric_key}"
        metric_source = sources_dir / f"{metric_id}.csv"
        table.to_csv(metric_source, header=False, index=False)
        render_options = _metric_render_options(
            table,
            prefix=prefix,
            metric_key=metric_key,
        )
        binding = (
            MaterializedTerminalSourceBinding.create(
                task_key=TEMPERATURE_TASK_KEYS[metric_key],
                rule_id=rule_id,
                template=template,
                x_metric="temperature",
                y_metric=metric_key,
                raw_sources=raw_sources,
                prepared_source=prepared_source,
                terminal_source=metric_source,
                sample_order=sample_order,
                point_counts=dict(zip(sample_order, point_counts, strict=True)),
            )
            if prefix == "temp"
            else None
        )
        records.append(
            RheologyTaskSource(
                metric_id=metric_id,
                source=metric_source,
                render_options=render_options,
                binding=binding,
            )
        )

    if prefix == "temp" and tuple(record.metric_id for record in records) != (
        "temp_storage_modulus",
        "temp_loss_factor",
    ):
        raise ValueError(
            "temperature_metric_source_unavailable: both required temperature "
            "metric task sources must be materialized."
        )

    prepared_hash_after = file_sha256(prepared_source)
    if prepared_hash_after != prepared_hash_before:
        raise RuntimeError(
            "rheology_terminal_source_binding_mismatch: the upstream prepared "
            "workbook changed while task sources were materialized."
        )
    if source_attestation is not None:
        source_attestation.verify_current(
            source_root=raw_source,
            prepared_source=prepared_source,
        )
    return records


def _metric_table(
    frame: pd.DataFrame,
    *,
    headers: list[str],
    samples: list[str],
    units: list[str],
    x_columns: list[int],
    metric_key: str,
    strict: bool,
) -> tuple[pd.DataFrame | None, tuple[str, ...], tuple[int, ...]]:
    metric_label = RHEOLOGY_METRIC_LABELS[metric_key]
    metric_token = _metric_token(metric_label)
    columns: list[pd.Series] = []
    output_headers: list[str] = []
    output_units: list[str] = []
    output_samples: list[str] = []
    sample_order: list[str] = []
    point_counts: list[int] = []
    for block_index, x_column in enumerate(x_columns):
        next_x = (
            x_columns[block_index + 1]
            if block_index + 1 < len(x_columns)
            else len(headers)
        )
        y_column = next(
            (
                index
                for index in range(x_column + 1, next_x)
                if _metric_token(headers[index]) == metric_token
            ),
            None,
        )
        if y_column is None:
            if strict:
                raise ValueError(
                    "temperature_metric_source_unavailable: metric "
                    f"`{metric_key}` is missing for prepared sample block "
                    f"{block_index + 1}."
                )
            continue
        x_sample = samples[x_column] if x_column < len(samples) else ""
        y_sample = samples[y_column] if y_column < len(samples) else ""
        sample = x_sample or y_sample
        if not sample or (x_sample and y_sample and x_sample != y_sample):
            raise ValueError(
                "rheology_terminal_source_binding_mismatch: prepared x/y sample "
                f"identity is missing or inconsistent in block {block_index + 1}."
            )
        if sample in sample_order:
            raise ValueError(
                "rheology_terminal_source_binding_mismatch: duplicate prepared "
                f"sample `{sample}` cannot be bound to one terminal table."
            )
        x_values = pd.to_numeric(frame.iloc[3:, x_column], errors="coerce")
        y_values = pd.to_numeric(frame.iloc[3:, y_column], errors="coerce")
        point_count = int((x_values.notna() & y_values.notna()).sum())
        if point_count <= 0:
            raise ValueError(
                "rheology_terminal_source_binding_mismatch: prepared sample "
                f"`{sample}` has no paired `{metric_key}` points."
            )
        columns.extend(
            [
                frame.iloc[3:, x_column].reset_index(drop=True),
                frame.iloc[3:, y_column].reset_index(drop=True),
            ]
        )
        output_headers.extend([headers[x_column], headers[y_column]])
        output_units.extend([units[x_column], units[y_column]])
        output_samples.extend([sample, sample])
        sample_order.append(sample)
        point_counts.append(point_count)
    if not columns:
        return None, (), ()
    metric_frame = pd.concat(columns, axis=1)
    metric_frame.columns = list(range(metric_frame.shape[1]))
    metric_frame = pd.concat(
        [
            pd.DataFrame([output_headers, output_samples, output_units]),
            metric_frame,
        ],
        ignore_index=True,
    )
    return metric_frame, tuple(sample_order), tuple(point_counts)


def _metric_render_options(
    metric_frame: pd.DataFrame,
    *,
    prefix: str,
    metric_key: str,
) -> dict[str, Any]:
    metric_label = RHEOLOGY_METRIC_LABELS[metric_key]
    options: dict[str, Any] = {
        "x_metric": "temperature" if prefix == "temp" else "angular_frequency",
        "y_metric": metric_key,
        "y_label_override": RHEOLOGY_METRIC_AXIS_LABELS.get(metric_key, metric_label),
    }
    plotted_values = pd.to_numeric(
        metric_frame.iloc[3:, 1::2].stack(), errors="coerce"
    ).dropna()
    if prefix == "temp":
        options["yscale"] = "log"
        if metric_key == "loss_factor":
            positive_values = plotted_values[plotted_values > 0]
            spans_two_decades = (
                not positive_values.empty
                and len(positive_values) == len(plotted_values)
                and float(positive_values.max()) / float(positive_values.min()) >= 100.0
            )
            options["yscale"] = "log" if spans_two_decades else "linear"
            if spans_two_decades:
                options["y_ticks"] = list(anchored_log_decade_ticks(positive_values))
    if prefix == "freq" and metric_key == "storage_modulus":
        if not plotted_values.empty and float(plotted_values.max()) <= 5e5:
            options.update(
                {
                    "y_max": 5e5,
                    "y_ticks": [1.0, 10.0, 100.0, 1000.0, 10000.0, 100000.0],
                }
            )
    elif prefix == "freq" and metric_key in {"loss_factor", "complex_viscosity"}:
        options["y_ticks"] = list(anchored_log_decade_ticks(plotted_values))
    return options


def _cell_text(value: object) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip()


__all__ = [
    "RHEOLOGY_METRIC_LABELS",
    "RheologyTaskSource",
    "build_rheology_task_sources",
    "sweep_prefix_for_request",
]
