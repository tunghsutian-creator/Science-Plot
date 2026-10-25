"""The old typed style entry delegates migrated plots to the same semantic service."""

from pathlib import Path
from typing import Any
from uuid import uuid4

from sciplot_core.studio_core.project_query import resolve_project_figure
from sciplot_core.studio_core.project_query_paths import canonical_path
from sciplot_core.studio_core.project_session import external_project_session
from sciplot_core.task_series_edits import compile_series_style

from .errors import EngineError
from .service import PlotService
from .storage import digest, document_root, load_head, read, write


def migrated_style(target: Path, *, samples: list[str] | None, all_samples: bool,
                   style: dict[str, str], figure_id: str | None, task_dir: Path | None) -> dict[str, Any] | None:
    """Unimported projects keep the legacy lifecycle. Never silently import an old task."""
    target = canonical_path(target)
    if task_dir is not None and (task_dir / "task.json").exists():
        return None
    if (target / "head.json").is_file():
        root = target
    else:
        try:
            selected = resolve_project_figure(target, figure_id)
        except (ValueError, OSError):
            return None
        root = document_root(Path(selected["project"]), selected["figure_id"])
        if not (root / "head.json").exists():
            return None
    intent = {"plot": str(root), "samples": samples, "all_samples": all_samples, "style": style}
    entry = canonical_path(task_dir) if task_dir is not None else root / "compatibility" / uuid4().hex
    entry.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with external_project_session(entry):
        record = entry / "semantic-style.json"
        if record.exists():
            state = read(record)
            if state["intent"] != intent:
                raise EngineError("document_idempotency_conflict", "This style key identifies a different intent.")
            request = state["request"]
        else:
            document = load_head(root)["document"]
            request = {"plot_id": document["plot_id"], "base_revision": document["revision"],
                       "idempotency_key": "style:" + digest(str(entry)), "intent_class": "presentation",
                       "changes": compile_series_style(document, samples=samples, all_samples=all_samples, style=style)}
            write(record, {"intent": intent, "request": request})
        return PlotService().patch(root, request)
