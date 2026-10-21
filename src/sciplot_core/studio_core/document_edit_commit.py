"""Durable native-edit outcomes and one-document replacement with rollback."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.json_io import atomic_write_json
from sciplot_core.studio_core.delivery_recovery import _write_durable
from sciplot_core.studio_core.document_edit_state import edit_state, history_directory, preview_identity
from sciplot_core.studio_core.delivery_recovery_state import canonical_path
from sciplot_core.studio_core.project_query_paths import read_object
from sciplot_core.studio_core.document_edit_companion import (
    archive_companion, companion_path, recover_companion, replace_companion,
)


def applied_native_edit_chain(
    project: Path, *, figure_id: str, document: Path, spec: Path,
    baseline_files: dict[str, Any],
) -> list[str] | None:
    """Prove saved native continuation from a historical shadow, without adopting it.

    Only complete applied operations and their byte-sealed archives can bridge
    the old native/spec pair. Source and other binding files must still match
    every reviewed baseline. The caller retains source guards and native audit.
    """
    project, document, spec = map(canonical_path, (project, document, spec))
    baseline = (baseline_files[str(document)], baseline_files[str(spec)])
    current = (file_sha256(document), file_sha256(spec))
    relative_document, relative_spec = str(document.relative_to(project)), str(spec.relative_to(project))
    history = history_directory(project, "0" * 64).parent
    if not history.is_dir():
        return None
    transitions: dict[tuple[str, str], list[tuple[tuple[str, str], str]]] = {}
    entries = sorted(history.iterdir())
    if len(entries) > 2000:
        raise ValueError("Native edit history exceeds the bounded evidence budget.")
    for entry in entries:
        operation = entry.name
        if len(operation) != 64 or any(c not in "0123456789abcdef" for c in operation):
            continue
        root = history_directory(project, operation)
        record = read_object(root / "outcome.json")
        if record.get("document_relative") != relative_document:
            continue
        if record.get("status") != "applied":
            # Pending/rolled-back history cannot prove a saved transition.
            continue
        review = read_object(root / "preview.json")
        if (
            review.get("operation_id") != operation
            or preview_identity(review) != operation
            or review.get("kind") != "sciplot_document_edit_preview"
            or review.get("version") not in {1, 2}
            or review.get("status") != "ready"
            or review.get("project") != str(project)
            or review.get("figure_id") != figure_id
            or review.get("document") != str(document)
            or (review.get("scientific_audit") or {}).get("status") != "passed"
        ):
            raise ValueError("Native edit history has an invalid reviewed identity.")
        files = review["base_state"]["project_files"]
        before_document, after_document = record["base_sha256"], record["result_sha256"]
        if (
            review["document_sha256"] != before_document
            or files[relative_document] != before_document
            or file_sha256(canonical_path(root / "before.vsz")) != before_document
            or file_sha256(canonical_path(root / "after.vsz")) != after_document
        ):
            raise ValueError("Native edit history document archives changed.")
        for name, digest in baseline_files.items():
            path = Path(name)
            if path not in {document, spec} and path.is_relative_to(project):
                if files.get(str(path.relative_to(project))) != digest:
                    raise ValueError("Native edit history used another source or project baseline.")
        before_spec = after_spec = files[relative_spec]
        companion = record.get("companion")
        if review["version"] == 2:
            if not isinstance(companion, dict) or companion_path(project, companion) != spec:
                raise ValueError("Native edit history lost its specification companion.")
            before_spec, after_spec = companion["base_sha256"], companion["result_sha256"]
            if (
                review.get("spec") != str(spec)
                or files[relative_spec] != before_spec
                or review["candidate_spec"]["sha256"] != after_spec
                or file_sha256(canonical_path(root / "before.spec.json")) != before_spec
                or file_sha256(canonical_path(root / "after.spec.json")) != after_spec
            ):
                raise ValueError("Native edit history specification archives changed.")
        elif companion is not None:
            raise ValueError("Native edit history has an unexpected specification companion.")
        before, after = (before_document, before_spec), (after_document, after_spec)
        if before != after:
            transitions.setdefault(after, []).append((before, operation))
    chain: list[str] = []
    state = current
    visited = set()
    while state != baseline:
        if state in visited or len(transitions.get(state, [])) != 1:
            return None
        visited.add(state)
        state, operation = transitions[state][0]
        chain.append(operation)
    if (file_sha256(document), file_sha256(spec)) != current:
        raise ValueError("The saved native revision changed during history inspection.")
    return list(reversed(chain))


def read_edit_operation(project: Path, operation_id: str) -> dict[str, Any]:
    root = history_directory(project, operation_id)
    record_path = canonical_path(root / "outcome.json")
    if not record_path.is_file():
        raise ValueError("No recorded document edit with that operation identity.")
    record = json.loads(record_path.read_text())
    relative = Path(record["document_relative"])
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or relative.parts[:1] != ("studio",)
    ):
        raise ValueError("The recorded edit does not name a managed document.")
    document = canonical_path(project / relative)
    current = file_sha256(document) if document.is_file() else None
    companion = record.get("companion")
    companion_current = (
        file_sha256(companion_path(project, companion)) == companion["result_sha256"]
        if isinstance(companion, dict) else True
    )
    return {
        "kind": "sciplot_document_edit_outcome",
        "version": 1,
        "project": str(project),
        "operation_id": operation_id,
        "status": record["status"],
        "document": str(document),
        "document_sha256": current,
        "result_sha256": record["result_sha256"],
        "result_is_current": current == record["result_sha256"] and companion_current,
        "previous_document_sha256": record["base_sha256"],
        "archive": str(root / "before.vsz"),
        "ready_to_use": False,
        "export_required": None,
        "readiness_evaluated": False,
    }


def prior_edit_result(project: Path, review: dict[str, Any]) -> dict[str, Any] | None:
    root = history_directory(project, review["operation_id"])
    if not (root / "outcome.json").exists():
        return None
    stored = json.loads((root / "preview.json").read_text())
    if stored != review:
        raise ValueError("The stored operation does not match this edit preview.")
    pending = json.loads((root / "outcome.json").read_text())
    recover_companion(project, root, pending, review)
    outcome = read_edit_operation(project, review["operation_id"])
    if outcome["result_is_current"]:
        # A process can stop after replace but before writing its success reply.
        # The durable intent and archived before/after files prove that case.
        pending = json.loads((root / "outcome.json").read_text())
        if file_sha256(root / "after.vsz") != pending["result_sha256"]:
            raise ValueError("Document edit recovery evidence changed.")
        if file_sha256(root / "before.vsz") != pending["base_sha256"]:
            raise ValueError("Document edit archive changed.")
        pending["status"] = "applied"
        atomic_write_json(root / "outcome.json", pending)
        return {**outcome, "status": "already_applied"}
    if outcome["status"] == "applied":
        raise ValueError(
            "This edit was applied, but the document has since changed. Inspect current state."
        )
    if outcome["document_sha256"] != outcome["previous_document_sha256"]:
        raise ValueError(
            "An interrupted edit has a conflicting current document. Preserve its archive."
        )
    return None


def _replace_current_document(staged: Path, document: Path) -> None:
    os.replace(staged, document)


def commit_document_edit(
    project: Path,
    document: Path,
    candidate: Path,
    review: dict[str, Any],
    *, spec: Path | None = None, candidate_spec: Path | None = None,
) -> dict[str, Any]:
    """Caller holds the external-session and canonical-project locks."""
    before_state = review["base_state"]
    if edit_state(project) != before_state:
        raise ValueError(
            "Project or delivery changed after preview; inspect current state."
        )
    original = document.read_bytes()
    original_mode = document.stat().st_mode & 0o777
    base_hash = file_sha256(document)
    result_hash = file_sha256(candidate)
    root = history_directory(project, review["operation_id"])
    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    before_path, after_path = root / "before.vsz", root / "after.vsz"
    if before_path.exists():
        if file_sha256(before_path) != base_hash:
            raise ValueError("The archived edit baseline conflicts with current state.")
    else:
        _write_durable(before_path, original)
    # A retry before commit may produce a different harmless native-save timestamp.
    atomic_write_json(root / "preview.json", review)
    shutil.copyfile(candidate, after_path)
    with after_path.open("rb") as handle:
        os.fsync(handle.fileno())
    record: dict[str, Any] = {
        "status": "pending",
        "document_relative": str(document.relative_to(project)),
        "base_sha256": base_hash,
        "result_sha256": result_hash,
    }
    if (spec is None) != (candidate_spec is None):
        raise ValueError("Annotation commits require both current and candidate specifications.")
    if spec is not None and candidate_spec is not None:
        record["companion"] = archive_companion(project, spec, candidate_spec, root)
    atomic_write_json(root / "outcome.json", record)
    descriptor, name = tempfile.mkstemp(
        prefix=".external-edit-", suffix=".vsz", dir=document.parent
    )
    os.close(descriptor)
    staged = Path(name)
    replaced = False
    companion_replaced = False
    try:
        shutil.copyfile(after_path, staged)
        staged.chmod(original_mode)
        with staged.open("rb") as handle:
            os.fsync(handle.fileno())
        # Exclude our temporary install file from the active project inventory.
        expected = {
            **before_state,
            "project_files": {
                **before_state["project_files"],
                str(staged.relative_to(project)): result_hash,
            },
        }
        if edit_state(project) != expected:
            raise ValueError("Project changed during staging; no edit was installed.")
        if spec is not None and candidate_spec is not None:
            replace_companion(spec, candidate_spec.read_bytes(), record["companion"]["mode"])
            companion_replaced = True
        _replace_current_document(staged, document)
        replaced = True
        after_state = {
            **before_state,
            "project_files": {
                **before_state["project_files"],
                str(document.relative_to(project)): result_hash,
            },
        }
        if spec is not None:
            after_state["project_files"][str(spec.relative_to(project))] = record["companion"]["result_sha256"]
        if edit_state(project) != after_state:
            raise ValueError("Project changed during edit installation.")
        record["status"] = "applied"
        atomic_write_json(root / "outcome.json", record)
    except BaseException:
        if companion_replaced and spec is not None:
            replace_companion(spec, (root / "before.spec.json").read_bytes(), record["companion"]["mode"])
        if replaced:
            if document.is_file() and file_sha256(document) != result_hash:
                shutil.copyfile(document, root / "conflicting_document.vsz")
            with staged.open("wb") as handle:
                handle.write(original)
                handle.flush()
                os.fsync(handle.fileno())
            staged.chmod(original_mode)
            os.replace(staged, document)
        record["status"] = "rolled_back"
        atomic_write_json(root / "outcome.json", record)
        raise
    finally:
        staged.unlink(missing_ok=True)
    return {
        **read_edit_operation(project, review["operation_id"]),
        "export_required": True,
    }
