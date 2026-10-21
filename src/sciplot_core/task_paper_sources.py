"""Read existing project authority and close exact selected source versions."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.source_coverage.file_snapshots import stable_file_snapshot, _assert_snapshot_current
from sciplot_core.source_coverage.managed_documents import source_records
from sciplot_core.studio_core.project_query import resolve_project_figure
from sciplot_core.studio_core.project_query_evidence import source_indicators
from sciplot_core.studio_core.project_query_paths import canonical_path, project_snapshot
from sciplot_core.task_contract import TaskControlError
from sciplot_core.veusz_runtime import veusz_worker_environment


def native_link_sources(document: Path) -> list[dict[str, Any]]:
    completed = subprocess.run([sys.executable, "-m", "sciplot_core.task_paper_native", "inspect", str(document)],
                               env=veusz_worker_environment(), capture_output=True, text=True, timeout=120, check=False)
    if completed.returncode:
        raise TaskControlError("paper_native_sources_unverified", completed.stderr[-2000:])
    result = json.loads(completed.stdout)
    if not isinstance(result, list):
        raise TaskControlError("paper_native_sources_unverified", "The selected native source inventory is invalid.")
    return result


def capture_selection(project: Path, figure_id: str) -> dict[str, Any]:
    selected = resolve_project_figure(project, figure_id)
    root = Path(selected["project"])
    request, _, figures = project_snapshot(root)
    source = source_indicators(root, request, [next(f for f in figures if f["figure_id"] == figure_id)])
    if source["current"] is False or source["prepared"]["current"] is not True:
        raise TaskControlError("paper_source_stale", "The selected figure's recorded sources are stale or unverified.")
    spec = json.loads(Path(selected["spec"]).read_text())
    files = source_records(spec)
    for record in native_link_sources(Path(selected["document"])):
        path = canonical_path(Path(record["path"]))
        if path in files and files[path] != record["sha256"]:
            raise TaskControlError("paper_source_stale", "Native imports and scientific source records disagree.")
        files[path] = record["sha256"]
    roots: set[Path] = set()
    for key in ("input", "input_path", "data_dir"):
        value = request.get(key)
        if isinstance(value, str) and value:
            path = Path(value).expanduser()
            roots.add(canonical_path(path if path.is_absolute() else root / path))
    for sample in (request.get("study_model") or {}).get("samples", []):
        for replicate in sample.get("replicates", []):
            record = replicate.get("source_file") or {}
            if isinstance(record.get("raw_path"), str):
                path = canonical_path(Path(record["raw_path"]))
                if record.get("sha256") and file_sha256(path) != record["sha256"]:
                    raise TaskControlError("paper_source_stale", "A recorded original source changed.")
                roots.add(path)
    memberships = {}
    for path in sorted(roots):
        members = [path] if path.is_file() else sorted(p for p in path.rglob("*") if p.is_file())
        if not members:
            raise TaskControlError("paper_source_missing", f"No source files exist at {path}.")
        memberships[str(path)] = [str(canonical_path(member)) for member in members]
        for member in members:
            files.setdefault(canonical_path(member), file_sha256(member))
    snapshots = []
    for path, expected in sorted(files.items()):
        snapshot = stable_file_snapshot(canonical_path(path), label="paper scientific source")
        if snapshot["sha256"] != expected:
            raise TaskControlError("paper_source_stale", f"Recorded scientific source changed: {path}")
        snapshots.append(snapshot)
    for snapshot in snapshots:
        _assert_snapshot_current(snapshot, label="paper scientific source")
    source_hashes = {str(s["path"]): s["sha256"] for s in snapshots}
    version = {"request_sha256": file_sha256(root / "plot_request.json"),
               "document_sha256": selected["document_sha256"], "spec_sha256": selected["spec_sha256"],
               "source_sha256": canonical_json_sha256({"files": source_hashes, "memberships": memberships}, allow_nan=False)}
    return {"project": str(root), "figure_id": figure_id, "document": selected["document"],
            "spec": selected["spec"], "version": version, "source_files": source_hashes,
            "source_memberships": memberships,
            "source_identities": {str(s["path"]): {k: v for k, v in s["identity"].items() if k != "ctime_ns"}
                                  for s in snapshots},
            "figure_set_sha256": file_sha256(root / "studio/figure_set.json")
            if (root / "studio/figure_set.json").exists() else None,
            "source_scope": source["scope"], "document_authority": "saved_vsz"}


def assert_selection_current(selection: dict[str, Any]) -> None:
    project = Path(selection["project"])
    current = resolve_project_figure(project, selection["figure_id"])
    version = selection["version"]
    registry = project / "studio/figure_set.json"
    if (current["project"] != selection["project"]
            or current["document"] != selection["document"] or current["spec"] != selection["spec"]
            or current["document_sha256"] != version["document_sha256"]
            or current["spec_sha256"] != version["spec_sha256"]
            or file_sha256(project / "plot_request.json") != version["request_sha256"]
            or (file_sha256(registry) if registry.exists() else None) != selection["figure_set_sha256"]):
        raise TaskControlError("paper_selection_changed", "A selected project's identity, specification or saved VSZ changed. Start a new paper selection.")
    for value, expected in selection["source_memberships"].items():
        path = canonical_path(Path(value))
        members = [path] if path.is_file() else sorted(p for p in path.rglob("*") if p.is_file())
        if [str(canonical_path(member)) for member in members] != expected:
            raise TaskControlError("paper_selection_changed", "A selected scientific source's file membership changed.")
    snapshots = []
    for value, expected in selection["source_files"].items():
        snapshot = stable_file_snapshot(canonical_path(Path(value)), label="paper scientific source")
        identity = {k: v for k, v in snapshot["identity"].items() if k != "ctime_ns"}
        if snapshot["sha256"] != expected or identity != selection["source_identities"][value]:
            raise TaskControlError("paper_selection_changed", "A selected scientific source changed. Start a new paper selection.")
        snapshots.append(snapshot)
    for snapshot in snapshots:
        _assert_snapshot_current(snapshot, label="paper scientific source")
