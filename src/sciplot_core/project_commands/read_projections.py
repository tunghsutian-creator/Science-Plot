"""Fixed, pure business read projections for shared project commands.

These values are read-set witnesses, never another project state. The repository
checks them against its immutable generation and verified current file at both
reservation and publication. Whole-set commands still bind the complete resource.
"""

from __future__ import annotations

from copy import deepcopy
import json
from typing import Any

from sciplot_core.foundation.json_hashing import canonical_json_sha256


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("A projected read cannot contain duplicate JSON fields")
        result[key] = value
    return result


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"A projected read requires {label}")
    return value


def _selected(values: Any, key: str, *, field: str, label: str) -> dict[str, Any]:
    if not isinstance(values, list) or not values:
        raise ValueError(f"A projected read requires a nonempty {label} list")
    identifiers: set[str] = set()
    selected: dict[str, Any] | None = None
    for value in values:
        if not isinstance(value, dict):
            raise ValueError(f"A projected read contains a malformed {label} entry")
        identifier = _text(value.get(field), f"{label} identity")
        if identifier in identifiers:
            raise ValueError(f"A projected read contains duplicate {label} identities")
        identifiers.add(identifier)
        if identifier == key:
            selected = value
    if selected is None:
        raise ValueError(f"The selected {label} is absent from its registered membership")
    return selected


def _studio_figure(value: dict[str, Any], key: str) -> dict[str, Any]:
    if value.get("kind") != "sciplot_studio_figure_set" or type(value.get("version")) is not int or value["version"] not in {1, 2}:
        raise ValueError("The Studio figure projection requires a supported figure-set registry")
    primary = _text(value.get("primary_figure_id"), "the primary figure identity")
    selected = _selected(value.get("figures"), key, field="figure_id", label="figure")
    if selected.get("status") not in {"ready", "unavailable"}:
        raise ValueError("The selected Studio figure has an unsupported status")
    if value["version"] == 2:
        for field in ("document", "spec"):
            _text(selected.get(field), f"the selected figure {field} path")
        if not isinstance(selected.get("resolved_figure_task"), dict):
            raise ValueError("The selected v2 Studio figure is missing its scientific task")
    # Native publication refreshes these two fields from the already saved VSZ.
    # Generated hashes, task/metric/source facts, unknown selected fields and path
    # bindings remain reads. Other figures and aggregate readiness are not reads.
    entry = {name: item for name, item in selected.items()
             if name not in {"document_state", "document_authority"}}
    root = {name: item for name, item in value.items()
            if name not in {"figures", "resolved_figure_plan", "status", "created_at", "updated_at"}}
    root["primary_figure_id"] = primary
    result: dict[str, Any] = {"registry": root, "figure": entry}
    plan = value.get("resolved_figure_plan")
    if plan is not None:
        if not isinstance(plan, dict):
            raise ValueError("The Studio figure plan is malformed")
        task = _selected(plan.get("tasks"), key, field="figure_id", label="scientific task")
        result["plan"] = {name: item for name, item in plan.items()
                          if name not in {"tasks", "outcomes", "status", "complete"}}
        result["task"] = task
        if "outcomes" in plan:
            outcome = _selected(plan["outcomes"], key, field="figure_id", label="figure outcome")
            result["outcome"] = {name: item for name, item in outcome.items() if name != "artifacts"}
    elif value["version"] == 2:
        raise ValueError("The v2 Studio figure registry is missing its scientific plan")
    return result


def _decode(data: bytes) -> dict[str, Any]:
    try:
        value = json.loads(data, object_pairs_hook=_object,
                           parse_constant=lambda _value: (_ for _ in ()).throw(ValueError("Nonfinite projected JSON")))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("The projected resource is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("A projected resource must be a JSON object")
    return value


def projection_digest(data: bytes, *, kind: str, key: str) -> str:
    """Hash one admitted domain projection; arbitrary selectors are unsupported."""
    _text(key, "a projection key")
    if kind not in {"studio_figure_v1", "native_suite_figure_v1"}:
        raise ValueError("Unsupported project read projection kind")
    value = _decode(data)
    if kind == "studio_figure_v1":
        selected = _studio_figure(value, key)
    else:
        from sciplot_core.project_commands.native_suite_projections import native_suite_figure

        selected = native_suite_figure(value, key)
    return canonical_json_sha256({"kind": kind, "key": key, "value": selected}, allow_nan=False)


def merge_projection(current: bytes, candidate: bytes, *, kind: str, key: str) -> bytes:
    """Merge a fixed selected publication, retaining current unrelated members.

    Whole-set/source/scientific changes use ordinary whole-resource CAS, never
    this selected-publication path. No caller-supplied pointer or callback runs.
    """
    if kind == "native_suite_figure_v1":
        from sciplot_core.project_commands.native_suite_projections import merge_native_suite_figure

        merged = merge_native_suite_figure(_decode(current), _decode(candidate), key)
        return json.dumps(merged, sort_keys=True, ensure_ascii=False, allow_nan=False).encode("utf-8")
    if kind != "studio_figure_v1":
        raise ValueError("Unsupported project write projection kind")
    if projection_digest(current, kind=kind, key=key) != projection_digest(candidate, kind=kind, key=key):
        raise ValueError("A selected Studio publication cannot change scientific, membership or path bindings")
    result, proposed = deepcopy(_decode(current)), _decode(candidate)
    selected = _selected(result["figures"], key, field="figure_id", label="figure")
    proposed_entry = _selected(proposed["figures"], key, field="figure_id", label="figure")
    for name in ("document_state", "document_authority"):
        if name in proposed_entry:
            selected[name] = proposed_entry[name]
        else:
            selected.pop(name, None)
    plan, proposed_plan = result.get("resolved_figure_plan"), proposed.get("resolved_figure_plan")
    if isinstance(plan, dict) and isinstance(proposed_plan, dict) and "outcomes" in proposed_plan:
        outcome = _selected(plan["outcomes"], key, field="figure_id", label="figure outcome")
        proposed_outcome = _selected(proposed_plan["outcomes"], key, field="figure_id", label="figure outcome")
        if "artifacts" in proposed_outcome:
            outcome["artifacts"] = proposed_outcome["artifacts"]
        else:
            outcome.pop("artifacts", None)
    return json.dumps(result, sort_keys=True, ensure_ascii=False, allow_nan=False).encode("utf-8")
