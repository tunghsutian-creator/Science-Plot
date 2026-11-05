"""Bind interactive unsaved edits to existing native preview/apply/export owners."""

from __future__ import annotations

import copy
import json
import shutil
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.project_commands.resources import FigureReadWitness
from sciplot_core.live_editor.worker import NativeWorker
from sciplot_core.live_editor.entry import resolve_editor_input
from sciplot_core.studio_core.document_edit import apply_document_edit, preview_document_edit
from sciplot_core.studio_core.document_edit_state import audit_edited_document, edit_state, new_preview_directory
from sciplot_core.studio_core.project_query import inspect_project, resolve_project_figure, resolve_project_path
from sciplot_core.studio_core.sample_style import sample_style_targets
from sciplot_core.task_control import start_task


def field_values(objects: dict[str, Any]) -> dict[str, Any]:
    return {field["setting_path"]: copy.deepcopy(field["current_value"])
            for obj in objects.values() for field in obj["editable_fields"]}


class LiveSession:
    def __init__(self, project: Path, *, figure_id: str | None = None,
                 output: Path | None = None):
        self.entry_target, _ = resolve_editor_input(project)
        self.project = resolve_project_path(self.entry_target)
        self.figure = resolve_project_figure(self.entry_target, figure_id)
        self.figure_id = self.figure["figure_id"]
        self.document = Path(self.figure["document"])
        self.spec = Path(self.figure["spec"])
        self.output = new_preview_directory(self.project, output or (
            Path(tempfile.gettempdir()) / ("sciplot-editor-" + uuid4().hex)))
        self.session_id = uuid4().hex
        self.lock = threading.RLock()
        self.revision = 0
        self.worker: NativeWorker | None = None
        self.native: dict[str, Any] = {}
        self.baseline_values: dict[str, Any] = {}
        self._baseline_witness: FigureReadWitness | None = None
        self._baseline_delivery = ""
        self.evidence: dict[str, Any] = {}
        self.sample_labels: dict[str, str] = {}
        self.figures: list[dict[str, Any]] = []
        self.checked_at = ""
        self.receipts: dict[str, tuple[str, dict[str, Any]]] = {}
        self.saved_hash = ""
        self.last_result: dict[str, Any] | None = None
        self.stale = False
        self.session_error: str | None = None
        self._load()

    @staticmethod
    def _read_witness(state: dict[str, Any]) -> FigureReadWitness:
        return FigureReadWitness.from_read_state({
            "project_files": state["project_files"],
            "source_files": state.get("source_files", {}),
            "projected_reads": state.get("projected_reads", []),
        })

    @property
    def baseline(self) -> dict[str, Any]:
        """Expose a detached v1 view; the session retains one immutable witness."""
        if self._baseline_witness is None:
            return {}
        return {**self._baseline_witness.to_read_state_payload(),
                "delivery": self._baseline_delivery, "delivery_files": None}

    @baseline.setter
    def baseline(self, state: dict[str, Any]) -> None:
        witness = self._read_witness(state)
        delivery = state["delivery"]
        if not isinstance(delivery, str) or state.get("delivery_files") is not None:
            raise ValueError("A live editor baseline requires selected figure reads and an explicit delivery identity.")
        self._baseline_witness, self._baseline_delivery = witness, delivery

    def _matches_baseline(self, state: dict[str, Any]) -> bool:
        return (self._read_witness(state) == self._baseline_witness
                and state["delivery"] == self._baseline_delivery
                and state.get("delivery_files") is None)

    def _load(self, figure_id: str | None = None) -> None:
        resolve_editor_input(self.entry_target)
        inspection = inspect_project(self.project)
        if (inspection.get("source") or {}).get("current") is False:
            raise ValueError("原始数据已变化，请通过源数据更新流程处理后再编辑。")
        selected = resolve_project_figure(self.project, figure_id or self.figure_id)
        document, spec = Path(selected["document"]), Path(selected["spec"])
        if figure_id is None and (document != self.document or spec != self.spec):
            raise ValueError("图形身份发生变化，请重新打开编辑器。")
        before = edit_state(self.project, selected)
        audit_edited_document(document, spec)
        folder = self.output / uuid4().hex
        folder.mkdir(mode=0o700)
        snapshot = folder / "baseline.vsz"
        shutil.copyfile(document, snapshot)
        worker = NativeWorker(snapshot, spec, folder / "frames")
        try:
            native = worker.request("state")["state"]
            labels = {path: item["sample"] for item in sample_style_targets(json.loads(spec.read_text()))
                      for path in item["object_paths"]}
            if edit_state(self.project, selected) != before:
                raise ValueError("打开编辑器期间项目发生变化，请重新打开。")
        except BaseException:
            worker.close()
            raise
        if self.worker is not None:
            self.worker.close()
        if selected["figure_id"] != self.figure_id:
            self.session_id = uuid4().hex
        self.figure, self.figure_id = selected, selected["figure_id"]
        self.document, self.spec = document, spec
        self.worker, self.native = worker, native
        self.figures = [{key: item.get(key) for key in ("figure_id", "title", "primary", "status")}
                        for item in inspection.get("figures", [selected])]
        self.saved_hash = file_sha256(snapshot)
        self.baseline, self.baseline_values = before, field_values(native["objects"])
        self.evidence = {key: inspection.get(key) for key in ("source", "qa", "delivery")}
        self.sample_labels = labels
        self.checked_at = datetime.now(timezone.utc).isoformat()
        self.stale = False
        self.session_error = None
        self.revision += 1

    def _check_worker(self) -> None:
        if self.worker is not None and not self.worker.alive:
            self.stale = True
            self.session_error = "原生编辑会话已停止；画布保留最后预览。请重新载入已保存的 VSZ 后继续编辑。"

    def _check_current(self) -> None:
        self._check_worker()
        if self.session_error:
            raise ValueError(self.session_error)
        if self.stale or not self._matches_baseline(edit_state(self.project, self.figure)):
            self.stale = True
            raise ValueError("项目、保存图或交付已在其他地方变化；请重新加载后编辑，当前草稿尚未保存。")
        inspection = inspect_project(self.project)
        if (inspection.get("source") or {}).get("current") is False:
            self.stale = True
            raise ValueError("原始数据已变化，当前编辑不能保存。请通过源数据更新流程处理。")
        self.evidence = {key: inspection.get(key) for key in ("source", "qa", "delivery")}
        self.checked_at = datetime.now(timezone.utc).isoformat()

    def _changes(self) -> list[dict[str, Any]]:
        return [{"object_path": path, "setting_path": field["setting_path"],
                 "expected_value": self.baseline_values[field["setting_path"]],
                 "value": field["current_value"]}
                for path, obj in self.native["objects"].items() for field in obj["editable_fields"]
                if field["current_value"] != self.baseline_values[field["setting_path"]]]

    def state(self) -> dict[str, Any]:
        with self.lock:
            self._check_worker()
            objects = {path: {**obj, "fields": obj["editable_fields"],
                              "label": self.sample_labels.get(path, obj["name"])}
                       for path, obj in self.native["objects"].items()}
            return copy.deepcopy({
                "session_id": self.session_id, "revision": self.revision,
                "figures": self.figures, "figure_id": self.figure_id, "title": self.figure.get("title", self.figure_id),
                "project": str(self.project), "document": str(self.document),
                "document_sha256": self.saved_hash, "objects": objects,
                "preview": {**self.native["preview"], "url": f"/api/preview?revision={self.revision}"},
                "can_undo": self.native["can_undo"], "can_redo": self.native["can_redo"],
                "dirty": bool(self._changes()), "stale": self.stale, "session_error": self.session_error,
                "evidence": self.evidence, "checked_at": self.checked_at, "result": self.last_result,
            })

    def preview_path(self, revision: int) -> Path:
        with self.lock:
            if revision != self.revision:
                raise ValueError("此预览已过期。")
            preview = self.native["preview"]
            path = Path(preview["path"]).resolve()
            if not path.is_relative_to(self.output) or file_sha256(path) != preview["sha256"]:
                raise ValueError("预览文件身份不匹配。")
            return path

    def _save(self) -> dict[str, Any]:
        changes = self._changes()
        if not changes:
            return {"status": "unchanged", "message": "图形已与保存版本一致。"}
        preview = preview_document_edit(
            self.project, changes, output_dir=self.output / ("save-" + uuid4().hex),
            figure_id=self.figure_id, expected_document_sha256=self.saved_hash,
        )
        if preview["preview"]["sha256"] != self.native["preview"]["sha256"]:
            raise ValueError("保存前的原生重放与当前画布不同；没有保存，请重新加载并核查。")
        result = apply_document_edit(self.project, preview)
        if not result.get("result_is_current") or file_sha256(self.document) != result["result_sha256"]:
            self.stale = True
            raise ValueError("保存结果已变化，请核查当前文档；原生事务记录已保留。")
        # A style save changes exactly one VSZ. Do not absorb unrelated changes
        # made after the existing apply owner's project lock has been released.
        expected = copy.deepcopy(self.baseline)
        expected["project_files"][str(self.document.relative_to(self.project))] = result["result_sha256"]
        try:
            current = edit_state(self.project, self.figure) == expected
        except (ValueError, OSError) as exc:
            self.stale = True
            self.last_result = {**result, "message": "保存已执行，但后续当前性核查失败；请核查原始错误后重新加载。"}
            if isinstance(exc, OSError):
                raise
            raise ValueError(self.last_result["message"]) from exc
        if not current:
            self.stale = True
            self.last_result = {**result, "message": "保存已执行，但项目或交付随后变化；请重新加载核查。"}
            raise ValueError(self.last_result["message"])
        self.saved_hash = result["result_sha256"]
        self.baseline_values = field_values(self.native["objects"])
        self.baseline = expected
        self.revision += 1
        self._check_current()
        return {**result, "message": "已保存 VSZ；导出会按当前保存图重新生成并检查交付。"}

    def _export(self) -> dict[str, Any]:
        if self._changes():
            raise ValueError("请先保存当前图形，再导出。")
        task = start_task({"version": 1, "action": "export", "project": str(self.project)},
                          task_dir=self.output / ("export-" + uuid4().hex))
        if file_sha256(self.document) != self.saved_hash:
            self.stale = True
            raise ValueError("导出过程中保存图已变化，请核查当前状态。")
        try:
            after = edit_state(self.project, self.figure)
            if not self._matches_baseline(after):
                raise ValueError("导出期间源规格、请求或项目元数据发生变化；请重新加载核查。")
        except (ValueError, OSError):
            self.stale = True
            self.last_result = {"task": task, "message": "导出任务记录已保留；后续当前性核查未通过，请核查原始错误后重新加载。"}
            raise
        self.baseline = after
        self.revision += 1
        self.last_result = {"task": task}
        self._check_current()
        if task.get("status") == "complete" and not all(
            (self.evidence.get(key) or {}).get("current") is True for key in ("qa", "delivery")
        ):
            self.stale = True
            self.last_result["message"] = "导出任务已结束，但当前 QA 或交付无法确认有效；请重新载入核查。"
            raise ValueError(self.last_result["message"])
        return {"task": task, "message": "导出与检查已完成。" if task.get("status") == "complete"
                  else "导出尚未完成；保存图仍保留，请查看任务状态。"}

    def command(self, request: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            identifier = request.get("request_id")
            if not isinstance(identifier, str) or not 1 <= len(identifier) <= 128:
                raise ValueError("需要有效的请求标识。")
            signature = json.dumps(request, sort_keys=True, allow_nan=False)
            if identifier in self.receipts:
                prior_signature, prior = self.receipts[identifier]
                if signature != prior_signature:
                    raise ValueError("不能以同一请求标识提交不同操作。")
                return copy.deepcopy(prior)
            if type(request.get("revision")) is not int or request["revision"] != self.revision:
                raise ValueError("编辑请求版本已过期，请使用当前会话状态。")
            action = request.get("action")
            started = perf_counter()
            result: dict[str, Any] = {}
            if action == "reload":
                self._load()
                result = {"message": "已重新读取保存图，未保存的草稿已丢弃。"}
            else:
                self._check_current()
                assert self.worker is not None
                if action in {"set", "undo", "redo", "move_key"}:
                    payload = {"changes": request.get("changes")} if action == "set" else {}
                    if action == "move_key":
                        if request.get("preview_revision") != self.revision:
                            raise ValueError("请等待当前画布加载完成，再移动图例。")
                        payload = {key: request.get(key) for key in ("object_path", "dx", "dy")}
                        payload["render_revision"] = self.native["render_revision"]
                    self.native = self.worker.request(action, **payload)["state"]
                    self.revision += 1
                    self._check_current()
                elif action == "hit":
                    if request.get("preview_revision") != self.revision:
                        raise ValueError("请等待当前画布加载完成，再选择图形对象。")
                    hit = self.worker.request("hit", x=request.get("x"), y=request.get("y"),
                                              render_revision=self.native["render_revision"])
                    result["selected_object_path"] = hit.get("object_path")
                elif action == "save":
                    result = self._save()
                elif action == "export":
                    result = self._export()
                elif action == "publish":
                    saved = self._save()
                    self.last_result = {"save": saved}
                    try:
                        result = self._export()
                        if result["task"].get("status") != "complete":
                            raise ValueError("导出任务尚未完成。")
                    except (ValueError, OSError, RuntimeError, TimeoutError) as exc:
                        message = f"图形已保存，但交付更新未完成：{exc} 修正问题后可重试更新交付，无需再次应用已保存修改。"
                        self.last_result = {**(self.last_result or {}), "save": saved, "message": message}
                        raise ValueError(message) from exc
                    result = {**result, "save": saved, "message": "已保存并更新交付。"}
                elif action == "switch":
                    figure_id = request.get("figure_id")
                    if not isinstance(figure_id, str) or not figure_id:
                        raise ValueError("请选择已注册的图形。")
                    if "discard" in request and type(request["discard"]) is not bool:
                        raise ValueError("放弃修改需要明确的布尔值。")
                    if self._changes() and request.get("discard") is not True:
                        raise ValueError("当前图形尚未保存；请先保存，或明确放弃后切换。")
                    self._load(figure_id)
                    result = {"message": "已切换到所选图形。"}
                else:
                    raise ValueError("不支持的编辑命令。")
            if action in {"save", "export", "publish", "reload", "switch"}:
                self.last_result = result
            response = {"request_id": identifier, "state": self.state(), "result": result,
                        "elapsed_ms": round((perf_counter() - started) * 1000, 3), **result}
            self.receipts[identifier] = (signature, copy.deepcopy(response))
            if len(self.receipts) > 64:
                del self.receipts[next(iter(self.receipts))]
            return response

    def close(self) -> None:
        if self.worker is not None:
            self.worker.close()
