"""Commit complete native figure sets through the immutable project repository."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from uuid import uuid4

from sciplot_core.figure_plan.plan import resolved_figure_plan_from_payload
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.project_commands.resources import MembershipRead, PreparedFile
from sciplot_core.project_store.adapters import publish_files, store_for_project
from sciplot_core.project_store.io import read_file, sha
from sciplot_core.studio_figure_set_contract import (
    STUDIO_FIGURE_SET_KIND, STUDIO_FIGURE_SET_LEGACY_VERSION, STUDIO_FIGURE_SET_TASK_VERSION,
)
from sciplot_core.studio_core.json_files import _read_json
from sciplot_core.studio_core.figure_set_state import _replace_studio_figure_set_path
from sciplot_core.studio_core.figure_task_evidence import (
    figure_task_from_registry_entry, validate_figure_registry_against_plan, validate_veusz_spec_figure_task,
)
from sciplot_core.studio_core.registry_state import _studio_figure_set_path, _veusz_spec_path


def _captured(path: Path) -> PreparedFile:
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        data, mode = read_file(descriptor, path.name, owned=True)
    finally:
        os.close(descriptor)
    return PreparedFile(data, mode)


def _commit_studio_figure_set_transaction(
    *, project_dir: Path, replacements: list[dict[str, Any]],
    manual_archive_requests: list[dict[str, Any]], registry: dict[str, Any] | None,
    path_replacer: Callable[[Path, Path], None] | None = None,
    command_binding: dict[str, Any] | None = None,
) -> None:
    """Validate private complete candidates, then publish one generation head.

    The injectable replacer operates only in the private candidate tree. Native
    producers with an existing edit session supply its original command binding.
    """
    root = project_dir.expanduser().resolve(strict=True)
    replace_path = path_replacer or _replace_studio_figure_set_path
    source_paths = [Path(item["staged"]) for item in replacements]
    pending: dict[str, PreparedFile] = {}
    archive_members: set[str] = set()
    try:
        if registry is not None:
            _validate_staged_figure_set_task_evidence(project_dir=root, replacements=replacements, registry=registry)
        for item in replacements:
            target, source = Path(item["target"]), Path(item["staged"])
            if target.is_symlink():
                raise RuntimeError(f"Cannot transactionally replace symbolic link {target}.")
            if target.absolute() == source.absolute():
                raise RuntimeError("A prepared figure must be separate from its active destination.")
            logical = target.absolute().relative_to(root).as_posix()
            if logical in pending:
                raise RuntimeError("A figure-set mutation cannot write the same target twice.")
            captured = _captured(source)
            if sha(captured.data) != item["expected_hash"]:
                raise RuntimeError("Prepared figure-set bytes changed before publication.")
            if item["kind"] == "spec" and not isinstance(json.loads(captured.data), dict):
                raise RuntimeError("A staged native spec must be one JSON object.")
            pending[logical] = captured
        if registry is not None:
            if registry.get("kind") != STUDIO_FIGURE_SET_KIND:
                raise RuntimeError("The staged figure-set registry failed validation.")
            name = _studio_figure_set_path(root).relative_to(root).as_posix()
            pending[name] = PreparedFile(json.dumps(json_safe(registry), indent=2, ensure_ascii=False).encode(), 0o644)
        # Candidate producer files are not imported as live project members.
        for source in source_paths:
            source.unlink(missing_ok=True)
        store = store_for_project(root)
        snapshot = store.snapshot(import_legacy=True)
        for request in manual_archive_requests:
            document = Path(request["document"])
            logical = document.absolute().relative_to(root).as_posix()
            before = snapshot["files"].get(logical)
            if logical not in pending or before is None or before["sha256"] == request.get("generated_hash"):
                continue
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ") + "_" + uuid4().hex[:8]
            history = document.parent.relative_to(root) / "history"
            pending[(history / f"{document.stem}_{stamp}{document.suffix}").as_posix()] = PreparedFile(
                store.read_bytes(logical, generation=snapshot["generation"]), before["mode"])
            archive_members.add((history / f"{document.stem}_{stamp}{document.suffix}").as_posix())
            spec = Path(request["spec"]).absolute().relative_to(root).as_posix()
            if spec in pending and spec in snapshot["files"]:
                entry = snapshot["files"][spec]
                pending[(history / f"{document.stem}_{stamp}.spec.json").as_posix()] = PreparedFile(
                    store.read_bytes(spec, generation=snapshot["generation"]), entry["mode"])
                archive_members.add((history / f"{document.stem}_{stamp}.spec.json").as_posix())
        if registry is not None:
            for entry in registry.get("figures", []):
                if not isinstance(entry, dict) or entry.get("status") != "ready":
                    continue
                document_name, spec_name = (Path(entry[field]).absolute().relative_to(root).as_posix() for field in ("document", "spec"))
                if any(name not in pending and name not in snapshot["files"] for name in (document_name, spec_name)):
                    raise RuntimeError(f"Ready figure {entry.get('figure_id')} is incomplete.")
                selected = pending[document_name].data if document_name in pending else store.read_bytes(document_name, generation=snapshot["generation"])
                state = entry.get("document_state")
                expected = state.get("current_hash") if isinstance(state, dict) else entry.get("generated_hash")
                if document_name in pending and expected != sha(selected):
                    raise RuntimeError(f"Ready figure {entry.get('figure_id')} has a stale hash.")
        baseline = command_binding or {"project_id": snapshot["project_id"], "generation": snapshot["generation"],
            "files": {name: entry["sha256"] for name, entry in snapshot["files"].items()},
            "read_memberships": [MembershipRead.capture(snapshot["files"]).to_payload()]}
        baseline = {**baseline, "files": {**baseline["files"]}}
        for name in pending:
            if command_binding is not None and name not in baseline["files"] and name not in archive_members:
                raise RuntimeError("The editing baseline did not observe this figure-set destination.")
            baseline["files"].setdefault(name, snapshot["files"].get(name, {}).get("sha256"))
        with TemporaryDirectory(prefix="sciplot-figure-generation-") as folder:
            candidate = Path(folder)
            frozen = {}
            for index, (name, prepared) in enumerate(pending.items()):
                source = candidate / f"input-{index}"
                destination = candidate / "candidate" / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                source.write_bytes(prepared.data)
                source.chmod(prepared.mode)
                replace_path(source, destination)
                captured = _captured(destination)
                if captured != prepared:
                    raise RuntimeError("The privately installed figure-set candidate failed validation.")
                frozen[name] = captured
            publish_files(store, frozen, kind="figure_set", baseline=baseline)
    finally:
        for source in source_paths:
            source.unlink(missing_ok=True)


def _validate_staged_figure_set_task_evidence(
    *,
    project_dir: Path,
    replacements: list[dict[str, Any]],
    registry: dict[str, Any],
) -> None:
    """Reject task/plan/path/spec splits before the first replacement."""

    version = registry.get("version")
    if version == STUDIO_FIGURE_SET_LEGACY_VERSION:
        if registry.get("resolved_figure_plan") is not None or any(
            isinstance(entry, dict) and "resolved_figure_task" in entry
            for entry in registry.get("figures", [])
        ):
            raise RuntimeError(
                "studio_figure_task_mismatch: legacy v1 registry cannot carry "
                "task-aware evidence."
            )
        return
    if version != STUDIO_FIGURE_SET_TASK_VERSION:
        raise RuntimeError(
            "studio_figure_task_mismatch: figure-set registry version is unsupported."
        )
    try:
        plan = resolved_figure_plan_from_payload(registry.get("resolved_figure_plan"))
        if plan is None:
            raise ValueError("missing resolved FigurePlan")
        validate_figure_registry_against_plan(registry, plan)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            "studio_figure_task_mismatch: task-aware registry does not contain "
            "one exact selected FigurePlan."
        ) from exc

    staged_by_target = {
        Path(str(item["target"])).expanduser().resolve(): Path(str(item["staged"]))
        for item in replacements
    }
    entries = registry.get("figures")
    assert isinstance(entries, list)
    outcomes = {outcome.figure_id: outcome for outcome in plan.outcomes}
    for entry in entries:
        assert isinstance(entry, dict)
        try:
            task = figure_task_from_registry_entry(entry, required=True)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(str(exc)) from exc
        assert task is not None
        document = Path(str(entry.get("document") or "")).expanduser().resolve()
        expected_document = (
            project_dir / "studio" / "document.vsz"
            if task.figure_id == plan.primary_figure_id
            else project_dir / "studio" / "figures" / f"{task.document_stem}.vsz"
        ).resolve()
        expected_spec = _veusz_spec_path(expected_document).resolve()
        spec = Path(str(entry.get("spec") or "")).expanduser().resolve()
        if document != expected_document or spec != expected_spec:
            raise RuntimeError(
                "studio_figure_task_mismatch: figure registry paths do not "
                f"match task `{task.figure_id}`."
            )
        outcome = outcomes[task.figure_id]
        if entry.get("status") == "ready":
            outcome_artifacts = tuple(
                str(Path(value).expanduser().resolve()) for value in outcome.artifacts
            )
            if outcome.status != "editable" or outcome_artifacts != (
                str(document),
                str(spec),
            ):
                raise RuntimeError(
                    "studio_figure_task_mismatch: editable outcome paths do not "
                    f"match task `{task.figure_id}`."
                )
            spec_source = staged_by_target.get(spec, spec)
            if not spec_source.is_file():
                raise RuntimeError(
                    "studio_figure_task_mismatch: ready figure spec is missing "
                    f"for task `{task.figure_id}`."
                )
            validate_veusz_spec_figure_task(
                _read_json(spec_source),
                expected=task,
                source=f"staged Studio figure `{task.figure_id}` Veusz spec",
            )
        elif entry.get("status") == "unavailable":
            if outcome.status != "unavailable":
                raise RuntimeError(
                    "studio_figure_task_mismatch: unavailable registry entry "
                    f"does not match task `{task.figure_id}` outcome."
                )
        else:
            raise RuntimeError(
                "studio_figure_task_mismatch: figure registry status is unsupported."
            )
