"""Closed common presentation intents compose the existing semantic transaction.

Only the request binding is stored here. Revision, review, recovery, scientific
and native audits, export and rollback remain owned by PlotService.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import re
from typing import Any
from uuid import uuid4

from sciplot_core.doctor import doctor_payload
from sciplot_core.plot_document.patch import validate_patch
from sciplot_core.plot_document.schema import closed
from sciplot_core.plot_engine.edit_entry import admit_edit_entry, bind_edit_entry, close_edit_owner, edit_entry_session, read_edit_entry
from sciplot_core.plot_engine.errors import EngineError
from sciplot_core.plot_engine.service import PlotService
from sciplot_core.plot_engine.storage import active, digest, load_head
from sciplot_core.plot_ir.figure_document import figure_spec, is_figure
from sciplot_core.policy.contract_loader import load_plot_contract
from sciplot_core.studio_core.project_query_paths import canonical_path
from sciplot_core.style_values import normalize_physical_size
from sciplot_core.task_series_edits import compile_series_edits

_FIELDS = ("palette", "font_size", "font_family", "legend_font_size", "legend_visible", "legend_position", "legend_columns", "series_labels", "series_visibility")
_FONT_KINDS = ("axis", "legend", "annotation", "text")
_EXAMPLES = ["换配色 tol_bright；统一字号 9pt；图例字号 7pt", "palette jama_editorial; font family Arial", "hide legend"]


def common_edit_capabilities() -> dict[str, Any]:
    """Small, model-free discovery surface; availability follows document authority."""
    return {"kind": "sciplot_common_edit_capabilities", "version": 1,
            "entrypoint": "task edit TARGET --intent TEXT --json", "model_required": False,
            "palettes": {name: list(palette.categorical) for name, palette in load_plot_contract().palettes.items() if palette.public},
            "examples": _EXAMPLES,
            "intent_syntax": "Exact clauses separated by ; or ；. No free-form interpretation or inferred units.",
            "fields": list(_FIELDS),
            "availability": {
                "ManagedPlot_FigureSpec_v2": ["palette", "font_size", "font_family", "legend_font_size", "legend_columns", "series_labels", "series_visibility"],
                "other_represented_documents": ["palette", "font_size", "legend_font_size", "legend_visible", "legend_position", "legend_columns", "series_labels", "series_visibility"]},
            "scope": {"palette": "All ordinary measurement line/point layers, or all advertised ordinary series, in current order; palette never cycles.",
                      "font_size": "v2: theme typography plus all explicit axes, legends, annotations and text marks. Other documents: advertised font.size objects only; native tick typography remains outside shadow coverage.",
                      "font_family": "v2 typography only; an exact installed font family is required.",
                      "legend_font_size": "Every represented legend only; overrides font_size for those legends.",
                      "legend_visible": "Advertised legend.visible only; may require existing preview review.",
                      "legend_position": "Advertised relative legend.position only; explicit x,y from 0 to 1, with existing review.",
                      "legend_columns": "Explicit integer 1–32; preserves the existing legend location and other presentation fields.",
                      "series_labels": "Explicit display aliases by stable semantic ID or unique current/source label; raw identity and data remain intact. CLI: --rename-series SOURCE ALIAS.",
                      "series_visibility": "Explicit show/hide of existing source members only; at least one remains visible. Retains all bound arrays and sources. CLI: --hide-series SOURCE / --show-series SOURCE."},
            "recovery": "For recovery after a lost first reply, supply a stable --task-dir on the first call. Reuse --task-dir with the identical normalized intent. Follow returned engine next_step for review/export/recovery; plot rollback restores the prior revision."}


def common_edit_schema() -> dict[str, Any]:
    """Closed transport arguments for the same CLI entry, with no request file."""
    text = {"type": "string", "minLength": 1, "maxLength": 2048}
    return closed({"target": text, "intent": text,
                   "palette": {"enum": list(common_edit_capabilities()["palettes"])},
                   "font_size": text, "font_family": text, "legend_font_size": text,
                   "legend_visible": {"type": "boolean"},
                   "legend_columns": {"type": "integer", "minimum": 1, "maximum": 32},
                   "series_labels": {"type": "object", "minProperties": 1, "additionalProperties": {"type": "string", "minLength": 1, "maxLength": 500}},
                   "series_visibility": {"type": "object", "minProperties": 1, "additionalProperties": {"type": "boolean"}},
                   "legend_position": {"type": "array", "minItems": 2, "maxItems": 2,
                                       "items": {"type": "number", "minimum": 0, "maximum": 1}},
                   "figure_id": text, "task_dir": text}, ["target"])


def _invalid(message: str, *, code: str = "common_edit_invalid", **details: Any) -> EngineError:
    return EngineError(code, message, action="correct_common_edit", examples=_EXAMPLES,
                       request_executed=False, **details)


def _parse_text(text: str) -> dict[str, Any]:
    if not isinstance(text, str) or not text.strip() or len(text) > 2048:
        raise _invalid("Provide one or more exact common-edit clauses.")
    result: dict[str, Any] = {}
    patterns = (
        ("palette", r"(?:palette|换配色|配色)\s+(.+)"),
        ("font_size", r"(?:font size|统一字号|字号)\s+(.+)"),
        ("font_family", r"(?:font family|统一字体|字体)\s+(.+)"),
        ("legend_font_size", r"(?:legend font size|图例字号)\s+(.+)"),
        ("legend_position", r"(?:legend position|图例位置)\s+(.+)"),
        ("legend_columns", r"(?:legend columns|图例列数)\s+(.+)"),
    )
    value: Any
    for raw_clause in re.split(r"[;；]", text):
        clause = raw_clause.strip()
        if not clause:
            raise _invalid("Empty clauses are not a supported common-edit intent.")
        if clause.lower() in {"hide legend", "show legend", "隐藏图例", "显示图例"}:
            field, value = "legend_visible", clause.lower() in {"show legend", "显示图例"}
        else:
            match = next(((name, found) for name, pattern in patterns
                          if (found := re.fullmatch(pattern, clause, re.IGNORECASE)) is not None), None)
            if match is None:
                raise _invalid("This clause is unknown or ambiguous; use an exact supported form.", clause=clause)
            field, value = match[0], match[1].group(1).strip()
        if field in result:
            raise _invalid("Set each common-edit field once per intent; repeated clauses are ambiguous.", field=field)
        result[field] = value
    return result


def _points(value: Any) -> str:
    if not isinstance(value, str):
        raise _invalid("A font size requires an explicit positive physical unit.")
    try:
        normalized = normalize_physical_size(value)
    except ValueError as exc:
        raise _invalid("A font size requires an explicit positive physical unit, such as 9pt.") from exc
    match = re.fullmatch(r"([0-9.]+)(pt|mm|cm|in|inch)", normalized)
    assert match is not None
    amount, unit = match.groups()
    points = float(amount) * {"pt": 1, "mm": 72 / 25.4, "cm": 72 / 2.54, "in": 72, "inch": 72}[unit]
    if not 4 <= points <= 72:
        raise _invalid("Common typography uses 4–72 pt; use the full advertised edit contract for other sizes.")
    return f"{points:.12g}pt"


def normalize_common_edit(*, intent: str | None = None, **options: Any) -> dict[str, Any]:
    """Reject unknown/ambiguous input before reading or reserving any document."""
    if set(options) - set(_FIELDS):
        raise _invalid("Unknown common-edit fields.", fields=sorted(set(options) - set(_FIELDS)))
    supplied = {key: value for key, value in options.items() if value is not None}
    if intent is not None and supplied:
        raise _invalid("Choose --intent or explicit fields; do not combine both forms.")
    selected = _parse_text(intent) if intent is not None else supplied
    if not selected:
        raise _invalid("Provide an exact intent or at least one explicit common-edit field.")
    result = deepcopy(selected)
    if "palette" in result:
        palette = load_plot_contract().palettes.get(result["palette"]) if isinstance(result["palette"], str) else None
        if palette is None or not palette.public:
            raise _invalid("Choose an exact public SciPlot palette.", palettes=list(common_edit_capabilities()["palettes"]))
    for field in ("font_size", "legend_font_size"):
        if field in result:
            result[field] = _points(result[field])
    if "font_family" in result:
        value = result["font_family"]
        if not isinstance(value, str) or not value.strip() or len(value) > 256 or any(ord(char) < 32 for char in value):
            raise _invalid("Provide an exact, non-empty native font family.")
        result["font_family"] = value.strip()
    if "legend_visible" in result and type(result["legend_visible"]) is not bool:
        raise _invalid("Legend visibility requires true or false.")
    if "legend_columns" in result:
        value = result["legend_columns"]
        if isinstance(value, str) and re.fullmatch(r"[0-9]+", value):
            value = int(value)
        if type(value) is not int or not 1 <= value <= 32:
            raise _invalid("Legend columns requires an integer from 1 to 32.")
        result["legend_columns"] = value
    for field in ("series_labels", "series_visibility"):
        if field not in result:
            continue
        values = result[field]
        if not isinstance(values, dict) or not values or any(not isinstance(key, str) or not key.strip() for key in values):
            raise _invalid("Series edits require exact, non-empty source selectors.", field=field)
        for value in values.values():
            if field == "series_visibility" and type(value) is not bool:
                raise _invalid("Series visibility requires true or false.")
            if field == "series_labels" and (not isinstance(value, str) or not value.strip() or len(value) > 500 or any(ord(char) < 32 for char in value)):
                raise _invalid("A display alias requires 1–500 non-blank printable characters.")
    if "legend_position" in result:
        value = result["legend_position"]
        if isinstance(value, str):
            if not re.fullmatch(r"\s*(?:0(?:\.\d+)?|1(?:\.0+)?)\s*,\s*(?:0(?:\.\d+)?|1(?:\.0+)?)\s*", value):
                raise _invalid("Legend position requires explicit relative x,y between 0 and 1.")
            value = [float(item) for item in value.split(",")]
        if not isinstance(value, list) or len(value) != 2 or any(type(item) not in {int, float} or not 0 <= item <= 1 for item in value):
            raise _invalid("Legend position requires explicit relative x,y between 0 and 1.")
        result["legend_position"] = value
    return result


def _installed_font(name: str) -> None:
    """Use the existing native font catalog; never accept silent font substitution."""
    from sciplot_core.native_font_catalog import installed_font_families

    available = installed_font_families()
    if name not in available:
        raise _invalid("Choose an exact installed native font family.", font_family=name,
                       fonts=available[:32], font_count=len(available), omitted_font_count=max(0, len(available) - 32))


def compile_common_edit(document: dict[str, Any], options: dict[str, Any], key: str) -> dict[str, Any]:
    """Merge only requested fields into current represented values, in one batch."""
    changes: dict[tuple[str, str], dict[str, Any]] = {}

    def set_value(target: str, prop: str, value: Any) -> None:
        changes[target, prop] = {"op": "set", "target": [target], "property": prop, "value": deepcopy(value)}

    compile_series_edits(document, options, set_value, _invalid)

    if document.get("plot_type") == "ManagedPlot" and is_figure(document):
        spec = figure_spec(document)
        unsupported = set(options) & {"legend_visible", "legend_position"}
        if unsupported:
            raise _invalid("Managed FigureSpec v2 currently supports legend typography; visibility/position require another advertised contract.",
                           code="common_edit_unavailable", fields=sorted(unsupported),
                           available=common_edit_capabilities()["availability"]["ManagedPlot_FigureSpec_v2"])
        typography = {name: options[source] for name, source in (("font_size_pt", "font_size"), ("font_family", "font_family")) if source in options}
        if "font_size_pt" in typography:
            typography["font_size_pt"] = float(typography["font_size_pt"][:-2])
        if typography:
            theme = deepcopy(spec["theme"])
            for kind in _FONT_KINDS:
                theme["figure"][kind] = {**theme["figure"].get(kind, {}), **typography}
            set_value(spec["id"], "theme", theme)
            text_items = [*spec["guides"], *spec["annotations"]]
            for view in spec["views"]:
                scope = deepcopy(view["style"])
                for kind in _FONT_KINDS:
                    if kind in scope:
                        for field, value in typography.items():
                            if field in scope[kind]:
                                scope[kind][field] = value
                if scope != view["style"]:
                    set_value(view["id"], "style", scope)
                text_items.extend(view["axes"])
                for layer in view["layers"]:
                    text_items.extend(mark for mark in layer["marks"] if mark["type"] == "text")
            for item in text_items:
                set_value(item["id"], "style", {**item["style"], **typography})
        if "palette" in options:
            layers = [layer for view in spec["views"] for layer in view["layers"]]
            colors = load_plot_contract().palettes[options["palette"]].categorical
            if not layers or len(layers) > len(colors) or any(layer["role"] != "measurement" or
                    not layer["marks"] or any(mark["type"] not in {"line", "point"} for mark in layer["marks"]) for layer in layers):
                raise _invalid("Palette edits require ordinary measurement line/point layers and enough distinct palette colors; no layer or color is inferred.", code="common_edit_palette_targets")
            for layer, color in zip(layers, colors, strict=False):
                for mark in layer["marks"]:
                    field = "line_color" if mark["type"] == "line" else "marker_color"
                    set_value(mark["id"], "style", {**mark["style"], field: color.lower()})
        if "legend_font_size" in options:
            if not spec["guides"]:
                raise _invalid("The figure has no represented legend.", code="common_edit_unknown_target")
            for guide in spec["guides"]:
                value = changes.get((guide["id"], "style"), {"value": guide["style"]})["value"]
                set_value(guide["id"], "style", {**value, "font_size_pt": float(options["legend_font_size"][:-2])})
        if "legend_columns" in options:
            if not spec["guides"]:
                raise _invalid("The figure has no represented legend.", code="common_edit_unknown_target")
            for guide in spec["guides"]:
                set_value(guide["id"], "legend.columns", options["legend_columns"])
    else:
        objects = document["presentation"]["objects"]
        if "font_family" in options:
            raise _invalid("This document advertises font sizes only; font family is unavailable under its current coverage.", code="common_edit_unavailable", fields=["font_family"])
        if "palette" in options:
            series = [(target, obj) for target, obj in objects.items() if obj["kind"] == "series"]
            colors = load_plot_contract().palettes[options["palette"]].categorical
            if not series or len(series) > len(colors) or any("style.line.color" not in obj["capabilities"] or obj.get("scientific_role") for _, obj in series):
                raise _invalid("Every ordinary series must advertise a presentation color and have a distinct palette entry.", code="common_edit_palette_targets")
            for (target, _), color in zip(series, colors, strict=False):
                set_value(target, "style.line.color", color)
        for option, prop, target_kind in (("font_size", "font.size", None), ("legend_font_size", "font.size", "legend"),
                                   ("legend_visible", "legend.visible", "legend"), ("legend_position", "legend.position", "legend"),
                                   ("legend_columns", "legend.columns", "legend")):
            if option not in options:
                continue
            selected = [(target, obj) for target, obj in objects.items() if (target_kind is None or obj["kind"] == target_kind) and prop in obj["capabilities"]]
            if not selected:
                raise _invalid("No current object advertises the requested typography/legend property.", code="common_edit_unknown_target", property=prop)
            for target, obj in selected:
                if prop == "legend.position" and obj["capabilities"][prop].get("coordinate_mode", "relative") != "relative":
                    raise _invalid("The legend does not advertise relative placement.", code="common_edit_unavailable")
                set_value(target, prop, options[option])
    return validate_patch({"plot_id": document["plot_id"], "base_revision": document["revision"],
                           "idempotency_key": key, "intent_class": "presentation", "changes": list(changes.values())})


def _edit_receipt(result: dict[str, Any], entry: Path, normalized: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    """Keep the engine continuation intact and expose the original replay binding."""
    arguments = ["task", "edit", normalized["target"], "--task-dir", str(entry), "--json"]
    if normalized["figure_id"] is not None:
        arguments += ["--figure", normalized["figure_id"]]
    for field, value in normalized["edits"].items():
        if field in {"series_labels", "series_visibility"}:
            for selector, setting in value.items():
                arguments += (["--rename-series", selector, setting] if field == "series_labels" else
                              ["--show-series" if setting else "--hide-series", selector])
        elif field == "legend_visible":
            arguments += ["--show-legend" if value else "--hide-legend"]
        elif field == "legend_position":
            arguments += ["--legend-position", ",".join(str(item) for item in value)]
        else:
            arguments += ["--" + field.replace("_", "-"), str(value)]
    return {**result, "edit_entry": str(entry),
            "edit_replay": {"cli_argv": arguments, "idempotency_key": request["idempotency_key"],
                            "base_revision": request["base_revision"]}}


def _bound_edit(saved: dict[str, Any], normalized: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    if saved["intent"] != normalized:
        raise _invalid("This task directory identifies another common-edit intent. Continue the original or use a new key.",
                       code="document_idempotency_conflict")
    return canonical_path(Path(saved["plot"])), saved["request"]


def edit_task(target: Path, *, intent: str | None = None, figure_id: str | None = None,
              task_dir: Path | None = None, service: PlotService | None = None, **options: Any) -> dict[str, Any]:
    """One discoverable entry; the existing engine owns all mutation and recovery."""
    selected = normalize_common_edit(intent=intent, **options)
    target = canonical_path(target)
    normalized = {"kind": "sciplot_common_edit_intent", "version": 1,
                  "target": str(target), "figure_id": figure_id, "edits": selected}
    entry = canonical_path(task_dir) if task_dir is not None else None
    owner = service or PlotService()
    try:
        # Replay reads the original bound request before today's revision/currentness
        # discovery, preserving uncertain-apply and export-pending continuation.
        if entry is not None and read_edit_entry(entry, "semantic-edit.json") is not None:
            with edit_entry_session(entry):
                saved = read_edit_entry(entry, "semantic-edit.json")
                if saved is None:
                    raise EngineError("document_state_missing", "The original common-edit binding disappeared.")
                root, request = _bound_edit(saved, normalized)
                return _edit_receipt(owner.patch(root, request), entry, normalized, request)
        if "font_family" in selected:
            _installed_font(selected["font_family"])
        runtime = doctor_payload()
        doctor = {"kind": runtime["kind"], "status": runtime["status"],
                  "failed_checks": [item for item in runtime["checks"] if item.get("status") != "passed"]}
        if runtime["status"] != "ready":
            return {"kind": "sciplot_common_edit", "version": 1, "status": "blocked", "reason_code": "runtime_not_ready",
                    "doctor": doctor, "next_step": {"action": "repair_runtime", "next_actions": runtime.get("next_actions", [])}}
        from sciplot_core.task_storage import load_task, task_path, task_summary

        resolved_target = target
        old_task = task_path(target)
        if target.name == "task.json" or (old_task / "task.json").is_file():
            state = load_task(old_task)
            if state["status"] not in {"complete", "cancelled"}:
                current = task_summary(state)
                return {"kind": "sciplot_common_edit", "version": 1, "status": "blocked",
                        "reason_code": "unfinished_task", "current_task": current,
                        "next_step": current["next_step"], "doctor": doctor}
            if not state.get("project"):
                raise _invalid("The selected task has no saved project.", code="common_edit_unknown_target")
            resolved_target = Path(state["project"])
            figure_id = figure_id or state["request"].get("figure_id")
        scope = ({"scope": "summary"} if (resolved_target / "head.json").is_file() and
                 load_head(resolved_target)["document"].get("plot_type") == "ManagedPlot" else None)
        description = owner.open(resolved_target, figure_id=figure_id, description=scope)
        if description["status"] != "current":
            return {**description, "current_status": description["status"], "status": "blocked",
                    "reason_code": "common_edit_currentness_required", "doctor": doctor,
                    "next_step": description.get("next_step", {"action": "plot.describe", "plot": description.get("plot")})}
        if description.get("pending"):
            from sciplot_core.plot_engine.receipts import receipt

            pending = active(Path(description["plot"]))
            continuation = receipt(Path(description["plot"]), pending) if pending is not None else {}
            next_step = (continuation["next_step"] if continuation.get("status") == "needs_review" else
                         description.get("next_step", continuation.get("next_step", {"action": "plot.describe", "plot": description["plot"]})))
            return {**description, "status": "blocked", "reason_code": "document_transaction_pending",
                    "doctor": doctor, "request_executed": False,
                    "message": "Continue the original pending edit before this new intent; its preview does not represent the requested new edit.",
                    **{field: continuation[field] for field in ("preview", "scientific_audit", "evidence", "decision_id") if field in continuation},
                    "next_step": next_step}
        root = Path(description["plot"])
        head = load_head(root)
        document = head["document"]
        if document["plot_id"] != description["plot_id"] or document["revision"] != description["revision"]:
            raise EngineError("document_revision_conflict", "The document changed while binding the edit.", action="plot.describe")
        entry = entry or root / "compatibility" / ("edit-" + uuid4().hex)
        admit_edit_entry(entry, root, head)
        request = compile_common_edit(document, selected, "edit:" + digest(str(entry)))
        with edit_entry_session(entry):
            saved = bind_edit_entry(entry, "semantic-edit.json", {"intent": normalized, "plot": str(root), "request": request})
            root, request = _bound_edit(saved, normalized)
            return _edit_receipt({**owner.patch(root, request), "doctor": doctor}, entry, normalized, request)
    finally:
        if service is None:
            close_edit_owner(owner)
