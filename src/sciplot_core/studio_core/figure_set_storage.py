"""Commit a complete Studio figure set as one atomic transaction."""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4
from sciplot_core.foundation.file_hashing import (
    existing_file_sha256,
)
from sciplot_core.foundation.json_values import json_safe

from sciplot_core.studio_core.json_files import (
    _read_json,
)

from sciplot_core.studio_core.figure_set_state import (
    _replace_studio_figure_set_path,
)

from sciplot_core.studio_core.registry_state import (
    _studio_figure_set_path,
)


def _commit_studio_figure_set_transaction(
    *,
    project_dir: Path,
    replacements: list[dict[str, Any]],
    manual_archive_requests: list[dict[str, Any]],
    registry: dict[str, Any],
    path_replacer: Callable[[Path, Path], None] | None = None,
) -> None:
    """Install secondary VSZ/spec files and their registry as one rollback set."""

    replace_path = (
        path_replacer if path_replacer is not None else _replace_studio_figure_set_path
    )
    registry_path = _studio_figure_set_path(project_dir)
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
    if staged_registry_payload.get("kind") != "sciplot_studio_figure_set":
        staged_registry.unlink(missing_ok=True)
        raise RuntimeError("The staged figure-set registry failed validation.")
    registry_hash = existing_file_sha256(staged_registry)
    if not registry_hash:
        staged_registry.unlink(missing_ok=True)
        raise RuntimeError("The staged figure-set registry is empty.")

    pending = [
        *replacements,
        {
            "staged": staged_registry,
            "target": registry_path,
            "expected_hash": registry_hash,
            "kind": "registry",
        },
    ]
    records: list[dict[str, Any]] = []
    archived_paths: list[Path] = []
    created_history_dirs: list[Path] = []
    committed = False
    rollback_incomplete = False
    try:
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
        for record in records[:-1]:
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

        registry_record = records[-1]
        replace_path(registry_record["staged"], registry_record["target"])
        registry_record["installed"] = True
        if existing_file_sha256(registry_path) != registry_record[
            "expected_hash"
        ] or _read_json(registry_path) != json_safe(registry):
            raise RuntimeError("The installed figure-set registry failed validation.")
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
            if document_record is not None and entry.get(
                "generated_hash"
            ) != existing_file_sha256(document):
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
        staged_registry.unlink(missing_ok=True)
        if not committed:
            for history_dir in reversed(created_history_dirs):
                try:
                    history_dir.rmdir()
                except OSError:
                    pass
