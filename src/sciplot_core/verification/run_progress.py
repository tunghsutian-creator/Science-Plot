"""Unsigned, best-effort checkpoints; never completion or reusable evidence."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
WRITE_INTERVAL = 5.0
PYTEST_PROGRESS = "pytest-progress.json"
_CLAIM = "diagnostic_only_not_completion_evidence"


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _read(path: Path) -> Any:
    if path.is_symlink():
        raise ValueError("aliased progress input")
    return json.loads(path.read_bytes())


def _source(root: Path = ROOT) -> dict[str, str]:
    names = ("durable_runner.py", "pytest_finish.py", "run_progress.py")
    paths = [root / "src/sciplot_core/verification" / name for name in names]
    if root.is_symlink() or any(path.is_symlink() for path in paths):
        raise ValueError("aliased progress source")
    return {"root": str(root), "sha256": _digest([hashlib.sha256(path.read_bytes()).hexdigest() for path in paths])}


def _log_bytes(directory: Path) -> int:
    path = directory / "command.log"
    return path.stat().st_size if path.is_file() and not path.is_symlink() else 0


def write_diagnostic(path: Path, value: dict[str, Any]) -> bool:
    """Atomic replacement without fsync; losing this mutable diagnostic is safe."""
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    created = False
    try:
        if path.is_symlink():
            return False
        with temporary.open("x", encoding="utf-8") as stream:
            created = True
            json.dump(value, stream, sort_keys=True, allow_nan=False)
            stream.write("\n")
        temporary.replace(path)
        return True
    except Exception:
        return False
    finally:
        if created:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def _base(directory: Path) -> dict[str, Any]:
    request = directory / "request.json"
    return {"version": 1, "claim": _CLAIM, "source": _source(),
            "request_sha256": hashlib.sha256(request.read_bytes()).hexdigest() if request.is_file() and not request.is_symlink() else None}


def stage_progress(directory: Path, request_hash: str, stage: str, timings: dict[str, float],
                   started_at: float, stage_started_at: float,
                   started_monotonic: float, stage_started_monotonic: float) -> dict[str, Any] | None:
    try:
        return {**_base(directory), "channel": "runner", "request_sha256": request_hash,
                "started_at": started_at, "updated_at": time.time(), "stage_started_at": stage_started_at,
                "started_monotonic": started_monotonic, "updated_monotonic": time.monotonic(),
                "stage_started_monotonic": stage_started_monotonic,
                "stage": stage, "timings": dict(timings), "log_bytes": _log_bytes(directory)}
    except Exception:
        return None


def record_preparation(directory: Path, request_hash: str, seconds: float) -> None:
    try:
        write_diagnostic(directory / "preparation-progress.json",
                         {"request_sha256": request_hash, "seconds": seconds, "source": _source()})
    except Exception:
        pass


def preparation_seconds(directory: Path, request_hash: str) -> float | None:
    try:
        value = _read(directory / "preparation-progress.json")
        seconds = value["seconds"]
        if value["request_sha256"] == request_hash and value["source"] == _source() and _finite(seconds):
            return float(seconds)
    except Exception:
        pass
    return None


class PytestProgress:
    """Synchronous phase starts; report checkpoints throttle, without fsync."""

    def __init__(self, directory: Path, selected: list[str]) -> None:
        self.directory = directory
        self.selected = set(selected)
        self.closed = False
        self.last_write = float("-inf")
        self.rows: dict[str, int] = {}
        now = time.time()
        monotonic = time.monotonic()
        self.value = {**_base(directory), "channel": "pytest", "pid": os.getpid(),
                      "selected_tests_sha256": _digest(selected), "selected_count": len(selected),
                      "started_at": now, "updated_at": now, "latest_node": None, "latest_phase": "collection",
                      "started_monotonic": monotonic, "updated_monotonic": monotonic,
                      "completed": 0, "passed": 0, "failed": 0, "skipped": 0}
        self._publish()

    def _publish(self) -> None:
        self.last_write = time.monotonic()
        write_diagnostic(self.directory / PYTEST_PROGRESS, {**self.value, "written_at": time.time(),
                                                          "written_monotonic": self.last_write,
                                                          "log_bytes": _log_bytes(self.directory)})

    @staticmethod
    def _classification(row: int) -> str | None:
        return ("failed" if row & 1 else "passed" if row & 4 else "skipped" if row & 2 else None) if row & 8 else None

    def event(self, node: str, phase: str, outcome: str | None = None) -> None:
        try:
            if self.closed or node not in self.selected:
                return
            changed = (node, phase) != (self.value["latest_node"], self.value["latest_phase"])
            self.value.update(latest_node=node, latest_phase=phase, updated_at=time.time(), updated_monotonic=time.monotonic())
            if outcome is not None:
                before = self.rows.get(node, 0)
                after = before | (1 if outcome == "failed" else 0) | (2 if outcome == "skipped" else 0)
                after |= 4 if phase == "call" and outcome == "passed" else 0
                after |= 8 if phase == "teardown" else 0
                previous, current = self._classification(before), self._classification(after)
                self.value["completed"] += bool(after & 8) - bool(before & 8)
                if previous != current:
                    if previous is not None:
                        self.value[previous] -= 1
                    if current is not None:
                        self.value[current] += 1
                self.rows[node] = after
            if (outcome is None and changed) or time.monotonic() - self.last_write >= WRITE_INTERVAL:
                self._publish()
        except Exception:
            pass

    def finish(self) -> None:
        try:
            self.closed = True
            self.value.update(latest_phase="session_finish", updated_at=time.time(), updated_monotonic=time.monotonic())
            self._publish()
        except Exception:
            pass


def _finite(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _bound(value: Any, directory: Path, request: Any, state: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("version") != 1 or value.get("claim") != _CLAIM:
        raise ValueError("unknown progress schema")
    source = value.get("source")
    known_roots = (ROOT, directory / "source")
    if not isinstance(source, dict) or not any(source == _source(root) for root in known_roots if (root / "src/sciplot_core/verification/run_progress.py").is_file()):
        raise ValueError("progress source changed")
    request_hash = hashlib.sha256((directory / "request.json").read_bytes()).hexdigest() if request is not None else None
    if value.get("request_sha256") != request_hash:
        raise ValueError("progress request changed")
    now = time.monotonic()
    for key in ("started_at", "updated_at", "started_monotonic", "updated_monotonic"):
        if not _finite(value.get(key)):
            raise ValueError("invalid progress time")
    if not value["started_monotonic"] <= value["updated_monotonic"] <= now:
        raise ValueError("invalid progress monotonic relation")
    if type(value.get("log_bytes")) is not int or value["log_bytes"] < 0:
        raise ValueError("invalid progress log size")
    if value.get("channel") == "pytest":
        fields = {"version", "claim", "source", "request_sha256", "channel", "pid", "selected_tests_sha256", "selected_count",
                  "started_at", "updated_at", "written_at", "latest_node", "latest_phase", "completed", "passed", "failed", "skipped", "log_bytes"}
        fields |= {"started_monotonic", "updated_monotonic", "written_monotonic"}
        if set(value) != fields or type(value.get("pid")) is not int or value["pid"] <= 0:
            raise ValueError("unknown pytest progress")
        if value.get("latest_phase") not in {"collection", "setup", "call", "teardown", "session_finish"}:
            raise ValueError("unknown pytest phase")
        count = value.get("selected_count")
        if type(count) is not int or count < 0 or any(type(value[k]) is not int or not 0 <= value[k] <= count for k in ("completed", "passed", "failed", "skipped")):
            raise ValueError("invalid progress counts")
        if value["passed"] + value["failed"] + value["skipped"] > value["completed"]:
            raise ValueError("inconsistent progress counts")
        if (not _finite(value.get("written_at")) or not _finite(value.get("written_monotonic"))
                or not value["updated_monotonic"] <= value["written_monotonic"] <= now):
            raise ValueError("invalid progress write time")
        if request is not None:
            selected = request["selected_tests"]
            if request["scope"]["kind"] != "pytest" or value["selected_tests_sha256"] != _digest(selected) or count != len(selected):
                raise ValueError("progress selection changed")
            if not isinstance(state, dict) or value["pid"] != state.get("child_pid"):
                raise ValueError("progress PID changed")
            if value["latest_node"] is not None and value["latest_node"] not in selected:
                raise ValueError("unknown progress node")
        elif value["latest_node"] is not None and not isinstance(value["latest_node"], str):
            raise ValueError("invalid standalone progress node")
    elif value.get("channel") == "runner":
        if set(value) != {"version", "claim", "source", "request_sha256", "channel", "started_at", "updated_at", "stage_started_at", "stage", "timings", "log_bytes",
                          "started_monotonic", "updated_monotonic", "stage_started_monotonic"}:
            raise ValueError("unknown runner progress")
        if value.get("stage") not in {"preparation", "capture_before", "command", "capture_after", "completed", "blocked"} or not _finite(value.get("stage_started_at")):
            raise ValueError("unknown runner stage")
        if (not _finite(value.get("stage_started_monotonic"))
                or not value["started_monotonic"] <= value["stage_started_monotonic"] <= value["updated_monotonic"]):
            raise ValueError("invalid stage monotonic relation")
        if not isinstance(value.get("timings"), dict) or any(k not in {"preparation_seconds", "capture_before_seconds", "command_seconds", "capture_after_seconds"} or not _finite(v) for k, v in value["timings"].items()):
            raise ValueError("invalid stage timings")
    else:
        raise ValueError("unknown progress channel")
    age = now - value["updated_monotonic"]
    return {**value, "available": True, "update_age_seconds": age, "stale": age > 15,
            **({"stage_elapsed_seconds": now - value["stage_started_monotonic"]} if value["channel"] == "runner" else {})}


def read_progress(directory: Path) -> dict[str, Any] | None:
    """Read known mutable files only. This result never changes execution status."""
    try:
        state = _read(directory / "state.json") if (directory / "state.json").is_file() else None
        path = directory / PYTEST_PROGRESS
        stage = state.get("diagnostic") if isinstance(state, dict) else None
        if stage is None and not path.exists():
            return None  # Keep legacy status responses unchanged.
        request = _read(directory / "request.json") if (directory / "request.json").is_file() else None
        result: dict[str, Any] = {"claim": _CLAIM}
        for name, value in (("runner", stage), ("pytest", _read(path) if path.exists() else None)):
            if value is not None:
                try:
                    result[name] = _bound(value, directory, request, state)
                except Exception:
                    result[name] = {"available": False, "reason": "unbound_or_invalid_progress"}
        log = directory / "command.log"
        if log.is_file() and not log.is_symlink():
            stat = log.stat()
            prior = next((result[k] for k in ("pytest", "runner") if result.get(k, {}).get("available")), None)
            growth = stat.st_size - prior["log_bytes"] if prior else None
            result["log"] = {"size_bytes": stat.st_size,
                             "observation_age_seconds": max(0, time.monotonic() - prior["updated_monotonic"]) if prior else None,
                             "growth_since_checkpoint_bytes": growth, "changed_since_checkpoint": growth != 0 if prior else None}
        return result
    except Exception:
        return {"claim": _CLAIM, "available": False, "reason": "progress_unavailable"}
