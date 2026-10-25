"""The old typed style entry delegates migrated plots to the same semantic service."""

from pathlib import Path
from typing import Any
from uuid import uuid4

from sciplot_core.studio_core.project_query import resolve_project_figure
from sciplot_core.studio_core.project_query_paths import canonical_path
from sciplot_core.task_series_edits import compile_series_style

from .edit_entry import admit_edit_entry, bind_edit_entry, close_edit_owner, edit_entry_owner, edit_entry_session, read_edit_entry
from .errors import EngineError
from .service import PlotService
from .storage import digest, document_root, load_head


def _style_binding(target: Path, samples: list[str] | None, all_samples: bool,
                   style: dict[str, str], figure_id: str | None) -> dict[str, Any]:
    return {"target": str(target), "figure_id": figure_id, "samples": samples,
            "all_samples": all_samples, "style": style}


def _bound_style(saved: dict[str, Any], caller: dict[str, Any],
                 root: Path | None = None) -> tuple[Path, dict[str, Any]]:
    """New entries bind the caller; old entries retain their resolved-root intent."""
    if "entry_intent" in saved:
        same = saved["entry_intent"] == caller
    else:
        same = saved["intent"] == {"plot": str(root or Path(caller["target"])),
                                  **{key: caller[key] for key in ("samples", "all_samples", "style")}}
    if not same:
        raise EngineError("document_idempotency_conflict", "This style key identifies a different intent.")
    return canonical_path(Path(saved["intent"]["plot"])), saved["request"]


def _execute_style(root: Path, request: dict[str, Any]) -> dict[str, Any]:
    owner = PlotService()
    try:
        return owner.patch(root, request)
    finally:
        close_edit_owner(owner)


def migrated_style(target: Path, *, samples: list[str] | None, all_samples: bool,
                   style: dict[str, str], figure_id: str | None, task_dir: Path | None) -> dict[str, Any] | None:
    """Unimported projects keep the legacy lifecycle. Never silently import an old task."""
    target = canonical_path(target)
    entry = canonical_path(task_dir) if task_dir is not None else None
    if entry is not None and edit_entry_owner(entry) == "task.json":
        return None
    caller = _style_binding(target, samples, all_samples, style, figure_id)
    saved = read_edit_entry(entry, "semantic-style.json") if entry is not None else None
    # An uncertain/successful reply belongs to its original request even when
    # today's launcher/registry no longer resolves. Old entries without caller
    # identity can bypass discovery only for their explicit original root.
    if saved is not None and ("entry_intent" in saved or saved["intent"]["plot"] == str(target)):
        assert entry is not None
        with edit_entry_session(entry):
            current = read_edit_entry(entry, "semantic-style.json")
            if current is None:
                raise EngineError("document_state_missing", "The original style binding disappeared.")
            root, request = _bound_style(current, caller)
            return _execute_style(root, request)
    if (target / "head.json").is_file():
        root = target
    else:
        try:
            selected = resolve_project_figure(target, figure_id)
        except (ValueError, OSError) as exc:
            if saved is not None:
                raise EngineError("document_idempotency_conflict",
                                  "Continue this style entry with its original plot root or original resolving entrypoint.") from exc
            return None
        root = document_root(Path(selected["project"]), selected["figure_id"])
        if saved is None and not (root / "head.json").exists():
            return None
    entry = entry or root / "compatibility" / uuid4().hex
    if saved is not None:
        with edit_entry_session(entry):
            current = read_edit_entry(entry, "semantic-style.json")
            if current is None:
                raise EngineError("document_state_missing", "The original style binding disappeared.")
            root, request = _bound_style(current, caller, root)
            return _execute_style(root, request)
    head = load_head(root)
    admit_edit_entry(entry, root, head)
    with edit_entry_session(entry):
        saved = read_edit_entry(entry, "semantic-style.json")
        if saved is not None:
            root, request = _bound_style(saved, caller, root)
        else:
            document = head["document"]
            request = {"plot_id": document["plot_id"], "base_revision": document["revision"],
                       "idempotency_key": "style:" + digest(str(entry)), "intent_class": "presentation",
                       "changes": compile_series_style(document, samples=samples, all_samples=all_samples, style=style)}
            intent = {"plot": str(root), **{key: caller[key] for key in ("samples", "all_samples", "style")}}
            saved = bind_edit_entry(entry, "semantic-style.json", {"intent": intent, "entry_intent": caller, "request": request})
            root, request = _bound_style(saved, caller, root)
        return _execute_style(root, request)
