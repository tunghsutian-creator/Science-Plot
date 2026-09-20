"""Serialized JSON-lines bridge to a Qt-main-thread native document session."""

from __future__ import annotations

import json
import selectors
import subprocess
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

from sciplot_core.veusz_runtime import veusz_worker_environment


class NativeWorker:
    def __init__(self, document: Path, spec: Path, output: Path):
        output.mkdir(parents=True, exist_ok=True)
        self.log = (output / "worker.stderr.log").open("w", encoding="utf-8")
        self.process = subprocess.Popen(
            [sys.executable, "-m", "sciplot_core.veusz_worker.live_session",
             "--document", str(document), "--spec", str(spec), "--out", str(output)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.log,
            text=True, bufsize=1, env=veusz_worker_environment(),
        )

    @property
    def alive(self) -> bool:
        return self.process.poll() is None

    def request(self, op: str, **values: Any) -> dict[str, Any]:
        if not self.alive:
            raise RuntimeError("原生编辑会话已结束，请重新打开编辑器。")
        assert self.process.stdin is not None and self.process.stdout is not None
        request_id = uuid4().hex
        message = json.dumps({"request_id": request_id, "op": op, **values},
                             ensure_ascii=False, allow_nan=False) + "\n"
        try:
            self.process.stdin.write(message)
            self.process.stdin.flush()
        except (OSError, ValueError):
            self.close()
            raise RuntimeError("原生编辑会话已停止，请重新载入保存图。") from None
        with selectors.DefaultSelector() as selector:
            selector.register(self.process.stdout, selectors.EVENT_READ)
            if not selector.select(timeout=120):
                self.close()
                raise TimeoutError("原生渲染超时；已停止此会话以免继续使用未确认的图形状态。")
        line = self.process.stdout.readline()
        if not line:
            self.close()
            raise RuntimeError("原生编辑进程没有返回结果，请查看会话日志。")
        try:
            result = json.loads(line)
        except ValueError:
            self.close()
            raise RuntimeError("原生编辑响应无法解析，会话已停止。") from None
        if not isinstance(result, dict) or result.get("request_id") != request_id:
            self.close()
            raise RuntimeError("原生编辑响应身份不匹配，会话已停止。")
        if result.get("status") != "ok":
            error = result.get("error") or {}
            if error.get("fatal"):
                self.close()
            raise ValueError(str(error.get("message", "原生编辑失败。")))
        return result

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
        for stream in (self.process.stdin, self.process.stdout):
            if stream is not None:
                stream.close()
        self.log.close()
