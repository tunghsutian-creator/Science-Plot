"""JSONL live editing over one native Veusz Document; canonical saves stay outside."""

from __future__ import annotations

import argparse
from contextlib import redirect_stdout
from importlib import import_module
import json
import math
from pathlib import Path
import sys
from time import perf_counter
from typing import Any, TextIO

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.native_settings import editable_fields
from sciplot_core.studio_core.document_edit_policy import (
    filter_editable_fields,
    validate_edit_science_policy,
)
from sciplot_core.veusz_worker.document_edit import (
    _preview,
    loaded_native_document,
    prepare_setting_batch,
)


class SessionTerminated(RuntimeError):
    """Native mutation or rendering failed; this in-memory document cannot continue."""


class LiveNativeSession:
    """Own live values, native Undo and frame-bound hit testing on the Qt main thread."""

    def __init__(
        self, document: Any, document_path: Path, spec_path: Path, output: Path,
        *, document_sha256: str, spec_sha256: str,
    ) -> None:
        self.document = document
        self.document_path = document_path.resolve()
        self.spec_path = spec_path.resolve()
        self.output = output.resolve()
        self.document_sha256 = document_sha256
        self.spec_sha256 = spec_sha256
        self.render_revision = 0
        self.preview: dict[str, Any] | None = None
        self.paint_helper: Any = None
        self.closed = False
        self._touched: dict[str, str] = {}
        self._check_inputs()
        self.output.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.initial_values = {
            field["setting_path"]: field["current_value"]
            for widget in self._objects().values() for field in widget["editable_fields"]
        }

    def _check_inputs(self) -> None:
        try:
            changed = (file_sha256(self.document_path) != self.document_sha256
                       or file_sha256(self.spec_path) != self.spec_sha256)
        except OSError as exc:
            self.closed = True
            raise SessionTerminated("The session document or specification is no longer readable.") from exc
        if changed:
            self.closed = True
            raise SessionTerminated("The session document or specification changed; reopen from current state.")

    def _objects(self) -> dict[str, dict[str, Any]]:
        objects: dict[str, dict[str, Any]] = {}

        def collect(path: str, widget: Any) -> None:
            objects[str(path)] = {
                "path": str(path), "name": str(widget.name), "type": str(widget.typename),
                "editable_fields": editable_fields(self.document, widget, safe_only=True),
            }

        self.document.walkNodes(collect, nodetypes=("widget",))
        objects = filter_editable_fields(objects, self.spec_path)
        for path, entry in objects.items():
            if entry["type"] == "key":
                control = self._key_control(self.document.resolveWidgetPath(None, path))
                if control is not None:
                    scale = float(self.paint_helper.scaling)
                    entry["drag_handle"] = {"kind": "key", "bounds": [
                        float(value) * scale for value in (*control.posn, *control.dims)
                    ]}
        return objects

    def _key_control(self, widget: Any) -> Any:
        if self.paint_helper is None or widget.typename != "key":
            return None
        ControlKey = import_module("veusz.widgets.key").ControlKey
        controls = [control for control in self.paint_helper.getControlGraph(widget) or []
                    if isinstance(control, ControlKey) and control.widget is widget]
        return controls[0] if len(controls) == 1 else None

    def _changes(self) -> list[dict[str, Any]]:
        changes = []
        for setting_path, object_path in self._touched.items():
            current = json_safe(self.document.resolveSettingPath(None, setting_path).get())
            initial = self.initial_values[setting_path]
            if current != initial:
                changes.append({"object_path": object_path, "setting_path": setting_path,
                                "expected_value": initial, "value": current})
        return changes

    def _render(self) -> None:
        PaintHelper = import_module("veusz.document").PaintHelper

        revision = self.render_revision + 1
        target = self.output / f"frame-{revision:08d}.png"
        if target.exists():
            raise FileExistsError("Live frame output already exists; use a fresh session directory.")
        # Use exactly the existing transaction preview, including its 150 dpi and white background.
        preview = _preview(self.document, target)
        # A separate native paint pass over the same Document and DPI creates hit/control records.
        size = self.document.pageSize(0, dpi=(150, 150), integer=False)
        helper = PaintHelper(self.document, size, dpi=(150, 150))
        self.document.paintTo(helper, 0)
        self._check_inputs()
        self.preview, self.paint_helper = preview, helper
        self.render_revision = revision

    def state(self) -> dict[str, Any]:
        if self.preview is None:
            self._render()
        changes = self._changes()
        return {
            "render_revision": self.render_revision,
            "document": {"path": str(self.document_path), "sha256": self.document_sha256},
            "spec_sha256": self.spec_sha256, "preview": dict(self.preview or {}),
            "objects": self._objects(), "can_undo": bool(self.document.canUndo()),
            "can_redo": bool(self.document.canRedo()), "changes": changes, "dirty": bool(changes),
        }

    def _set(self, changes: Any) -> None:
        OperationMultiple = import_module("veusz.document.operations").OperationMultiple

        native, actual = prepare_setting_batch(self.document, changes)
        validate_edit_science_policy(changes, self.spec_path)
        if any(change["setting_path"] not in self.initial_values for change in actual):
            raise ValueError("A setting is outside this session's original advertised fields.")
        effective = [(operation, change) for operation, change in zip(native, actual, strict=True)
                     if change["old_value"] != change["new_value"]]
        if effective:
            try:
                self.document.applyOperation(OperationMultiple(
                    [operation for operation, _change in effective], descr="SciPlot live style edit"))
            except Exception as exc:
                self.closed = True
                raise SessionTerminated("Native editing failed; discard this session without saving.") from exc
            for _operation, change in effective:
                self._touched[change["setting_path"]] = change["object_path"]

    def _require_current_frame(self, request: dict[str, Any]) -> None:
        revision = request.get("render_revision")
        if (type(revision) is not int or revision != self.render_revision
                or self.preview is None or self.paint_helper is None):
            raise ValueError("The interaction frame is stale; use the current render_revision.")

    def _move_key(self, request: dict[str, Any]) -> None:
        self._require_current_frame(request)
        path, dx, dy = request.get("object_path"), request.get("dx"), request.get("dy")
        if not isinstance(path, str) or not path.startswith("/"):
            raise ValueError("Choose a canonical native key path from the current frame.")
        if (isinstance(dx, bool) or isinstance(dy, bool)
                or not isinstance(dx, int | float) or not isinstance(dy, int | float)
                or not math.isfinite(dx) or not math.isfinite(dy)):
            raise ValueError("Key movement must use finite pixel deltas.")
        widget = self.document.resolveWidgetPath(None, path)
        control = self._key_control(widget)
        if widget.path != path or control is None:
            raise ValueError("Only a rendered native key with a current control handle can be moved.")
        item = control.createGraphicsItem(None)
        scale = float(self.paint_helper.scaling)
        # Native scaled geometry converts PNG pixels to this control's cgscale.
        item.setScaledPos(dx / scale, dy / scale)
        highlight = item.checkHighlight()
        if highlight:
            horizontal, vertical = highlight
            manual_x, manual_y = 0.0, 0.0
        else:
            # Adapter for upstream widgets/key.py:_GraphControlKey.mouseReleaseEvent.
            # Use its actual recorded rectangle and parent; never estimate text bounds.
            rect = item.scaledRect()
            rect.translate(item.scaledPos())
            parent = control.parentposn
            horizontal, vertical = "manual", "manual"
            manual_x = (rect.left() - parent[0]) / (parent[2] - parent[0])
            manual_y = (parent[3] - rect.bottom()) / (parent[3] - parent[1])
        values = {"horzPosn": horizontal, "vertPosn": vertical,
                  "horzManual": manual_x, "vertManual": manual_y}
        # Validate all four fields before a single native operation can mutate anything.
        self._set([{"object_path": path, "setting_path": f"{path}/{suffix}",
                    "expected_value": json_safe(widget.settings.get(suffix).get()), "value": value}
                   for suffix, value in values.items()])

    def _hit(self, request: dict[str, Any]) -> str | None:
        self._require_current_frame(request)
        assert self.preview is not None
        x, y = request.get("x"), request.get("y")
        if (isinstance(x, bool) or isinstance(y, bool)
                or not isinstance(x, int | float) or not isinstance(y, int | float)
                or not math.isfinite(x) or not math.isfinite(y)
                or not 0 <= x < self.preview["width"] or not 0 <= y < self.preview["height"]):
            raise ValueError("Hit-test coordinates must be finite pixels within the current native image.")
        widget = self.paint_helper.identifyWidgetAtPoint(float(x), float(y), antialias=True)
        return str(widget.path) if widget is not None else None

    def dispatch(self, request: dict[str, Any]) -> dict[str, Any]:
        op = request.get("op")
        allowed = {
            "state": set(), "render": set(), "set": {"changes"}, "undo": set(),
            "redo": set(), "hit": {"x", "y", "render_revision"}, "close": set(),
            "move_key": {"object_path", "dx", "dy", "render_revision"},
        }
        if not isinstance(op, str) or op not in allowed:
            raise ValueError("Unknown live session operation.")
        if set(request) - {"request_id", "op"} - allowed[op]:
            raise ValueError("Unexpected fields for this live session operation.")
        if op == "close":
            self.closed = True
            return {"closed": True}
        if self.closed:
            raise SessionTerminated("This native session is closed.")
        self._check_inputs()
        if op == "hit":
            return {"object_path": self._hit(request), "state": self.state()}
        if op == "set":
            self._set(request.get("changes"))
        if op == "move_key":
            self._move_key(request)
        if op in {"undo", "redo"}:
            can_apply = self.document.canUndo() if op == "undo" else self.document.canRedo()
            if not can_apply:
                raise ValueError(f"No native {op} operation is available.")
            try:
                self.document.undoOperation() if op == "undo" else self.document.redoOperation()
            except Exception as exc:
                self.closed = True
                raise SessionTerminated(f"Native {op} failed; discard this session without saving.") from exc
        if op in {"render", "set", "move_key", "undo", "redo"}:
            try:
                self._render()
                return {"state": self.state()}
            except Exception as exc:
                self.closed = True
                raise SessionTerminated("Native rendering failed; discard this session without saving.") from exc
        return {"state": self.state()}


def serve(session: LiveNativeSession, incoming: TextIO, outgoing: TextIO) -> int:
    """Read one command at a time; Qt work remains on this process's main thread."""
    for line in incoming:
        started = perf_counter()
        request_id: Any = None
        try:
            request = json.loads(line, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
            if not isinstance(request, dict):
                raise ValueError("A live session request must be a JSON object.")
            request_id = request.get("request_id")
            response = {"request_id": request_id, "status": "ok", **session.dispatch(request)}
        except Exception as exc:
            fatal = isinstance(exc, SessionTerminated) or session.closed
            response = {"request_id": request_id, "status": "error",
                        "error": {"type": type(exc).__name__, "message": str(exc), "fatal": fatal}}
        response["timing"] = {"request_ms": round((perf_counter() - started) * 1000, 3)}
        print(json.dumps(response, ensure_ascii=False, allow_nan=False), file=outgoing, flush=True)
        if session.closed:
            return 1 if response["status"] == "error" else 0
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--document", type=Path, required=True)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    incoming, outgoing = sys.stdin, sys.stdout
    try:
        document_hash, spec_hash = file_sha256(args.document), file_sha256(args.spec)
        # Native diagnostic prints must never corrupt the JSONL protocol.
        with redirect_stdout(sys.stderr), loaded_native_document(args.document) as document:
            session = LiveNativeSession(document, args.document, args.spec, args.out,
                                        document_sha256=document_hash, spec_sha256=spec_hash)
            return serve(session, incoming, outgoing)
    except Exception as exc:
        print(json.dumps({"request_id": None, "status": "error", "error": {
            "type": type(exc).__name__, "message": str(exc), "fatal": True}}), file=outgoing, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
