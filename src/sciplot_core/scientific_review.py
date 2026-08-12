"""Project persisted scientific-transform evidence into one shared review model."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sciplot_core import scientific_review_ledger
from sciplot_core.semantic_sources.scientific_transform import (
    SCIENTIFIC_TRANSFORM_KIND,
    SCIENTIFIC_TRANSFORM_VERSION,
)


SCIENTIFIC_REVIEW_KIND = "sciplot_scientific_transform_review"
SCIENTIFIC_REVIEW_VERSION = 1


def scientific_transform_review_from_ledger(
    ledger: object,
) -> dict[str, Any] | None:
    """Return the latest persisted transform review without reading its source."""

    selected = scientific_review_ledger.scientific_transform_review_input_from_ledger(
        ledger
    )
    if selected is None:
        return None
    payload, ledger_status, step_status = selected
    blocker = scientific_review_ledger.scientific_transform_ledger_blocker(
        ledger_status, step_status
    )
    if blocker is not None:
        blocked_subject, blocked_status = blocker
        return {
            "kind": SCIENTIFIC_REVIEW_KIND,
            "version": SCIENTIFIC_REVIEW_VERSION,
            "status": "blocked",
            "reason_code": "scientific_transform_ledger_unavailable",
            "message": (
                "Persisted scientific-transform evidence is unavailable for review "
                f"because its {blocked_subject} status is {blocked_status!r}."
            ),
            "ledger_status": ledger_status,
            "step_status": step_status,
            "items": [],
        }
    try:
        review = build_scientific_transform_review(payload)
    except (TypeError, ValueError) as exc:
        return {
            "kind": SCIENTIFIC_REVIEW_KIND,
            "version": SCIENTIFIC_REVIEW_VERSION,
            "status": "blocked",
            "reason_code": "scientific_transform_review_invalid",
            "message": str(exc),
            "items": [],
        }
    if ledger_status is not None:
        review["ledger_status"] = ledger_status
    return review


def scientific_transform_payload_from_ledger(
    ledger: object,
) -> dict[str, Any] | None:
    """Find the newest scientific-transform payload in an existing ledger."""

    return scientific_review_ledger.scientific_transform_payload_from_ledger(ledger)


def build_scientific_transform_review(
    payload: Mapping[str, object],
) -> dict[str, Any]:
    """Build a family-neutral human/AI review from one persisted contract."""

    if payload.get("kind") != SCIENTIFIC_TRANSFORM_KIND or payload.get(
        "version"
    ) != SCIENTIFIC_TRANSFORM_VERSION:
        raise ValueError("Unsupported scientific-transform contract kind or version.")
    family = _required_text(payload.get("semantic_family"), "semantic_family")
    output = _mapping(payload.get("output"), "output")
    series = _mapping_list(output.get("series"), "output.series")
    series_order = _text_list(output.get("series_order"))
    if not series_order:
        series_order = [
            sample
            for item in series
            for sample in [_optional_text(item.get("sample"))]
            if sample is not None
        ]

    output_text = _output_text(output)
    column_text = _column_text(payload.get("source_columns"))
    unit_text = _unit_text(payload.get("unit_conversions"))
    coordinate_text = _coordinate_text(payload.get("x_coordinate_policy"))
    normalizer_text = _normalizer_text(payload.get("normalizer"))
    anchor_text, anchor_records = _anchor_review(payload.get("anchor"))
    point_text, point_records = _point_review(series)
    axis_text = _axis_text(payload.get("axis_compatibility"))
    selected_sources = _text_list(payload.get("selected_sources"))

    items = [
        _item("output", "Output", output_text),
        _item("series", "Series", " -> ".join(series_order) or "not declared"),
        _item("columns", "Columns", column_text),
        _item("units", "Units", unit_text),
        _item(
            "transform",
            "Transform",
            "; ".join(value for value in (coordinate_text, normalizer_text) if value),
        ),
        _item("anchors", "Anchors", anchor_text),
        _item("points", "Points", point_text),
        _item("axes", "Axes", axis_text),
        _item(
            "sources",
            "Sources",
            f"{len(selected_sources)} selected source"
            f"{'s' if len(selected_sources) != 1 else ''}",
        ),
    ]
    return {
        "kind": SCIENTIFIC_REVIEW_KIND,
        "version": SCIENTIFIC_REVIEW_VERSION,
        "status": "available",
        "semantic_family": family,
        "series_order": series_order,
        "series_count": len(series_order),
        "selected_source_count": len(selected_sources),
        "items": items,
        "anchors": anchor_records,
        "points": point_records,
    }


def _item(item_id: str, label: str, value: str) -> dict[str, str]:
    return {"id": item_id, "label": label, "value": value or "not declared"}


def _output_text(output: Mapping[str, object]) -> str:
    x_metric = _optional_text(output.get("x_metric")) or "x"
    y_metric = _optional_text(output.get("y_metric")) or "y"
    return (
        f"{x_metric}{_unit_suffix(output.get('x_unit'))} -> "
        f"{y_metric}{_unit_suffix(output.get('y_unit'))}"
    )


def _column_text(value: object) -> str:
    records = _mapping_list(value, "source_columns")
    summaries: list[str] = []
    for record in records:
        sample = _optional_text(record.get("sample")) or "series"
        roles: list[str] = []
        for role_name, role_value in record.items():
            if not isinstance(role_value, Mapping) or "role" not in role_value:
                continue
            role = _optional_text(role_value.get("role")) or str(role_name)
            header = _optional_text(role_value.get("header")) or "unnamed"
            roles.append(f"{role}={header}{_unit_suffix(role_value.get('unit'))}")
        summaries.append(f"{sample}: {', '.join(roles) or 'not declared'}")
    return "; ".join(summaries) or "not declared"


def _unit_text(value: object) -> str:
    conversions = _mapping_list(value, "unit_conversions")
    paths: list[str] = []
    for item in conversions:
        sample = _optional_text(item.get("sample")) or "series"
        role = _optional_text(item.get("role")) or "value"
        units = [
            _optional_text(item.get("source_unit")),
            _optional_text(item.get("canonical_unit")),
            _optional_text(item.get("display_unit")),
        ]
        compact = [unit for index, unit in enumerate(units) if unit and unit not in units[:index]]
        paths.append(f"{sample} {role}: {' -> '.join(compact) or 'not declared'}")
    return "; ".join(paths) or "not declared"


def _coordinate_text(value: object) -> str:
    policy = _mapping(value, "x_coordinate_policy")
    operation = _optional_text(policy.get("operation")) or "not declared"
    metric = _optional_text(policy.get("metric"))
    return f"x={operation}" + (f" ({metric}{_unit_suffix(policy.get('unit'))})" if metric else "")


def _normalizer_text(value: object) -> str:
    normalizer = _mapping(value, "normalizer")
    scope = _optional_text(normalizer.get("scope")) or "none"
    if scope == "none":
        return "normalizer=not applicable"
    operations: list[str] = []
    direct = _optional_text(normalizer.get("operation"))
    if direct and direct != "none":
        operations.append(direct)
    for item in _mapping_list(normalizer.get("series"), "normalizer.series"):
        operation = _optional_text(item.get("operation"))
        if operation and operation not in operations:
            operations.append(operation)
    return "normalizer=" + (", ".join(operations) or scope)


def _anchor_review(value: object) -> tuple[str, list[dict[str, Any]]]:
    anchor = _mapping(value, "anchor")
    scope = _optional_text(anchor.get("scope"))
    if scope == "none":
        return "not applicable", []
    if scope is None:
        return "scope not declared", []
    selections = _mapping_list(anchor.get("selections"), "anchor.selections")
    records: list[dict[str, Any]] = []
    summaries: list[str] = []
    for selection in selections:
        sample = _optional_text(selection.get("sample")) or "series"
        applicable = _optional_bool(
            selection.get("applicable"), f"anchor selection for {sample!r}.applicable"
        )
        retained = _optional_bool(
            selection.get("retained"), f"anchor selection for {sample!r}.retained"
        )
        record: dict[str, Any] = {
            "sample": sample,
            "applicable": applicable,
            "selector": _optional_text(selection.get("selector")),
            "retained": retained,
        }
        if applicable is False:
            summaries.append(f"{sample}: not applicable")
            records.append(record)
            continue
        source_time = selection.get("source_time")
        if source_time is None and applicable is None:
            summaries.append(f"{sample}: applicability not declared")
            records.append(record)
            continue
        if isinstance(source_time, bool) or not isinstance(source_time, int | float):
            raise ValueError(f"Applicable anchor for {sample!r} has no source_time.")
        record["source_time"] = float(source_time)
        record["source_time_unit"] = _optional_text(
            selection.get("source_time_unit")
        )
        response = selection.get("response_value")
        if isinstance(response, int | float):
            record["response_value"] = float(response)
            record["response_unit"] = _optional_text(selection.get("response_unit"))
        states: list[str] = []
        if applicable is None:
            states.append("applicability not declared")
        states.append(
            "retained"
            if retained is True
            else "not retained"
            if retained is False
            else "retention not declared"
        )
        summaries.append(
            f"{sample}: {_number(source_time)}"
            f"{_unit_suffix(selection.get('source_time_unit'))}"
            f" ({'; '.join(states)})"
        )
        records.append(record)
    return "; ".join(summaries) or "not declared", records


def _point_review(
    series: list[Mapping[str, object]],
) -> tuple[str, list[dict[str, Any]]]:
    records: list[dict[str, Any]] = []
    retained_total = 0
    excluded_total = 0
    negative_total = 0
    for item in series:
        sample = _optional_text(item.get("sample")) or "series"
        retained = _nonnegative_int(
            item.get("retained_point_count", item.get("point_count", 0)),
            f"{sample}.retained_point_count",
        )
        excluded = _nonnegative_int(
            item.get("excluded_point_count", 0),
            f"{sample}.excluded_point_count",
        )
        negative = _nonnegative_int(
            item.get("negative_y_count", 0),
            f"{sample}.negative_y_count",
        )
        retained_total += retained
        excluded_total += excluded
        negative_total += negative
        records.append(
            {
                "sample": sample,
                "retained_point_count": retained,
                "excluded_point_count": excluded,
                "negative_y_count": negative,
                "excluded_by_reason": dict(item.get("excluded_by_reason", {}))
                if isinstance(item.get("excluded_by_reason"), Mapping)
                else {},
            }
        )
    summary = f"{retained_total} retained; {excluded_total} excluded"
    if negative_total:
        summary += f"; {negative_total} negative retained"
    return summary, records


def _axis_text(value: object) -> str:
    axes = _mapping(value, "axis_compatibility")
    summaries: list[str] = []
    for axis_name in ("x", "y"):
        axis = axes.get(axis_name)
        if not isinstance(axis, Mapping):
            continue
        scale = _optional_text(axis.get("registered_scale")) or "not declared"
        log_compatible = _optional_bool(
            axis.get("log_compatible"), f"axis.{axis_name}.log_compatible"
        )
        log_state = (
            "log-compatible"
            if log_compatible is True
            else "not log-compatible"
            if log_compatible is False
            else "log compatibility not declared"
        )
        nonpositive = _nonnegative_int(
            axis.get("nonpositive_count", 0), f"axis.{axis_name}.nonpositive_count"
        )
        detail = f", {nonpositive} nonpositive" if nonpositive else ""
        summaries.append(f"{axis_name}={scale}, {log_state}{detail}")
    return "; ".join(summaries) or "not declared"


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"Scientific-transform field {field!r} must be an object.")
    return value


def _mapping_list(value: object, field: str) -> list[Mapping[str, object]]:
    if not isinstance(value, list | tuple):
        raise ValueError(f"Scientific-transform field {field!r} must be a list.")
    if not all(isinstance(item, Mapping) for item in value):
        raise ValueError(f"Scientific-transform field {field!r} has a non-object item.")
    return list(value)


def _text_list(value: object) -> list[str]:
    if not isinstance(value, list | tuple):
        return []
    return [text for item in value for text in [_optional_text(item)] if text]


def _required_text(value: object, field: str) -> str:
    text = _optional_text(value)
    if text is None:
        raise ValueError(f"Scientific-transform field {field!r} must be non-empty.")
    return text


def _optional_text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _optional_bool(value: object, field: str) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    raise ValueError(f"Scientific-transform field {field!r} must be boolean or null.")


def _unit_suffix(value: object) -> str:
    text = _optional_text(value)
    return f" [{text}]" if text else ""


def _nonnegative_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"Scientific-transform count {field!r} must be numeric.")
    result = int(value)
    if result < 0 or result != value:
        raise ValueError(f"Scientific-transform count {field!r} must be a nonnegative integer.")
    return result


def _number(value: object) -> str:
    return f"{float(value):g}"


__all__ = [
    "SCIENTIFIC_REVIEW_KIND",
    "SCIENTIFIC_REVIEW_VERSION",
    "build_scientific_transform_review",
    "scientific_transform_payload_from_ledger",
    "scientific_transform_review_from_ledger",
]
