"""Commit a complete Studio figure set as one atomic transaction."""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4
from sciplot_core.figure_plan.plan import resolved_figure_plan_from_payload
from sciplot_core.foundation.file_hashing import (
    existing_file_sha256,
)
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.studio_figure_set_contract import (
    STUDIO_FIGURE_SET_KIND,
    STUDIO_FIGURE_SET_LEGACY_VERSION,
    STUDIO_FIGURE_SET_TASK_VERSION,
)

from sciplot_core.studio_core.json_files import (
    _read_json,
)

from sciplot_core.studio_core.figure_set_state import (
    _replace_studio_figure_set_path,
)
from sciplot_core.studio_core.figure_task_evidence import (
    figure_task_from_registry_entry,
    validate_figure_registry_against_plan,
    validate_veusz_spec_figure_task,
)

from sciplot_core.studio_core.registry_state import (
    _studio_figure_set_path,
    _veusz_spec_path,
)


def _commit_studio_figure_set_transaction(
    *,
    project_dir: Path,
    replacements: list[dict[str, Any]],
    manual_archive_requests: list[dict[str, Any]],
    registry: dict[str, Any] | None,
    path_replacer: Callable[[Path, Path], None] | None = None,
) -> None:
    """Install prepared Studio files and an optional registry as one rollback set."""

    replace_path = (
        path_replacer if path_replacer is not None else _replace_studio_figure_set_path
    )
    registry_path = _studio_figure_set_path(project_dir)
    staged_registry: Path | None = None
    pending = list(replacements)
    if registry is not None:
        staged_registry = registry_path.with_name(
            f".sciplot-figure-set-transaction-{uuid4().hex}.json"
        )
        try:
            staged_registry.write_text(
                json.dumps(json_safe(registry), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            staged_registry_payload = _read_json(staged_registry)
        except Exception:
            staged_registry.unlink(missing_ok=True)
            raise
        if staged_registry_payload.get("kind") != STUDIO_FIGURE_SET_KIND:
            staged_registry.unlink(missing_ok=True)
            raise RuntimeError("The staged figure-set registry failed validation.")
        registry_hash = existing_file_sha256(staged_registry)
        if not registry_hash:
            staged_registry.unlink(missing_ok=True)
            raise RuntimeError("The staged figure-set registry is empty.")
        pending.append(
            {
                "staged": staged_registry,
                "target": registry_path,
                "expected_hash": registry_hash,
                "kind": "registry",
            }
        )
    records: list[dict[str, Any]] = []
    archived_paths: list[Path] = []
    created_history_dirs: list[Path] = []
    committed = False
    rollback_incomplete = False
    try:
        if registry is not None:
            _validate_staged_figure_set_task_evidence(
                project_dir=project_dir,
                replacements=replacements,
                registry=registry,
            )
        for item in pending:
            target = Path(item["target"])
            prior_hash = existing_file_sha256(target)
            backup = None
            if target.exists():
                if not target.is_file() or not prior_hash:
                    raise RuntimeError(
                        f"Cannot transactionally replace invalid file {target}."
                    )
                backup = target.with_name(
                    f".sciplot-figure-set-transaction-{uuid4().hex}.backup"
                )
            record = {
                **item,
                "target": target,
                "prior_hash": prior_hash,
                "backup": backup,
                "installed": False,
            }
            records.append(record)
            if backup is not None:
                shutil.copy2(target, backup)
                if existing_file_sha256(backup) != prior_hash:
                    raise RuntimeError(
                        f"Could not verify the figure-set backup for {target}."
                    )

        by_target = {record["target"]: record for record in records}
        file_records = records[:-1] if registry is not None else records
        for record in file_records:
            replace_path(record["staged"], record["target"])
            record["installed"] = True
            if existing_file_sha256(record["target"]) != record["expected_hash"]:
                raise RuntimeError(
                    f"Installed figure-set {record['kind']} failed validation."
                )
            if record["kind"] == "spec":
                _read_json(record["target"])

        for request in manual_archive_requests:
            document_path = Path(request["document"])
            document_record = by_target.get(document_path)
            if document_record is None or document_record["backup"] is None:
                continue
            current_hash = document_record["prior_hash"]
            generated_hash = request.get("generated_hash")
            if generated_hash and current_hash == generated_hash:
                continue
            history_dir = document_path.parent / "history"
            if not history_dir.exists():
                history_dir.mkdir(parents=True)
                created_history_dirs.append(history_dir)
            stamp = (
                datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ") + f"_{uuid4().hex[:8]}"
            )
            archived_document = (
                history_dir / f"{document_path.stem}_{stamp}{document_path.suffix}"
            )
            archived_paths.append(archived_document)
            shutil.copy2(document_record["backup"], archived_document)
            if existing_file_sha256(archived_document) != current_hash:
                raise RuntimeError(
                    f"Could not verify the manual figure archive for {document_path}."
                )
            spec_path = Path(request["spec"])
            spec_record = by_target.get(spec_path)
            if spec_record is not None and spec_record["backup"] is not None:
                archived_spec = history_dir / f"{document_path.stem}_{stamp}.spec.json"
                archived_paths.append(archived_spec)
                shutil.copy2(spec_record["backup"], archived_spec)
                if existing_file_sha256(archived_spec) != spec_record["prior_hash"]:
                    raise RuntimeError(
                        f"Could not verify the manual spec archive for {spec_path}."
                    )

        if registry is not None:
            registry_record = records[-1]
            replace_path(registry_record["staged"], registry_record["target"])
            registry_record["installed"] = True
            if existing_file_sha256(registry_path) != registry_record[
                "expected_hash"
            ] or _read_json(registry_path) != json_safe(registry):
                raise RuntimeError(
                    "The installed figure-set registry failed validation."
                )
            for entry in registry.get("figures", []):
                if not isinstance(entry, dict) or entry.get("status") != "ready":
                    continue
                document = Path(str(entry.get("document") or ""))
                spec = Path(str(entry.get("spec") or ""))
                if not document.is_file() or not spec.is_file():
                    raise RuntimeError(
                        f"Ready figure {entry.get('figure_id')} is incomplete."
                    )
                _read_json(spec)
                document_record = by_target.get(document)
                document_state = entry.get("document_state")
                expected_current_hash = (
                    document_state.get("current_hash")
                    if isinstance(document_state, dict)
                    else entry.get("generated_hash")
                )
                if (
                    document_record is not None
                    and expected_current_hash != existing_file_sha256(document)
                ):
                    raise RuntimeError(
                        f"Ready figure {entry.get('figure_id')} has a stale hash."
                    )
        committed = True
    except Exception as exc:
        for path in reversed(archived_paths):
            path.unlink(missing_ok=True)
        rollback_errors: list[str] = []
        for record in reversed(records):
            if not record["installed"]:
                continue
            target = record["target"]
            backup = record["backup"]
            try:
                if backup is None:
                    target.unlink(missing_ok=True)
                else:
                    # Keep the verified backup until restoration itself has
                    # been hash-checked. If the copy fails, the original bytes
                    # remain beside the target for recovery instead of being
                    # consumed by the rollback attempt.
                    shutil.copy2(backup, target)
                if existing_file_sha256(target) != record["prior_hash"]:
                    raise RuntimeError("restored hash mismatch")
            except Exception as rollback_exc:
                rollback_errors.append(f"{target}: {rollback_exc}")
        if rollback_errors:
            rollback_incomplete = True
            raise RuntimeError(
                "Figure-set transaction failed and rollback was incomplete: "
                + "; ".join(rollback_errors)
            ) from exc
        raise
    finally:
        for record in records:
            Path(record["staged"]).unlink(missing_ok=True)
            backup = record["backup"]
            if backup is not None and not rollback_incomplete:
                backup.unlink(missing_ok=True)
        if staged_registry is not None:
            staged_registry.unlink(missing_ok=True)
        if not committed:
            for history_dir in reversed(created_history_dirs):
                try:
                    history_dir.rmdir()
                except OSError:
                    pass


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
