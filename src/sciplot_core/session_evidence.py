from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from collections import Counter
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Iterator
from uuid import uuid4

from sciplot_core._paths import (
    REPO_ROOT,
    VEUSZ_ROOT,
    VEUSZ_UPSTREAM_COMMIT,
)
from sciplot_core._utils import file_sha256
from sciplot_core.canvas.persistence import (
    atomic_write_json,
    load_canvas_session,
    load_composition_project,
    load_review_annotations,
)
from sciplot_core.data_mapping import load_data_mapping_execution
from sciplot_core.readiness import DEFAULT_VALIDATED_ENVELOPE_REGISTRY
from sciplot_core.session_evidence_artifacts import (
    artifact_content_record,
    audit_native_composition_runtime,
    require_within,
    verify_composition_production_qa,
    verify_regular_production_qa,
    verify_regular_source_lineage,
)
from sciplot_core.session_evidence_runtime import (
    inspect_wheel_against_runtime,
    runtime_identity,
)

SESSION_EVIDENCE_EVENT_KIND = "sciplot_session_evidence_event"
SESSION_EVIDENCE_EVENT_VERSION = 1
SESSION_EVIDENCE_HEAD_KIND = "sciplot_session_evidence_head"
SESSION_EVIDENCE_HEAD_VERSION = 1
SESSION_EVIDENCE_PENDING_KIND = "sciplot_session_evidence_pending_append"
SESSION_EVIDENCE_PENDING_VERSION = 1
SESSION_EVIDENCE_STATUS_KIND = "sciplot_session_evidence_status"
SESSION_EVIDENCE_STATUS_VERSION = 1
GENESIS_SHA256 = "0" * 64

ACCEPTANCE_LANES = (
    "rheology_dma_torque",
    "spectroscopy_scattering_chromatography",
    "thermal_analysis",
    "mechanical_categorical_swelling",
    "scalar_review_composition",
)
SESSION_SCOPES = (
    "m3_live_model_scored",
    "m6_discovery",
    "m6_qualification",
    "formal_contract_probe",
    "synthetic_probe",
)
SOURCE_CLASSES = (
    "owner_authorized_real",
    "public_authorized_real",
    "synthetic_contract_fixture",
)
ENTRY_ROUTES = (
    "studio",
    "canvas",
    "compose",
    "autoplot",
    "one_step",
    "mapped_candidate_canvas",
    "advanced_editor",
    "cli_run",
)
EXPECTED_EVIDENCE = (
    "canvas_lifecycle",
    "provider_disabled",
    "ai_operation",
    "cancellation_rollback",
    "data_mapping",
    "review_sidecar",
    "review_promotion",
    "composition_lifecycle",
)
CANONICAL_MODEL_TASKS = (
    "axis_format",
    "multi_series",
    "spatial_legend",
    "review_promotion",
    "qa_layout_repair",
    "cancellation_rollback",
)
SESSION_OUTCOMES = ("pass", "needs_fix", "abandoned")
MODEL_SCORES = ("correct", "incorrect", "not_applicable")
EXTERNAL_EDITOR_USES = ("none", "recorded_p2", "unrecorded")
FALLBACK_CLASSES = (
    "p0_integrity",
    "p1_ordinary",
    "p2_low_frequency",
    "p3_distribution",
)

_FORMAL_SCOPES = {
    "m3_live_model_scored",
    "m6_discovery",
    "m6_qualification",
}
_FROZEN_BUILD_SCOPES = _FORMAL_SCOPES | {"formal_contract_probe"}
_SYNTHETIC_SCOPES = {"formal_contract_probe", "synthetic_probe"}
_HASH = re.compile(r"^[0-9a-f]{64}$")
_EVENT_TYPES = ("preregistered", "reopen_witnessed", "completed")
_EVENT_KEYS = {
    "kind",
    "version",
    "sequence",
    "event_id",
    "event_type",
    "session_id",
    "recorded_at",
    "previous_event_sha256",
    "payload",
    "event_sha256",
}
_PREREGISTRATION_KEYS = {
    "owner",
    "lane",
    "scope",
    "source_class",
    "task",
    "round_id",
    "task_fingerprint",
    "entry_route",
    "expected_evidence",
    "sources",
    "project",
    "build",
    "operation_journal_baseline",
    "provider",
    "model",
    "canonical_task",
    "attempt",
    "limitations",
}
_WITNESS_KEYS = {
    "owner",
    "attestation",
    "authority_mode",
    "authority",
    "journal",
    "optional_evidence",
    "limitations",
}
_COMPLETION_KEYS = {
    "owner",
    "outcome",
    "active_seconds",
    "failures",
    "fallback_events",
    "external_editor_use",
    "model_score",
    "authority",
    "manifest",
    "evidence_checks",
    "evaluation",
    "limitations",
}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _required_text(
    value: object,
    label: str,
    *,
    maximum: int = 2048,
) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be text.")
    text = value.strip()
    if not text:
        raise ValueError(f"{label} cannot be empty.")
    if len(text) > maximum:
        raise ValueError(f"{label} exceeds {maximum} characters.")
    return text


def _optional_text(
    value: object,
    label: str,
    *,
    maximum: int = 2048,
) -> str | None:
    if value is None:
        return None
    return _required_text(value, label, maximum=maximum)


def _closed_text(value: object, label: str, choices: tuple[str, ...]) -> str:
    text = _required_text(value, label, maximum=128)
    if text not in choices:
        raise ValueError(
            f"{label} must be one of: {', '.join(choices)}; received {text!r}."
        )
    return text


def _required_int(value: object, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an integer.")
    if value < minimum:
        raise ValueError(f"{label} must be at least {minimum}.")
    return value


def _required_number(value: object, label: str, *, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{label} must be numeric.")
    number = float(value)
    if number < minimum:
        raise ValueError(f"{label} must be at least {minimum:g}.")
    return number


def _required_hash(value: object, label: str) -> str:
    text = _required_text(value, label, maximum=64).casefold()
    if _HASH.fullmatch(text) is None:
        raise ValueError(f"{label} must be a lowercase SHA-256 digest.")
    return text


def _required_timestamp(value: object, label: str) -> str:
    text = _required_text(value, label, maximum=80)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO-8601 timestamp.") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must include a timezone.")
    return text


def _object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object.")
    return value


def _list(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list.")
    return value


def _reject_unknown(
    value: dict[str, Any],
    allowed: set[str],
    *,
    label: str,
) -> None:
    unknown = set(value) - allowed
    if unknown:
        raise ValueError(f"{label} has unknown fields: {sorted(unknown)!r}.")


def _read_json(path: Path, label: str) -> dict[str, Any]:
    target = path.expanduser().resolve()
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise FileNotFoundError(f"{label} not found: {target}") from None
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} is not valid JSON: {target}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain an object: {target}")
    return value


def _validate_hash_file_record(
    value: object,
    *,
    label: str,
    path_field: str = "path",
) -> dict[str, Any]:
    record = _object(value, label)
    _reject_unknown(
        record,
        {path_field, "size_bytes", "sha256"},
        label=label,
    )
    _required_text(record.get(path_field), f"{label}.{path_field}")
    _required_int(record.get("size_bytes"), f"{label}.size_bytes")
    _required_hash(record.get("sha256"), f"{label}.sha256")
    return record


def _validate_build_payload(value: object) -> dict[str, Any]:
    build = _object(value, "build")
    _reject_unknown(
        build,
        {
            "git",
            "artifact",
            "artifact_contract",
            "validated_envelope_registry",
            "runtime",
        },
        label="build",
    )
    git = _object(build.get("git"), "build.git")
    _reject_unknown(
        git,
        {
            "repo",
            "commit",
            "branch",
            "worktree_clean",
            "status_sha256",
        },
        label="build.git",
    )
    _required_text(git.get("repo"), "build.git.repo")
    commit = git.get("commit")
    if commit is not None:
        _required_text(commit, "build.git.commit", maximum=80)
    branch = git.get("branch")
    if branch is not None:
        _required_text(branch, "build.git.branch", maximum=300)
    if not isinstance(git.get("worktree_clean"), bool):
        raise ValueError("build.git.worktree_clean must be boolean.")
    _required_hash(git.get("status_sha256"), "build.git.status_sha256")

    artifact = _validate_hash_file_record(
        build.get("artifact"),
        label="build.artifact",
    )
    contract = _object(
        build.get("artifact_contract"),
        "build.artifact_contract",
    )
    contract_kind = _required_text(
        contract.get("kind"),
        "build.artifact_contract.kind",
        maximum=100,
    )
    if contract_kind == "sciplot_frozen_wheel_runtime_match":
        _reject_unknown(
            contract,
            {
                "kind",
                "version",
                "wheel",
                "wheel_sha256",
                "wheel_size_bytes",
                "distribution",
                "record_member",
                "record_verified",
                "package_member_count",
                "package_tree_sha256",
                "runtime_import_roots",
                "runtime_content_matches_wheel",
            },
            label="build.artifact_contract",
        )
        if contract.get("version") != 1:
            raise ValueError("Unsupported frozen-wheel artifact contract.")
        _required_text(contract.get("wheel"), "build.artifact_contract.wheel")
        _required_hash(
            contract.get("wheel_sha256"),
            "build.artifact_contract.wheel_sha256",
        )
        _required_int(
            contract.get("wheel_size_bytes"),
            "build.artifact_contract.wheel_size_bytes",
            minimum=1,
        )
        distribution = _object(
            contract.get("distribution"),
            "build.artifact_contract.distribution",
        )
        _reject_unknown(
            distribution,
            {"name", "version"},
            label="build.artifact_contract.distribution",
        )
        _required_text(
            distribution.get("name"),
            "build.artifact_contract.distribution.name",
            maximum=200,
        )
        _required_text(
            distribution.get("version"),
            "build.artifact_contract.distribution.version",
            maximum=100,
        )
        _required_text(
            contract.get("record_member"),
            "build.artifact_contract.record_member",
        )
        if (
            contract.get("record_verified") is not True
            or contract.get("runtime_content_matches_wheel") is not True
        ):
            raise ValueError("Frozen-wheel artifact contract is not verified.")
        _required_int(
            contract.get("package_member_count"),
            "build.artifact_contract.package_member_count",
            minimum=1,
        )
        _required_hash(
            contract.get("package_tree_sha256"),
            "build.artifact_contract.package_tree_sha256",
        )
        roots = _object(
            contract.get("runtime_import_roots"),
            "build.artifact_contract.runtime_import_roots",
        )
        _reject_unknown(
            roots,
            {"sciplot_core", "sciplot_gui", "sciplot_recipes"},
            label="build.artifact_contract.runtime_import_roots",
        )
        if set(roots) != {"sciplot_core", "sciplot_gui", "sciplot_recipes"}:
            raise ValueError(
                "build.artifact_contract.runtime_import_roots is incomplete."
            )
        for package, path in roots.items():
            _required_text(path, f"runtime import root {package}")
    elif contract_kind == "sciplot_synthetic_unverified_build_artifact":
        _reject_unknown(
            contract,
            {
                "kind",
                "version",
                "wheel",
                "wheel_sha256",
                "record_verified",
                "runtime_content_matches_wheel",
            },
            label="build.artifact_contract",
        )
        if (
            contract.get("version") != 1
            or contract.get("record_verified") is not False
            or contract.get("runtime_content_matches_wheel") is not False
        ):
            raise ValueError("Synthetic build artifact contract is inconsistent.")
        _required_text(contract.get("wheel"), "build.artifact_contract.wheel")
        _required_hash(
            contract.get("wheel_sha256"),
            "build.artifact_contract.wheel_sha256",
        )
    else:
        raise ValueError(f"Unsupported build artifact contract: {contract_kind!r}.")
    if Path(str(contract.get("wheel"))).expanduser().resolve() != Path(
        str(artifact["path"])
    ).expanduser().resolve() or contract.get("wheel_sha256") != artifact.get("sha256"):
        raise ValueError("Build artifact and artifact contract disagree.")

    registry = _object(
        build.get("validated_envelope_registry"),
        "build.validated_envelope_registry",
    )
    _reject_unknown(
        registry,
        {"path", "sha256"},
        label="build.validated_envelope_registry",
    )
    _required_text(
        registry.get("path"),
        "build.validated_envelope_registry.path",
    )
    _required_hash(
        registry.get("sha256"),
        "build.validated_envelope_registry.sha256",
    )

    runtime = _object(build.get("runtime"), "build.runtime")
    if contract_kind == "sciplot_synthetic_unverified_build_artifact":
        _reject_unknown(
            runtime,
            {"veusz_upstream_commit", "identity_sha256"},
            label="build.runtime",
        )
    else:
        _reject_unknown(
            runtime,
            {
                "veusz_upstream_commit",
                "veusz",
                "qt_binding",
                "linked_qt_binaries",
                "python",
                "platform",
                "dependencies",
                "identity_sha256",
            },
            label="build.runtime",
        )
        veusz = _object(runtime.get("veusz"), "build.runtime.veusz")
        _reject_unknown(
            veusz,
            {"root", "file_count", "tree_sha256"},
            label="build.runtime.veusz",
        )
        _required_text(veusz.get("root"), "build.runtime.veusz.root")
        _required_int(
            veusz.get("file_count"),
            "build.runtime.veusz.file_count",
            minimum=1,
        )
        _required_hash(
            veusz.get("tree_sha256"),
            "build.runtime.veusz.tree_sha256",
        )
        qt_binding = _object(
            runtime.get("qt_binding"),
            "build.runtime.qt_binding",
        )
        _reject_unknown(
            qt_binding,
            {"package", "root", "file_count", "tree_sha256"},
            label="build.runtime.qt_binding",
        )
        _required_text(qt_binding.get("package"), "build.runtime.qt_binding.package")
        _required_text(qt_binding.get("root"), "build.runtime.qt_binding.root")
        _required_int(
            qt_binding.get("file_count"),
            "build.runtime.qt_binding.file_count",
            minimum=1,
        )
        _required_hash(
            qt_binding.get("tree_sha256"),
            "build.runtime.qt_binding.tree_sha256",
        )
        linked = _object(
            runtime.get("linked_qt_binaries"),
            "build.runtime.linked_qt_binaries",
        )
        _reject_unknown(
            linked,
            {"platform", "binaries", "tree_sha256"},
            label="build.runtime.linked_qt_binaries",
        )
        _required_text(
            linked.get("platform"),
            "build.runtime.linked_qt_binaries.platform",
        )
        for index, binary in enumerate(
            _list(
                linked.get("binaries"),
                "build.runtime.linked_qt_binaries.binaries",
            )
        ):
            _validate_hash_file_record(
                binary,
                label=f"build.runtime.linked_qt_binaries.binaries[{index}]",
            )
        _required_hash(
            linked.get("tree_sha256"),
            "build.runtime.linked_qt_binaries.tree_sha256",
        )
        python = _object(runtime.get("python"), "build.runtime.python")
        _reject_unknown(
            python,
            {"version", "implementation", "executable"},
            label="build.runtime.python",
        )
        for field in ("version", "implementation", "executable"):
            _required_text(python.get(field), f"build.runtime.python.{field}")
        _required_text(runtime.get("platform"), "build.runtime.platform")
        dependencies = _object(
            runtime.get("dependencies"),
            "build.runtime.dependencies",
        )
        _reject_unknown(
            dependencies,
            {"count", "sha256"},
            label="build.runtime.dependencies",
        )
        _required_int(
            dependencies.get("count"),
            "build.runtime.dependencies.count",
            minimum=1,
        )
        _required_hash(
            dependencies.get("sha256"),
            "build.runtime.dependencies.sha256",
        )
    _required_text(
        runtime.get("veusz_upstream_commit"),
        "build.runtime.veusz_upstream_commit",
        maximum=100,
    )
    identity_sha256 = _required_hash(
        runtime.get("identity_sha256"),
        "build.runtime.identity_sha256",
    )
    if (
        contract_kind == "sciplot_frozen_wheel_runtime_match"
        and canonical_sha256(
            {key: item for key, item in runtime.items() if key != "identity_sha256"}
        )
        != identity_sha256
    ):
        raise ValueError("build.runtime.identity_sha256 is stale.")
    return build


def _head_path(ledger_path: Path) -> Path:
    target = ledger_path.expanduser().resolve()
    return target.with_name(f"{target.name}.head.json")


def _lock_path(ledger_path: Path) -> Path:
    target = ledger_path.expanduser().resolve()
    return target.with_name(f".{target.name}.lock")


def _pending_path(ledger_path: Path) -> Path:
    target = ledger_path.expanduser().resolve()
    return target.with_name(f"{target.name}.pending.json")


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


@contextmanager
def _ledger_lock(ledger_path: Path, *, exclusive: bool) -> Iterator[None]:
    lock_path = _lock_path(ledger_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as handle:
        try:
            import fcntl

            fcntl.flock(
                handle.fileno(),
                fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH,
            )
        except ImportError:
            pass
        try:
            yield
        finally:
            try:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except ImportError:
                pass


def _fingerprint_path(path: Path, *, label: str) -> dict[str, Any]:
    target = path.expanduser().resolve()
    if not target.exists():
        raise FileNotFoundError(f"{label} not found: {target}")
    if target.is_file():
        return {
            "kind": "file",
            "path": str(target),
            "size_bytes": target.stat().st_size,
            "sha256": file_sha256(target),
        }
    if not target.is_dir():
        raise ValueError(f"{label} must be a file or directory: {target}")
    content = artifact_content_record(target)
    members = _list(content.get("members"), f"{label} members")
    return {
        "kind": "directory",
        "path": str(target),
        "file_count": len(members),
        "size_bytes": _required_int(
            content.get("size_bytes"),
            f"{label} size_bytes",
        ),
        "tree_sha256": canonical_sha256(members),
        "artifact_sha256": _required_hash(
            content.get("sha256"),
            f"{label} artifact_sha256",
        ),
        "members": members,
    }


def _source_fingerprints(paths: list[Path]) -> list[dict[str, Any]]:
    if not paths:
        raise ValueError("At least one explicit source path is required.")
    resolved = [path.expanduser().resolve() for path in paths]
    if len(set(resolved)) != len(resolved):
        raise ValueError("Source paths must be unique.")
    return [
        {
            "source_id": f"source_{index:02d}",
            **_fingerprint_path(path, label=f"source {index}"),
        }
        for index, path in enumerate(resolved, 1)
    ]


def _verify_source_fingerprints(records: list[dict[str, Any]]) -> None:
    for index, record in enumerate(records, 1):
        expected = dict(record)
        source_id = _required_text(
            expected.pop("source_id", None),
            f"sources[{index}].source_id",
            maximum=64,
        )
        current = _fingerprint_path(
            Path(_required_text(expected.get("path"), "source path")),
            label=f"source {source_id}",
        )
        if current != expected:
            raise ValueError(f"Source {source_id} changed after preregistration.")


def _project_baseline(project_path: Path) -> dict[str, Any]:
    project = project_path.expanduser().resolve()
    if not project.exists():
        raise FileNotFoundError(f"Project path not found: {project}")
    root = project if project.is_dir() else project.parent
    candidates = (
        ".sciplot.json",
        "plot_request.json",
        "studio/document.vsz",
        ".sciplot_canvas/canvas_session.json",
        ".sciplot_canvas/review_annotations.json",
        ".sciplot_composition/composition.json",
        "composition.json",
    )
    authority_files: list[dict[str, Any]] = []
    if project.is_file():
        authority_files.append(
            {
                "relative_path": project.name,
                "size_bytes": project.stat().st_size,
                "sha256": file_sha256(project),
            }
        )
    for relative in candidates:
        candidate = root / relative
        if not candidate.is_file() or candidate.resolve() == project:
            continue
        authority_files.append(
            {
                "relative_path": relative,
                "size_bytes": candidate.stat().st_size,
                "sha256": file_sha256(candidate),
            }
        )
    authority_files.sort(key=lambda item: str(item["relative_path"]))
    return {
        "path": str(project),
        "root": str(root),
        "authority_files": authority_files,
        "baseline_sha256": canonical_sha256(authority_files),
    }


def _preregistered_project_root(preregistration: dict[str, Any]) -> Path:
    project = _object(preregistration.get("project"), "preregistered project")
    return (
        Path(_required_text(project.get("root"), "preregistered project root"))
        .expanduser()
        .resolve()
    )


def _baseline_authority_hash(
    preregistration: dict[str, Any],
    path: Path,
) -> str | None:
    project = _object(preregistration.get("project"), "preregistered project")
    root = (
        Path(_required_text(project.get("root"), "preregistered project root"))
        .expanduser()
        .resolve()
    )
    target = path.expanduser().resolve()
    try:
        relative = target.relative_to(root).as_posix()
    except ValueError:
        return None
    for raw in _list(
        project.get("authority_files"),
        "preregistered project authority_files",
    ):
        record = _object(raw, "preregistered authority file")
        if record.get("relative_path") == relative:
            return _required_hash(
                record.get("sha256"),
                "preregistered authority sha256",
            )
    return None


def _run_git(repo_root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def _build_identity(
    build_artifact: Path,
    *,
    require_frozen: bool,
    repo_root: Path | None = None,
    veusz_root: Path | None = None,
) -> dict[str, Any]:
    artifact = build_artifact.expanduser().resolve()
    if not artifact.is_file():
        raise FileNotFoundError(f"Build artifact not found: {artifact}")
    repo = (repo_root or REPO_ROOT).expanduser().resolve()
    active_veusz_root = (veusz_root or VEUSZ_ROOT).expanduser().resolve()
    commit = _run_git(repo, "rev-parse", "HEAD")
    branch = _run_git(repo, "branch", "--show-current")
    worktree_status = _run_git(
        repo,
        "status",
        "--porcelain",
        "--untracked-files=normal",
    )
    registry = DEFAULT_VALIDATED_ENVELOPE_REGISTRY.expanduser().resolve()
    if not registry.is_file():
        raise FileNotFoundError(f"Validated-envelope registry not found: {registry}")
    artifact_contract = (
        inspect_wheel_against_runtime(artifact)
        if require_frozen
        else {
            "kind": "sciplot_synthetic_unverified_build_artifact",
            "version": 1,
            "wheel": str(artifact),
            "wheel_sha256": file_sha256(artifact),
            "record_verified": False,
            "runtime_content_matches_wheel": False,
        }
    )
    actual_runtime = (
        runtime_identity(
            veusz_root=active_veusz_root,
            veusz_upstream_commit=VEUSZ_UPSTREAM_COMMIT,
        )
        if require_frozen
        else {
            "veusz_upstream_commit": VEUSZ_UPSTREAM_COMMIT,
            "identity_sha256": canonical_sha256(
                {
                    "synthetic_probe": True,
                    "veusz_upstream_commit": VEUSZ_UPSTREAM_COMMIT,
                }
            ),
        }
    )
    return {
        "git": {
            "repo": str(repo),
            "commit": commit or None,
            "branch": branch or None,
            "worktree_clean": not bool(worktree_status),
            "status_sha256": canonical_sha256(worktree_status.splitlines()),
        },
        "artifact": {
            "path": str(artifact),
            "size_bytes": artifact.stat().st_size,
            "sha256": file_sha256(artifact),
        },
        "artifact_contract": artifact_contract,
        "validated_envelope_registry": {
            "path": str(registry),
            "sha256": file_sha256(registry),
        },
        "runtime": actual_runtime,
    }


def _verify_build_identity(expected: dict[str, Any]) -> None:
    artifact = _object(expected.get("artifact"), "build.artifact")
    artifact_contract = _object(
        expected.get("artifact_contract"),
        "build.artifact_contract",
    )
    expected_git = _object(expected.get("git"), "build.git")
    expected_runtime = _object(expected.get("runtime"), "build.runtime")
    runtime_veusz = expected_runtime.get("veusz")
    expected_veusz_root = (
        Path(
            _required_text(
                _object(runtime_veusz, "build.runtime.veusz").get("root"),
                "build.runtime.veusz.root",
            )
        )
        .expanduser()
        .resolve()
        .parent
        if artifact_contract.get("runtime_content_matches_wheel") is True
        else VEUSZ_ROOT
    )
    current = _build_identity(
        Path(_required_text(artifact.get("path"), "build artifact path")),
        require_frozen=(artifact_contract.get("runtime_content_matches_wheel") is True),
        repo_root=Path(_required_text(expected_git.get("repo"), "build.git.repo")),
        veusz_root=expected_veusz_root,
    )
    current_git = _object(current.get("git"), "current build.git")
    for field in (
        "repo",
        "commit",
        "branch",
        "worktree_clean",
        "status_sha256",
    ):
        if current_git.get(field) != expected_git.get(field):
            raise ValueError(
                f"Build identity changed after preregistration: git.{field}."
            )
    if current["artifact"] != artifact:
        raise ValueError("Build artifact changed after preregistration.")
    if current["artifact_contract"] != artifact_contract:
        raise ValueError(
            "Active SciPlot runtime no longer matches the frozen artifact."
        )
    if current["validated_envelope_registry"] != expected.get(
        "validated_envelope_registry"
    ):
        raise ValueError("Validated-envelope registry changed after preregistration.")
    if current["runtime"] != expected.get("runtime"):
        raise ValueError("Runtime identity changed after preregistration.")


def _journal_baseline(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    target = path.expanduser().resolve()
    if target.exists() and not target.is_file():
        raise ValueError(f"Operation journal must be a file: {target}")
    data = target.read_bytes() if target.is_file() else b""
    if data and not data.endswith(b"\n"):
        raise ValueError(
            "The preregistered operation journal must end on a JSONL boundary."
        )
    return {
        "path": str(target),
        "existed": target.is_file(),
        "size_bytes": len(data),
        "line_count": len(data.splitlines()),
        "prefix_sha256": hashlib.sha256(data).hexdigest(),
    }


def _journal_after_baseline(
    baseline: dict[str, Any],
    path: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    target = path.expanduser().resolve()
    recorded_path = (
        Path(_required_text(baseline.get("path"), "journal baseline path"))
        .expanduser()
        .resolve()
    )
    if target != recorded_path:
        raise ValueError("Operation journal path changed after preregistration.")
    if not target.is_file():
        raise FileNotFoundError(f"Operation journal not found: {target}")
    data = target.read_bytes()
    baseline_size = _required_int(
        baseline.get("size_bytes"),
        "journal baseline size",
    )
    if len(data) < baseline_size:
        raise ValueError("Operation journal was truncated after preregistration.")
    prefix = data[:baseline_size]
    if hashlib.sha256(prefix).hexdigest() != _required_hash(
        baseline.get("prefix_sha256"),
        "journal baseline prefix_sha256",
    ):
        raise ValueError("Operation journal prefix changed after preregistration.")
    suffix = data[baseline_size:]
    if suffix and not suffix.endswith(b"\n"):
        raise ValueError("Operation journal ends with an incomplete JSONL event.")
    entries: list[dict[str, Any]] = []
    for index, raw_line in enumerate(suffix.splitlines(), 1):
        if not raw_line.strip():
            continue
        try:
            value = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Operation journal post-baseline line {index} is invalid JSON."
            ) from exc
        if not isinstance(value, dict):
            raise ValueError(
                f"Operation journal post-baseline line {index} is not an object."
            )
        entries.append(value)
    return entries, {
        "path": str(target),
        "baseline_size_bytes": baseline_size,
        "end_size_bytes": len(data),
        "end_sha256": hashlib.sha256(data).hexdigest(),
        "post_baseline_size_bytes": len(suffix),
        "post_baseline_sha256": hashlib.sha256(suffix).hexdigest(),
        "post_baseline_event_count": len(entries),
    }


def _event_reference(entry: dict[str, Any], index: int) -> dict[str, Any]:
    response = entry.get("response")
    response_object = response if isinstance(response, dict) else None
    batch = entry.get("batch")
    batch_object = batch if isinstance(batch, dict) else None
    transaction = entry.get("transaction")
    transaction_object = transaction if isinstance(transaction, dict) else None
    descriptor = entry.get("descriptor")
    descriptor_object = descriptor if isinstance(descriptor, dict) else None
    reference = {
        "index": index,
        "event": str(entry.get("event") or ""),
        "event_id": (
            str(entry.get("event_id")) if entry.get("event_id") is not None else None
        ),
        "event_sha256": canonical_sha256(entry),
        "revision": (
            int(entry["revision"])
            if isinstance(entry.get("revision"), int)
            and not isinstance(entry.get("revision"), bool)
            else None
        ),
        "provider": (
            str(entry.get("provider")) if entry.get("provider") is not None else None
        ),
        "model": (
            str(descriptor_object.get("model_label") or "")
            if descriptor_object is not None
            else None
        ),
        "transaction_id": (
            str(entry.get("transaction_id"))
            if entry.get("transaction_id") is not None
            else None
        ),
        "request_id": (
            str(entry.get("request_id"))
            if entry.get("request_id") is not None
            else None
        ),
        "batch_id": (
            str(entry.get("batch_id") or (batch_object or {}).get("batch_id") or "")
            or None
        ),
        "response_sha256": (
            canonical_sha256(response_object) if response_object is not None else None
        ),
        "response_status": (
            str(response_object.get("status") or "")
            if response_object is not None
            else None
        ),
        "proposal_kind": (
            str(response_object.get("proposal_kind") or "")
            if response_object is not None
            else None
        ),
    }
    if entry.get("event") == "assistant_provider_state":
        reference["provider_connected"] = entry.get("provider_connected")
        reference["provider_configuration"] = str(
            entry.get("provider_configuration") or ""
        )
    if entry.get("event") == "assistant_data_mapping_handoff_opened":
        reference["execution_manifest"] = str(entry.get("execution_manifest") or "")
        reference["execution_manifest_sha256"] = str(
            entry.get("execution_manifest_sha256") or ""
        )
        reference["raw_inputs_mutated"] = entry.get("raw_inputs_mutated")
    if entry.get("event") == "review_annotation_promoted":
        after = entry.get("after")
        after_object = after if isinstance(after, dict) else {}
        reference["annotation_id"] = str(entry.get("annotation_id") or "")
        reference["promoted_object_id"] = str(
            after_object.get("promoted_object_id") or ""
        )
    if entry.get("event") == "assistant_transaction_committed":
        accepted = [
            str(value)
            for value in (transaction_object or {}).get("accepted_batch_ids", [])
        ]
        undone = [
            str(value)
            for value in (transaction_object or {}).get("undone_batch_ids", [])
        ]
        rejected = [
            str(value)
            for value in (transaction_object or {}).get("rejected_batch_ids", [])
        ]
        reference["accepted_batch_ids"] = accepted
        reference["undone_batch_ids"] = undone
        reference["rejected_batch_ids"] = rejected
        reference["active_batch_ids"] = [
            value for value in accepted if value not in set(undone)
        ]
        verification = (
            entry.get("verification")
            if isinstance(entry.get("verification"), dict)
            else {}
        )
        reference["verification"] = {
            "structural_qa_passed": (verification.get("structural_qa_passed") is True),
            "canonical_vsz_unchanged_before_save": (
                verification.get("canonical_vsz_unchanged_before_save") is True
            ),
            "raw_inputs_mutated": verification.get("raw_inputs_mutated"),
        }
    if entry.get("event") == "assistant_transaction_rolled_back":
        verification = (
            entry.get("verification")
            if isinstance(entry.get("verification"), dict)
            else {}
        )
        reference["verification"] = {
            "exact_baseline_render": (
                verification.get("exact_baseline_render") is True
            ),
            "baseline_vsz_hash_verified": (
                verification.get("baseline_vsz_hash_verified") is True
            ),
            "baseline_review_hash_verified": (
                verification.get("baseline_review_hash_verified") is True
            ),
            "canonical_vsz_unchanged": (
                verification.get("canonical_vsz_unchanged") is True
            ),
        }
    return reference


def _journal_summary(
    entries: list[dict[str, Any]],
    boundary: dict[str, Any],
) -> dict[str, Any]:
    relevant_names = {
        "assistant_provider_state",
        "assistant_request_submitted",
        "assistant_batch_proposed",
        "assistant_data_mapping_proposed",
        "assistant_response_received",
        "assistant_response_discarded_after_cancel",
        "assistant_batch_applied",
        "assistant_batch_undone",
        "assistant_batch_rejected",
        "assistant_transaction_committed",
        "assistant_transaction_rolled_back",
        "assistant_request_cancel_requested",
        "assistant_data_mapping_handoff_opened",
        "save",
        "exact_current_export",
        "composition_batch_applied",
        "composition_variant_created",
        "composition_variant_activated",
        "undo",
        "redo",
        "review_annotation_added",
        "review_annotation_updated",
        "review_annotation_promoted",
    }
    references = [
        _event_reference(entry, index)
        for index, entry in enumerate(entries)
        if str(entry.get("event") or "") in relevant_names
    ]
    request_references = [
        item for item in references if item["event"] == "assistant_request_submitted"
    ]
    proposal_references = [
        item
        for item in references
        if item["event"]
        in {
            "assistant_batch_proposed",
            "assistant_data_mapping_proposed",
            "assistant_response_received",
            "assistant_response_discarded_after_cancel",
        }
    ]
    commit_references = [
        item
        for item in references
        if item["event"] == "assistant_transaction_committed"
    ]
    return {
        **boundary,
        "event_types": dict(
            sorted(Counter(str(entry.get("event") or "") for entry in entries).items())
        ),
        "references": references,
        "assistant_request_count": len(request_references),
        "assistant_proposal_count": len(proposal_references),
        "assistant_commit_count": len(commit_references),
        "first_proposal": proposal_references[0] if proposal_references else None,
        "retry_count": max(0, len(proposal_references) - 1),
        "raw_event_payloads_copied": False,
    }


def _validate_export_records(
    records: list[Any],
    *,
    path_field: str = "path",
    hash_field: str | None = "sha256",
) -> dict[str, list[dict[str, Any]]]:
    by_format: dict[str, list[dict[str, Any]]] = {}
    for index, raw in enumerate(records):
        record = _object(raw, f"exports[{index}]")
        export_format = _required_text(
            record.get("format"),
            f"exports[{index}].format",
            maximum=32,
        )
        path = (
            Path(
                _required_text(
                    record.get(path_field),
                    f"exports[{index}].{path_field}",
                )
            )
            .expanduser()
            .resolve()
        )
        if not path.is_file() or path.stat().st_size <= 0:
            raise FileNotFoundError(f"Export is missing or empty: {path}")
        actual_hash = file_sha256(path)
        if hash_field is not None and record.get(hash_field) is not None:
            if actual_hash != _required_hash(
                record.get(hash_field),
                f"exports[{index}].{hash_field}",
            ):
                raise ValueError(f"Export hash mismatch: {path}")
        normalized_format = (
            "tiff_300" if export_format in {"tiff", "tif"} else export_format
        )
        by_format.setdefault(normalized_format, []).append(
            {
                "format": normalized_format,
                "path": str(path),
                "size_bytes": path.stat().st_size,
                "sha256": actual_hash,
            }
        )
    if not by_format.get("pdf") or not by_format.get("tiff_300"):
        raise ValueError("A canonical PDF and 300 dpi TIFF pair is required.")
    return by_format


def _canvas_witness(
    preregistration: dict[str, Any],
    *,
    canvas_session_path: Path,
    journal_path: Path,
    document_path: Path,
    review_path: Path | None,
    mapping_execution_path: Path | None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    project_root = _preregistered_project_root(preregistration)
    session_path = require_within(
        project_root,
        canvas_session_path,
        label="CanvasSession authority",
    )
    session = load_canvas_session(session_path)
    document = require_within(
        project_root,
        document_path,
        label="Canvas document authority",
    )
    journal_path = require_within(
        project_root,
        journal_path,
        label="Canvas operation journal",
    )
    if Path(session.document_path).expanduser().resolve() != document:
        raise ValueError(
            "CanvasSession document path does not match the witnessed VSZ."
        )
    if not document.is_file():
        raise FileNotFoundError(f"Exact-current VSZ not found: {document}")
    document_hash = file_sha256(document)
    if session.document_sha256 != document_hash:
        raise ValueError("CanvasSession exact-current VSZ hash is stale.")
    if session.active_transaction is not None:
        raise ValueError("Resolve the active Assistant transaction before witness.")
    if session.state != "ready":
        raise ValueError(
            f"CanvasSession must be ready before witness; found {session.state!r}."
        )
    if not (session.revision == session.saved_revision == session.exported_revision):
        raise ValueError("Witness requires revision=saved_revision=exported_revision.")
    if (
        session.qa_summary.get("status") != "passed"
        or session.qa_summary.get("state") != "ready"
        or session.qa_summary.get("ready_to_use") is not True
    ):
        raise ValueError("CanvasSession does not bind passing ready artifact QA.")
    baseline = preregistration.get("operation_journal_baseline")
    if not isinstance(baseline, dict):
        raise ValueError(
            "Canvas lifecycle evidence requires a preregistered journal baseline."
        )
    entries, boundary = _journal_after_baseline(baseline, journal_path)
    if not entries:
        raise ValueError(
            "A natural Canvas session requires post-preregistration journal events."
        )
    final_revision = session.revision
    saves = [
        (index, entry)
        for index, entry in enumerate(entries)
        if entry.get("event") == "save"
        and entry.get("revision") == final_revision
        and entry.get("document_sha256") == document_hash
    ]
    exports = [
        (index, entry)
        for index, entry in enumerate(entries)
        if entry.get("event") == "exact_current_export"
        and entry.get("revision") == final_revision
    ]
    if not saves:
        raise ValueError(
            "No post-preregistration save binds the final Canvas revision."
        )
    if not exports:
        raise ValueError(
            "No post-preregistration exact-current export binds the final revision."
        )
    save_index, _save = saves[-1]
    export_index, export_entry = exports[-1]
    if export_index <= save_index:
        raise ValueError("Exact-current export must occur after the final save.")
    export_records = _list(
        export_entry.get("exports"),
        "exact_current_export.exports",
    )
    verified_exports = _validate_export_records(
        export_records,
        hash_field=None,
    )
    summary = _journal_summary(entries, boundary)
    optional: dict[str, Any] = {}
    expected = set(preregistration["expected_evidence"])
    if expected & {"review_sidecar", "review_promotion"}:
        if review_path is None:
            raise ValueError("Review evidence requires review_annotations.json.")
        review = require_within(
            project_root,
            review_path,
            label="Canvas review sidecar",
        )
        annotations = load_review_annotations(review)
        annotation_ids = [annotation.annotation_id for annotation in annotations]
        if annotation_ids != session.review_annotation_ids:
            raise ValueError(
                "CanvasSession and review sidecar annotation IDs disagree."
            )
        if not annotations:
            raise ValueError("Review sidecar evidence requires an annotation.")
        promoted = [
            annotation
            for annotation in annotations
            if annotation.state == "promoted"
            and annotation.promoted_object_id is not None
        ]
        if "review_promotion" in expected and not promoted:
            raise ValueError(
                "Review-promotion evidence requires a promoted annotation."
            )
        promotion_events = [
            entry
            for entry in entries
            if entry.get("event") == "review_annotation_promoted"
        ]
        promoted_event_pairs = {
            (
                str(entry.get("annotation_id") or ""),
                str(
                    (
                        entry.get("after")
                        if isinstance(entry.get("after"), dict)
                        else {}
                    ).get("promoted_object_id")
                    or ""
                ),
            )
            for entry in promotion_events
        }
        promoted_pairs = {
            (
                annotation.annotation_id,
                str(annotation.promoted_object_id),
            )
            for annotation in promoted
        }
        if (
            "review_promotion" in expected
            and not promoted_pairs <= promoted_event_pairs
        ):
            raise ValueError(
                "Promoted review annotations are not bound to matching "
                "post-preregistration native-promotion events."
            )
        if any(
            session.object_registry.by_id(str(annotation.promoted_object_id)) is None
            for annotation in promoted
        ):
            raise ValueError(
                "A promoted annotation is absent from the reopened native "
                "object registry."
            )
        optional["review"] = {
            "path": str(review),
            "sha256": file_sha256(review),
            "annotation_ids": annotation_ids,
            "annotation_count": len(annotations),
            "promoted_count": len(promoted),
            "promoted_annotation_ids": [
                annotation.annotation_id for annotation in promoted
            ],
            "promoted_object_ids": [
                str(annotation.promoted_object_id) for annotation in promoted
            ],
        }
    if "data_mapping" in expected:
        if mapping_execution_path is None:
            raise ValueError("Data-mapping evidence requires execution.json.")
        mapping = require_within(
            project_root,
            mapping_execution_path,
            label="Canvas data-mapping execution",
        )
        execution = load_data_mapping_execution(mapping)
        if (
            execution.get("raw_inputs_unchanged") is not True
            or execution.get("ready_to_use") is not True
            or execution.get("handoff_allowed") is not True
        ):
            raise ValueError("Data-mapping execution is not handoff-ready.")
        mapping_hash = file_sha256(mapping)
        handoffs = [
            entry
            for entry in entries
            if entry.get("event") == "assistant_data_mapping_handoff_opened"
            and Path(str(entry.get("execution_manifest") or "")).expanduser().resolve()
            == mapping
            and entry.get("execution_manifest_sha256") == mapping_hash
            and entry.get("raw_inputs_mutated") is False
        ]
        if not handoffs:
            raise ValueError("The journal does not bind the verified mapping handoff.")
        optional["data_mapping"] = {
            "path": str(mapping),
            "sha256": mapping_hash,
            "proposal_id": execution.get("proposal_id"),
            "proposal_sha256": execution.get("proposal_sha256"),
            "provider": execution.get("provider"),
            "confirmation_id": execution.get("confirmation_id"),
            "transform_ledger_sha256": execution.get("transform_ledger_sha256"),
            "raw_inputs_unchanged": True,
            "handoff_allowed": True,
        }
    baseline_document_hash = _baseline_authority_hash(
        preregistration,
        document,
    )
    baseline_review_hash = (
        _baseline_authority_hash(
            preregistration,
            review_path.expanduser().resolve(),
        )
        if review_path is not None
        else None
    )
    current_review_hash = (
        optional.get("review", {}).get("sha256")
        if isinstance(optional.get("review"), dict)
        else None
    )
    meaningful_events = {
        "operation_batch_applied",
        "assistant_transaction_committed",
        "assistant_transaction_rolled_back",
        "assistant_data_mapping_handoff_opened",
        "review_annotation_added",
        "review_annotation_updated",
        "review_annotation_promoted",
    }
    meaningful_change = bool(
        baseline_document_hash != document_hash
        or (
            current_review_hash is not None
            and current_review_hash != baseline_review_hash
        )
        or any(entry.get("event") in meaningful_events for entry in entries)
    )
    if not meaningful_change:
        raise ValueError(
            "The witnessed Canvas has no post-preregistration plot, edit, "
            "review, mapping, or rollback change; re-exporting an unchanged "
            "finished artifact is not a natural session."
        )
    return (
        {
            "canvas_session": str(session_path),
            "canvas_session_sha256": file_sha256(session_path),
            "canvas_session_id": session.session_id,
            "document": str(document),
            "document_sha256": document_hash,
            "revision": final_revision,
            "saved_revision": session.saved_revision,
            "exported_revision": session.exported_revision,
            "qa_status": session.qa_summary.get("status"),
            "ready_to_use": True,
            "baseline_document_sha256": baseline_document_hash,
            "meaningful_change_after_preregistration": True,
            "review_annotation_ids": list(session.review_annotation_ids),
            "exports": {
                key: values for key, values in sorted(verified_exports.items())
            },
        },
        summary,
        optional,
    )


def _composition_witness(
    preregistration: dict[str, Any],
    *,
    composition_path: Path,
    journal_path: Path,
    delivery_manifest_path: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    project_root = _preregistered_project_root(preregistration)
    composition = require_within(
        project_root,
        composition_path,
        label="Composition authority",
    )
    journal_path = require_within(
        project_root,
        journal_path,
        label="Composition operation journal",
    )
    project = load_composition_project(composition)
    variant = project.active_variant
    if variant.state not in {"compiled", "edited", "ready"}:
        raise ValueError(
            "Composition witness requires compiled, edited, or ready authority."
        )
    if (
        variant.compiled_document_ref is None
        or variant.compiled_document_sha256 is None
    ):
        raise ValueError("Composition variant has no compiled VSZ authority.")
    root = composition.parent
    document = (root / variant.compiled_document_ref).resolve()
    if not document.is_file():
        raise FileNotFoundError(f"Compiled composition VSZ not found: {document}")
    document_hash = file_sha256(document)
    if document_hash != variant.compiled_document_sha256:
        raise ValueError("Compiled composition VSZ hash is stale.")
    source_records: list[dict[str, Any]] = []
    for module in project.source_modules:
        source_path = (root / module.source_ref).resolve()
        if not source_path.is_file():
            raise FileNotFoundError(
                f"Composition source module not found: {source_path}"
            )
        source_hash = file_sha256(source_path)
        if source_hash != module.source_sha256:
            raise ValueError(f"Composition source module changed: {module.module_id}.")
        source_records.append(
            {
                "module_id": module.module_id,
                "path": str(source_path),
                "sha256": source_hash,
            }
        )
    baseline = preregistration.get("operation_journal_baseline")
    if not isinstance(baseline, dict):
        raise ValueError("Composition lifecycle evidence requires a journal baseline.")
    entries, boundary = _journal_after_baseline(baseline, journal_path)
    if not entries:
        raise ValueError(
            "A natural composition session requires a post-preregistration "
            "operation event."
        )
    baseline_composition_hash = _baseline_authority_hash(
        preregistration,
        composition,
    )
    current_composition_hash = file_sha256(composition)
    meaningful_change = bool(
        baseline_composition_hash != current_composition_hash
        or any(
            entry.get("event")
            in {
                "composition_batch_applied",
                "composition_variant_created",
                "composition_variant_activated",
            }
            for entry in entries
        )
    )
    if not meaningful_change:
        raise ValueError(
            "The witnessed composition has no post-preregistration native "
            "composition change."
        )
    authority = {
        "composition": str(composition),
        "composition_sha256": current_composition_hash,
        "baseline_composition_sha256": baseline_composition_hash,
        "meaningful_change_after_preregistration": True,
        "composition_id": project.composition_id,
        "variant_id": variant.variant_id,
        "variant_revision": variant.revision,
        "variant_state": variant.state,
        "document": str(document),
        "document_sha256": document_hash,
        "layout_id": variant.layout.layout_id,
        "page_size_mm": [
            183.0,
            variant.layout.canvas_height_mm,
        ],
        "source_modules": source_records,
        "raster_panel_composition_allowed": False,
    }
    delivery = _verify_composition_manifest(
        delivery_manifest_path,
        preregistration=preregistration,
        authority=authority,
    )
    authority["delivery_witness"] = delivery
    return (
        authority,
        _journal_summary(entries, boundary),
        {},
    )


def _verify_canvas_witness_current(witness: dict[str, Any]) -> None:
    authority = _object(witness.get("authority"), "witness authority")
    session_path = Path(
        _required_text(authority.get("canvas_session"), "canvas_session")
    )
    if not session_path.is_file() or file_sha256(session_path) != _required_hash(
        authority.get("canvas_session_sha256"),
        "canvas_session_sha256",
    ):
        raise ValueError("CanvasSession changed after the reopen witness.")
    session = load_canvas_session(session_path)
    document = (
        Path(_required_text(authority.get("document"), "witness document"))
        .expanduser()
        .resolve()
    )
    expected_hash = _required_hash(
        authority.get("document_sha256"),
        "witness document_sha256",
    )
    if not document.is_file() or file_sha256(document) != expected_hash:
        raise ValueError("Exact-current VSZ changed after the reopen witness.")
    expected_revision = _required_int(
        authority.get("revision"),
        "witness revision",
    )
    if not (
        session.revision
        == session.saved_revision
        == session.exported_revision
        == expected_revision
    ):
        raise ValueError("Canvas revision changed after the reopen witness.")
    if session.document_sha256 != expected_hash:
        raise ValueError("CanvasSession document authority changed after witness.")
    if (
        session.active_transaction is not None
        or session.state != "ready"
        or session.qa_summary.get("status") != "passed"
        or session.qa_summary.get("state") != "ready"
        or session.qa_summary.get("ready_to_use") is not True
    ):
        raise ValueError("CanvasSession is no longer ready at completion.")
    if session.session_id != authority.get("canvas_session_id"):
        raise ValueError("CanvasSession identity changed after reopen witness.")
    journal = _object(witness.get("journal"), "witness journal")
    journal_path = (
        Path(_required_text(journal.get("path"), "witness journal path"))
        .expanduser()
        .resolve()
    )
    if not journal_path.is_file():
        raise FileNotFoundError(f"Witness journal not found: {journal_path}")
    data = journal_path.read_bytes()
    if len(data) != _required_int(
        journal.get("end_size_bytes"),
        "witness journal end_size_bytes",
    ) or hashlib.sha256(data).hexdigest() != _required_hash(
        journal.get("end_sha256"),
        "witness journal end_sha256",
    ):
        raise ValueError("Operation journal changed after the reopen witness.")
    optional = _object(
        witness.get("optional_evidence"),
        "witness optional_evidence",
    )
    review = optional.get("review")
    if isinstance(review, dict):
        review_path = Path(_required_text(review.get("path"), "witness review path"))
        if not review_path.is_file() or file_sha256(review_path) != _required_hash(
            review.get("sha256"), "witness review sha256"
        ):
            raise ValueError("Review sidecar changed after the reopen witness.")
        annotations = load_review_annotations(review_path)
        annotation_ids = [value.annotation_id for value in annotations]
        if (
            annotation_ids != session.review_annotation_ids
            or annotation_ids != review.get("annotation_ids")
        ):
            raise ValueError(
                "Review sidecar identity changed after the reopen witness."
            )
        promoted_ids = {
            value.promoted_object_id
            for value in annotations
            if value.state == "promoted"
        }
        expected_promoted_ids = set(review.get("promoted_object_ids") or [])
        if promoted_ids != expected_promoted_ids or None in promoted_ids:
            raise ValueError("Promoted review-object identities changed after witness.")
        if any(
            session.object_registry.by_id(str(object_id)) is None
            for object_id in promoted_ids
        ):
            raise ValueError(
                "A promoted review annotation is absent from the current native "
                "object registry."
            )
    mapping = optional.get("data_mapping")
    if isinstance(mapping, dict):
        mapping_path = Path(_required_text(mapping.get("path"), "witness mapping path"))
        if not mapping_path.is_file() or file_sha256(mapping_path) != _required_hash(
            mapping.get("sha256"),
            "witness mapping sha256",
        ):
            raise ValueError("Data-mapping execution changed after the reopen witness.")
        load_data_mapping_execution(mapping_path)


def _verify_composition_witness_current(witness: dict[str, Any]) -> None:
    authority = _object(witness.get("authority"), "witness authority")
    composition = (
        Path(_required_text(authority.get("composition"), "composition path"))
        .expanduser()
        .resolve()
    )
    project = load_composition_project(composition)
    variant = project.active_variant
    if file_sha256(composition) != _required_hash(
        authority.get("composition_sha256"),
        "composition authority sha256",
    ):
        raise ValueError("Composition model changed after reopen witness.")
    if (
        project.composition_id != authority.get("composition_id")
        or variant.variant_id != authority.get("variant_id")
        or variant.revision != authority.get("variant_revision")
        or variant.state != authority.get("variant_state")
        or variant.layout.layout_id != authority.get("layout_id")
    ):
        raise ValueError("Composition authority changed after reopen witness.")
    document = (
        Path(_required_text(authority.get("document"), "composition document"))
        .expanduser()
        .resolve()
    )
    expected_hash = _required_hash(
        authority.get("document_sha256"),
        "composition document_sha256",
    )
    if not document.is_file() or file_sha256(document) != expected_hash:
        raise ValueError("Composition VSZ changed after reopen witness.")
    if variant.compiled_document_sha256 != expected_hash:
        raise ValueError("Composition model no longer binds the witnessed VSZ.")
    page_size = _list(
        authority.get("page_size_mm"),
        "composition witnessed page_size_mm",
    )
    if page_size != [183.0, variant.layout.canvas_height_mm]:
        raise ValueError("Composition page size changed after reopen witness.")
    journal = _object(witness.get("journal"), "witness journal")
    journal_path = (
        Path(_required_text(journal.get("path"), "witness journal path"))
        .expanduser()
        .resolve()
    )
    data = journal_path.read_bytes()
    if len(data) != _required_int(
        journal.get("end_size_bytes"),
        "witness journal end_size_bytes",
    ) or hashlib.sha256(data).hexdigest() != _required_hash(
        journal.get("end_sha256"),
        "witness journal end_sha256",
    ):
        raise ValueError("Composition journal changed after reopen witness.")
    for record in _list(
        authority.get("source_modules"),
        "composition source_modules",
    ):
        item = _object(record, "composition source module")
        path = Path(_required_text(item.get("path"), "source module path"))
        if not path.is_file() or file_sha256(path) != _required_hash(
            item.get("sha256"), "source module sha256"
        ):
            raise ValueError("Composition source module changed after witness.")
    delivery = _object(
        authority.get("delivery_witness"),
        "composition delivery witness",
    )
    delivery_path = Path(
        _required_text(
            delivery.get("path"),
            "composition witnessed delivery manifest",
        )
    )
    if not delivery_path.is_file() or file_sha256(delivery_path) != _required_hash(
        delivery.get("sha256"),
        "composition witnessed delivery manifest sha256",
    ):
        raise ValueError("Composition delivery manifest changed after reopen witness.")


def _verify_regular_manifest(
    manifest_path: Path,
    *,
    preregistration: dict[str, Any],
    witness: dict[str, Any],
) -> dict[str, Any]:
    project_root = _preregistered_project_root(preregistration)
    manifest = require_within(
        project_root,
        manifest_path,
        label="SciPlot run manifest",
    )
    payload = _read_json(manifest, "SciPlot run manifest")
    if payload.get("kind") != "sciplot_run":
        raise ValueError("Completion manifest is not a SciPlot run manifest.")
    if payload.get("state") != "ready" or payload.get("ready_to_use") is not True:
        raise ValueError("SciPlot run manifest is not ready_to_use.")
    witness_authority = _object(
        witness.get("authority"),
        "witness authority",
    )
    document = require_within(
        project_root,
        Path(_required_text(witness_authority.get("document"), "witness document")),
        label="Witnessed Canvas document",
    )
    document_sha256 = _required_hash(
        witness_authority.get("document_sha256"),
        "witness document sha256",
    )
    witnessed_exports = _object(
        witness_authority.get("exports"),
        "witness exports",
    )
    manifest_document = require_within(
        project_root,
        Path(_required_text(payload.get("veusz_document"), "manifest Veusz document")),
        label="Manifest Veusz document",
    )
    if manifest_document != document:
        raise ValueError("Run manifest points to another Veusz document.")
    output_root = require_within(
        project_root,
        Path(_required_text(payload.get("output"), "manifest output")),
        label="SciPlot run output",
    )
    if manifest.parent != output_root:
        raise ValueError("SciPlot run manifest is outside its declared output root.")
    if payload.get("exported_document_hash") != document_sha256:
        raise ValueError("Run manifest does not bind the witnessed exact-current VSZ.")
    qa = _object(payload.get("qa"), "manifest.qa")
    if qa.get("status") != "passed":
        raise ValueError("Run manifest QA did not pass.")
    pdfs = _list(qa.get("pdfs"), "manifest.qa.pdfs")
    tiffs = _list(qa.get("tiffs"), "manifest.qa.tiffs")
    verified_qa = _validate_export_records(
        [{"format": "pdf", **_object(value, "qa pdf")} for value in pdfs]
        + [{"format": "tiff_300", **_object(value, "qa tiff")} for value in tiffs]
    )
    recomputed_qa = verify_regular_production_qa(
        payload,
        document=document,
        witnessed_exports=witnessed_exports,
    )
    recomputed_by_format = {
        "pdf": [
            {
                "format": "pdf",
                "path": str(value["path"]),
                "size_bytes": int(value["size_bytes"]),
                "sha256": str(value["sha256"]),
            }
            for value in recomputed_qa["pdfs"]
        ],
        "tiff_300": [
            {
                "format": "tiff_300",
                "path": str(value["path"]),
                "size_bytes": int(value["size_bytes"]),
                "sha256": str(value["sha256"]),
            }
            for value in recomputed_qa["tiffs"]
        ],
    }
    for export_format in ("pdf", "tiff_300"):
        if sorted(value["sha256"] for value in verified_qa[export_format]) != sorted(
            value["sha256"] for value in recomputed_by_format[export_format]
        ):
            raise ValueError(
                f"Stored manifest QA {export_format} differs from recomputed "
                "production QA."
            )
    for export_format in ("pdf", "tiff_300"):
        witnessed = [
            _object(value, f"witnessed {export_format}")
            for value in _list(
                witnessed_exports.get(export_format),
                f"witnessed exports.{export_format}",
            )
        ]
        witnessed_hashes = sorted(
            _required_hash(
                value.get("sha256"),
                f"witnessed {export_format} sha256",
            )
            for value in witnessed
        )
        qa_hashes = sorted(
            _required_hash(
                value.get("sha256"),
                f"QA {export_format} sha256",
            )
            for value in verified_qa[export_format]
        )
        if witnessed_hashes != qa_hashes:
            raise ValueError(
                f"Manifest QA {export_format} does not match the "
                "witnessed exact-current export."
            )
    delivery = _object(
        payload.get("delivery_package"),
        "manifest.delivery_package",
    )
    if delivery.get("complete") is not True:
        raise ValueError("SciPlot delivery package is incomplete.")
    editable = _object(delivery.get("editable_vsz"), "delivery editable_vsz")
    if (
        editable.get("exists") is not True
        or editable.get("hash_matches_export") is not True
        or editable.get("expected_hash") != document_sha256
        or editable.get("actual_hash") != document_sha256
    ):
        raise ValueError(
            "Delivery editable VSZ does not match exact-current authority."
        )
    editable_path = (
        Path(_required_text(editable.get("path"), "delivery editable VSZ path"))
        .expanduser()
        .resolve()
    )
    require_within(
        project_root,
        editable_path,
        label="Delivered editable VSZ",
    )
    if not editable_path.is_file() or file_sha256(editable_path) != document_sha256:
        raise ValueError("Delivered editable VSZ hash mismatch.")
    delivery_figures = _list(
        delivery.get("figures"),
        "delivery figures",
    )
    normalized_delivery: list[dict[str, Any]] = []
    for index, raw in enumerate(delivery_figures):
        record = _object(raw, f"delivery figures[{index}]")
        if record.get("copy_hash_matches") is not True or record.get(
            "source_sha256"
        ) != record.get("delivery_sha256"):
            raise ValueError("Delivery figure copy hash parity failed.")
        source = Path(_required_text(record.get("source"), "delivery figure source"))
        destination = Path(_required_text(record.get("path"), "delivery figure path"))
        source = require_within(
            project_root,
            source,
            label="Delivery figure source",
        )
        destination = require_within(
            project_root,
            destination,
            label="Delivered figure",
        )
        expected_hash = _required_hash(
            record.get("source_sha256"),
            "delivery figure sha256",
        )
        if (
            not source.is_file()
            or not destination.is_file()
            or file_sha256(source) != expected_hash
            or file_sha256(destination) != expected_hash
        ):
            raise ValueError("Delivery figure file hash mismatch.")
        normalized_delivery.append(
            {
                "format": str(record.get("format") or ""),
                "source": str(source.resolve()),
                "path": str(destination.resolve()),
                "sha256": expected_hash,
            }
        )
    formats = {
        "tiff_300" if item["format"] in {"tiff", "tif"} else item["format"]
        for item in normalized_delivery
    }
    if not {"pdf", "tiff_300"}.issubset(formats):
        raise ValueError("Delivery package lacks the canonical PDF/TIFF pair.")
    for export_format in ("pdf", "tiff_300"):
        delivery_hashes = sorted(
            item["sha256"]
            for item in normalized_delivery
            if ("tiff_300" if item["format"] in {"tiff", "tif"} else item["format"])
            == export_format
        )
        qa_hashes = sorted(item["sha256"] for item in verified_qa[export_format])
        if delivery_hashes != qa_hashes:
            raise ValueError(
                f"Delivered {export_format} does not match final QA artifacts."
            )
    optional = _object(
        witness.get("optional_evidence"),
        "witness optional evidence",
    )
    witnessed_mapping = optional.get("data_mapping")
    source_lineage = verify_regular_source_lineage(
        payload,
        preregistration=preregistration,
        witnessed_mapping=(
            witnessed_mapping if isinstance(witnessed_mapping, dict) else None
        ),
    )
    return {
        "kind": "sciplot_run",
        "path": str(manifest),
        "sha256": file_sha256(manifest),
        "state": "ready",
        "ready_to_use": True,
        "document_sha256": document_sha256,
        "qa_status": "passed",
        "qa_exports": recomputed_by_format,
        "recomputed_qa": recomputed_qa,
        "delivery_complete": True,
        "delivery_editable_vsz": str(editable_path),
        "delivery_figure_count": len(normalized_delivery),
        "transform_ledger_sha256": source_lineage["transform_ledger_sha256"],
        "source_lineage": source_lineage,
        "raw_sources_preserved": True,
    }


def _verify_composition_manifest(
    manifest_path: Path,
    *,
    preregistration: dict[str, Any],
    authority: dict[str, Any],
) -> dict[str, Any]:
    from sciplot_core.composition_workspace import (
        CompositionWorkspace,
        verify_composition_sources,
    )

    project_root = _preregistered_project_root(preregistration)
    manifest = require_within(
        project_root,
        manifest_path,
        label="Composition delivery manifest",
    )
    payload = _read_json(manifest, "composition delivery manifest")
    if (
        payload.get("kind") != "sciplot_composition_delivery"
        or payload.get("version") != 1
    ):
        raise ValueError("Not a supported composition delivery manifest.")
    if (
        payload.get("status") != "passed"
        or payload.get("state") != "ready"
        or payload.get("ready_to_use") is not True
    ):
        raise ValueError("Composition delivery is not ready.")
    expected_document_hash = _required_hash(
        authority.get("document_sha256"),
        "witness document sha256",
    )
    for field in ("composition_id", "variant_id", "variant_revision"):
        if payload.get(field) != authority.get(field):
            raise ValueError(f"Composition delivery changed witnessed field {field}.")
    exact_current_document = require_within(
        project_root,
        Path(
            _required_text(
                payload.get("exact_current_document"),
                "composition exact-current document",
            )
        ),
        label="Composition exact-current document",
    )
    witnessed_document = require_within(
        project_root,
        Path(_required_text(authority.get("document"), "witness document")),
        label="Witnessed composition document",
    )
    if (
        exact_current_document != witnessed_document
        or payload.get("exact_current_document_sha256") != expected_document_hash
        or payload.get("delivery_document_sha256") != expected_document_hash
        or payload.get("delivery_hash_parity") is not True
    ):
        raise ValueError(
            "Composition delivery does not preserve exact-current VSZ authority."
        )
    exports = _list(payload.get("exports"), "composition exports")
    verified_source = _validate_export_records(exports, hash_field=None)
    verified_delivery = _validate_export_records(
        exports,
        path_field="delivery_path",
        hash_field="delivery_sha256",
    )
    for export_format in ("pdf", "tiff_300"):
        for record in verified_source[export_format] + verified_delivery[export_format]:
            require_within(
                project_root,
                Path(record["path"]),
                label=f"Composition {export_format} artifact",
            )
        source_hashes = sorted(
            record["sha256"] for record in verified_source[export_format]
        )
        delivery_hashes = sorted(
            record["sha256"] for record in verified_delivery[export_format]
        )
        if source_hashes != delivery_hashes:
            raise ValueError(
                f"Composition delivery {export_format} does not match the "
                "exact-current source export."
            )
    files = _list(payload.get("files"), "composition delivery files")
    normalized_files: list[dict[str, Any]] = []
    for index, raw in enumerate(files):
        record = _object(raw, f"composition files[{index}]")
        source = require_within(
            project_root,
            Path(
                _required_text(
                    record.get("source"),
                    "composition delivery file source",
                )
            ),
            label="Composition delivery file source",
        )
        path = require_within(
            project_root,
            Path(
                _required_text(
                    record.get("path"),
                    "composition delivery file path",
                )
            ),
            label="Composition delivered file",
        )
        expected_hash = _required_hash(
            record.get("sha256"),
            "composition delivery file sha256",
        )
        if (
            record.get("byte_identical") is not True
            or not source.is_file()
            or not path.is_file()
            or file_sha256(source) != expected_hash
            or file_sha256(path) != expected_hash
        ):
            raise ValueError(f"Composition delivery file failed parity: {path}")
        normalized_files.append(
            {
                "source": str(source),
                "path": str(path),
                "sha256": expected_hash,
            }
        )
    qa_path = require_within(
        project_root,
        Path(_required_text(payload.get("qa_report"), "composition QA report")),
        label="Composition QA report",
    )
    qa = _read_json(qa_path, "composition QA report")
    if (
        _object(qa.get("physical_qa"), "composition physical QA").get("status")
        != "passed"
        or _object(qa.get("artifact_qa"), "composition artifact QA").get("status")
        != "passed"
    ):
        raise ValueError("Composition QA did not pass.")
    manifest_authority = _object(
        payload.get("authority"),
        "composition manifest authority",
    )
    if (
        manifest_authority.get("source_vsz_snapshots_unchanged") is not True
        or manifest_authority.get("exact_current_composite_delivered") is not True
        or manifest_authority.get("raster_panel_composition_used") is not False
    ):
        raise ValueError("Composition delivery authority contract failed.")
    composition = require_within(
        project_root,
        Path(_required_text(authority.get("composition"), "composition authority")),
        label="Composition authority",
    )
    workspace = CompositionWorkspace(composition.parent)
    project = workspace.load()
    source_verification = verify_composition_sources(workspace, project)
    witnessed_sources = [
        _object(value, "witness composition source")
        for value in _list(
            authority.get("source_modules"),
            "witness composition source_modules",
        )
    ]
    if sorted(
        (
            str(value["module_id"]),
            str(Path(value["path"]).expanduser().resolve()),
            str(value["sha256"]),
        )
        for value in witnessed_sources
    ) != sorted(
        (
            str(value["module_id"]),
            str(workspace.source_path(project.source_modules[index])),
            str(value["source_sha256"]),
        )
        for index, value in enumerate(source_verification)
    ):
        raise ValueError("Composition source snapshots differ from the reopen witness.")
    source_manifest = _read_json(
        workspace.source_manifest_path,
        "composition source manifest",
    )
    original_sources = [
        _object(value, "composition original source")
        for value in _list(
            source_manifest.get("sources"),
            "composition source manifest sources",
        )
    ]
    preregistered_sources = [
        _object(value, "preregistered composition source")
        for value in _list(
            preregistration.get("sources"),
            "preregistered composition sources",
        )
    ]
    if any(value.get("kind") != "file" for value in preregistered_sources):
        raise ValueError("Composition sessions must preregister each source VSZ file.")
    if sorted(
        (
            str(Path(str(value.get("original_source") or "")).expanduser().resolve()),
            str(value.get("original_source_sha256") or ""),
            str(value.get("snapshot_sha256") or ""),
        )
        for value in original_sources
    ) != sorted(
        (
            str(Path(str(value["path"])).expanduser().resolve()),
            str(value["sha256"]),
            str(value["sha256"]),
        )
        for value in preregistered_sources
    ):
        raise ValueError(
            "Composition source snapshots do not derive from the preregistered "
            "source VSZ files."
        )
    native_audit = audit_native_composition_runtime(
        workspace.root,
        variant_id=str(payload["variant_id"]),
    )
    geometry_error = native_audit.get("maximum_geometry_error_mm")
    style_alignment = _object(
        native_audit.get("style_alignment"),
        "composition native style alignment",
    )
    if (
        native_audit.get("raster_panel_composition_detected") is not False
        or native_audit.get("panel_labels_aligned") is not True
        or style_alignment.get("axes_aligned") is not True
        or style_alignment.get("series_strokes_aligned") is not True
        or isinstance(geometry_error, bool)
        or not isinstance(geometry_error, int | float)
        or float(geometry_error) > 0.02
    ):
        raise ValueError("Recomputed native Composition audit did not pass.")
    if canonical_sha256(native_audit) != canonical_sha256(
        _object(qa.get("native_audit"), "stored composition native audit")
    ):
        raise ValueError("Stored Composition native audit is stale.")
    if source_verification != _list(
        qa.get("source_verification"),
        "stored composition source verification",
    ):
        raise ValueError("Stored Composition source verification is stale.")
    recomputed_qa = verify_composition_production_qa(
        payload,
        document=exact_current_document,
        source_exports=verified_source,
    )
    return {
        "kind": "sciplot_composition_delivery",
        "path": str(manifest),
        "sha256": file_sha256(manifest),
        "state": "ready",
        "ready_to_use": True,
        "document_sha256": expected_document_hash,
        "qa_status": "passed",
        "source_exports": {
            key: value for key, value in sorted(verified_source.items())
        },
        "delivery_exports": {
            key: value for key, value in sorted(verified_delivery.items())
        },
        "delivery_hash_parity": True,
        "file_count": len(normalized_files),
        "qa_report": str(qa_path),
        "qa_report_sha256": file_sha256(qa_path),
        "recomputed_qa": recomputed_qa,
        "native_audit_sha256": canonical_sha256(native_audit),
        "source_manifest_sha256": file_sha256(workspace.source_manifest_path),
        "source_verification": source_verification,
        "native_composition": True,
        "raster_panel_composition_used": False,
    }


def _validate_preregistration(payload: dict[str, Any]) -> None:
    _reject_unknown(
        payload,
        _PREREGISTRATION_KEYS,
        label="preregistration payload",
    )
    _required_text(payload.get("owner"), "owner", maximum=160)
    _closed_text(payload.get("lane"), "lane", ACCEPTANCE_LANES)
    scope = _closed_text(payload.get("scope"), "scope", SESSION_SCOPES)
    source_class = _closed_text(
        payload.get("source_class"),
        "source_class",
        SOURCE_CLASSES,
    )
    _required_text(payload.get("task"), "task", maximum=1000)
    round_id = _optional_text(
        payload.get("round_id"),
        "round_id",
        maximum=100,
    )
    _required_hash(payload.get("task_fingerprint"), "task_fingerprint")
    entry_route = _closed_text(
        payload.get("entry_route"),
        "entry_route",
        ENTRY_ROUTES,
    )
    expected = [
        _closed_text(value, "expected evidence", EXPECTED_EVIDENCE)
        for value in _list(
            payload.get("expected_evidence"),
            "expected_evidence",
        )
    ]
    if not expected or expected != sorted(set(expected)):
        raise ValueError("expected_evidence must be a non-empty sorted unique list.")
    if entry_route == "compose" and "composition_lifecycle" not in expected:
        raise ValueError("The compose route requires composition_lifecycle evidence.")
    if "composition_lifecycle" in expected and entry_route != "compose":
        raise ValueError("composition_lifecycle evidence requires the compose route.")
    if {
        "canvas_lifecycle",
        "composition_lifecycle",
    }.issubset(expected):
        raise ValueError(
            "A session cannot claim Canvas and composition authority together."
        )
    if "composition_lifecycle" not in expected and "canvas_lifecycle" not in expected:
        raise ValueError(
            "A session must expect Canvas or composition lifecycle evidence."
        )
    if "review_promotion" in expected and "review_sidecar" not in expected:
        raise ValueError("review_promotion evidence requires review_sidecar evidence.")
    sources = _list(payload.get("sources"), "sources")
    if not sources:
        raise ValueError("Preregistration requires explicit source evidence.")
    for value in sources:
        record = _object(value, "source record")
        kind = _closed_text(
            record.get("kind"),
            "source kind",
            ("file", "directory"),
        )
        _reject_unknown(
            record,
            (
                {
                    "source_id",
                    "path",
                    "kind",
                    "size_bytes",
                    "sha256",
                }
                if kind == "file"
                else {
                    "source_id",
                    "path",
                    "kind",
                    "size_bytes",
                    "file_count",
                    "tree_sha256",
                    "artifact_sha256",
                    "members",
                }
            ),
            label="source record",
        )
        _required_text(record.get("source_id"), "source_id", maximum=64)
        _required_text(record.get("path"), "source path")
        _required_int(record.get("size_bytes"), "source size_bytes")
        if kind == "file":
            _required_hash(record.get("sha256"), "source sha256")
        else:
            _required_int(record.get("file_count"), "source file_count", minimum=1)
            _required_hash(record.get("tree_sha256"), "source tree_sha256")
            _required_hash(
                record.get("artifact_sha256"),
                "source artifact_sha256",
            )
            members = _list(record.get("members"), "source members")
            if len(members) != record.get("file_count"):
                raise ValueError("Source member count does not match file_count.")
            for member in members:
                member_record = _object(member, "source member")
                _reject_unknown(
                    member_record,
                    {"relative_path", "size_bytes", "sha256"},
                    label="source member",
                )
                _required_text(
                    member_record.get("relative_path"),
                    "source member relative_path",
                )
                _required_int(
                    member_record.get("size_bytes"),
                    "source member size_bytes",
                )
                _required_hash(
                    member_record.get("sha256"),
                    "source member sha256",
                )
    project = _object(payload.get("project"), "project")
    _reject_unknown(
        project,
        {"path", "root", "authority_files", "baseline_sha256"},
        label="project",
    )
    project_path = Path(_required_text(project.get("path"), "project path"))
    project_root = Path(_required_text(project.get("root"), "project root"))
    require_within(project_root, project_path, label="Preregistered project path")
    authority_files = _list(
        project.get("authority_files"),
        "project authority_files",
    )
    for value in authority_files:
        record = _object(value, "project authority file")
        _reject_unknown(
            record,
            {"relative_path", "size_bytes", "sha256"},
            label="project authority file",
        )
        _required_text(record.get("relative_path"), "project authority relative_path")
        _required_int(record.get("size_bytes"), "project authority size_bytes")
        _required_hash(record.get("sha256"), "project authority sha256")
    if canonical_sha256(authority_files) != _required_hash(
        project.get("baseline_sha256"),
        "project baseline_sha256",
    ):
        raise ValueError("Project authority baseline hash is stale.")
    build = _validate_build_payload(payload.get("build"))
    git = _object(build.get("git"), "build.git")
    artifact_contract = _object(
        build.get("artifact_contract"),
        "build.artifact_contract",
    )
    runtime = _object(build.get("runtime"), "build.runtime")
    _required_hash(
        runtime.get("identity_sha256"),
        "build.runtime.identity_sha256",
    )
    if scope in _FROZEN_BUILD_SCOPES:
        if not git.get("commit") or git.get("worktree_clean") is not True:
            raise ValueError(
                "Frozen-build sessions require a clean committed source checkout."
            )
        if round_id is None:
            raise ValueError("Frozen-build sessions require an explicit round_id.")
        if (
            artifact_contract.get("record_verified") is not True
            or artifact_contract.get("runtime_content_matches_wheel") is not True
        ):
            raise ValueError(
                "Frozen-build sessions require a verified wheel matching the active "
                "SciPlot runtime."
            )
    if scope in _FORMAL_SCOPES:
        if source_class == "synthetic_contract_fixture":
            raise ValueError("Formal sessions cannot use synthetic source evidence.")
    elif scope in _SYNTHETIC_SCOPES:
        if source_class != "synthetic_contract_fixture":
            raise ValueError(f"{scope} scope requires synthetic_contract_fixture.")
    journal = payload.get("operation_journal_baseline")
    if journal is None:
        raise ValueError("Preregistration requires an operation-journal baseline path.")
    journal_object = _object(journal, "operation_journal_baseline")
    _reject_unknown(
        journal_object,
        {
            "path",
            "existed",
            "size_bytes",
            "line_count",
            "prefix_sha256",
        },
        label="operation_journal_baseline",
    )
    _required_text(journal_object.get("path"), "journal baseline path")
    _required_int(
        journal_object.get("size_bytes"),
        "journal baseline size_bytes",
    )
    _required_int(
        journal_object.get("line_count"),
        "journal baseline line_count",
    )
    _required_hash(
        journal_object.get("prefix_sha256"),
        "journal baseline prefix_sha256",
    )
    provider = _optional_text(payload.get("provider"), "provider", maximum=160)
    model = _optional_text(payload.get("model"), "model", maximum=160)
    canonical_task = payload.get("canonical_task")
    attempt = payload.get("attempt")
    if scope == "m3_live_model_scored":
        if provider is None or model is None:
            raise ValueError("M3 scored attempts require provider and model.")
        _closed_text(canonical_task, "canonical_task", CANONICAL_MODEL_TASKS)
        if attempt not in {1, 2}:
            raise ValueError("M3 canonical attempts must be exactly 1 or 2.")
        if canonical_task == "cancellation_rollback":
            if "cancellation_rollback" not in expected:
                raise ValueError(
                    "M3 cancellation attempts require cancellation_rollback evidence."
                )
            if "ai_operation" in expected:
                raise ValueError(
                    "A rolled-back cancellation attempt cannot claim a "
                    "committed AI operation."
                )
        elif "ai_operation" not in expected:
            raise ValueError(
                "M3 model-planning attempts require ai_operation evidence."
            )
    elif canonical_task is not None or attempt is not None:
        raise ValueError(
            "canonical_task and attempt are reserved for M3 scored sessions."
        )
    if "provider_disabled" in expected:
        if provider is not None or model is not None:
            raise ValueError(
                "provider_disabled sessions cannot declare provider or model."
            )
        if "ai_operation" in expected:
            raise ValueError(
                "provider_disabled and ai_operation are mutually exclusive."
            )
        if entry_route == "compose":
            raise ValueError(
                "provider_disabled evidence requires a reopened Canvas runtime "
                "that recorded its concrete provider state."
            )
    if {"ai_operation", "cancellation_rollback", "data_mapping"} & set(expected) and (
        provider is None or model is None
    ):
        raise ValueError(
            "AI, cancellation, and mapping evidence require provider and model."
        )
    limitations = _list(payload.get("limitations"), "limitations")
    if not limitations:
        raise ValueError("Preregistration must disclose evidence limitations.")
    for value in limitations:
        _required_text(value, "limitation", maximum=1000)


def _validate_journal_reference(value: object, *, label: str) -> None:
    reference = _object(value, label)
    base_keys = {
        "index",
        "event",
        "event_id",
        "event_sha256",
        "revision",
        "provider",
        "model",
        "transaction_id",
        "request_id",
        "batch_id",
        "response_sha256",
        "response_status",
        "proposal_kind",
    }
    event = _required_text(reference.get("event"), f"{label}.event", maximum=100)
    conditional: set[str] = set()
    if event == "assistant_provider_state":
        conditional = {"provider_connected", "provider_configuration"}
    elif event == "assistant_data_mapping_handoff_opened":
        conditional = {
            "execution_manifest",
            "execution_manifest_sha256",
            "raw_inputs_mutated",
        }
    elif event == "review_annotation_promoted":
        conditional = {"annotation_id", "promoted_object_id"}
    elif event == "assistant_transaction_committed":
        conditional = {
            "accepted_batch_ids",
            "undone_batch_ids",
            "rejected_batch_ids",
            "active_batch_ids",
            "verification",
        }
    elif event == "assistant_transaction_rolled_back":
        conditional = {"verification"}
    _reject_unknown(reference, base_keys | conditional, label=label)
    missing = base_keys - set(reference)
    if missing:
        raise ValueError(f"{label} is missing fields: {sorted(missing)!r}.")
    _required_int(reference.get("index"), f"{label}.index")
    _required_hash(reference.get("event_sha256"), f"{label}.event_sha256")
    for field in (
        "event_id",
        "revision",
        "provider",
        "model",
        "transaction_id",
        "request_id",
        "batch_id",
        "response_sha256",
        "response_status",
        "proposal_kind",
    ):
        item = reference.get(field)
        if item is None:
            continue
        if field == "revision":
            _required_int(item, f"{label}.{field}")
        elif field in {"event_sha256", "response_sha256"}:
            _required_hash(item, f"{label}.{field}")
        else:
            _required_text(item, f"{label}.{field}")
    if event == "assistant_provider_state":
        if not isinstance(reference.get("provider_connected"), bool):
            raise ValueError(f"{label}.provider_connected must be boolean.")
        _required_text(
            reference.get("provider_configuration"),
            f"{label}.provider_configuration",
            maximum=200,
        )
    if event == "assistant_data_mapping_handoff_opened":
        _required_text(
            reference.get("execution_manifest"),
            f"{label}.execution_manifest",
        )
        _required_hash(
            reference.get("execution_manifest_sha256"),
            f"{label}.execution_manifest_sha256",
        )
        if not isinstance(reference.get("raw_inputs_mutated"), bool):
            raise ValueError(f"{label}.raw_inputs_mutated must be boolean.")
    if event == "review_annotation_promoted":
        _required_text(reference.get("annotation_id"), f"{label}.annotation_id")
        _required_text(
            reference.get("promoted_object_id"),
            f"{label}.promoted_object_id",
        )
    if event == "assistant_transaction_committed":
        for field in (
            "accepted_batch_ids",
            "undone_batch_ids",
            "rejected_batch_ids",
            "active_batch_ids",
        ):
            items = _list(reference.get(field), f"{label}.{field}")
            for item in items:
                _required_text(item, f"{label}.{field} item")
        verification = _object(
            reference.get("verification"),
            f"{label}.verification",
        )
        _reject_unknown(
            verification,
            {
                "structural_qa_passed",
                "canonical_vsz_unchanged_before_save",
                "raw_inputs_mutated",
            },
            label=f"{label}.verification",
        )
        if set(verification) != {
            "structural_qa_passed",
            "canonical_vsz_unchanged_before_save",
            "raw_inputs_mutated",
        }:
            raise ValueError(f"{label}.verification is incomplete.")
        if (
            not isinstance(verification["structural_qa_passed"], bool)
            or not isinstance(
                verification["canonical_vsz_unchanged_before_save"],
                bool,
            )
            or not isinstance(verification["raw_inputs_mutated"], bool)
        ):
            raise ValueError(f"{label}.verification fields must be boolean.")
    if event == "assistant_transaction_rolled_back":
        verification = _object(
            reference.get("verification"),
            f"{label}.verification",
        )
        _reject_unknown(
            verification,
            {
                "exact_baseline_render",
                "baseline_vsz_hash_verified",
                "baseline_review_hash_verified",
                "canonical_vsz_unchanged",
            },
            label=f"{label}.verification",
        )
        if set(verification) != {
            "exact_baseline_render",
            "baseline_vsz_hash_verified",
            "baseline_review_hash_verified",
            "canonical_vsz_unchanged",
        } or not all(isinstance(item, bool) for item in verification.values()):
            raise ValueError(f"{label}.verification fields must be boolean.")


def _validate_witness_journal(value: object) -> dict[str, Any]:
    journal = _object(value, "witness journal")
    _reject_unknown(
        journal,
        {
            "path",
            "baseline_size_bytes",
            "end_size_bytes",
            "end_sha256",
            "post_baseline_size_bytes",
            "post_baseline_sha256",
            "post_baseline_event_count",
            "event_types",
            "references",
            "assistant_request_count",
            "assistant_proposal_count",
            "assistant_commit_count",
            "first_proposal",
            "retry_count",
            "raw_event_payloads_copied",
        },
        label="witness journal",
    )
    _required_text(journal.get("path"), "witness journal.path")
    for field in (
        "baseline_size_bytes",
        "end_size_bytes",
        "post_baseline_size_bytes",
        "post_baseline_event_count",
        "assistant_request_count",
        "assistant_proposal_count",
        "assistant_commit_count",
        "retry_count",
    ):
        _required_int(journal.get(field), f"witness journal.{field}")
    for field in ("end_sha256", "post_baseline_sha256"):
        _required_hash(journal.get(field), f"witness journal.{field}")
    event_types = _object(journal.get("event_types"), "witness journal.event_types")
    for event_name, count in event_types.items():
        _required_text(event_name, "witness journal event name", maximum=100)
        _required_int(count, f"witness journal.event_types.{event_name}")
    references = _list(journal.get("references"), "witness journal.references")
    for index, reference in enumerate(references):
        _validate_journal_reference(
            reference,
            label=f"witness journal.references[{index}]",
        )
    first_proposal = journal.get("first_proposal")
    if first_proposal is not None:
        _validate_journal_reference(
            first_proposal,
            label="witness journal.first_proposal",
        )
        if first_proposal not in references:
            raise ValueError(
                "witness journal.first_proposal is absent from references."
            )
    if journal.get("raw_event_payloads_copied") is not False:
        raise ValueError("Witness journal cannot copy raw event payloads.")
    return journal


def _validate_export_inventory(value: object, *, label: str) -> None:
    inventory = _object(value, label)
    if not {"pdf", "tiff_300"}.issubset(inventory):
        raise ValueError(f"{label} lacks the canonical PDF/TIFF pair.")
    for export_format, records in inventory.items():
        _required_text(export_format, f"{label} format", maximum=32)
        for index, record_value in enumerate(
            _list(records, f"{label}.{export_format}")
        ):
            record = _object(record_value, f"{label}.{export_format}[{index}]")
            _reject_unknown(
                record,
                {"format", "path", "size_bytes", "sha256"},
                label=f"{label}.{export_format}[{index}]",
            )
            _required_text(
                record.get("format"),
                f"{label}.{export_format}[{index}].format",
                maximum=32,
            )
            _required_text(
                record.get("path"),
                f"{label}.{export_format}[{index}].path",
            )
            _required_int(
                record.get("size_bytes"),
                f"{label}.{export_format}[{index}].size_bytes",
                minimum=1,
            )
            _required_hash(
                record.get("sha256"),
                f"{label}.{export_format}[{index}].sha256",
            )


def _validate_witness_authority(value: object, *, mode: str) -> dict[str, Any]:
    authority = _object(value, "witness authority")
    if mode == "canvas":
        _reject_unknown(
            authority,
            {
                "canvas_session",
                "canvas_session_sha256",
                "canvas_session_id",
                "document",
                "document_sha256",
                "revision",
                "saved_revision",
                "exported_revision",
                "qa_status",
                "ready_to_use",
                "baseline_document_sha256",
                "meaningful_change_after_preregistration",
                "review_annotation_ids",
                "exports",
            },
            label="Canvas witness authority",
        )
        for field in ("canvas_session", "canvas_session_id", "document", "qa_status"):
            _required_text(authority.get(field), f"Canvas authority.{field}")
        for field in ("canvas_session_sha256", "document_sha256"):
            _required_hash(authority.get(field), f"Canvas authority.{field}")
        baseline_hash = authority.get("baseline_document_sha256")
        if baseline_hash is not None:
            _required_hash(
                baseline_hash,
                "Canvas authority.baseline_document_sha256",
            )
        for field in ("revision", "saved_revision", "exported_revision"):
            _required_int(authority.get(field), f"Canvas authority.{field}")
        if (
            authority.get("ready_to_use") is not True
            or authority.get("meaningful_change_after_preregistration") is not True
        ):
            raise ValueError("Canvas witness authority is not ready and changed.")
        annotation_ids = _list(
            authority.get("review_annotation_ids"),
            "Canvas authority.review_annotation_ids",
        )
        for annotation_id in annotation_ids:
            _required_text(annotation_id, "Canvas review annotation ID")
        _validate_export_inventory(
            authority.get("exports"),
            label="Canvas authority.exports",
        )
    else:
        _reject_unknown(
            authority,
            {
                "composition",
                "composition_sha256",
                "baseline_composition_sha256",
                "meaningful_change_after_preregistration",
                "composition_id",
                "variant_id",
                "variant_revision",
                "variant_state",
                "document",
                "document_sha256",
                "layout_id",
                "page_size_mm",
                "source_modules",
                "raster_panel_composition_allowed",
                "delivery_witness",
            },
            label="Composition witness authority",
        )
        for field in (
            "composition",
            "composition_id",
            "variant_id",
            "variant_state",
            "document",
            "layout_id",
        ):
            _required_text(authority.get(field), f"Composition authority.{field}")
        for field in ("composition_sha256", "document_sha256"):
            _required_hash(authority.get(field), f"Composition authority.{field}")
        baseline_hash = authority.get("baseline_composition_sha256")
        if baseline_hash is not None:
            _required_hash(
                baseline_hash,
                "Composition authority.baseline_composition_sha256",
            )
        _required_int(
            authority.get("variant_revision"),
            "Composition authority.variant_revision",
        )
        size = _list(
            authority.get("page_size_mm"),
            "Composition authority.page_size_mm",
        )
        if len(size) != 2 or any(
            isinstance(item, bool) or not isinstance(item, int | float) for item in size
        ):
            raise ValueError("Composition authority.page_size_mm is invalid.")
        for index, source in enumerate(
            _list(
                authority.get("source_modules"),
                "Composition authority.source_modules",
            )
        ):
            record = _object(source, f"Composition source_modules[{index}]")
            _reject_unknown(
                record,
                {"module_id", "path", "sha256"},
                label=f"Composition source_modules[{index}]",
            )
            _required_text(record.get("module_id"), "Composition source module ID")
            _required_text(record.get("path"), "Composition source module path")
            _required_hash(record.get("sha256"), "Composition source module sha256")
        if (
            authority.get("meaningful_change_after_preregistration") is not True
            or authority.get("raster_panel_composition_allowed") is not False
        ):
            raise ValueError("Composition witness authority is not native and changed.")
        _validate_completion_manifest(
            authority.get("delivery_witness"),
            label="Composition delivery witness",
            expected_kind="sciplot_composition_delivery",
        )
    return authority


def _validate_witness_optional(value: object) -> dict[str, Any]:
    optional = _object(value, "witness optional_evidence")
    _reject_unknown(
        optional,
        {"review", "data_mapping"},
        label="witness optional_evidence",
    )
    review = optional.get("review")
    if review is not None:
        record = _object(review, "witness review")
        _reject_unknown(
            record,
            {
                "path",
                "sha256",
                "annotation_ids",
                "annotation_count",
                "promoted_count",
                "promoted_annotation_ids",
                "promoted_object_ids",
            },
            label="witness review",
        )
        _required_text(record.get("path"), "witness review.path")
        _required_hash(record.get("sha256"), "witness review.sha256")
        for field in ("annotation_count", "promoted_count"):
            _required_int(record.get(field), f"witness review.{field}")
        for field in (
            "annotation_ids",
            "promoted_annotation_ids",
            "promoted_object_ids",
        ):
            items = _list(record.get(field), f"witness review.{field}")
            for item in items:
                _required_text(item, f"witness review.{field} item")
    mapping = optional.get("data_mapping")
    if mapping is not None:
        record = _object(mapping, "witness data_mapping")
        _reject_unknown(
            record,
            {
                "path",
                "sha256",
                "proposal_id",
                "proposal_sha256",
                "provider",
                "confirmation_id",
                "transform_ledger_sha256",
                "raw_inputs_unchanged",
                "handoff_allowed",
            },
            label="witness data_mapping",
        )
        for field in ("path", "proposal_id", "provider", "confirmation_id"):
            _required_text(record.get(field), f"witness data_mapping.{field}")
        for field in ("sha256", "proposal_sha256", "transform_ledger_sha256"):
            _required_hash(record.get(field), f"witness data_mapping.{field}")
        if (
            record.get("raw_inputs_unchanged") is not True
            or record.get("handoff_allowed") is not True
        ):
            raise ValueError("Witnessed data mapping is not safe for handoff.")
    return optional


def _validate_witness(payload: dict[str, Any]) -> None:
    _reject_unknown(payload, _WITNESS_KEYS, label="witness payload")
    _required_text(payload.get("owner"), "witness owner", maximum=160)
    if payload.get("attestation") is not True:
        raise ValueError("Reopen witness must contain owner attestation=true.")
    mode = _closed_text(
        payload.get("authority_mode"),
        "witness authority_mode",
        ("canvas", "composition"),
    )
    _validate_witness_authority(payload.get("authority"), mode=mode)
    _validate_witness_journal(payload.get("journal"))
    _validate_witness_optional(payload.get("optional_evidence"))
    limitations = _list(payload.get("limitations"), "witness limitations")
    if not limitations:
        raise ValueError("Witness must disclose its attestation limitation.")


def _validate_completion_manifest(
    value: object,
    *,
    label: str,
    expected_kind: str | None = None,
) -> dict[str, Any]:
    manifest = _object(value, label)
    kind = _required_text(manifest.get("kind"), f"{label}.kind", maximum=100)
    if expected_kind is not None and kind != expected_kind:
        raise ValueError(f"{label} has the wrong kind: {kind!r}.")
    common = {
        "kind",
        "path",
        "sha256",
        "state",
        "ready_to_use",
        "document_sha256",
        "qa_status",
        "recomputed_qa",
    }
    if kind == "sciplot_run":
        _reject_unknown(
            manifest,
            common
            | {
                "qa_exports",
                "delivery_complete",
                "delivery_editable_vsz",
                "delivery_figure_count",
                "transform_ledger_sha256",
                "source_lineage",
                "raw_sources_preserved",
            },
            label=label,
        )
        _validate_export_inventory(
            manifest.get("qa_exports"),
            label=f"{label}.qa_exports",
        )
        if (
            manifest.get("delivery_complete") is not True
            or manifest.get("raw_sources_preserved") is not True
        ):
            raise ValueError(f"{label} delivery/source contract is incomplete.")
        _required_text(
            manifest.get("delivery_editable_vsz"),
            f"{label}.delivery_editable_vsz",
        )
        _required_int(
            manifest.get("delivery_figure_count"),
            f"{label}.delivery_figure_count",
            minimum=2,
        )
        _required_hash(
            manifest.get("transform_ledger_sha256"),
            f"{label}.transform_ledger_sha256",
        )
        lineage = _object(manifest.get("source_lineage"), f"{label}.source_lineage")
        _reject_unknown(
            lineage,
            {
                "kind",
                "version",
                "source_count",
                "initial_input_count",
                "step_count",
                "terminal_snapshot",
                "transform_ledger_sha256",
                "mapping_bound",
                "raw_archive_bound",
            },
            label=f"{label}.source_lineage",
        )
        if (
            lineage.get("kind") != "sciplot_verified_source_lineage"
            or lineage.get("version") != 1
        ):
            raise ValueError(f"{label}.source_lineage is unsupported.")
        for field in ("source_count", "initial_input_count", "step_count"):
            _required_int(
                lineage.get(field),
                f"{label}.source_lineage.{field}",
                minimum=1,
            )
        _object(
            lineage.get("terminal_snapshot"),
            f"{label}.source_lineage.terminal_snapshot",
        )
        _required_hash(
            lineage.get("transform_ledger_sha256"),
            f"{label}.source_lineage.transform_ledger_sha256",
        )
        for field in ("mapping_bound", "raw_archive_bound"):
            if not isinstance(lineage.get(field), bool):
                raise ValueError(f"{label}.source_lineage.{field} must be boolean.")
    elif kind == "sciplot_composition_delivery":
        _reject_unknown(
            manifest,
            common
            | {
                "source_exports",
                "delivery_exports",
                "delivery_hash_parity",
                "file_count",
                "qa_report",
                "qa_report_sha256",
                "native_audit_sha256",
                "source_manifest_sha256",
                "source_verification",
                "native_composition",
                "raster_panel_composition_used",
            },
            label=label,
        )
        _validate_export_inventory(
            manifest.get("source_exports"),
            label=f"{label}.source_exports",
        )
        _validate_export_inventory(
            manifest.get("delivery_exports"),
            label=f"{label}.delivery_exports",
        )
        if (
            manifest.get("delivery_hash_parity") is not True
            or manifest.get("native_composition") is not True
            or manifest.get("raster_panel_composition_used") is not False
        ):
            raise ValueError(f"{label} native composition contract is incomplete.")
        _required_int(manifest.get("file_count"), f"{label}.file_count", minimum=1)
        _required_text(manifest.get("qa_report"), f"{label}.qa_report")
        for field in (
            "qa_report_sha256",
            "native_audit_sha256",
            "source_manifest_sha256",
        ):
            _required_hash(manifest.get(field), f"{label}.{field}")
        _list(
            manifest.get("source_verification"),
            f"{label}.source_verification",
        )
    else:
        raise ValueError(f"Unsupported completion manifest kind: {kind!r}.")
    for field in ("path", "state", "qa_status"):
        _required_text(manifest.get(field), f"{label}.{field}")
    for field in ("sha256", "document_sha256"):
        _required_hash(manifest.get(field), f"{label}.{field}")
    if (
        manifest.get("state") != "ready"
        or manifest.get("qa_status") != "passed"
        or manifest.get("ready_to_use") is not True
    ):
        raise ValueError(f"{label} is not ready.")
    recomputed = _object(manifest.get("recomputed_qa"), f"{label}.recomputed_qa")
    allowed_recomputed = {
        "kind",
        "version",
        "status",
        "report_sha256",
        "pdfs",
        "tiffs",
        "veusz_document_audited",
    }
    _reject_unknown(
        recomputed,
        allowed_recomputed,
        label=f"{label}.recomputed_qa",
    )
    if recomputed.get("version") != 1 or recomputed.get("status") != "passed":
        raise ValueError(f"{label}.recomputed_qa is not passing version 1.")
    _required_text(
        recomputed.get("kind"),
        f"{label}.recomputed_qa.kind",
        maximum=100,
    )
    _required_hash(
        recomputed.get("report_sha256"),
        f"{label}.recomputed_qa.report_sha256",
    )
    _list(recomputed.get("pdfs"), f"{label}.recomputed_qa.pdfs")
    _list(recomputed.get("tiffs"), f"{label}.recomputed_qa.tiffs")
    audited = recomputed.get("veusz_document_audited")
    if kind == "sciplot_run" and audited is not True:
        raise ValueError(f"{label}.recomputed_qa did not audit the VSZ.")
    if kind == "sciplot_composition_delivery" and audited is not None:
        raise ValueError(
            f"{label}.recomputed_qa has an unexpected regular-run audit field."
        )
    return manifest


def _validate_completion_authority(value: object) -> dict[str, Any]:
    authority = _object(value, "completion authority")
    _reject_unknown(
        authority,
        {
            "authority_mode",
            "document",
            "document_sha256",
            "revision",
            "reopen_witness_event_sha256",
        },
        label="completion authority",
    )
    _closed_text(
        authority.get("authority_mode"),
        "completion authority.authority_mode",
        ("canvas", "composition"),
    )
    _required_text(authority.get("document"), "completion authority.document")
    _required_hash(
        authority.get("document_sha256"),
        "completion authority.document_sha256",
    )
    _required_int(authority.get("revision"), "completion authority.revision")
    _required_hash(
        authority.get("reopen_witness_event_sha256"),
        "completion authority.reopen_witness_event_sha256",
    )
    return authority


def _validate_completion(payload: dict[str, Any]) -> None:
    _reject_unknown(payload, _COMPLETION_KEYS, label="completion payload")
    _required_text(payload.get("owner"), "completion owner", maximum=160)
    outcome = _closed_text(payload.get("outcome"), "outcome", SESSION_OUTCOMES)
    _required_number(
        payload.get("active_seconds"),
        "active_seconds",
        minimum=0.0,
    )
    for value in _list(payload.get("failures"), "failures"):
        _required_text(value, "failure", maximum=1000)
    fallback_events = _list(payload.get("fallback_events"), "fallback_events")
    for value in fallback_events:
        event = _object(value, "fallback event")
        _reject_unknown(
            event,
            {"class", "reason"},
            label="fallback event",
        )
        _closed_text(event.get("class"), "fallback class", FALLBACK_CLASSES)
        _required_text(event.get("reason"), "fallback reason", maximum=1000)
    _closed_text(
        payload.get("external_editor_use"),
        "external_editor_use",
        EXTERNAL_EDITOR_USES,
    )
    _closed_text(payload.get("model_score"), "model_score", MODEL_SCORES)
    authority = payload.get("authority")
    manifest = payload.get("manifest")
    if outcome == "pass":
        _validate_completion_authority(authority)
        _validate_completion_manifest(manifest, label="completion manifest")
    elif authority is not None or manifest is not None:
        raise ValueError(
            "Non-passing completion cannot attach ready authority or manifest."
        )
    _normalized_evidence_checks(
        payload.get("evidence_checks"),
        label="evidence_checks",
    )
    evaluation = _object(payload.get("evaluation"), "evaluation")
    _reject_unknown(
        evaluation,
        {
            "formal_scope",
            "frozen_build_scope",
            "synthetic_source",
            "discovery_only",
            "qualifying_m6",
            "m3_scored",
            "m3_first_proposal_correct",
            "all_expected_evidence_passed",
            "fallback_classes",
            "advanced_editor_used",
            "counting_rule",
        },
        label="completion evaluation",
    )
    for field in (
        "formal_scope",
        "frozen_build_scope",
        "synthetic_source",
        "discovery_only",
        "qualifying_m6",
        "m3_scored",
        "all_expected_evidence_passed",
        "advanced_editor_used",
    ):
        if not isinstance(evaluation.get(field), bool):
            raise ValueError(f"completion evaluation.{field} must be boolean.")
    first_correct = evaluation.get("m3_first_proposal_correct")
    if first_correct is not None and not isinstance(first_correct, bool):
        raise ValueError(
            "completion evaluation.m3_first_proposal_correct must be boolean or null."
        )
    fallback_classes = _list(
        evaluation.get("fallback_classes"),
        "completion evaluation.fallback_classes",
    )
    if fallback_classes != sorted(set(fallback_classes)):
        raise ValueError(
            "completion evaluation.fallback_classes must be sorted and unique."
        )
    for value in fallback_classes:
        _closed_text(value, "completion evaluation fallback class", FALLBACK_CLASSES)
    _required_text(
        evaluation.get("counting_rule"),
        "completion evaluation.counting_rule",
        maximum=1000,
    )
    limitations = _list(payload.get("limitations"), "completion limitations")
    if not limitations:
        raise ValueError("Completion must preserve evidence limitations.")


def _validate_event(
    event: dict[str, Any],
    *,
    expected_sequence: int,
    previous_sha256: str,
) -> None:
    _reject_unknown(event, _EVENT_KEYS, label="session evidence event")
    if event.get("kind") != SESSION_EVIDENCE_EVENT_KIND:
        raise ValueError("Not a SciPlot session evidence event.")
    if event.get("version") != SESSION_EVIDENCE_EVENT_VERSION:
        raise ValueError(
            f"Unsupported session evidence version: {event.get('version')!r}."
        )
    sequence = _required_int(event.get("sequence"), "event sequence", minimum=1)
    if sequence != expected_sequence:
        raise ValueError(
            f"Session evidence sequence gap: expected {expected_sequence}, "
            f"found {sequence}."
        )
    _required_text(event.get("event_id"), "event_id", maximum=80)
    event_type = _closed_text(event.get("event_type"), "event_type", _EVENT_TYPES)
    _required_text(event.get("session_id"), "session_id", maximum=100)
    _required_timestamp(event.get("recorded_at"), "recorded_at")
    if (
        _required_hash(
            event.get("previous_event_sha256"),
            "previous_event_sha256",
        )
        != previous_sha256
    ):
        raise ValueError(f"Session evidence chain is broken at sequence {sequence}.")
    payload = _object(event.get("payload"), "event payload")
    if event_type == "preregistered":
        _validate_preregistration(payload)
    elif event_type == "reopen_witnessed":
        _validate_witness(payload)
    else:
        _validate_completion(payload)
    expected_hash = canonical_sha256(
        {key: value for key, value in event.items() if key != "event_sha256"}
    )
    if _required_hash(event.get("event_sha256"), "event_sha256") != expected_hash:
        raise ValueError(
            f"Session evidence event hash mismatch at sequence {sequence}."
        )


def _validate_transitions(events: list[dict[str, Any]]) -> None:
    states: dict[str, list[str]] = {}
    event_ids: set[str] = set()
    for event in events:
        event_id = str(event["event_id"])
        if event_id in event_ids:
            raise ValueError(f"Duplicate session evidence event ID: {event_id}")
        event_ids.add(event_id)
        session_id = str(event["session_id"])
        event_type = str(event["event_type"])
        history = states.setdefault(session_id, [])
        if not history and event_type != "preregistered":
            raise ValueError(
                f"Session {session_id} has evidence before preregistration."
            )
        if event_type == "preregistered" and history:
            raise ValueError(f"Session {session_id} was preregistered twice.")
        if event_type == "reopen_witnessed":
            if "reopen_witnessed" in history:
                raise ValueError(f"Session {session_id} has two reopen witnesses.")
            if "completed" in history:
                raise ValueError(
                    f"Session {session_id} was witnessed after completion."
                )
        if event_type == "completed":
            if "completed" in history:
                raise ValueError(f"Session {session_id} was completed twice.")
        history.append(event_type)


def _validate_completion_relations(events: list[dict[str, Any]]) -> None:
    sessions: dict[str, dict[str, dict[str, Any]]] = {}
    preregistrations: list[dict[str, Any]] = []
    for event in events:
        payload = _object(
            event.get("payload"),
            f"{event['event_type']} payload",
        )
        if event.get("event_type") == "preregistered":
            _assert_unique_preregistration(preregistrations, payload)
            preregistrations.append(payload)
        record = sessions.setdefault(str(event["session_id"]), {})
        record[str(event["event_type"])] = payload
    for session_id, record in sessions.items():
        completion = record.get("completed")
        if completion is None:
            continue
        preregistration = record.get("preregistered")
        if preregistration is None:
            raise ValueError(f"Session {session_id} completed without preregistration.")
        witness = record.get("reopen_witnessed")
        stored_checks = _normalized_evidence_checks(
            completion.get("evidence_checks"),
            label=f"session {session_id} evidence_checks",
        )
        if completion.get("outcome") == "pass":
            if witness is None:
                raise ValueError(f"Session {session_id} passed without a witness.")
            derived_checks = _completion_evidence_checks(
                preregistration,
                witness,
            )
        else:
            derived_checks = {key: False for key in EXPECTED_EVIDENCE}
        if stored_checks != derived_checks:
            raise ValueError(
                f"Session {session_id} stored evidence checks do not match "
                "the preregistration-bound witness."
            )
        derived_evaluation = _completion_evaluation(
            preregistration,
            completion,
            evidence_checks=derived_checks,
        )
        if completion.get("evaluation") != derived_evaluation:
            raise ValueError(
                f"Session {session_id} stored evaluation does not match "
                "the raw completion evidence."
            )


def _read_events_unlocked(ledger_path: Path) -> list[dict[str, Any]]:
    ledger = ledger_path.expanduser().resolve()
    if not ledger.is_file():
        return []
    events: list[dict[str, Any]] = []
    previous = GENESIS_SHA256
    for line_number, line in enumerate(
        ledger.read_text(encoding="utf-8").splitlines(),
        1,
    ):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Session evidence ledger line {line_number} is invalid JSON."
            ) from exc
        if not isinstance(value, dict):
            raise ValueError(
                f"Session evidence ledger line {line_number} is not an object."
            )
        _validate_event(
            value,
            expected_sequence=len(events) + 1,
            previous_sha256=previous,
        )
        events.append(value)
        previous = str(value["event_sha256"])
    _validate_transitions(events)
    _validate_completion_relations(events)
    return events


def _verify_head_unlocked(
    ledger_path: Path,
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    ledger = ledger_path.expanduser().resolve()
    head_path = _head_path(ledger)
    if not events:
        if head_path.exists():
            raise ValueError("Empty ledger has a stale head checkpoint.")
        return {
            "event_count": 0,
            "last_event_sha256": GENESIS_SHA256,
            "head": None,
        }
    head = _read_json(head_path, "session evidence head checkpoint")
    _reject_unknown(
        head,
        {
            "kind",
            "version",
            "ledger",
            "event_count",
            "last_event_sha256",
            "ledger_size_bytes",
            "ledger_sha256",
            "updated_at",
        },
        label="session evidence head",
    )
    if (
        head.get("kind") != SESSION_EVIDENCE_HEAD_KIND
        or head.get("version") != SESSION_EVIDENCE_HEAD_VERSION
    ):
        raise ValueError("Unsupported session evidence head checkpoint.")
    if (
        Path(_required_text(head.get("ledger"), "head ledger")).expanduser().resolve()
        != ledger
    ):
        raise ValueError("Session evidence head points to another ledger.")
    data = ledger.read_bytes()
    if (
        _required_int(head.get("event_count"), "head event_count") != len(events)
        or _required_hash(
            head.get("last_event_sha256"),
            "head last_event_sha256",
        )
        != events[-1]["event_sha256"]
        or _required_int(
            head.get("ledger_size_bytes"),
            "head ledger_size_bytes",
        )
        != len(data)
        or _required_hash(head.get("ledger_sha256"), "head ledger_sha256")
        != hashlib.sha256(data).hexdigest()
    ):
        raise ValueError(
            "Session evidence head does not match the ledger; the ledger may "
            "have been truncated or replaced."
        )
    _required_timestamp(head.get("updated_at"), "head updated_at")
    return {
        "event_count": len(events),
        "last_event_sha256": events[-1]["event_sha256"],
        "head": str(head_path),
    }


def _read_verified_events(ledger_path: Path) -> list[dict[str, Any]]:
    with _ledger_lock(ledger_path, exclusive=False):
        pending = _pending_path(ledger_path)
        if pending.exists():
            raise ValueError(
                "Session evidence ledger has a pending append; run "
                "`sciplot sessions recover LEDGER` before trusting status."
            )
        events = _read_events_unlocked(ledger_path)
        _verify_head_unlocked(ledger_path, events)
        return events


def _write_head_unlocked(
    ledger_path: Path,
    events: list[dict[str, Any]],
) -> Path:
    ledger = ledger_path.expanduser().resolve()
    data = ledger.read_bytes()
    path = atomic_write_json(
        _head_path(ledger),
        {
            "kind": SESSION_EVIDENCE_HEAD_KIND,
            "version": SESSION_EVIDENCE_HEAD_VERSION,
            "ledger": str(ledger),
            "event_count": len(events),
            "last_event_sha256": (
                events[-1]["event_sha256"] if events else GENESIS_SHA256
            ),
            "ledger_size_bytes": len(data),
            "ledger_sha256": hashlib.sha256(data).hexdigest(),
            "updated_at": _now(),
        },
    )
    _fsync_directory(path.parent)
    return path


def _pending_record(
    ledger_path: Path,
    *,
    events: list[dict[str, Any]],
    event: dict[str, Any],
) -> dict[str, Any]:
    ledger = ledger_path.expanduser().resolve()
    data = ledger.read_bytes() if ledger.is_file() else b""
    record = {
        "kind": SESSION_EVIDENCE_PENDING_KIND,
        "version": SESSION_EVIDENCE_PENDING_VERSION,
        "ledger": str(ledger),
        "created_at": _now(),
        "base_event_count": len(events),
        "base_last_event_sha256": (
            events[-1]["event_sha256"] if events else GENESIS_SHA256
        ),
        "base_ledger_size_bytes": len(data),
        "base_ledger_sha256": hashlib.sha256(data).hexdigest(),
        "event": event,
    }
    record["pending_sha256"] = canonical_sha256(record)
    return record


def _validate_pending_record(
    ledger_path: Path,
    value: dict[str, Any],
) -> tuple[dict[str, Any], int, int, str, str]:
    _reject_unknown(
        value,
        {
            "kind",
            "version",
            "ledger",
            "created_at",
            "base_event_count",
            "base_last_event_sha256",
            "base_ledger_size_bytes",
            "base_ledger_sha256",
            "event",
            "pending_sha256",
        },
        label="session evidence pending append",
    )
    if (
        value.get("kind") != SESSION_EVIDENCE_PENDING_KIND
        or value.get("version") != SESSION_EVIDENCE_PENDING_VERSION
    ):
        raise ValueError("Unsupported session evidence pending append.")
    ledger = ledger_path.expanduser().resolve()
    recorded_ledger = (
        Path(_required_text(value.get("ledger"), "pending ledger"))
        .expanduser()
        .resolve()
    )
    if recorded_ledger != ledger:
        raise ValueError("Session evidence pending append points to another ledger.")
    _required_timestamp(value.get("created_at"), "pending created_at")
    base_count = _required_int(
        value.get("base_event_count"),
        "pending base_event_count",
    )
    base_size = _required_int(
        value.get("base_ledger_size_bytes"),
        "pending base_ledger_size_bytes",
    )
    base_last = _required_hash(
        value.get("base_last_event_sha256"),
        "pending base_last_event_sha256",
    )
    base_sha = _required_hash(
        value.get("base_ledger_sha256"),
        "pending base_ledger_sha256",
    )
    expected_pending_hash = canonical_sha256(
        {key: item for key, item in value.items() if key != "pending_sha256"}
    )
    if (
        _required_hash(
            value.get("pending_sha256"),
            "pending_sha256",
        )
        != expected_pending_hash
    ):
        raise ValueError("Session evidence pending append hash mismatch.")
    event = _object(value.get("event"), "pending event")
    _validate_event(
        event,
        expected_sequence=base_count + 1,
        previous_sha256=base_last,
    )
    return event, base_count, base_size, base_last, base_sha


def _head_matches_pending_base(
    ledger_path: Path,
    *,
    base_count: int,
    base_size: int,
    base_last: str,
    base_sha: str,
) -> bool:
    head_path = _head_path(ledger_path)
    if not head_path.exists():
        return base_count == 0 and base_size == 0 and base_last == GENESIS_SHA256
    try:
        head = _read_json(head_path, "session evidence head checkpoint")
    except Exception:
        return False
    return bool(
        head.get("kind") == SESSION_EVIDENCE_HEAD_KIND
        and head.get("version") == SESSION_EVIDENCE_HEAD_VERSION
        and Path(str(head.get("ledger") or "")).expanduser().resolve()
        == ledger_path.expanduser().resolve()
        and head.get("event_count") == base_count
        and head.get("last_event_sha256") == base_last
        and head.get("ledger_size_bytes") == base_size
        and head.get("ledger_sha256") == base_sha
    )


def _remove_pending_unlocked(ledger_path: Path) -> None:
    pending = _pending_path(ledger_path)
    pending.unlink()
    _fsync_directory(pending.parent)


def recover_session_ledger(ledger_path: Path) -> dict[str, Any]:
    ledger = ledger_path.expanduser().resolve()
    pending_path = _pending_path(ledger)
    with _ledger_lock(ledger, exclusive=True):
        if not pending_path.is_file():
            events = _read_events_unlocked(ledger)
            _verify_head_unlocked(ledger, events)
            return {
                "kind": "sciplot_session_evidence_recovery",
                "version": 1,
                "status": "clean",
                "ledger": str(ledger),
                "pending": str(pending_path),
                "event_count": len(events),
                "action": "none",
            }
        pending = _read_json(
            pending_path,
            "session evidence pending append",
        )
        event, base_count, base_size, base_last, base_sha = _validate_pending_record(
            ledger, pending
        )
        data = ledger.read_bytes() if ledger.is_file() else b""
        events = _read_events_unlocked(ledger)
        candidate_line = _canonical_bytes(event) + b"\n"
        if len(events) == base_count:
            if (
                len(data) != base_size
                or hashlib.sha256(data).hexdigest() != base_sha
                or (events[-1]["event_sha256"] if events else GENESIS_SHA256)
                != base_last
                or not _head_matches_pending_base(
                    ledger,
                    base_count=base_count,
                    base_size=base_size,
                    base_last=base_last,
                    base_sha=base_sha,
                )
            ):
                raise ValueError(
                    "Pending append base does not match the current ledger/head; "
                    "automatic recovery is unsafe."
                )
            candidate_events = [*events, event]
            _validate_transitions(candidate_events)
            _validate_completion_relations(candidate_events)
            with ledger.open("ab") as handle:
                handle.write(candidate_line)
                handle.flush()
                os.fsync(handle.fileno())
            events = candidate_events
            _write_head_unlocked(ledger, events)
            _remove_pending_unlocked(ledger)
            action = "appended_and_finalized"
        elif len(events) == base_count + 1 and events[-1] == event:
            if (
                len(data) != base_size + len(candidate_line)
                or data[:base_size] != data[: -len(candidate_line)]
                or hashlib.sha256(data[:base_size]).hexdigest() != base_sha
                or data[base_size:] != candidate_line
            ):
                raise ValueError(
                    "Pending event bytes do not match the current ledger tail; "
                    "automatic recovery is unsafe."
                )
            try:
                _verify_head_unlocked(ledger, events)
                action = "cleared_completed_pending"
            except Exception:
                if not _head_matches_pending_base(
                    ledger,
                    base_count=base_count,
                    base_size=base_size,
                    base_last=base_last,
                    base_sha=base_sha,
                ):
                    raise ValueError(
                        "Ledger contains the pending event but the head is "
                        "neither the proven base nor final state."
                    ) from None
                _write_head_unlocked(ledger, events)
                action = "finalized_head"
            _remove_pending_unlocked(ledger)
        else:
            raise ValueError(
                "Ledger event count is incompatible with the pending append; "
                "automatic recovery is unsafe."
            )
        verified = _read_events_unlocked(ledger)
        _verify_head_unlocked(ledger, verified)
        return {
            "kind": "sciplot_session_evidence_recovery",
            "version": 1,
            "status": "recovered",
            "ledger": str(ledger),
            "pending": str(pending_path),
            "event_count": len(verified),
            "last_event_sha256": verified[-1]["event_sha256"],
            "action": action,
        }


def _append_event(
    ledger_path: Path,
    *,
    session_id: str,
    event_type: str,
    payload: dict[str, Any],
    precondition: Callable[[list[dict[str, Any]]], None] | None = None,
) -> dict[str, Any]:
    ledger = ledger_path.expanduser().resolve()
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with _ledger_lock(ledger, exclusive=True):
        pending_path = _pending_path(ledger)
        if pending_path.exists():
            raise ValueError(
                "Session evidence ledger has a pending append; run "
                "`sciplot sessions recover LEDGER` first."
            )
        events = _read_events_unlocked(ledger)
        _verify_head_unlocked(ledger, events)
        if precondition is not None:
            precondition(events)
        event = {
            "kind": SESSION_EVIDENCE_EVENT_KIND,
            "version": SESSION_EVIDENCE_EVENT_VERSION,
            "sequence": len(events) + 1,
            "event_id": str(uuid4()),
            "event_type": event_type,
            "session_id": session_id,
            "recorded_at": _now(),
            "previous_event_sha256": (
                events[-1]["event_sha256"] if events else GENESIS_SHA256
            ),
            "payload": payload,
        }
        event["event_sha256"] = canonical_sha256(event)
        _validate_event(
            event,
            expected_sequence=len(events) + 1,
            previous_sha256=event["previous_event_sha256"],
        )
        candidate = [*events, event]
        _validate_transitions(candidate)
        _validate_completion_relations(candidate)
        line = _canonical_bytes(event) + b"\n"
        pending = _pending_record(ledger, events=events, event=event)
        atomic_write_json(pending_path, pending)
        _fsync_directory(pending_path.parent)
        with ledger.open("ab") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())
        _write_head_unlocked(ledger, candidate)
        _remove_pending_unlocked(ledger)
        return event


def _session_events(
    events: list[dict[str, Any]],
    session_id: str,
) -> list[dict[str, Any]]:
    matching = [event for event in events if event.get("session_id") == session_id]
    if not matching:
        raise ValueError(f"Unknown session evidence ID: {session_id}")
    return matching


def _event_payload(
    session_events: list[dict[str, Any]],
    event_type: str,
) -> dict[str, Any] | None:
    match = next(
        (event for event in session_events if event.get("event_type") == event_type),
        None,
    )
    return (
        _object(match.get("payload"), f"{event_type} payload")
        if match is not None
        else None
    )


def default_session_ledger(project_path: Path) -> Path:
    project = project_path.expanduser().resolve()
    root = project if project.is_dir() else project.parent
    return root / ".sciplot_evidence" / "session_evidence.jsonl"


def _assert_unique_preregistration(
    existing_payloads: list[dict[str, Any]],
    payload: dict[str, Any],
) -> None:
    for existing_payload in existing_payloads:
        same_fingerprint = (
            existing_payload.get("task_fingerprint") == payload["task_fingerprint"]
        )
        both_m3 = (
            existing_payload.get("scope") == "m3_live_model_scored"
            and payload.get("scope") == "m3_live_model_scored"
            and existing_payload.get("canonical_task") == payload.get("canonical_task")
        )
        if same_fingerprint and not both_m3:
            raise ValueError(
                "This natural task and source evidence were already preregistered."
            )
        if payload.get("scope") == "m3_live_model_scored" and (
            existing_payload.get("scope") == "m3_live_model_scored"
            and existing_payload.get("round_id") == payload.get("round_id")
            and existing_payload.get("provider") == payload.get("provider")
            and existing_payload.get("model") == payload.get("model")
            and existing_payload.get("canonical_task") == payload.get("canonical_task")
            and existing_payload.get("attempt") == payload.get("attempt")
        ):
            raise ValueError(
                "This provider/model canonical-task attempt is already registered."
            )


def preregister_session(
    ledger_path: Path,
    *,
    project_path: Path,
    source_paths: list[Path],
    lane: str,
    scope: str,
    source_class: str,
    task: str,
    round_id: str | None = None,
    owner: str,
    entry_route: str,
    build_artifact: Path,
    expected_evidence: list[str],
    repo_root: Path | None = None,
    veusz_root: Path | None = None,
    journal_path: Path | None = None,
    provider: str | None = None,
    model: str | None = None,
    canonical_task: str | None = None,
    attempt: int | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    ledger = ledger_path.expanduser().resolve()
    identifier = (
        _required_text(session_id, "session_id", maximum=100)
        if session_id is not None
        else f"session_{uuid4().hex}"
    )
    source_records = _source_fingerprints(source_paths)
    normalized_task = " ".join(
        _required_text(task, "task", maximum=1000).casefold().split()
    )
    fingerprint_basis = {
        "task": normalized_task,
        "sources": sorted(
            [
                {
                    "kind": record["kind"],
                    "sha256": (record.get("sha256") or record.get("artifact_sha256")),
                }
                for record in source_records
            ],
            key=lambda value: (str(value["kind"]), str(value["sha256"])),
        ),
    }
    payload = {
        "owner": _required_text(owner, "owner", maximum=160),
        "lane": lane,
        "scope": scope,
        "source_class": source_class,
        "task": _required_text(task, "task", maximum=1000),
        "round_id": _optional_text(round_id, "round_id", maximum=100),
        "task_fingerprint": canonical_sha256(fingerprint_basis),
        "entry_route": entry_route,
        "expected_evidence": sorted(set(expected_evidence)),
        "sources": source_records,
        "project": _project_baseline(project_path),
        "build": _build_identity(
            build_artifact,
            require_frozen=scope in _FROZEN_BUILD_SCOPES,
            repo_root=repo_root,
            veusz_root=veusz_root,
        ),
        "operation_journal_baseline": _journal_baseline(journal_path),
        "provider": _optional_text(provider, "provider", maximum=160),
        "model": _optional_text(model, "model", maximum=160),
        "canonical_task": canonical_task,
        "attempt": attempt,
        "limitations": [
            "This local hash chain is tamper-evident, not a signed identity or remote timestamp authority.",
            "Source values are not copied into the ledger; explicit paths, sizes, and SHA-256 evidence are recorded.",
            "The wheel bytes must equal the active clean-checkout package bytes; this local equality proof is not a signed supply-chain attestation.",
            "No existing session or artifact may be retroactively promoted into this preregistration.",
        ],
    }
    _validate_preregistration(payload)

    def assert_preregistration_available(
        current_events: list[dict[str, Any]],
    ) -> None:
        if any(event.get("session_id") == identifier for event in current_events):
            raise ValueError(f"Duplicate session evidence ID: {identifier}")
        preregistrations = [
            _object(event.get("payload"), "existing preregistration")
            for event in current_events
            if event.get("event_type") == "preregistered"
        ]
        _assert_unique_preregistration(preregistrations, payload)

    event = _append_event(
        ledger,
        session_id=identifier,
        event_type="preregistered",
        payload=payload,
        precondition=assert_preregistration_available,
    )
    return {
        "kind": "sciplot_session_preregistration",
        "version": 1,
        "status": "preregistered",
        "session_id": identifier,
        "ledger": str(ledger),
        "head": str(_head_path(ledger)),
        "event": event,
        "formal_evidence_eligible": scope in _FORMAL_SCOPES,
        "frozen_build_contract": scope in _FROZEN_BUILD_SCOPES,
        "next_action": (
            "Complete the declared natural task, save/export exact-current "
            "artifacts, close and actually reopen the SciPlot Canvas, then "
            "record `sciplot sessions witness`."
        ),
    }


def witness_session_reopen(
    ledger_path: Path,
    session_id: str,
    *,
    owner: str,
    journal_path: Path,
    canvas_session_path: Path | None = None,
    document_path: Path | None = None,
    review_path: Path | None = None,
    mapping_execution_path: Path | None = None,
    composition_path: Path | None = None,
    composition_delivery_path: Path | None = None,
) -> dict[str, Any]:
    ledger = ledger_path.expanduser().resolve()
    events = _read_verified_events(ledger)
    session_history = _session_events(events, session_id)
    preregistration = _event_payload(session_history, "preregistered")
    if preregistration is None:
        raise ValueError("Session has no preregistration.")
    if _event_payload(session_history, "reopen_witnessed") is not None:
        raise ValueError("Session already has a reopen witness.")
    if _event_payload(session_history, "completed") is not None:
        raise ValueError("Completed sessions cannot be witnessed again.")
    operator = _required_text(owner, "owner", maximum=160)
    if operator != preregistration.get("owner"):
        raise ValueError("Reopen witness owner differs from preregistration.")
    canvas_mode = canvas_session_path is not None or document_path is not None
    composition_mode = composition_path is not None
    if canvas_mode == composition_mode:
        raise ValueError("Witness exactly one authority mode: Canvas or composition.")
    if canvas_mode:
        if canvas_session_path is None or document_path is None:
            raise ValueError(
                "Canvas witness requires canvas_session.json and document.vsz."
            )
        authority, journal, optional = _canvas_witness(
            preregistration,
            canvas_session_path=canvas_session_path,
            journal_path=journal_path,
            document_path=document_path,
            review_path=review_path,
            mapping_execution_path=mapping_execution_path,
        )
        authority_mode = "canvas"
    else:
        if composition_path is None:
            raise ValueError("Composition witness requires composition.json.")
        if composition_delivery_path is None:
            raise ValueError(
                "Composition witness requires the final delivery manifest "
                "created before close/reopen."
            )
        authority, journal, optional = _composition_witness(
            preregistration,
            composition_path=composition_path,
            journal_path=journal_path,
            delivery_manifest_path=composition_delivery_path,
        )
        authority_mode = "composition"
    expected = set(preregistration["expected_evidence"])
    if authority_mode == "canvas" and "composition_lifecycle" in expected:
        raise ValueError(
            "A composition-lifecycle session must witness composition authority."
        )
    if authority_mode == "composition" and "canvas_lifecycle" in expected:
        raise ValueError("A Canvas-lifecycle session must witness Canvas authority.")
    payload = {
        "owner": operator,
        "attestation": True,
        "authority_mode": authority_mode,
        "authority": authority,
        "journal": journal,
        "optional_evidence": optional,
        "limitations": [
            "The owner attests that the named GUI authority was actually closed and reopened before this event.",
            "Version 1 verifies the reopened files, revisions, journal boundary, QA, and hashes; it cannot independently observe or authenticate a human at the display.",
            "The witness is valid only while the exact-current authority and journal remain unchanged.",
        ],
    }
    _validate_witness(payload)
    event = _append_event(
        ledger,
        session_id=session_id,
        event_type="reopen_witnessed",
        payload=payload,
    )
    return {
        "kind": "sciplot_session_reopen_witness",
        "version": 1,
        "status": "witnessed",
        "session_id": session_id,
        "ledger": str(ledger),
        "authority_mode": authority_mode,
        "document_sha256": authority["document_sha256"],
        "revision": authority.get("revision") or authority.get("variant_revision"),
        "event": event,
        "next_action": (
            "Do not edit the witnessed authority. Record completion against "
            "the matching ready manifest/delivery manifest."
        ),
    }


def _parse_fallback_events(values: list[str]) -> list[dict[str, str]]:
    events: list[dict[str, str]] = []
    for value in values:
        text = _required_text(value, "fallback", maximum=1200)
        fallback_class, separator, reason = text.partition(":")
        if not separator:
            raise ValueError(
                "Fallbacks must use CLOSED_CLASS:reason, for example "
                "p2_low_frequency:used an unsupported low-frequency editor."
            )
        events.append(
            {
                "class": _closed_text(
                    fallback_class.strip(),
                    "fallback class",
                    FALLBACK_CLASSES,
                ),
                "reason": _required_text(
                    reason,
                    "fallback reason",
                    maximum=1000,
                ),
            }
        )
    return events


def _completion_evidence_checks(
    preregistration: dict[str, Any],
    witness: dict[str, Any],
) -> dict[str, bool]:
    expected = set(preregistration["expected_evidence"])
    journal = _object(witness.get("journal"), "witness journal")
    references = [
        _object(value, "journal reference")
        for value in _list(journal.get("references"), "journal references")
    ]
    checks: dict[str, bool] = {}
    checks["canvas_lifecycle"] = (
        witness.get("authority_mode") == "canvas"
        and _object(witness.get("authority"), "witness authority").get("ready_to_use")
        is True
    )
    checks["composition_lifecycle"] = (
        witness.get("authority_mode") == "composition"
        and _object(witness.get("authority"), "witness authority").get(
            "raster_panel_composition_allowed"
        )
        is False
    )
    event_types = _object(
        journal.get("event_types"),
        "journal event_types",
    )
    assistant_activity = any(
        str(name).startswith("assistant_")
        and name != "assistant_provider_state"
        and int(count or 0) > 0
        for name, count in event_types.items()
    )
    provider_states = [
        value
        for value in references
        if value.get("event") == "assistant_provider_state"
    ]
    checks["provider_disabled"] = bool(
        witness.get("authority_mode") == "canvas"
        and provider_states
        and all(value.get("provider_connected") is False for value in provider_states)
        and not assistant_activity
    )
    expected_provider = preregistration.get("provider")
    expected_model = preregistration.get("model")
    matching_requests = [
        value
        for value in references
        if value.get("event") == "assistant_request_submitted"
        and value.get("provider") == expected_provider
        and value.get("model") == expected_model
        and value.get("transaction_id")
    ]
    linked_ai_chains: list[dict[str, Any]] = []
    linked_cancellation_chains: list[dict[str, Any]] = []
    for request in matching_requests:
        transaction_id = str(request["transaction_id"])
        request_id = str(request.get("request_id") or "")
        request_index = int(request["index"])
        proposals = [
            value
            for value in references
            if value.get("event") == "assistant_batch_proposed"
            and value.get("provider") == expected_provider
            and value.get("transaction_id") == transaction_id
            and value.get("request_id") == request_id
            and int(value.get("index") or -1) > request_index
            and value.get("response_status") == "proposal"
            and value.get("proposal_kind") == "canvas_operation_batch"
            and value.get("response_sha256") is not None
            and value.get("batch_id")
        ]
        for proposal in proposals:
            batch_id = str(proposal["batch_id"])
            commits = [
                value
                for value in references
                if value.get("event") == "assistant_transaction_committed"
                and value.get("provider") == expected_provider
                and value.get("transaction_id") == transaction_id
                and int(value.get("index") or -1) > int(proposal["index"])
                and batch_id in (value.get("active_batch_ids") or [])
                and _object(
                    value.get("verification"),
                    "assistant commit verification",
                ).get("structural_qa_passed")
                is True
                and _object(
                    value.get("verification"),
                    "assistant commit verification",
                ).get("canonical_vsz_unchanged_before_save")
                is True
                and _object(
                    value.get("verification"),
                    "assistant commit verification",
                ).get("raw_inputs_mutated")
                is False
            ]
            for commit in commits:
                later_same_batch_undo = any(
                    value.get("event") == "assistant_batch_undone"
                    and value.get("provider") == expected_provider
                    and value.get("transaction_id") == transaction_id
                    and value.get("batch_id") == batch_id
                    and int(value.get("index") or -1) > int(commit["index"])
                    for value in references
                )
                if not later_same_batch_undo:
                    linked_ai_chains.append(
                        {
                            "transaction_id": transaction_id,
                            "request_id": request_id,
                            "batch_id": batch_id,
                        }
                    )
        cancels = [
            value
            for value in references
            if value.get("event") == "assistant_request_cancel_requested"
            and value.get("provider") == expected_provider
            and value.get("transaction_id") == transaction_id
            and value.get("request_id") == request_id
            and int(value.get("index") or -1) > request_index
        ]
        for cancel in cancels:
            rollbacks = [
                value
                for value in references
                if value.get("event") == "assistant_transaction_rolled_back"
                and value.get("provider") == expected_provider
                and value.get("transaction_id") == transaction_id
                and int(value.get("index") or -1) > int(cancel["index"])
                and all(
                    _object(
                        value.get("verification"),
                        "assistant rollback verification",
                    ).get(field)
                    is True
                    for field in (
                        "exact_baseline_render",
                        "baseline_vsz_hash_verified",
                        "baseline_review_hash_verified",
                        "canonical_vsz_unchanged",
                    )
                )
            ]
            if rollbacks:
                linked_cancellation_chains.append(
                    {
                        "transaction_id": transaction_id,
                        "request_id": request_id,
                    }
                )
    checks["ai_operation"] = bool(linked_ai_chains)
    checks["cancellation_rollback"] = bool(linked_cancellation_chains)
    optional = _object(
        witness.get("optional_evidence"),
        "witness optional_evidence",
    )
    mapping = optional.get("data_mapping")
    mapping_handoffs = []
    if isinstance(mapping, dict):
        mapping_path = str(Path(str(mapping.get("path") or "")).expanduser().resolve())
        for request in matching_requests:
            mapping_handoffs.extend(
                value
                for value in references
                if value.get("event") == "assistant_data_mapping_handoff_opened"
                and value.get("provider") == expected_provider
                and value.get("transaction_id") == request.get("transaction_id")
                and value.get("request_id") == request.get("request_id")
                and value.get("execution_manifest") == mapping_path
                and value.get("execution_manifest_sha256") == mapping.get("sha256")
                and value.get("raw_inputs_mutated") is False
                and int(value.get("index") or -1) > int(request["index"])
            )
    checks["data_mapping"] = bool(
        isinstance(mapping, dict)
        and mapping.get("provider") == expected_provider
        and mapping.get("raw_inputs_unchanged") is True
        and mapping.get("handoff_allowed") is True
        and mapping_handoffs
    )
    review = optional.get("review")
    checks["review_sidecar"] = (
        isinstance(review, dict) and int(review.get("annotation_count") or 0) > 0
    )
    checks["review_promotion"] = (
        isinstance(review, dict)
        and int(review.get("promoted_count") or 0) > 0
        and {
            (
                str(value.get("annotation_id") or ""),
                str(value.get("promoted_object_id") or ""),
            )
            for value in references
            if value.get("event") == "review_annotation_promoted"
        }
        >= set(
            zip(
                review.get("promoted_annotation_ids") or [],
                review.get("promoted_object_ids") or [],
                strict=True,
            )
        )
    )
    for evidence_id in expected:
        if checks.get(evidence_id) is not True:
            raise ValueError(
                f"Expected completion evidence did not pass: {evidence_id}."
            )
    return {key: checks[key] for key in EXPECTED_EVIDENCE}


def _normalized_evidence_checks(
    value: object,
    *,
    label: str,
) -> dict[str, bool]:
    checks = _object(value, label)
    _reject_unknown(checks, set(EXPECTED_EVIDENCE), label=label)
    missing = set(EXPECTED_EVIDENCE) - set(checks)
    if missing:
        raise ValueError(f"{label} is missing fields: {sorted(missing)!r}.")
    normalized: dict[str, bool] = {}
    for key in EXPECTED_EVIDENCE:
        result = checks.get(key)
        if not isinstance(result, bool):
            raise ValueError(f"{label}.{key} must be boolean.")
        normalized[key] = result
    return normalized


def _completion_evaluation(
    preregistration: dict[str, Any],
    completion: dict[str, Any],
    *,
    evidence_checks: dict[str, bool],
) -> dict[str, Any]:
    outcome = str(completion.get("outcome") or "")
    score = str(completion.get("model_score") or "")
    editor_use = str(completion.get("external_editor_use") or "")
    fallback_events = [
        _object(value, "completion fallback event")
        for value in _list(
            completion.get("fallback_events"),
            "completion fallback_events",
        )
    ]
    fallback_classes = {
        _closed_text(value.get("class"), "fallback class", FALLBACK_CLASSES)
        for value in fallback_events
    }
    expected = [
        _closed_text(value, "expected evidence", EXPECTED_EVIDENCE)
        for value in _list(
            preregistration.get("expected_evidence"),
            "preregistration expected_evidence",
        )
    ]
    all_expected_passed = all(evidence_checks.get(value) is True for value in expected)
    qualifying_m6 = bool(
        outcome == "pass"
        and preregistration.get("scope") == "m6_qualification"
        and preregistration.get("source_class")
        in {"owner_authorized_real", "public_authorized_real"}
        and all_expected_passed
        and not fallback_events
        and editor_use == "none"
    )
    m3_scored = bool(
        outcome == "pass"
        and preregistration.get("scope") == "m3_live_model_scored"
        and (
            score in {"correct", "incorrect"}
            or preregistration.get("canonical_task") == "cancellation_rollback"
        )
        and all_expected_passed
        and not fallback_events
        and editor_use == "none"
        and preregistration.get("entry_route") != "advanced_editor"
    )
    return {
        "formal_scope": preregistration.get("scope") in _FORMAL_SCOPES,
        "frozen_build_scope": (preregistration.get("scope") in _FROZEN_BUILD_SCOPES),
        "synthetic_source": (
            preregistration.get("source_class") == "synthetic_contract_fixture"
        ),
        "discovery_only": preregistration.get("scope") == "m6_discovery",
        "qualifying_m6": qualifying_m6,
        "m3_scored": m3_scored,
        "m3_first_proposal_correct": (
            score == "correct"
            if m3_scored
            and preregistration.get("canonical_task") != "cancellation_rollback"
            else None
        ),
        "all_expected_evidence_passed": all_expected_passed,
        "fallback_classes": sorted(fallback_classes),
        "advanced_editor_used": editor_use != "none",
        "counting_rule": (
            "One completed preregistered session counts at most once. Synthetic "
            "probes (including formal_contract_probe), discovery sessions, failed "
            "attempts, copied artifacts, fallback sessions, and agent-only "
            "attestations never qualify for the final M6 fifteen."
        ),
    }


def complete_session(
    ledger_path: Path,
    session_id: str,
    *,
    owner: str,
    outcome: str,
    active_seconds: float,
    manifest_path: Path | None = None,
    fallback_values: list[str] | None = None,
    external_editor_use: str = "none",
    failures: list[str] | None = None,
    model_score: str = "not_applicable",
) -> dict[str, Any]:
    ledger = ledger_path.expanduser().resolve()
    events = _read_verified_events(ledger)
    session_history = _session_events(events, session_id)
    preregistration = _event_payload(session_history, "preregistered")
    if preregistration is None:
        raise ValueError("Session has no preregistration.")
    if _event_payload(session_history, "completed") is not None:
        raise ValueError("Session was already completed.")
    operator = _required_text(owner, "owner", maximum=160)
    if operator != preregistration.get("owner"):
        raise ValueError("Completion owner differs from preregistration.")
    resolved_outcome = _closed_text(outcome, "outcome", SESSION_OUTCOMES)
    seconds = _required_number(
        active_seconds,
        "active_seconds",
        minimum=0.0,
    )
    failure_records = [
        _required_text(value, "failure", maximum=1000) for value in (failures or [])
    ]
    fallback_events = _parse_fallback_events(fallback_values or [])
    editor_use = _closed_text(
        external_editor_use,
        "external_editor_use",
        EXTERNAL_EDITOR_USES,
    )
    score = _closed_text(model_score, "model_score", MODEL_SCORES)
    if editor_use == "unrecorded":
        raise ValueError(
            "Unrecorded external-editor use cannot complete an evidence session."
        )
    if editor_use == "recorded_p2" and not any(
        value["class"] == "p2_low_frequency" for value in fallback_events
    ):
        raise ValueError(
            "recorded_p2 external-editor use requires a p2_low_frequency fallback."
        )
    if resolved_outcome == "pass" and any(
        value["class"] in {"p0_integrity", "p1_ordinary"} for value in fallback_events
    ):
        raise ValueError(
            "P0 integrity or P1 ordinary-task fallback cannot be marked pass."
        )
    if resolved_outcome == "pass" and failure_records:
        raise ValueError("A passed session cannot contain terminal failure records.")
    if (
        resolved_outcome == "pass"
        and preregistration.get("entry_route") == "advanced_editor"
        and editor_use != "recorded_p2"
    ):
        raise ValueError(
            "A passed Advanced Editor session must record its P2 editor use."
        )
    witness = _event_payload(session_history, "reopen_witnessed")
    authority: dict[str, Any] | None = None
    manifest: dict[str, Any] | None = None
    checks = {key: False for key in EXPECTED_EVIDENCE}
    if resolved_outcome == "pass":
        if witness is None:
            raise ValueError("Pass completion requires a reopen witness.")
        if seconds <= 0.0:
            raise ValueError("Pass completion requires positive active_seconds.")
        _verify_source_fingerprints(
            [
                _object(value, "preregistered source")
                for value in preregistration["sources"]
            ]
        )
        _verify_build_identity(
            _object(preregistration.get("build"), "preregistered build")
        )
        mode = _closed_text(
            witness.get("authority_mode"),
            "witness authority_mode",
            ("canvas", "composition"),
        )
        if mode == "canvas":
            _verify_canvas_witness_current(witness)
        else:
            _verify_composition_witness_current(witness)
        if manifest_path is None:
            raise ValueError("Pass completion requires a ready manifest.")
        require_within(
            _preregistered_project_root(preregistration),
            manifest_path,
            label="Completion manifest",
        )
        witness_authority = _object(
            witness.get("authority"),
            "witness authority",
        )
        if mode == "canvas":
            manifest = _verify_regular_manifest(
                manifest_path,
                preregistration=preregistration,
                witness=witness,
            )
        else:
            manifest = _verify_composition_manifest(
                manifest_path,
                preregistration=preregistration,
                authority=witness_authority,
            )
            delivery_witness = _object(
                witness_authority.get("delivery_witness"),
                "composition delivery witness",
            )
            if (
                manifest.get("path") != delivery_witness.get("path")
                or manifest.get("sha256") != delivery_witness.get("sha256")
                or manifest.get("document_sha256")
                != delivery_witness.get("document_sha256")
                or manifest.get("recomputed_qa", {}).get("report_sha256")
                != delivery_witness.get("recomputed_qa", {}).get("report_sha256")
                or manifest.get("native_audit_sha256")
                != delivery_witness.get("native_audit_sha256")
            ):
                raise ValueError(
                    "Composition completion does not match the final export and "
                    "QA witnessed after close/reopen."
                )
        authority_revision = witness_authority.get("revision")
        if authority_revision is None:
            authority_revision = witness_authority.get("variant_revision")
        authority = {
            "authority_mode": mode,
            "document": witness_authority["document"],
            "document_sha256": witness_authority["document_sha256"],
            "revision": authority_revision,
            "reopen_witness_event_sha256": next(
                event["event_sha256"]
                for event in session_history
                if event.get("event_type") == "reopen_witnessed"
            ),
        }
        checks = _completion_evidence_checks(preregistration, witness)
    elif not failure_records:
        raise ValueError(
            "needs_fix or abandoned completion requires a recorded failure."
        )
    if preregistration.get("scope") == "m3_live_model_scored":
        cancellation_task = (
            preregistration.get("canonical_task") == "cancellation_rollback"
        )
        if cancellation_task and score != "not_applicable":
            raise ValueError(
                "M3 cancellation/rollback attempts use model_score=not_applicable."
            )
        if (
            not cancellation_task
            and resolved_outcome == "pass"
            and score not in {"correct", "incorrect"}
        ):
            raise ValueError(
                "A passed M3 model-planning attempt requires correct or "
                "incorrect model_score."
            )
    elif score != "not_applicable":
        raise ValueError("model_score is reserved for M3 scored sessions.")
    payload = {
        "owner": operator,
        "outcome": resolved_outcome,
        "active_seconds": seconds,
        "failures": failure_records,
        "fallback_events": fallback_events,
        "external_editor_use": editor_use,
        "model_score": score,
        "authority": authority,
        "manifest": manifest,
        "evidence_checks": checks,
        "evaluation": {},
        "limitations": [
            "Completion proves the closed local evidence contract and exact bound artifacts, not scientific truth outside the declared task.",
            "Local owner identity and the GUI reopen remain attestations, not signed remote identity proofs.",
            "A qualifying flag is a ledger classification; M3/M6 thresholds are satisfied only by the aggregate status report.",
        ],
    }
    payload["evaluation"] = _completion_evaluation(
        preregistration,
        payload,
        evidence_checks=checks,
    )
    evaluation = _object(payload["evaluation"], "completion evaluation")
    qualifying_m6 = bool(evaluation["qualifying_m6"])
    m3_scored = bool(evaluation["m3_scored"])
    _validate_completion(payload)
    event = _append_event(
        ledger,
        session_id=session_id,
        event_type="completed",
        payload=payload,
    )
    return {
        "kind": "sciplot_session_completion",
        "version": 1,
        "status": "completed",
        "session_id": session_id,
        "outcome": resolved_outcome,
        "qualifying_m6": qualifying_m6,
        "m3_scored": m3_scored,
        "ledger": str(ledger),
        "event": event,
    }


def _candidate_identity(preregistration: dict[str, Any]) -> str:
    build = _object(preregistration.get("build"), "preregistration build")
    git = _object(build.get("git"), "preregistration build.git")
    artifact = _object(
        build.get("artifact"),
        "preregistration build.artifact",
    )
    registry = _object(
        build.get("validated_envelope_registry"),
        "preregistration registry",
    )
    runtime = _object(build.get("runtime"), "preregistration runtime")
    return canonical_sha256(
        {
            "git_commit": git.get("commit"),
            "artifact_sha256": artifact.get("sha256"),
            "registry_sha256": registry.get("sha256"),
            "runtime_identity_sha256": runtime.get("identity_sha256"),
        }
    )


def _m3_round_summary(
    round_id: str,
    attempts: list[dict[str, Any]],
) -> dict[str, Any]:
    by_task = {
        task: sorted(
            [attempt for attempt in attempts if attempt["canonical_task"] == task],
            key=lambda value: int(value["attempt"]),
        )
        for task in CANONICAL_MODEL_TASKS
    }
    registered = len(attempts)
    lifecycle_passed = sum(bool(attempt["lifecycle_passed"]) for attempt in attempts)
    planning_tasks = tuple(
        task for task in CANONICAL_MODEL_TASKS if task != "cancellation_rollback"
    )
    planning_lifecycle_passed = sum(
        bool(attempt["lifecycle_passed"])
        for task in planning_tasks
        for attempt in by_task[task]
    )
    first_correct = sum(
        attempt["score"] == "correct"
        for task in planning_tasks
        for attempt in by_task[task]
        if attempt["lifecycle_passed"]
    )
    cancellation_gate = bool(
        len(by_task["cancellation_rollback"]) == 2
        and all(
            attempt["lifecycle_passed"] for attempt in by_task["cancellation_rollback"]
        )
    )
    exactly_two_each = all(
        len(task_attempts) == 2
        and {attempt["attempt"] for attempt in task_attempts} == {1, 2}
        for task_attempts in by_task.values()
    )
    each_planning_task_success = all(
        any(
            attempt["lifecycle_passed"] and attempt["score"] == "correct"
            for attempt in by_task[task]
        )
        for task in planning_tasks
    )
    candidate_identities = sorted(
        {str(attempt["candidate_identity"]) for attempt in attempts}
    )
    provider_models = sorted(
        {f"{attempt['provider']}::{attempt['model']}" for attempt in attempts}
    )
    coherent_round = bool(len(candidate_identities) == 1 and len(provider_models) == 1)
    fallback_free = bool(
        attempts and all(attempt.get("fallback_free") is True for attempt in attempts)
    )
    advanced_editor_free = bool(
        attempts
        and all(attempt.get("advanced_editor_free") is True for attempt in attempts)
    )
    gate = bool(
        coherent_round
        and fallback_free
        and advanced_editor_free
        and exactly_two_each
        and registered == 12
        and lifecycle_passed == 12
        and planning_lifecycle_passed == 10
        and cancellation_gate
        and first_correct >= 9
        and each_planning_task_success
    )
    return {
        "round_id": round_id,
        "attempts": by_task,
        "registered_attempt_count": registered,
        "lifecycle_passed_count": lifecycle_passed,
        "planning_attempt_lifecycle_passed_count": planning_lifecycle_passed,
        "first_proposal_correct_count": first_correct,
        "exactly_two_attempts_per_task": exactly_two_each,
        "each_planning_task_succeeds_at_least_once": (each_planning_task_success),
        "safe_authority_gate_12_of_12": lifecycle_passed == 12,
        "first_proposal_gate_9_of_10": first_correct >= 9,
        "cancellation_rollback_gate_2_of_2": cancellation_gate,
        "candidate_identities": candidate_identities,
        "provider_models": provider_models,
        "coherent_round_identity": coherent_round,
        "fallback_free": fallback_free,
        "advanced_editor_free": advanced_editor_free,
        "gate_passed": gate,
    }


def _m6_round_summary(
    round_id: str,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    qualifying_rows = [row for row in rows if row["qualifying_m6"]]
    registered_count = len(rows)
    completed_count = sum(bool(row.get("completed")) for row in rows)
    lane_counts = {lane: 0 for lane in ACCEPTANCE_LANES}
    evidence_by_lane = {
        lane: {evidence_id: 0 for evidence_id in EXPECTED_EVIDENCE}
        for lane in ACCEPTANCE_LANES
    }
    coverage = {evidence_id: 0 for evidence_id in EXPECTED_EVIDENCE}
    for row in qualifying_rows:
        lane = str(row["lane"])
        lane_counts[lane] += 1
        expected_evidence = {str(value) for value in row.get("expected_evidence", [])}
        for evidence_id, passed in row["evidence_checks"].items():
            if (
                evidence_id in coverage
                and evidence_id in expected_evidence
                and passed is True
            ):
                coverage[evidence_id] += 1
                evidence_by_lane[lane][evidence_id] += 1
    lane_gate = all(count == 3 for count in lane_counts.values())
    provider_disabled_lane_gate = all(
        evidence_by_lane[lane]["provider_disabled"] >= 1 for lane in ACCEPTANCE_LANES
    )
    ai_lanes = [
        lane for lane in ACCEPTANCE_LANES if evidence_by_lane[lane]["ai_operation"] >= 1
    ]
    candidate_identities = sorted(
        {str(row["candidate_identity"]) for row in qualifying_rows}
    )
    one_frozen_candidate = len(candidate_identities) == 1
    orthogonal_gate = bool(
        provider_disabled_lane_gate
        and coverage["ai_operation"] >= 3
        and len(ai_lanes) >= 3
        and coverage["data_mapping"] >= 1
        and coverage["review_sidecar"] >= 1
        and coverage["review_promotion"] >= 1
        and coverage["composition_lifecycle"] >= 1
    )
    gate = bool(
        registered_count == 15
        and completed_count == 15
        and len(qualifying_rows) == 15
        and lane_gate
        and orthogonal_gate
        and one_frozen_candidate
    )
    return {
        "round_id": round_id,
        "registered_count": registered_count,
        "completed_count": completed_count,
        "qualifying_count": len(qualifying_rows),
        "required_count": 15,
        "qualifying_lane_counts": lane_counts,
        "exactly_three_per_lane": lane_gate,
        "fixed_cohort_15": (
            registered_count == completed_count == len(qualifying_rows) == 15
        ),
        "orthogonal_coverage": coverage,
        "orthogonal_coverage_by_lane": evidence_by_lane,
        "provider_disabled_in_every_lane": provider_disabled_lane_gate,
        "ai_operation_lanes": ai_lanes,
        "orthogonal_gate_passed": orthogonal_gate,
        "candidate_identity_count": len(candidate_identities),
        "candidate_identities": candidate_identities,
        "one_frozen_candidate": one_frozen_candidate,
        "gate_passed": gate,
    }


def _select_m6_round(
    rounds: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], list[str]]:
    passing_round_ids = sorted(
        round_id
        for round_id, summary in rounds.items()
        if summary.get("gate_passed") is True
    )
    default = {
        "round_id": None,
        "registered_count": 0,
        "completed_count": 0,
        "qualifying_count": 0,
        "required_count": 15,
        "qualifying_lane_counts": {lane: 0 for lane in ACCEPTANCE_LANES},
        "exactly_three_per_lane": False,
        "fixed_cohort_15": False,
        "orthogonal_coverage": {evidence_id: 0 for evidence_id in EXPECTED_EVIDENCE},
        "orthogonal_coverage_by_lane": {
            lane: {evidence_id: 0 for evidence_id in EXPECTED_EVIDENCE}
            for lane in ACCEPTANCE_LANES
        },
        "provider_disabled_in_every_lane": False,
        "ai_operation_lanes": [],
        "orthogonal_gate_passed": False,
        "candidate_identity_count": 0,
        "candidate_identities": [],
        "one_frozen_candidate": False,
        "gate_passed": False,
    }
    if passing_round_ids:
        return rounds[passing_round_ids[-1]], passing_round_ids
    return (
        max(
            rounds.values(),
            key=lambda value: int(value["qualifying_count"]),
            default=default,
        ),
        passing_round_ids,
    )


def _status_from_events(
    ledger_path: Path,
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    sessions: dict[str, dict[str, Any]] = {}
    for event in events:
        identifier = str(event["session_id"])
        record = sessions.setdefault(
            identifier,
            {
                "session_id": identifier,
                "preregistration": None,
                "witness": None,
                "completion": None,
            },
        )
        event_type = str(event["event_type"])
        if event_type == "preregistered":
            record["preregistration"] = event["payload"]
        elif event_type == "reopen_witnessed":
            record["witness"] = event["payload"]
        else:
            record["completion"] = event["payload"]
    session_rows: list[dict[str, Any]] = []
    lane_counts = {lane: 0 for lane in ACCEPTANCE_LANES}
    scope_counts = {scope: 0 for scope in SESSION_SCOPES}
    m3_by_round: dict[str, list[dict[str, Any]]] = {}
    m6_by_round: dict[str, list[dict[str, Any]]] = {}
    historical_qualifying_m6_count = 0
    for identifier, record in sessions.items():
        prereg = _object(record["preregistration"], "preregistration")
        completion = (
            _object(record["completion"], "completion")
            if isinstance(record["completion"], dict)
            else None
        )
        lane = str(prereg["lane"])
        scope = str(prereg["scope"])
        round_id = prereg.get("round_id")
        candidate_identity = _candidate_identity(prereg)
        lane_counts[lane] += 1
        scope_counts[scope] += 1
        witness = (
            _object(record["witness"], "witness")
            if isinstance(record["witness"], dict)
            else None
        )
        if completion is not None and completion.get("outcome") == "pass":
            if witness is None:
                raise ValueError(
                    f"Completed session {identifier} has no reopen witness."
                )
            evidence_checks = _completion_evidence_checks(prereg, witness)
        else:
            evidence_checks = {evidence_id: False for evidence_id in EXPECTED_EVIDENCE}
        evaluation = (
            _completion_evaluation(
                prereg,
                completion,
                evidence_checks=evidence_checks,
            )
            if completion is not None
            else None
        )
        qualifying = bool(
            evaluation is not None and evaluation["qualifying_m6"] is True
        )
        if qualifying:
            historical_qualifying_m6_count += 1
        if scope == "m3_live_model_scored":
            formal_round = _required_text(
                round_id,
                "M3 round_id",
                maximum=100,
            )
            m3_by_round.setdefault(formal_round, []).append(
                {
                    "session_id": identifier,
                    "canonical_task": prereg["canonical_task"],
                    "attempt": prereg["attempt"],
                    "provider": prereg["provider"],
                    "model": prereg["model"],
                    "candidate_identity": candidate_identity,
                    "completed": completion is not None,
                    "outcome": (completion.get("outcome") if completion else None),
                    "score": (completion.get("model_score") if completion else None),
                    "lifecycle_passed": bool(
                        completion
                        and completion.get("outcome") == "pass"
                        and evaluation is not None
                        and evaluation["m3_scored"] is True
                    ),
                    "fallback_free": bool(
                        completion is not None and not completion.get("fallback_events")
                    ),
                    "advanced_editor_free": bool(
                        completion is not None
                        and completion.get("external_editor_use") == "none"
                        and prereg.get("entry_route") != "advanced_editor"
                    ),
                }
            )
        if scope == "m6_qualification":
            formal_round = _required_text(
                round_id,
                "M6 round_id",
                maximum=100,
            )
            m6_by_round.setdefault(formal_round, []).append(
                {
                    "session_id": identifier,
                    "lane": lane,
                    "candidate_identity": candidate_identity,
                    "completed": completion is not None,
                    "qualifying_m6": qualifying,
                    "evidence_checks": evidence_checks,
                    "expected_evidence": prereg["expected_evidence"],
                }
            )
        state = (
            "completed"
            if completion is not None
            else ("witnessed" if record["witness"] is not None else "preregistered")
        )
        session_rows.append(
            {
                "session_id": identifier,
                "state": state,
                "owner": prereg["owner"],
                "lane": lane,
                "scope": scope,
                "round_id": round_id,
                "candidate_identity": candidate_identity,
                "source_class": prereg["source_class"],
                "task": prereg["task"],
                "task_fingerprint": prereg["task_fingerprint"],
                "entry_route": prereg["entry_route"],
                "expected_evidence": prereg["expected_evidence"],
                "qualifying_m6": qualifying,
                "outcome": completion.get("outcome") if completion else None,
            }
        )
    m3_rounds = {
        round_id: _m3_round_summary(round_id, attempts)
        for round_id, attempts in sorted(m3_by_round.items())
    }
    m6_rounds = {
        round_id: _m6_round_summary(round_id, rows)
        for round_id, rows in sorted(m6_by_round.items())
    }
    m3_passing_round_ids = [
        round_id for round_id, summary in m3_rounds.items() if summary["gate_passed"]
    ]
    selected_m6, m6_passing_round_ids = _select_m6_round(m6_rounds)
    return {
        "kind": SESSION_EVIDENCE_STATUS_KIND,
        "version": SESSION_EVIDENCE_STATUS_VERSION,
        "status": "passed",
        "integrity": {
            "hash_chain_valid": True,
            "head_checkpoint_valid": True,
            "event_count": len(events),
            "last_event_sha256": (
                events[-1]["event_sha256"] if events else GENESIS_SHA256
            ),
            "ledger_sha256": (
                file_sha256(ledger_path)
                if ledger_path.expanduser().resolve().is_file()
                else None
            ),
        },
        "ledger": str(ledger_path.expanduser().resolve()),
        "head": (str(_head_path(ledger_path)) if events else None),
        "summary": {
            "session_count": len(sessions),
            "preregistered_count": len(sessions),
            "witnessed_count": sum(
                record["witness"] is not None for record in sessions.values()
            ),
            "completed_count": sum(
                record["completion"] is not None for record in sessions.values()
            ),
            "qualifying_m6_count": selected_m6["qualifying_count"],
            "historical_qualifying_m6_count": (historical_qualifying_m6_count),
        },
        "lane_counts": lane_counts,
        "scope_counts": scope_counts,
        "m3": {
            "rounds": m3_rounds,
            "passing_round_ids": m3_passing_round_ids,
            "gate_passed": bool(m3_passing_round_ids),
            "rounds_are_not_combined": True,
        },
        "m6": {
            **selected_m6,
            "rounds": m6_rounds,
            "passing_round_ids": m6_passing_round_ids,
            "gate_passed": bool(selected_m6["gate_passed"]),
            "selected_round_id": selected_m6["round_id"],
            "selected_round_is_passing": bool(selected_m6["gate_passed"]),
            "rounds_are_not_combined": True,
        },
        "sessions": sorted(
            session_rows,
            key=lambda value: value["session_id"],
        ),
        "limitations": [
            "The local chain and companion head detect accidental edits, middle-event deletion, reordering, replacement, and ordinary truncation, but an attacker with write access can rewrite both.",
            "Owner identity and GUI reopen are explicit attestations, not signed remote identity proofs.",
            "status=passed means ledger integrity passed; M3 and M6 completion are reported only by their separate gate_passed fields.",
        ],
    }


def session_ledger_status(ledger_path: Path) -> dict[str, Any]:
    ledger = ledger_path.expanduser().resolve()
    if not ledger.is_file():
        return {
            "kind": SESSION_EVIDENCE_STATUS_KIND,
            "version": SESSION_EVIDENCE_STATUS_VERSION,
            "status": "failed",
            "ledger": str(ledger),
            "head": str(_head_path(ledger)),
            "integrity": {
                "hash_chain_valid": False,
                "head_checkpoint_valid": False,
                "error": (f"FileNotFoundError: evidence ledger not found: {ledger}"),
            },
            "summary": {
                "session_count": 0,
                "qualifying_m6_count": 0,
                "historical_qualifying_m6_count": 0,
            },
            "m3": {"gate_passed": False, "rounds": {}},
            "m6": {"gate_passed": False, "rounds": {}},
            "sessions": [],
            "limitations": [
                "No evidence claim can be made without an existing ledger."
            ],
        }
    try:
        events = _read_verified_events(ledger)
        return _status_from_events(ledger, events)
    except Exception as exc:
        return {
            "kind": SESSION_EVIDENCE_STATUS_KIND,
            "version": SESSION_EVIDENCE_STATUS_VERSION,
            "status": "failed",
            "ledger": str(ledger),
            "head": str(_head_path(ledger)),
            "integrity": {
                "hash_chain_valid": False,
                "head_checkpoint_valid": False,
                "error": f"{type(exc).__name__}: {exc}",
            },
            "summary": {
                "session_count": 0,
                "qualifying_m6_count": 0,
            },
            "m3": {"gate_passed": False},
            "m6": {"gate_passed": False},
            "sessions": [],
            "limitations": [
                "No session counts are trusted while ledger integrity fails."
            ],
        }


def session_evidence_schema() -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "SciPlot preregistered session evidence contract",
        "kind": "sciplot_session_evidence_schema",
        "version": 1,
        "status": "ready",
        "additionalProperties": False,
        "closed_enums": {
            "acceptance_lanes": list(ACCEPTANCE_LANES),
            "session_scopes": list(SESSION_SCOPES),
            "source_classes": list(SOURCE_CLASSES),
            "entry_routes": list(ENTRY_ROUTES),
            "expected_evidence": list(EXPECTED_EVIDENCE),
            "canonical_model_tasks": list(CANONICAL_MODEL_TASKS),
            "session_outcomes": list(SESSION_OUTCOMES),
            "model_scores": list(MODEL_SCORES),
            "external_editor_uses": list(EXTERNAL_EDITOR_USES),
            "fallback_classes": list(FALLBACK_CLASSES),
        },
        "event_contract": {
            "kind": SESSION_EVIDENCE_EVENT_KIND,
            "version": SESSION_EVIDENCE_EVENT_VERSION,
            "event_types": list(_EVENT_TYPES),
            "event_fields": sorted(_EVENT_KEYS),
            "preregistration_fields": sorted(_PREREGISTRATION_KEYS),
            "witness_fields": sorted(_WITNESS_KEYS),
            "completion_fields": sorted(_COMPLETION_KEYS),
        },
        "aggregate_gates": {
            "m3": {
                "fixed_attempts": 12,
                "attempts_per_task": 2,
                "authority_safe": "12/12",
                "cancellation_rollback": "2/2",
                "first_proposal_correct": "at_least_9_of_10",
                "same_round_provider_model_candidate": True,
                "fallback_free": True,
                "advanced_editor_free": True,
            },
            "m6": {
                "fixed_cohort": 15,
                "exactly_per_lane": 3,
                "same_round_candidate": True,
                "provider_disabled": "at_least_one_per_lane",
                "ai_operation": "at_least_three_sessions_across_three_lanes",
                "data_mapping": "at_least_one",
                "review_sidecar_and_promotion": "at_least_one",
                "native_composition": "at_least_one",
            },
        },
        "trust_boundary": [
            "Status recomputes classifications from preregistration, witness, and raw completion fields.",
            "A pending append blocks all status claims until explicit recovery.",
            "formal_contract_probe requires the frozen clean-build contract but is synthetic and never counts toward M3 or M6.",
            "Local owner identity and reopen remain attestations, not signed remote identity.",
        ],
    }


__all__ = [
    "ACCEPTANCE_LANES",
    "CANONICAL_MODEL_TASKS",
    "ENTRY_ROUTES",
    "EXPECTED_EVIDENCE",
    "EXTERNAL_EDITOR_USES",
    "FALLBACK_CLASSES",
    "MODEL_SCORES",
    "SESSION_OUTCOMES",
    "SESSION_SCOPES",
    "SOURCE_CLASSES",
    "canonical_sha256",
    "complete_session",
    "default_session_ledger",
    "preregister_session",
    "recover_session_ledger",
    "session_evidence_schema",
    "session_ledger_status",
    "witness_session_reopen",
]
