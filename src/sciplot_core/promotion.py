from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import pwd
import re
import stat
import subprocess
import sys
import tarfile
import tempfile
import unicodedata
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from sciplot_core._utils import json_safe
from sciplot_core.canvas.model import CanvasSession
from sciplot_core.canvas.operations import CanvasOperationBatch
from sciplot_core.canvas.persistence import (
    atomic_write_json,
    load_canvas_session,
)
from sciplot_core.data_mapping import (
    DATA_MAPPING_EXECUTION_FILENAME,
    load_data_mapping_execution,
    load_data_mapping_proposal,
)
from sciplot_core.session_evidence import (
    canonical_sha256,
    verified_session_evidence_snapshot,
)
from sciplot_core.session_evidence_artifacts import (
    verify_regular_source_lineage,
)

PROMOTION_COLLECTION_KIND = "sciplot_promotion_collection"
PROMOTION_CANDIDATE_SET_KIND = "sciplot_promotion_candidate_set"
PROMOTION_DECISION_RECEIPT_KIND = "sciplot_promotion_owner_decision_receipt"
PROMOTION_DECISION_KIND = "sciplot_promotion_owner_decision"
PROMOTION_PLAN_KIND = "sciplot_promotion_implementation_plan"
PROMOTION_VERIFICATION_RECEIPT_KIND = (
    "sciplot_promotion_verification_receipt"
)
PROMOTION_VERIFICATION_KIND = "sciplot_promotion_verification"
PROMOTION_TRUST_REGISTRY_KIND = "sciplot_promotion_owner_trust_registry"
PROMOTION_PROBE_CONTEXT_KIND = "sciplot_promotion_probe_execution_context"
PROMOTION_ARTIFACT_VERSION = 1
PROMOTION_THRESHOLD = 3
PROMOTION_SIGNATURE_ALGORITHM = "rsa-pkcs1v15-sha256"


def _account_home() -> Path:
    return Path(pwd.getpwuid(os.getuid()).pw_dir).resolve()


DEFAULT_PROMOTION_TRUST_REGISTRY = (
    _account_home()
    / (
        "Library/Application Support/sciplot/trusted_promotion_owners.json"
        if sys.platform == "darwin"
        else ".config/sciplot/trusted_promotion_owners.json"
    )
)

REAL_SOURCE_CLASSES = frozenset(
    {"owner_authorized_real", "public_authorized_real"}
)
REAL_SESSION_SCOPES = frozenset(
    {"m3_live_model_scored", "m6_discovery", "m6_qualification"}
)
OWNER_DECISIONS = frozenset({"approve", "reject", "defer"})
OWNER_DECISION_ATTESTATION = (
    "I reviewed this powerless promotion candidate and made this decision."
)
VERIFICATION_ATTESTATION = (
    "I reviewed the source change, probe evidence, and real lifecycle evidence."
)

_HASH = re.compile(r"^[0-9a-f]{64}$")
_GIT_COMMIT = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_DATA_BEARING_SETTING = re.compile(
    r"(?:^|/)(?:xdata|ydata|zdata|dataset|data|values?)(?:$|/)",
    re.IGNORECASE,
)
_FREE_TEXT_SETTING = re.compile(
    r"(?:^|/)(?:label|title|text|description)(?:$|/)",
    re.IGNORECASE,
)
_RANGE_SETTING = re.compile(
    r"(?:^|/)(?:min|max|lower|upper|range)(?:$|/)",
    re.IGNORECASE,
)
_PROBE_FILE = re.compile(
    r"^src/(?:[^/]+/)*[^/]*_promotion_probe\.py$"
)
_SHA256_DIGEST_INFO_PREFIX = bytes.fromhex(
    "3031300d060960864801650304020105000420"
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _required_text(
    value: object,
    label: str,
    *,
    maximum: int = 4000,
) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string.")
    text = value.strip()
    if not text:
        raise ValueError(f"{label} must be non-empty.")
    if len(text) > maximum:
        raise ValueError(f"{label} is longer than {maximum} characters.")
    return text


def _required_hash(value: object, label: str) -> str:
    text = _required_text(value, label, maximum=64).casefold()
    if _HASH.fullmatch(text) is None:
        raise ValueError(f"{label} must be a lowercase SHA-256 digest.")
    return text


def _required_bool(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"{label} must be a boolean.")
    return value


def _required_list(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be an array.")
    return value


def _required_object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object.")
    return value


def _reject_unknown(
    payload: dict[str, Any],
    allowed: set[str],
    *,
    label: str,
) -> None:
    unknown = set(payload) - allowed
    if unknown:
        raise ValueError(f"{label} has unsupported fields: {sorted(unknown)!r}")


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _read_file_snapshot(path: Path, label: str) -> tuple[Path, bytes, str]:
    target = path.expanduser().resolve()
    if not target.is_file():
        raise FileNotFoundError(f"{label} not found: {target}")
    with target.open("rb") as handle:
        before = os.fstat(handle.fileno())
        data = handle.read()
        after = os.fstat(handle.fileno())
    if (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    ) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    ) or len(data) != after.st_size:
        raise ValueError(f"{label} changed during one snapshot read: {target}")
    return target, data, hashlib.sha256(data).hexdigest()


def _read_json_snapshot(
    path: Path,
    label: str,
) -> tuple[dict[str, Any], str]:
    target, data, digest = _read_file_snapshot(path, label)
    try:
        payload = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not valid JSON: {target}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must contain one JSON object.")
    return payload, digest


def _read_json(path: Path, label: str) -> dict[str, Any]:
    payload, _digest = _read_json_snapshot(path, label)
    return payload


def _stable_load(
    path: Path,
    label: str,
    loader: Any,
) -> tuple[Any, str]:
    target, data, digest = _read_file_snapshot(path, label)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=target.parent,
            prefix=f".{target.name}.promotion-snapshot.",
            suffix=target.suffix,
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        temporary_path.chmod(0o400)
        loaded = loader(temporary_path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.chmod(0o600)
            temporary_path.unlink()
    return loaded, digest


def _tree_snapshot(
    root: Path,
    label: str,
) -> dict[str, dict[str, Any]]:
    resolved = root.expanduser().resolve()
    if not resolved.is_dir():
        raise FileNotFoundError(f"{label} not found: {resolved}")
    snapshot: dict[str, dict[str, Any]] = {}
    paths = [resolved, *sorted(resolved.rglob("*"))]
    for path in paths:
        relative = "." if path == resolved else path.relative_to(resolved).as_posix()
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            raise ValueError(f"{label} cannot contain symlinks: {relative}")
        if stat.S_ISDIR(metadata.st_mode):
            snapshot[relative] = {
                "kind": "directory",
                "device": metadata.st_dev,
                "inode": metadata.st_ino,
                "mode": stat.S_IMODE(metadata.st_mode),
                "mtime_ns": metadata.st_mtime_ns,
                "ctime_ns": metadata.st_ctime_ns,
            }
            continue
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError(
                f"{label} can contain only directories and regular files: {relative}"
            )
        relative = path.relative_to(resolved).as_posix()
        target, _data, digest = _read_file_snapshot(
            path,
            f"{label} file {relative}",
        )
        verified = target.stat()
        snapshot[relative] = {
            "kind": "file",
            "device": verified.st_dev,
            "inode": verified.st_ino,
            "mode": stat.S_IMODE(verified.st_mode),
            "size": verified.st_size,
            "mtime_ns": verified.st_mtime_ns,
            "ctime_ns": verified.st_ctime_ns,
            "sha256": digest,
        }
    return snapshot


def _owner_attestation_sha256(owner: object) -> str:
    return hashlib.sha256(
        _required_text(owner, "owner", maximum=200).encode("utf-8")
    ).hexdigest()


def _safe_repo_path(value: object, label: str) -> str:
    text = _required_text(value, label, maximum=500)
    path = Path(text)
    if (
        "\\" in text
        or path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
        or text.startswith("/")
        or path.as_posix() != text
    ):
        raise ValueError(f"{label} must be a safe repository-relative path.")
    return path.as_posix()


def _sorted_unique_text(
    value: object,
    label: str,
    *,
    maximum: int = 500,
) -> list[str]:
    values = [
        _required_text(item, f"{label} item", maximum=maximum)
        for item in _required_list(value, label)
    ]
    if not values or values != sorted(set(values)):
        raise ValueError(f"{label} must be a non-empty sorted unique array.")
    return values


def _validate_implementation_contract(value: object) -> dict[str, Any]:
    contract = _required_object(value, "implementation_contract")
    _reject_unknown(
        contract,
        {
            "candidate_id",
            "source_files",
            "probe_files",
            "probe_kinds",
            "lifecycle_lanes",
            "lifecycle_assertions",
        },
        label="implementation_contract",
    )
    candidate_id = _required_hash(
        contract.get("candidate_id"),
        "implementation_contract.candidate_id",
    )
    source_files = [
        _safe_repo_path(item, "implementation source file")
        for item in _required_list(
            contract.get("source_files"),
            "implementation_contract.source_files",
        )
    ]
    probe_files = [
        _safe_repo_path(item, "implementation probe file")
        for item in _required_list(
            contract.get("probe_files"),
            "implementation_contract.probe_files",
        )
    ]
    for label, values in (
        ("implementation_contract.source_files", source_files),
        ("implementation_contract.probe_files", probe_files),
    ):
        if not values or values != sorted(set(values)):
            raise ValueError(f"{label} must be non-empty, sorted, and unique.")
    if any(not path.startswith("src/") for path in source_files):
        raise ValueError("Implementation source files must stay below src/.")
    if any(_PROBE_FILE.search(path) is None for path in probe_files):
        raise ValueError(
            "Every implementation probe must be a tracked "
            "src/**/*_promotion_probe.py file."
        )
    if set(source_files) & set(probe_files):
        raise ValueError("Source and probe file scopes must be disjoint.")
    probe_kinds = _sorted_unique_text(
        contract.get("probe_kinds"),
        "implementation_contract.probe_kinds",
        maximum=160,
    )
    lifecycle_lanes = _sorted_unique_text(
        contract.get("lifecycle_lanes"),
        "implementation_contract.lifecycle_lanes",
        maximum=160,
    )
    lifecycle_assertions: list[dict[str, Any]] = []
    for index, raw in enumerate(
        _required_list(
            contract.get("lifecycle_assertions"),
            "implementation_contract.lifecycle_assertions",
        )
    ):
        assertion = _required_object(
            raw,
            f"implementation_contract.lifecycle_assertions[{index}]",
        )
        _reject_unknown(
            assertion,
            {
                "assertion_id",
                "candidate_id",
                "lane",
                "kind",
                "path",
                "operation_index",
                "setting_paths",
            },
            label=f"implementation_contract.lifecycle_assertions[{index}]",
        )
        assertion_candidate_id = _required_hash(
            assertion.get("candidate_id"),
            "lifecycle assertion candidate_id",
        )
        if assertion_candidate_id != candidate_id:
            raise ValueError(
                "Lifecycle assertion is bound to another candidate."
            )
        lane = _required_text(
            assertion.get("lane"),
            "lifecycle assertion lane",
            maximum=160,
        )
        if lane not in lifecycle_lanes:
            raise ValueError(
                "Lifecycle assertion lane is outside lifecycle_lanes."
            )
        kind = _required_text(
            assertion.get("kind"),
            "lifecycle assertion kind",
            maximum=100,
        )
        identity: dict[str, Any] = {
            "candidate_id": candidate_id,
            "lane": lane,
            "kind": kind,
        }
        if kind == "candidate_effect_manifest_equals":
            path_value: Any = [
                _required_text(
                    item,
                    "candidate-effect manifest field",
                    maximum=160,
                )
                for item in _required_list(
                    assertion.get("path"),
                    "candidate-effect manifest field path",
                )
            ]
            if not path_value or len(path_value) > 12:
                raise ValueError(
                    "Candidate-effect manifest field path must contain 1-12 keys."
                )
            if assertion.get("operation_index") is not None or (
                assertion.get("setting_paths") is not None
            ):
                raise ValueError(
                    "Candidate-effect manifest assertions cannot name an operation."
                )
            identity["path"] = path_value
        elif kind == "veusz_setting_matches_operation":
            path_value: Any = _required_text(
                assertion.get("path"),
                "Veusz candidate-effect setting path",
                maximum=500,
            )
            if (
                not path_value.startswith("/")
                or ".." in path_value.split("/")
                or _DATA_BEARING_SETTING.search(path_value)
            ):
                raise ValueError(
                    "Veusz candidate-effect setting assertions require an "
                    "absolute non-data-bearing setting path."
                )
            operation_index = assertion.get("operation_index")
            if (
                type(operation_index) is not int
                or operation_index < 0
                or operation_index > 100
            ):
                raise ValueError(
                    "Veusz setting assertions require a bounded operation_index."
                )
            if assertion.get("setting_paths") is not None:
                raise ValueError(
                    "Veusz setting assertions cannot declare widget settings."
                )
            identity.update(
                {
                    "path": path_value,
                    "operation_index": operation_index,
                }
            )
        elif kind == "veusz_widget_matches_operation":
            path_value = _required_text(
                assertion.get("path"),
                "Veusz candidate-effect widget path",
                maximum=500,
            )
            if not path_value.startswith("/") or ".." in path_value.split("/"):
                raise ValueError(
                    "Veusz widget assertions require an absolute widget path."
                )
            operation_index = assertion.get("operation_index")
            if (
                type(operation_index) is not int
                or operation_index < 0
                or operation_index > 100
            ):
                raise ValueError(
                    "Veusz widget assertions require a bounded operation_index."
                )
            raw_setting_paths = _required_object(
                assertion.get("setting_paths"),
                "Veusz widget assertion setting_paths",
            )
            if len(raw_setting_paths) > 50:
                raise ValueError(
                    "Veusz widget assertion has too many setting paths."
                )
            setting_paths: dict[str, str] = {}
            for raw_key, raw_path in sorted(raw_setting_paths.items()):
                key = _normalize_identifier(raw_key)
                if raw_key != key or key in setting_paths:
                    raise ValueError(
                        "Veusz widget assertion setting keys must be canonical."
                    )
                setting_path = _required_text(
                    raw_path,
                    "Veusz widget setting path",
                    maximum=500,
                )
                if (
                    not setting_path.startswith(f"{path_value.rstrip('/')}/")
                    or ".." in setting_path.split("/")
                    or _DATA_BEARING_SETTING.search(setting_path)
                ):
                    raise ValueError(
                        "Veusz widget setting paths must stay below the widget "
                        "and remain non-data-bearing."
                    )
                setting_paths[key] = setting_path
            identity.update(
                {
                    "path": path_value,
                    "operation_index": operation_index,
                    "setting_paths": setting_paths,
                }
            )
        elif kind == "mapping_execution_matches_candidate":
            if any(
                assertion.get(field) is not None
                for field in ("path", "operation_index", "setting_paths")
            ):
                raise ValueError(
                    "Mapping-execution assertions use the witnessed execution "
                    "authority and cannot declare an implementation path."
                )
        else:
            raise ValueError(
                f"Unsupported lifecycle assertion kind: {kind!r}"
            )
        assertion_id = canonical_sha256(identity)
        if (
            _required_hash(
                assertion.get("assertion_id"),
                "lifecycle assertion_id",
            )
            != assertion_id
        ):
            raise ValueError("Lifecycle assertion identity hash is stale.")
        lifecycle_assertions.append(
            {
                "assertion_id": assertion_id,
                **identity,
            }
        )
    if not lifecycle_assertions:
        raise ValueError(
            "implementation_contract.lifecycle_assertions must be non-empty."
        )
    assertion_ids = [
        assertion["assertion_id"] for assertion in lifecycle_assertions
    ]
    if assertion_ids != sorted(set(assertion_ids)):
        raise ValueError(
            "Lifecycle assertions must be sorted by unique assertion_id."
        )
    covered_lanes = {
        assertion["lane"] for assertion in lifecycle_assertions
    }
    if covered_lanes != set(lifecycle_lanes):
        raise ValueError(
            "Every lifecycle lane requires at least one behavior assertion."
        )
    for lane in lifecycle_lanes:
        whole_candidate_assertions = [
            assertion
            for assertion in lifecycle_assertions
            if assertion["lane"] == lane
            and assertion["kind"] == "candidate_effect_manifest_equals"
        ]
        if len(whole_candidate_assertions) != 1:
            raise ValueError(
                "Every lifecycle lane requires exactly one whole-candidate "
                "manifest assertion."
            )
    return {
        "candidate_id": candidate_id,
        "source_files": source_files,
        "probe_files": probe_files,
        "probe_kinds": probe_kinds,
        "lifecycle_lanes": lifecycle_lanes,
        "lifecycle_assertions": lifecycle_assertions,
    }


def _validate_candidate_specific_contract(
    contract_value: object,
    candidate: dict[str, Any],
) -> dict[str, Any]:
    contract = _validate_implementation_contract(contract_value)
    candidate_id = _required_hash(
        candidate.get("candidate_id"),
        "candidate candidate_id",
    )
    decision = _required_object(
        candidate.get("canonical_decision"),
        "candidate canonical_decision",
    )
    if (
        contract["candidate_id"] != candidate_id
        or canonical_sha256(decision) != candidate_id
    ):
        raise ValueError(
            "Implementation contract is not bound to the canonical candidate."
        )
    decision_kind = decision.get("decision_kind")
    for lane in contract["lifecycle_lanes"]:
        operation_assertions = [
            assertion
            for assertion in contract["lifecycle_assertions"]
            if assertion["lane"] == lane
            and assertion["kind"]
            in {
                "veusz_setting_matches_operation",
                "veusz_widget_matches_operation",
            }
        ]
        operation_assertions.sort(
            key=lambda assertion: assertion["operation_index"]
        )
        if decision_kind == "data_mapping":
            if operation_assertions:
                raise ValueError(
                    "Data-mapping candidates cannot use Canvas operation assertions."
                )
            mapping_assertions = [
                assertion
                for assertion in contract["lifecycle_assertions"]
                if assertion["lane"] == lane
                and assertion["kind"]
                == "mapping_execution_matches_candidate"
            ]
            if len(mapping_assertions) != 1:
                raise ValueError(
                    "Every data-mapping lifecycle lane requires exactly one "
                    "independently replayed mapping-execution assertion."
                )
            continue
        if decision_kind != "canvas_operation_batch":
            raise ValueError(
                f"Unsupported candidate decision kind: {decision_kind!r}"
            )
        if any(
            assertion["lane"] == lane
            and assertion["kind"] == "mapping_execution_matches_candidate"
            for assertion in contract["lifecycle_assertions"]
        ):
            raise ValueError(
                "Canvas candidates cannot use data-mapping execution assertions."
            )
        operations = _required_list(
            decision.get("operations"),
            "candidate Canvas operations",
        )
        indexes = [
            assertion["operation_index"]
            for assertion in operation_assertions
        ]
        if indexes != list(range(len(operations))):
            raise ValueError(
                "Every Canvas candidate operation must have exactly one "
                "ordered final-VSZ behavior assertion in every lane."
            )
        for assertion, raw_operation in zip(
            operation_assertions,
            operations,
            strict=True,
        ):
            operation = _required_object(
                raw_operation,
                "candidate Canvas operation",
            )
            expected_kind = {
                "set_setting": "veusz_setting_matches_operation",
                "add_widget": "veusz_widget_matches_operation",
            }.get(operation.get("operation_type"))
            if assertion["kind"] != expected_kind:
                raise ValueError(
                    "Canvas lifecycle assertion kind does not match its "
                    "canonical operation."
                )
            if expected_kind == "veusz_widget_matches_operation":
                if set(assertion["setting_paths"]) != set(
                    _required_object(
                        operation.get("settings"),
                        "candidate widget settings",
                    )
                ):
                    raise ValueError(
                        "Widget assertion must cover every canonical setting."
                    )
    return contract


def _validate_changed_file_scope(
    changed_files: list[str],
    contract: dict[str, Any],
) -> tuple[list[str], list[str]]:
    allowed_exact = set(contract["source_files"]) | set(
        contract["probe_files"]
    )
    ancillary = {
        "README.md",
        "DEVELOPMENT_LOG.md",
    }
    unauthorized = [
        path
        for path in changed_files
        if path not in allowed_exact
        and path not in ancillary
        and not path.startswith("docs/")
    ]
    if unauthorized:
        raise ValueError(
            "Promotion commit changed files outside the owner-approved scope: "
            f"{unauthorized!r}"
        )
    changed_source = sorted(
        path for path in changed_files if path in contract["source_files"]
    )
    changed_probes = sorted(
        path for path in changed_files if path in contract["probe_files"]
    )
    if changed_source != contract["source_files"]:
        raise ValueError(
            "Promotion commit did not change every approved source file."
        )
    if changed_probes != contract["probe_files"]:
        raise ValueError(
            "Promotion commit did not change every approved probe or fixture."
        )
    return changed_source, changed_probes


def _protected_registry_snapshot(path: Path) -> tuple[dict[str, Any], str]:
    lexical = path.expanduser().absolute()
    expected = DEFAULT_PROMOTION_TRUST_REGISTRY.absolute()
    if lexical != expected:
        raise ValueError(
            "Production owner trust registry path is fixed to the OS account."
        )
    account_home = _account_home()
    try:
        relative = lexical.relative_to(account_home)
    except ValueError as exc:
        raise ValueError(
            "Owner trust registry escaped the OS account home."
        ) from exc
    current = account_home
    for part in relative.parts:
        current = current / part
        metadata = current.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            raise ValueError("Owner trust registry path cannot contain symlinks.")
        if metadata.st_mode & 0o022:
            raise ValueError(
                "Owner trust registry path cannot be group/world writable."
            )
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(lexical, flags)
    try:
        before = os.fstat(descriptor)
        if before.st_size > 2_000_000:
            raise ValueError("Owner trust registry exceeds the 2 MB limit.")
        data = b""
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            data += chunk
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    ) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    ) or len(data) != after.st_size:
        raise ValueError("Owner trust registry changed during snapshot read.")
    if (
        not stat.S_ISREG(after.st_mode)
        or after.st_uid != os.getuid()
        or after.st_mode & 0o022
    ):
        raise ValueError(
            "Owner trust registry must be a protected file owned by this account."
        )
    immutable_flag = getattr(stat, "UF_IMMUTABLE", 0)
    if immutable_flag and not (after.st_flags & immutable_flag):
        raise ValueError(
            "Owner trust registry must be user-immutable (`chflags uchg`)."
        )
    try:
        registry = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Owner trust registry is not valid JSON.") from exc
    if not isinstance(registry, dict):
        raise ValueError("Owner trust registry must contain one JSON object.")
    return registry, hashlib.sha256(data).hexdigest()


def _load_trust_registry(
    path: Path,
    *,
    require_protected: bool,
) -> tuple[dict[str, Any], str]:
    if require_protected:
        registry, registry_sha256 = _protected_registry_snapshot(path)
    else:
        registry, registry_sha256 = _read_json_snapshot(
            path,
            "promotion owner trust registry",
        )
    _reject_unknown(
        registry,
        {"kind", "version", "owners"},
        label="promotion owner trust registry",
    )
    if (
        registry.get("kind") != PROMOTION_TRUST_REGISTRY_KIND
        or registry.get("version") != PROMOTION_ARTIFACT_VERSION
    ):
        raise ValueError("Unsupported promotion owner trust registry.")
    owners = _required_list(registry.get("owners"), "trusted owners")
    if not owners:
        raise ValueError("Promotion owner trust registry is empty.")
    seen: set[tuple[str, str]] = set()
    for index, raw in enumerate(owners):
        record = _required_object(raw, f"trusted owners[{index}]")
        _reject_unknown(
            record,
            {
                "owner",
                "key_id",
                "signature_algorithm",
                "modulus_hex",
                "exponent",
                "public_key_sha256",
                "state",
            },
            label=f"trusted owners[{index}]",
        )
        owner = _required_text(record.get("owner"), "trusted owner", maximum=200)
        key_id = _required_hash(record.get("key_id"), "trusted key_id")
        if record.get("signature_algorithm") != PROMOTION_SIGNATURE_ALGORITHM:
            raise ValueError("Trusted owner uses an unsupported signature algorithm.")
        modulus_hex = _required_text(
            record.get("modulus_hex"),
            "trusted RSA modulus",
            maximum=4096,
        ).casefold()
        if (
            re.fullmatch(r"[0-9a-f]+", modulus_hex) is None
            or len(modulus_hex) % 2
            or modulus_hex.startswith("00")
            or record.get("modulus_hex") != modulus_hex
        ):
            raise ValueError(
                "Trusted RSA modulus must be canonical even-length lowercase hex."
            )
        modulus = int(modulus_hex, 16)
        exponent = record.get("exponent")
        if (
            type(exponent) is not int
            or exponent < 3
            or exponent > 2**31 - 1
            or exponent % 2 == 0
            or modulus.bit_length() < 2048
        ):
            raise ValueError("Trusted RSA key must be at least 2048 bits.")
        public_key = {
            "signature_algorithm": PROMOTION_SIGNATURE_ALGORITHM,
            "modulus_hex": modulus_hex,
            "exponent": exponent,
        }
        public_key_sha256 = canonical_sha256(public_key)
        if (
            _required_hash(
                record.get("public_key_sha256"),
                "trusted public_key_sha256",
            )
            != public_key_sha256
            or key_id != public_key_sha256
        ):
            raise ValueError("Trusted owner public-key fingerprint is stale.")
        if record.get("state") not in {"active", "revoked"}:
            raise ValueError("Trusted owner key state must be active or revoked.")
        identity = (owner, key_id)
        if identity in seen:
            raise ValueError("Trusted owner registry contains a duplicate key.")
        seen.add(identity)
    return registry, registry_sha256


def _verify_rsa_signature(
    *,
    payload: bytes,
    signature: str,
    modulus_hex: str,
    exponent: int,
) -> None:
    try:
        raw_signature = base64.b64decode(signature, validate=True)
    except ValueError as exc:
        raise ValueError("Owner receipt signature must be canonical base64.") from exc
    if base64.b64encode(raw_signature).decode("ascii") != signature:
        raise ValueError("Owner receipt signature must use canonical base64.")
    modulus = int(modulus_hex, 16)
    modulus_bytes = (modulus.bit_length() + 7) // 8
    if len(raw_signature) != modulus_bytes:
        raise ValueError("Owner receipt signature has the wrong RSA size.")
    signature_integer = int.from_bytes(raw_signature, "big")
    if signature_integer >= modulus:
        raise ValueError("Owner receipt signature is outside the RSA modulus.")
    encoded = pow(signature_integer, exponent, modulus).to_bytes(
        modulus_bytes,
        "big",
    )
    digest_info = _SHA256_DIGEST_INFO_PREFIX + hashlib.sha256(payload).digest()
    padding_size = modulus_bytes - len(digest_info) - 3
    if padding_size < 8:
        raise ValueError("Trusted RSA key is too small for SHA-256 verification.")
    expected = b"\x00\x01" + (b"\xff" * padding_size) + b"\x00" + digest_info
    if not hmac.compare_digest(encoded, expected):
        raise ValueError("Owner receipt signature verification failed.")


def _verify_owner_authority(
    receipt: dict[str, Any],
    *,
    trust_registry_path: Path | None,
) -> dict[str, Any]:
    require_protected = trust_registry_path is None
    registry_path = (
        DEFAULT_PROMOTION_TRUST_REGISTRY.absolute()
        if require_protected
        else trust_registry_path.expanduser().resolve()
    )
    registry, registry_sha256 = _load_trust_registry(
        registry_path,
        require_protected=require_protected,
    )
    owner = _required_text(receipt.get("owner"), "receipt owner", maximum=200)
    key_id = _required_hash(receipt.get("owner_key_id"), "receipt owner_key_id")
    if receipt.get("signature_algorithm") != PROMOTION_SIGNATURE_ALGORITHM:
        raise ValueError("Owner receipt signature algorithm is unsupported.")
    matches = [
        _required_object(record, "trusted owner")
        for record in registry["owners"]
        if isinstance(record, dict)
        and record.get("owner") == owner
        and record.get("key_id") == key_id
    ]
    if len(matches) != 1 or matches[0].get("state") != "active":
        raise ValueError("Owner receipt is not signed by one active trusted key.")
    key = matches[0]
    unsigned = {
        field: value
        for field, value in receipt.items()
        if field != "signature"
    }
    _verify_rsa_signature(
        payload=_canonical_bytes(unsigned),
        signature=_required_text(
            receipt.get("signature"),
            "owner receipt signature",
            maximum=8192,
        ),
        modulus_hex=str(key["modulus_hex"]),
        exponent=int(key["exponent"]),
    )
    return {
        "trust_registry": str(registry_path),
        "trust_registry_sha256": registry_sha256,
        "owner_key_id": key_id,
        "public_key_sha256": key["public_key_sha256"],
        "signature_algorithm": PROMOTION_SIGNATURE_ALGORITHM,
        "protected_registry": require_protected,
        "signature_sha256": hashlib.sha256(
            base64.b64decode(str(receipt["signature"]), validate=True)
        ).hexdigest(),
    }


def _artifact_hash(payload: dict[str, Any], hash_field: str) -> str:
    return canonical_sha256(
        {key: value for key, value in payload.items() if key != hash_field}
    )


def _bind_artifact(
    payload: dict[str, Any],
    *,
    hash_field: str,
) -> dict[str, Any]:
    bound = json.loads(json.dumps(payload))
    bound[hash_field] = _artifact_hash(bound, hash_field)
    return bound


def _validate_bound_artifact(
    payload: dict[str, Any],
    *,
    kind: str,
    hash_field: str,
    label: str,
) -> dict[str, Any]:
    if (
        payload.get("kind") != kind
        or payload.get("version") != PROMOTION_ARTIFACT_VERSION
    ):
        raise ValueError(f"Unsupported {label} contract.")
    recorded = _required_hash(payload.get(hash_field), f"{label}.{hash_field}")
    if _artifact_hash(payload, hash_field) != recorded:
        raise ValueError(f"{label} content hash is stale.")
    if payload.get("runtime_effect") is not False:
        raise ValueError(f"{label} must remain powerless at runtime.")
    if payload.get("status") != "passed":
        raise ValueError(f"{label} must remain in passed status.")
    return payload


def _write_artifact(path: Path, payload: dict[str, Any]) -> Path:
    return atomic_write_json(path.expanduser().resolve(), payload)


def _normalize_identifier(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip().casefold()
    return re.sub(r"\s+", " ", text)


def _count_bucket(count: int) -> str:
    if count <= 0:
        return "none"
    if count == 1:
        return "one"
    if count <= 4:
        return "few"
    if count <= 12:
        return "several"
    return "many"


def _value_shape(value: Any) -> dict[str, Any]:
    if value is None:
        return {"value_class": "null"}
    if type(value) is bool:
        return {"value_class": "boolean"}
    if isinstance(value, int | float) and not isinstance(value, bool):
        return {"value_class": "number"}
    if isinstance(value, str):
        return {
            "value_class": "text",
            "length": (
                "empty"
                if not value
                else "short"
                if len(value) <= 24
                else "medium"
                if len(value) <= 120
                else "long"
            ),
        }
    if isinstance(value, list):
        return {
            "value_class": "array",
            "count": _count_bucket(len(value)),
            "item_classes": sorted(
                {
                    str(_value_shape(item).get("value_class"))
                    for item in value
                }
            ),
        }
    if isinstance(value, dict):
        return {
            "value_class": "object",
            "keys": sorted(_normalize_identifier(key) for key in value),
        }
    raise ValueError(f"Unsupported canonical value type: {type(value).__name__}")


def _safe_visual_literal(value: Any) -> Any:
    if value is None or type(value) is bool:
        return value
    if isinstance(value, int | float) and not isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = unicodedata.normalize("NFKC", value).strip()
        if (
            len(text) > 160
            or _UUID.fullmatch(text)
            or text.startswith("/")
            or re.match(r"^[A-Za-z]:[\\/]", text)
        ):
            return _value_shape(text)
        return text
    if isinstance(value, list):
        if len(value) > 24:
            return _value_shape(value)
        return [_safe_visual_literal(item) for item in value]
    if isinstance(value, dict):
        if len(value) > 24:
            return _value_shape(value)
        return {
            _normalize_identifier(key): _safe_visual_literal(item)
            for key, item in sorted(value.items())
        }
    raise ValueError(f"Unsupported visual literal: {type(value).__name__}")


def _canonical_transform_parameters(
    transformation_type: str,
    parameters: dict[str, Any],
) -> dict[str, Any]:
    canonical: dict[str, Any] = {}
    for key, value in sorted(parameters.items()):
        normalized_key = _normalize_identifier(key)
        if normalized_key == "row_indices":
            rows = value if isinstance(value, list) else []
            canonical[normalized_key] = {
                "value_class": "row_selection",
                "count": _count_bucket(len(rows)),
            }
        elif normalized_key == "value":
            canonical[normalized_key] = _value_shape(value)
        elif normalized_key == "where" and isinstance(value, list):
            conditions: list[dict[str, Any]] = []
            for item in value:
                condition = _required_object(item, "mapping condition")
                result = {
                    "column": _normalize_identifier(condition.get("column")),
                    "operator": _normalize_identifier(condition.get("operator")),
                }
                if "value" in condition:
                    result["value"] = _value_shape(condition["value"])
                conditions.append(result)
            canonical[normalized_key] = conditions
        elif isinstance(value, dict):
            canonical[normalized_key] = {
                _normalize_identifier(item_key): (
                    _value_shape(item_value)
                    if item_key.casefold() == "value"
                    else _safe_visual_literal(item_value)
                )
                for item_key, item_value in sorted(value.items())
            }
        else:
            canonical[normalized_key] = _safe_visual_literal(value)
    return {
        "transformation_type": _normalize_identifier(transformation_type),
        "parameters": canonical,
    }


def canonicalize_data_mapping_execution(
    execution_path: Path,
) -> dict[str, Any]:
    resolved_execution = execution_path.expanduser().resolve()
    execution_root = (
        resolved_execution
        if resolved_execution.is_dir()
        else resolved_execution.parent
    )
    execution_manifest = (
        execution_root / DATA_MAPPING_EXECUTION_FILENAME
        if resolved_execution.is_dir()
        else resolved_execution
    )
    tree_before = _tree_snapshot(
        execution_root,
        "data mapping execution tree",
    )
    initial_execution, _execution_sha256 = _read_json_snapshot(
        execution_manifest,
        "data mapping execution manifest",
    )
    initial_proposal_path = Path(
        str(initial_execution.get("proposal") or "")
    ).expanduser()
    initial_proposal, _proposal_sha256 = _read_json_snapshot(
        initial_proposal_path,
        "data mapping proposal",
    )
    execution = load_data_mapping_execution(resolved_execution)
    normalized_execution_fields = {
        "confirmation_migration_required",
        "confirmation_schema_version",
        "handoff_allowed",
    }
    if any(
        execution.get(key) != value
        for key, value in initial_execution.items()
    ) or (
        set(execution) - set(initial_execution) - normalized_execution_fields
    ):
        raise ValueError(
            "Data mapping loader did not validate the captured execution manifest."
        )
    if (
        execution.get("raw_inputs_unchanged") is not True
        or execution.get("ready_to_use") is not True
        or execution.get("handoff_allowed") is not True
    ):
        raise ValueError("Only verified handoff-ready mapping executions qualify.")
    proposal = load_data_mapping_proposal(Path(str(execution["proposal"])))
    payload = proposal.to_dict()
    if payload != initial_proposal:
        raise ValueError(
            "Data mapping loader did not validate the captured proposal."
        )
    source_slots = {
        str(source.get("source_id")): index
        for index, source in enumerate(payload.get("sources") or [])
        if isinstance(source, dict)
    }
    columns: list[dict[str, Any]] = []
    for column_value in payload.get("columns") or []:
        column = _required_object(column_value, "mapping column")
        source_id = str(column.get("source_id") or "")
        columns.append(
            {
                "source_slot": source_slots.get(source_id),
                "source_column_index": column.get("source_column_index"),
                "output_column": _normalize_identifier(
                    column.get("output_column")
                ),
                "role": _normalize_identifier(column.get("role")),
                "expected_header": (
                    _normalize_identifier(column.get("expected_header"))
                    if column.get("expected_header") is not None
                    else None
                ),
                "required": column.get("required") is True,
            }
        )
    transformations = [
        _canonical_transform_parameters(
            str(item.get("transformation_type") or ""),
            _required_object(item.get("parameters"), "transformation parameters"),
        )
        for item in payload.get("transformations") or []
        if isinstance(item, dict)
    ]
    request_patch: dict[str, Any] = {}
    for key, value in sorted(
        _required_object(payload.get("request_patch"), "request_patch").items()
    ):
        if key == "series_order":
            series = value if isinstance(value, list) else []
            request_patch["series_count"] = _count_bucket(len(series))
        else:
            request_patch[_normalize_identifier(key)] = _safe_visual_literal(
                value
            )
    unit_overrides = {
        _normalize_identifier(key): _normalize_identifier(value)
        for key, value in sorted(
            _required_object(
                payload.get("unit_overrides"),
                "unit_overrides",
            ).items()
        )
    }
    canonical = {
        "decision_kind": "data_mapping",
        "source_count": len(source_slots),
        "columns": columns,
        "sample_label_policy": {
            "present": bool(payload.get("sample_labels")),
            "count": _count_bucket(len(payload.get("sample_labels") or {})),
        },
        "unit_overrides": unit_overrides,
        "transformations": transformations,
        "request_patch": request_patch,
    }
    tree_after = _tree_snapshot(
        execution_root,
        "data mapping execution tree",
    )
    if tree_after != tree_before:
        raise ValueError(
            "Data mapping execution tree changed during canonical replay."
        )
    return canonical


def _target_descriptor(
    session: CanvasSession,
    target_id: str,
    setting_path: str | None = None,
) -> tuple[dict[str, Any], str | None]:
    record = session.object_registry.by_id(target_id)
    if record is None:
        raise ValueError(
            "Canvas operation target is absent from the reopened final object tree."
        )
    relative: str | None = None
    if setting_path is not None:
        prefix = record.current_path.rstrip("/")
        if not setting_path.startswith(f"{prefix}/"):
            raise ValueError(
                "Canvas setting path no longer resolves below its final target."
            )
        relative = setting_path[len(prefix) :]
    return (
        {
            "object_type": _normalize_identifier(record.object_type),
            "structural_depth": len(
                [part for part in record.current_path.split("/") if part]
            ),
        },
        relative,
    )


def _canonical_canvas_setting_value(setting_path: str, value: Any) -> Any:
    if _DATA_BEARING_SETTING.search(setting_path):
        raise ValueError(
            "Data-bearing Canvas settings cannot enter promotion candidates."
        )
    if _FREE_TEXT_SETTING.search(setting_path):
        text = str(value or "")
        return {
            **_value_shape(text),
            "contains_math_markup": any(
                marker in text for marker in ("\\", "^", "_", "{", "}")
            ),
            "contains_unit_delimiter": any(
                marker in text for marker in ("(", ")", "[", "]")
            ),
        }
    if _RANGE_SETTING.search(setting_path):
        if isinstance(value, str) and value.casefold() == "auto":
            return {"value_class": "range_policy", "mode": "auto"}
        return {"value_class": "data_range", "literal_removed": True}
    return _safe_visual_literal(value)


def canonicalize_canvas_batch(
    batch_payload: dict[str, Any],
    *,
    session: CanvasSession,
) -> dict[str, Any]:
    batch = CanvasOperationBatch.from_dict(batch_payload)
    operations: list[dict[str, Any]] = []
    for operation in batch.operations:
        arguments = operation.arguments
        operation_type = operation.operation_type
        if operation_type == "set_setting":
            setting_path = _required_text(
                arguments.get("setting_path"),
                "Canvas setting_path",
            )
            target, relative = _target_descriptor(
                session,
                operation.target_id,
                setting_path,
            )
            operations.append(
                {
                    "operation_type": operation_type,
                    "target": target,
                    "setting_path": relative,
                    "value": _canonical_canvas_setting_value(
                        str(relative),
                        arguments.get("value"),
                    ),
                }
            )
        elif operation_type == "add_widget":
            target, _ = _target_descriptor(session, operation.target_id)
            widget_type = _normalize_identifier(arguments.get("widget_type"))
            raw_settings = _required_object(
                arguments.get("settings"),
                "add_widget settings",
            )
            settings: dict[str, Any] = {}
            for key, value in sorted(raw_settings.items()):
                normalized_key = _normalize_identifier(key)
                if normalized_key in {
                    "xpos",
                    "ypos",
                    "xpos2",
                    "ypos2",
                    "width",
                    "height",
                }:
                    settings[normalized_key] = _value_shape(value)
                else:
                    settings[normalized_key] = (
                        _canonical_canvas_setting_value(
                            f"/{normalized_key}",
                            value,
                        )
                    )
            operations.append(
                {
                    "operation_type": operation_type,
                    "target": target,
                    "widget_type": widget_type,
                    "front_or_append": (
                        "front" if arguments.get("index") == 0 else "append"
                    ),
                    "settings": settings,
                }
            )
        elif operation_type == "composition_place_module":
            operations.append(
                {
                    "operation_type": operation_type,
                    "target": {"object_type": "composition_variant"},
                    "slot_policy": (
                        "unplaced"
                        if arguments.get("slot_ref") is None
                        else "named_slot"
                    ),
                }
            )
        elif operation_type == "composition_reorder_modules":
            ordered = arguments.get("ordered_module_ids")
            operations.append(
                {
                    "operation_type": operation_type,
                    "target": {"object_type": "composition_variant"},
                    "module_count": _count_bucket(
                        len(ordered) if isinstance(ordered, list) else 0
                    ),
                }
            )
        elif operation_type == "composition_set_layout":
            operations.append(
                {
                    "operation_type": operation_type,
                    "target": {"object_type": "composition_variant"},
                    "layout_id": _safe_visual_literal(
                        arguments.get("layout_id")
                    ),
                }
            )
        elif operation_type == "composition_set_canvas_height":
            operations.append(
                {
                    "operation_type": operation_type,
                    "target": {"object_type": "composition_variant"},
                    "height_mm": _safe_visual_literal(
                        arguments.get("height_mm")
                    ),
                }
            )
        elif operation_type == "composition_set_legend_policy":
            operations.append(
                {
                    "operation_type": operation_type,
                    "target": {"object_type": "composition_variant"},
                    "legend_policy": _safe_visual_literal(
                        arguments.get("legend_policy")
                    ),
                }
            )
        else:
            raise ValueError(
                f"Unsupported promotion Canvas operation: {operation_type!r}"
            )
    return {
        "decision_kind": "canvas_operation_batch",
        "atomic": True,
        "operations": operations,
    }


def _session_records(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    key_for_type = {
        "preregistered": "preregistration",
        "reopen_witnessed": "witness",
        "completed": "completion",
    }
    for event in events:
        event_type = str(event.get("event_type") or "")
        key = key_for_type.get(event_type)
        if key is None:
            continue
        session_id = _required_text(event.get("session_id"), "session_id")
        record = records.setdefault(session_id, {})
        record[key] = event
    return records


def _session_authority_artifacts(
    session: dict[str, Any],
) -> list[dict[str, Any]]:
    witness = _required_object(
        _required_object(session.get("witness"), "session witness event").get(
            "payload"
        ),
        "session witness",
    )
    completion = _required_object(
        _required_object(
            session.get("completion"),
            "session completion event",
        ).get("payload"),
        "session completion",
    )
    authority = _required_object(
        witness.get("authority"),
        "session witness authority",
    )
    artifacts: list[dict[str, Any]] = []

    def append_file(role: str, path_value: object, sha_value: object) -> None:
        path_text = _required_text(path_value, f"{role} path")
        artifacts.append(
            {
                "role": role,
                "path": str(Path(path_text).expanduser().resolve()),
                "sha256": _required_hash(sha_value, f"{role} sha256"),
            }
        )

    append_file(
        "canvas_session",
        authority.get("canvas_session"),
        authority.get("canvas_session_sha256"),
    )
    append_file(
        "exact_current_document",
        authority.get("document"),
        authority.get("document_sha256"),
    )
    exports = _required_object(
        authority.get("exports"),
        "session witness exports",
    )
    for export_format, raw_records in sorted(exports.items()):
        for index, raw_record in enumerate(
            _required_list(
                raw_records,
                f"session witness exports.{export_format}",
            )
        ):
            record = _required_object(
                raw_record,
                f"session witness exports.{export_format}[{index}]",
            )
            append_file(
                f"export:{_normalize_identifier(export_format)}:{index}",
                record.get("path"),
                record.get("sha256"),
            )
    optional = _required_object(
        witness.get("optional_evidence"),
        "session witness optional_evidence",
    )
    review = optional.get("review")
    if isinstance(review, dict):
        append_file(
            "review_sidecar",
            review.get("path"),
            review.get("sha256"),
        )
    mapping = optional.get("data_mapping")
    if isinstance(mapping, dict):
        append_file(
            "data_mapping_execution",
            mapping.get("path"),
            mapping.get("sha256"),
        )
    journal = _required_object(
        witness.get("journal"),
        "session witness journal",
    )
    journal_path = str(
        Path(
            _required_text(
                journal.get("path"),
                "session witness journal path",
            )
        )
        .expanduser()
        .resolve()
    )
    journal_size = journal.get("end_size_bytes")
    if type(journal_size) is not int or journal_size < 0:
        raise ValueError(
            "Session witness journal end_size_bytes must be non-negative."
        )
    artifacts.append(
        {
            "role": "operation_journal_prefix",
            "path": journal_path,
            "sha256": _required_hash(
                journal.get("end_sha256"),
                "session witness journal end_sha256",
            ),
            "prefix_size_bytes": journal_size,
        }
    )
    manifest = _required_object(
        completion.get("manifest"),
        "session completion manifest",
    )
    append_file(
        "completion_manifest",
        manifest.get("path"),
        manifest.get("sha256"),
    )
    artifacts.sort(
        key=lambda item: (
            item["role"],
            item["path"],
            item["sha256"],
            int(item.get("prefix_size_bytes", -1)),
        )
    )
    identities = [
        (
            item["role"],
            item["path"],
            item["sha256"],
            item.get("prefix_size_bytes"),
        )
        for item in artifacts
    ]
    if len(identities) != len(set(identities)):
        raise ValueError("Session authority artifact inventory repeats an entry.")
    return artifacts


def _session_receipt_binding_from_snapshot(
    snapshot: dict[str, Any],
    session_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    sessions = _session_records(
        _required_list(snapshot.get("events"), "session snapshot events")
    )
    session = sessions.get(session_id)
    if session is None or not {
        "preregistration",
        "witness",
        "completion",
    } <= set(session):
        raise ValueError(f"Real session is incomplete: {session_id}")
    preregistration_hash = _required_hash(
        session["preregistration"].get("event_sha256"),
        "preregistration event hash",
    )
    witness_hash = _required_hash(
        session["witness"].get("event_sha256"),
        "witness event hash",
    )
    completion_hash = _required_hash(
        session["completion"].get("event_sha256"),
        "completion event hash",
    )
    prefixes = {
        _required_hash(
            record.get("event_sha256"),
            "event-prefix event_sha256",
        ): record
        for record in (
            _required_object(item, "event-prefix record")
            for item in _required_list(
                snapshot.get("event_prefixes"),
                "session snapshot event_prefixes",
            )
        )
    }
    completion_prefix = _required_object(
        prefixes.get(completion_hash),
        "completion ledger prefix",
    )
    prefix_size = completion_prefix.get("prefix_size_bytes")
    if type(prefix_size) is not int or prefix_size <= 0:
        raise ValueError(
            "Completion ledger prefix size must be a positive integer."
        )
    ledger = str(
        Path(
            _required_text(snapshot.get("ledger"), "session snapshot ledger")
        )
        .expanduser()
        .resolve()
    )
    return (
        {
            "ledger": ledger,
            "session_id": session_id,
            "ledger_prefix_size_bytes": prefix_size,
            "ledger_prefix_sha256": _required_hash(
                completion_prefix.get("prefix_sha256"),
                "completion ledger prefix sha256",
            ),
            "preregistration_event_sha256": preregistration_hash,
            "witness_event_sha256": witness_hash,
            "completion_event_sha256": completion_hash,
            "authority_artifacts": _session_authority_artifacts(session),
        },
        session,
    )


def build_promotion_session_binding(
    ledger_path: Path,
    session_id: str,
) -> dict[str, Any]:
    """Build the powerless real-session facts an owner signs for verification."""

    ledger = ledger_path.expanduser().resolve()
    snapshot = verified_session_evidence_snapshot(ledger)
    binding, _session = _session_receipt_binding_from_snapshot(
        snapshot,
        _required_text(session_id, "session_id", maximum=100),
    )
    return binding


def _verify_signed_session_reference(
    record: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    ledger_text = _required_text(record.get("ledger"), "real ledger")
    ledger = Path(ledger_text).expanduser().resolve()
    if ledger_text != str(ledger):
        raise ValueError(
            "Verification receipt real-session ledger paths must be canonical."
        )
    session_id = _required_text(
        record.get("session_id"),
        "real session_id",
        maximum=100,
    )
    snapshot = verified_session_evidence_snapshot(ledger)
    expected, session = _session_receipt_binding_from_snapshot(
        snapshot,
        session_id,
    )
    if record != expected:
        raise ValueError(
            f"Signed real-session binding changed for {session_id!r}."
        )
    for artifact in expected["authority_artifacts"]:
        path = Path(artifact["path"])
        _target, data, digest = _read_file_snapshot(
            path,
            f"signed session authority {artifact['role']}",
        )
        prefix_size = artifact.get("prefix_size_bytes")
        if prefix_size is None:
            actual = digest
        else:
            if type(prefix_size) is not int or prefix_size > len(data):
                raise ValueError(
                    "Signed authority prefix is outside the current file."
                )
            actual = hashlib.sha256(data[:prefix_size]).hexdigest()
        if actual != artifact["sha256"]:
            raise ValueError(
                "Signed real-session authority changed: "
                f"{artifact['role']}."
            )
    return snapshot, session, expected


def _within(root: Path, path: Path, label: str) -> Path:
    resolved_root = root.expanduser().resolve()
    resolved = path.expanduser().resolve()
    if not resolved.is_relative_to(resolved_root):
        raise ValueError(f"{label} escaped the preregistered project.")
    return resolved


def _verified_journal_segment(
    preregistration: dict[str, Any],
    witness: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    project_payload = _required_object(
        preregistration.get("project"),
        "preregistered project",
    )
    project_root = Path(
        _required_text(project_payload.get("root"), "project root")
    )
    baseline = _required_object(
        preregistration.get("operation_journal_baseline"),
        "journal baseline",
    )
    journal = _required_object(witness.get("journal"), "witness journal")
    journal_path = _within(
        project_root,
        Path(_required_text(journal.get("path"), "journal path")),
        "Witness journal",
    )
    baseline_path = _within(
        project_root,
        Path(_required_text(baseline.get("path"), "baseline journal path")),
        "Baseline journal",
    )
    if baseline_path != journal_path:
        raise ValueError("Witness journal path changed after preregistration.")
    data = journal_path.read_bytes()
    end_size = journal.get("end_size_bytes")
    baseline_size = baseline.get("size_bytes")
    if (
        type(end_size) is not int
        or type(baseline_size) is not int
        or baseline_size < 0
        or end_size < baseline_size
        or end_size > len(data)
    ):
        raise ValueError("Witness journal byte boundary is invalid.")
    prefix = data[:end_size]
    baseline_prefix = data[:baseline_size]
    if hashlib.sha256(baseline_prefix).hexdigest() != _required_hash(
        baseline.get("prefix_sha256"),
        "journal baseline prefix_sha256",
    ):
        raise ValueError("Preregistered journal prefix changed.")
    if hashlib.sha256(prefix).hexdigest() != _required_hash(
        journal.get("end_sha256"),
        "journal end_sha256",
    ):
        raise ValueError("Witness journal prefix changed after completion.")
    segment = data[baseline_size:end_size]
    if (
        journal.get("post_baseline_size_bytes") != len(segment)
        or journal.get("baseline_size_bytes") != baseline_size
    ):
        raise ValueError("Witness journal byte accounting changed.")
    if hashlib.sha256(segment).hexdigest() != _required_hash(
        journal.get("post_baseline_sha256"),
        "journal post_baseline_sha256",
    ):
        raise ValueError("Witness journal segment changed after completion.")
    if segment and not segment.endswith(b"\n"):
        raise ValueError("Witness journal segment has an incomplete JSONL line.")
    entries: list[dict[str, Any]] = []
    for index, raw_line in enumerate(segment.splitlines(), 1):
        try:
            entry = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Witness journal line {index} is invalid JSON."
            ) from exc
        if not isinstance(entry, dict):
            raise ValueError(f"Witness journal line {index} is not an object.")
        entries.append(entry)
    if len(entries) != journal.get("post_baseline_event_count"):
        raise ValueError("Witness journal event count changed.")
    return entries, {
        "journal_sha256": hashlib.sha256(prefix).hexdigest(),
        "journal_segment_sha256": hashlib.sha256(segment).hexdigest(),
        "journal_event_count": len(entries),
    }


def _session_base_evidence(
    prereg_event: dict[str, Any],
    witness_event: dict[str, Any],
    completion_event: dict[str, Any],
    *,
    ledger_sha256: str,
) -> tuple[dict[str, Any], bool]:
    preregistration = _required_object(
        prereg_event.get("payload"),
        "preregistration payload",
    )
    witness = _required_object(witness_event.get("payload"), "witness payload")
    completion = _required_object(
        completion_event.get("payload"),
        "completion payload",
    )
    owners = {
        _required_text(preregistration.get("owner"), "preregistration owner"),
        _required_text(witness.get("owner"), "witness owner"),
        _required_text(completion.get("owner"), "completion owner"),
    }
    if len(owners) != 1 or witness.get("attestation") is not True:
        raise ValueError("Promotion requires one explicitly attested owner.")
    if completion.get("outcome") != "pass" or completion.get("failures"):
        raise ValueError("Promotion requires a completed passing session.")
    source_class = _required_text(
        preregistration.get("source_class"),
        "source_class",
    )
    scope = _required_text(preregistration.get("scope"), "scope")
    eligible = (
        source_class in REAL_SOURCE_CLASSES and scope in REAL_SESSION_SCOPES
    )
    owner = next(iter(owners))
    return (
        {
            "ledger_sha256": ledger_sha256,
            "session_id": str(prereg_event["session_id"]),
            "task_fingerprint": _required_hash(
                preregistration.get("task_fingerprint"),
                "task_fingerprint",
            ),
            "preregistration_event_sha256": _required_hash(
                prereg_event.get("event_sha256"),
                "preregistration event hash",
            ),
            "witness_event_sha256": _required_hash(
                witness_event.get("event_sha256"),
                "witness event hash",
            ),
            "completion_event_sha256": _required_hash(
                completion_event.get("event_sha256"),
                "completion event hash",
            ),
            "source_class": source_class,
            "scope": scope,
            "lane": _required_text(preregistration.get("lane"), "lane"),
            "owner_attested": True,
            "owner_attestation_sha256": hashlib.sha256(
                owner.encode("utf-8")
            ).hexdigest(),
            "outcome": "pass",
        },
        eligible,
    )


def _promotion_observation_exclusion_reason(
    preregistration: dict[str, Any],
) -> str | None:
    if (
        "promotion_binding" in preregistration
        and preregistration.get("promotion_binding") is not None
    ):
        return "promotion_verification_session_non_voting"
    return None


def _observation(
    *,
    decision: dict[str, Any],
    evidence: dict[str, Any],
    artifact_sha256: str,
    eligible: bool,
) -> dict[str, Any]:
    decision_sha256 = canonical_sha256(decision)
    identity = {
        "ledger_sha256": evidence["ledger_sha256"],
        "session_id": evidence["session_id"],
        "completion_event_sha256": evidence["completion_event_sha256"],
        "decision_sha256": decision_sha256,
        "artifact_sha256": artifact_sha256,
    }
    return {
        "observation_id": canonical_sha256(identity),
        "decision_kind": decision["decision_kind"],
        "canonical_decision": decision,
        "canonical_decision_sha256": decision_sha256,
        "evidence": evidence,
        "artifact_sha256": artifact_sha256,
        "eligible_for_threshold": eligible,
    }


def _mapping_observation(
    *,
    prereg_event: dict[str, Any],
    witness_event: dict[str, Any],
    completion_event: dict[str, Any],
    ledger_sha256: str,
) -> dict[str, Any] | None:
    preregistration = _required_object(prereg_event["payload"], "preregistration")
    completion = _required_object(completion_event["payload"], "completion")
    expected = set(preregistration.get("expected_evidence") or [])
    checks = _required_object(completion.get("evidence_checks"), "evidence checks")
    if "data_mapping" not in expected or checks.get("data_mapping") is not True:
        return None
    witness = _required_object(witness_event["payload"], "witness")
    optional = _required_object(
        witness.get("optional_evidence"),
        "optional evidence",
    )
    mapping = _required_object(optional.get("data_mapping"), "mapping evidence")
    project_root = Path(
        _required_text(
            _required_object(
                preregistration.get("project"),
                "project",
            ).get("root"),
            "project root",
        )
    )
    execution_path = _within(
        project_root,
        Path(_required_text(mapping.get("path"), "mapping execution path")),
        "Mapping execution",
    )
    _target, execution_before, artifact_sha256 = _read_file_snapshot(
        execution_path,
        "mapping execution",
    )
    if artifact_sha256 != _required_hash(
        mapping.get("sha256"),
        "mapping execution sha256",
    ):
        raise ValueError("Mapping execution changed after session completion.")
    decision = canonicalize_data_mapping_execution(execution_path)
    _target, execution_after, after_sha256 = _read_file_snapshot(
        execution_path,
        "mapping execution",
    )
    if execution_after != execution_before or after_sha256 != artifact_sha256:
        raise ValueError(
            "Mapping execution changed while promotion replayed it."
        )
    evidence, eligible = _session_base_evidence(
        prereg_event,
        witness_event,
        completion_event,
        ledger_sha256=ledger_sha256,
    )
    evidence["execution_sha256"] = artifact_sha256
    return _observation(
        decision=decision,
        evidence=evidence,
        artifact_sha256=artifact_sha256,
        eligible=eligible,
    )


def _batch_was_later_reversed(
    entries: list[dict[str, Any]],
    *,
    commit_index: int,
    transaction_id: str,
    batch_id: str,
) -> bool:
    for entry in entries[commit_index + 1 :]:
        event = str(entry.get("event") or "")
        if event == "assistant_transaction_rolled_back" and (
            entry.get("transaction_id") == transaction_id
        ):
            return True
        if event in {"assistant_batch_undone", "undo"} and (
            entry.get("batch_id") == batch_id
            or (
                entry.get("transaction_id") == transaction_id
                and entry.get("batch_id") is None
            )
            or (
                event == "undo"
                and entry.get("batch_id") is None
                and entry.get("transaction_id") is None
            )
        ):
            return True
    return False


def _batch_setting_keys(batch_payload: dict[str, Any]) -> set[tuple[str, str]]:
    batch = CanvasOperationBatch.from_dict(batch_payload)
    keys = [
        (
            operation.target_id,
            str(operation.arguments.get("setting_path") or ""),
        )
        for operation in batch.operations
        if operation.operation_type == "set_setting"
    ]
    if len(keys) != len(set(keys)):
        raise ValueError(
            "A promotable batch cannot write one setting more than once."
        )
    return set(keys)


def _batch_was_later_superseded(
    entries: list[dict[str, Any]],
    *,
    applied_index: int,
    batch_payload: dict[str, Any],
) -> bool:
    setting_keys = _batch_setting_keys(batch_payload)
    if not setting_keys:
        return False
    for entry in entries[applied_index + 1 :]:
        if entry.get("event") not in {
            "assistant_batch_applied",
            "operation_batch_applied",
            "review_annotation_promoted",
        }:
            continue
        later_batch = entry.get("batch")
        if not isinstance(later_batch, dict):
            continue
        try:
            later_keys = _batch_setting_keys(later_batch)
        except ValueError:
            return True
        if setting_keys & later_keys:
            return True
    return False


def _load_veusz_document(document_path: Path) -> Any:
    from sciplot_core._paths import VEUSZ_ROOT

    runtime = str(VEUSZ_ROOT)
    if runtime not in sys.path:
        sys.path.insert(0, runtime)
    from sciplot_core.studio import ensure_veusz_qsettings_compat

    ensure_veusz_qsettings_compat()
    from veusz import dataimport, document, widgets

    _ = dataimport, widgets
    loaded = document.Document()
    loaded.load(str(document_path.expanduser().resolve()))
    return loaded


def _batch_matches_final_document(
    *,
    document: Any,
    batch_payload: dict[str, Any],
    applied_entry: dict[str, Any],
) -> bool:
    batch = CanvasOperationBatch.from_dict(batch_payload)
    raw_changes = applied_entry.get("changes")
    if not isinstance(raw_changes, list):
        return False
    changes = {
        str(change.get("operation_id") or ""): change
        for change in raw_changes
        if isinstance(change, dict)
    }
    if len(changes) != len(raw_changes):
        return False
    for operation in batch.operations:
        change = changes.get(operation.operation_id)
        if change is None or change.get("operation_type") != operation.operation_type:
            return False
        if operation.operation_type == "set_setting":
            setting_path = str(operation.arguments.get("setting_path") or "")
            if change.get("setting_path") != setting_path:
                return False
            try:
                current = document.resolveSettingPath(None, setting_path).get()
            except ValueError:
                return False
            if json_safe(current) != json_safe(change.get("new_value")):
                return False
            continue
        if operation.operation_type == "add_widget":
            created_path = str(change.get("created_path") or "")
            if not created_path:
                return False
            try:
                widget = document.resolveWidgetPath(None, created_path)
            except ValueError:
                return False
            if str(widget.typename) != str(operation.arguments.get("widget_type")):
                return False
            settings = operation.arguments.get("settings")
            if not isinstance(settings, dict):
                return False
            for key, requested in settings.items():
                setting_path = (
                    f"{created_path}/{str(key).replace('__', '/')}"
                )
                try:
                    setting = document.resolveSettingPath(None, setting_path)
                    expected = setting.normalize(requested)
                    current = setting.get()
                except (TypeError, ValueError):
                    return False
                if json_safe(current) != json_safe(expected):
                    return False
            continue
        # Composition authority has its own operation journal and final-state
        # audit.  A Canvas session cannot promote composition operations.
        return False
    return True


def _canvas_observations(
    *,
    prereg_event: dict[str, Any],
    witness_event: dict[str, Any],
    completion_event: dict[str, Any],
    ledger_sha256: str,
) -> list[dict[str, Any]]:
    preregistration = _required_object(prereg_event["payload"], "preregistration")
    completion = _required_object(completion_event["payload"], "completion")
    expected = set(preregistration.get("expected_evidence") or [])
    checks = _required_object(completion.get("evidence_checks"), "evidence checks")
    if "ai_operation" not in expected or checks.get("ai_operation") is not True:
        return []
    witness = _required_object(witness_event["payload"], "witness")
    entries, journal_evidence = _verified_journal_segment(
        preregistration,
        witness,
    )
    authority = _required_object(witness.get("authority"), "witness authority")
    project_root = Path(
        _required_text(
            _required_object(preregistration.get("project"), "project").get(
                "root"
            ),
            "project root",
        )
    )
    session_path = _within(
        project_root,
        Path(
            _required_text(
                authority.get("canvas_session"),
                "CanvasSession path",
            )
        ),
        "CanvasSession",
    )
    session, session_sha256 = _stable_load(
        session_path,
        "CanvasSession",
        load_canvas_session,
    )
    if session_sha256 != _required_hash(
        authority.get("canvas_session_sha256"),
        "CanvasSession sha256",
    ):
        raise ValueError("CanvasSession changed after session completion.")
    document_path = _within(
        project_root,
        Path(_required_text(authority.get("document"), "Canvas document path")),
        "Canvas document",
    )
    final_document, document_sha256 = _stable_load(
        document_path,
        "Canvas document",
        _load_veusz_document,
    )
    if document_sha256 != _required_hash(
        authority.get("document_sha256"),
        "Canvas document sha256",
    ):
        raise ValueError("Canvas document changed after session completion.")
    completion_authority = _required_object(
        completion.get("authority"),
        "completion authority",
    )
    if (
        session.document_sha256 != document_sha256
        or session.state != "ready"
        or not (
            session.revision
            == session.saved_revision
            == session.exported_revision
        )
        or session.qa_summary.get("status") != "passed"
        or session.qa_summary.get("ready_to_use") is not True
        or completion_authority.get("document_sha256") != document_sha256
        or completion_authority.get("revision") != session.revision
    ):
        raise ValueError(
            "Canvas promotion authority is no longer exact-current and ready."
        )
    provider = preregistration.get("provider")
    observations: list[dict[str, Any]] = []
    for commit_index, commit in enumerate(entries):
        if commit.get("event") != "assistant_transaction_committed":
            continue
        transaction_id = str(commit.get("transaction_id") or "")
        transaction = commit.get("transaction")
        transaction = transaction if isinstance(transaction, dict) else {}
        verification = commit.get("verification")
        verification = verification if isinstance(verification, dict) else {}
        if (
            not transaction_id
            or commit.get("provider") != provider
            or transaction.get("status") != "committed"
            or transaction.get("transaction_id") != transaction_id
            or verification.get("structural_qa_passed") is not True
            or verification.get("canonical_vsz_unchanged_before_save") is not True
            or verification.get("raw_inputs_mutated") is not False
        ):
            continue
        accepted = transaction.get("accepted_batch_ids")
        accepted = accepted if isinstance(accepted, list) else []
        undone = set(transaction.get("undone_batch_ids") or [])
        rejected = set(transaction.get("rejected_batch_ids") or [])
        for batch_id in accepted:
            if batch_id in undone or batch_id in rejected:
                continue
            applied_matches = [
                (index, entry)
                for index, entry in enumerate(entries[:commit_index])
                if entry.get("event") == "assistant_batch_applied"
                and entry.get("transaction_id") == transaction_id
                and isinstance(entry.get("batch"), dict)
                and entry["batch"].get("batch_id") == batch_id
            ]
            if len(applied_matches) != 1:
                continue
            if _batch_was_later_reversed(
                entries,
                commit_index=commit_index,
                transaction_id=transaction_id,
                batch_id=str(batch_id),
            ):
                continue
            applied_index, applied = applied_matches[0]
            applied_verification = applied.get("verification")
            applied_verification = (
                applied_verification
                if isinstance(applied_verification, dict)
                else {}
            )
            if (
                applied_verification.get("target_resolution") != "passed"
                or applied_verification.get("atomic_batch") is not True
                or applied_verification.get("live_render_changed") is not True
                or applied_verification.get("recovery_snapshot_verified")
                is not True
            ):
                continue
            batch_payload = _required_object(
                applied.get("batch"),
                "applied CanvasOperationBatch",
            )
            if _batch_was_later_superseded(
                entries,
                applied_index=applied_index,
                batch_payload=batch_payload,
            ):
                continue
            if not _batch_matches_final_document(
                document=final_document,
                batch_payload=batch_payload,
                applied_entry=applied,
            ):
                continue
            decision = canonicalize_canvas_batch(
                batch_payload,
                session=session,
            )
            evidence, eligible = _session_base_evidence(
                prereg_event,
                witness_event,
                completion_event,
                ledger_sha256=ledger_sha256,
            )
            evidence.update(journal_evidence)
            evidence["applied_event_sha256"] = canonical_sha256(applied)
            evidence["commit_event_sha256"] = canonical_sha256(commit)
            evidence["applied_event_index"] = applied_index
            evidence["commit_event_index"] = commit_index
            observations.append(
                _observation(
                    decision=decision,
                    evidence=evidence,
                    artifact_sha256=canonical_sha256(batch_payload),
                    eligible=eligible,
                )
            )
    return observations


def _collect_payload(ledger_paths: Iterable[Path]) -> dict[str, Any]:
    resolved = sorted({Path(path).expanduser().resolve() for path in ledger_paths})
    if not resolved:
        raise ValueError("At least one session evidence ledger is required.")
    source_ledgers: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    seen_observations: set[str] = set()
    for ledger_path in resolved:
        snapshot = verified_session_evidence_snapshot(ledger_path)
        ledger_sha256 = _required_hash(
            snapshot.get("ledger_sha256"),
            "ledger_sha256",
        )
        source_ledgers.append(
            {
                "path": str(ledger_path),
                "sha256": ledger_sha256,
                "event_count": snapshot["event_count"],
                "last_event_sha256": snapshot["last_event_sha256"],
            }
        )
        records = _session_records(snapshot["events"])
        for session_id, record in sorted(records.items()):
            if not {"preregistration", "witness", "completion"} <= set(record):
                exclusions.append(
                    {
                        "ledger_sha256": ledger_sha256,
                        "session_id": session_id,
                        "reason_code": "incomplete_session",
                    }
                )
                continue
            prereg_event = record["preregistration"]
            witness_event = record["witness"]
            completion_event = record["completion"]
            completion_payload = _required_object(
                completion_event.get("payload"),
                "completion payload",
            )
            if (
                completion_payload.get("outcome") != "pass"
                or completion_payload.get("failures")
            ):
                exclusions.append(
                    {
                        "ledger_sha256": ledger_sha256,
                        "session_id": session_id,
                        "reason_code": "session_not_passed",
                    }
                )
                continue
            preregistration = _required_object(
                prereg_event.get("payload"),
                "preregistration payload",
            )
            promotion_exclusion = _promotion_observation_exclusion_reason(
                preregistration
            )
            if promotion_exclusion is not None:
                exclusions.append(
                    {
                        "ledger_sha256": ledger_sha256,
                        "session_id": session_id,
                        "reason_code": promotion_exclusion,
                    }
                )
                continue
            session_observations: list[dict[str, Any]] = []
            try:
                mapping = _mapping_observation(
                    prereg_event=prereg_event,
                    witness_event=witness_event,
                    completion_event=completion_event,
                    ledger_sha256=ledger_sha256,
                )
                if mapping is not None:
                    session_observations.append(mapping)
                session_observations.extend(
                    _canvas_observations(
                        prereg_event=prereg_event,
                        witness_event=witness_event,
                        completion_event=completion_event,
                        ledger_sha256=ledger_sha256,
                    )
                )
            except Exception as exc:
                raise ValueError(
                    "Promotion evidence replay failed for "
                    f"{session_id!r} in {ledger_path}: "
                    f"{type(exc).__name__}: {exc}"
                ) from exc
            if not session_observations:
                exclusions.append(
                    {
                        "ledger_sha256": ledger_sha256,
                        "session_id": session_id,
                        "reason_code": "no_eligible_committed_decision",
                    }
                )
            for observation in session_observations:
                observation_id = str(observation["observation_id"])
                if observation_id not in seen_observations:
                    seen_observations.add(observation_id)
                    observations.append(observation)
    observations.sort(key=lambda value: value["observation_id"])
    exclusions.sort(
        key=lambda value: (
            value["ledger_sha256"],
            value["session_id"],
            value["reason_code"],
        )
    )
    eligible_count = sum(
        item["eligible_for_threshold"] is True for item in observations
    )
    return {
        "kind": PROMOTION_COLLECTION_KIND,
        "version": PROMOTION_ARTIFACT_VERSION,
        "generated_at": _now(),
        "status": "passed",
        "source_ledgers": source_ledgers,
        "observations": observations,
        "exclusions": exclusions,
        "summary": {
            "ledger_count": len(source_ledgers),
            "observation_count": len(observations),
            "eligible_real_observation_count": eligible_count,
            "synthetic_or_nonqualifying_observation_count": (
                len(observations) - eligible_count
            ),
            "excluded_session_count": len(exclusions),
        },
        "runtime_effect": False,
        "limitations": [
            "Local ledger and owner identity proofs are hash-bound attestations, not signed remote identities.",
            "A collected observation is evidence for review, never executable policy.",
            "Synthetic and non-formal observations may be visible for diagnostics but never count toward the review threshold.",
        ],
    }


def collect_promotion_observations(
    ledger_paths: Iterable[Path],
    *,
    output_path: Path | None = None,
) -> dict[str, Any]:
    payload = _bind_artifact(
        _collect_payload(ledger_paths),
        hash_field="collection_sha256",
    )
    if output_path is not None:
        _write_artifact(output_path, payload)
    return payload


def _validate_collection(
    collection_path: Path,
    *,
    replay: bool,
) -> dict[str, Any]:
    path = collection_path.expanduser().resolve()
    collection = _validate_bound_artifact(
        _read_json(path, "promotion collection"),
        kind=PROMOTION_COLLECTION_KIND,
        hash_field="collection_sha256",
        label="promotion collection",
    )
    if replay:
        source_ledgers = _required_list(
            collection.get("source_ledgers"),
            "source_ledgers",
        )
        paths = [
            Path(
                _required_text(
                    _required_object(item, "source ledger").get("path"),
                    "source ledger path",
                )
            )
            for item in source_ledgers
        ]
        replayed = _collect_payload(paths)
        for field in (
            "source_ledgers",
            "observations",
            "exclusions",
            "summary",
            "runtime_effect",
        ):
            if replayed[field] != collection.get(field):
                raise ValueError(
                    f"Promotion collection replay changed field {field!r}."
                )
    return collection


def _candidate_rows(
    observations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for observation in observations:
        decision_sha256 = _required_hash(
            observation.get("canonical_decision_sha256"),
            "canonical_decision_sha256",
        )
        if canonical_sha256(observation.get("canonical_decision")) != (
            decision_sha256
        ):
            raise ValueError("Observation canonical decision hash is stale.")
        grouped[decision_sha256].append(observation)
    candidates: list[dict[str, Any]] = []
    for decision_sha256, group in sorted(grouped.items()):
        eligible = [
            item for item in group if item.get("eligible_for_threshold") is True
        ]
        owner_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in eligible:
            owner_hash = _required_hash(
                item["evidence"].get("owner_attestation_sha256"),
                "observation owner_attestation_sha256",
            )
            owner_groups[owner_hash].append(item)
        owner_thresholds: list[dict[str, Any]] = []
        for owner_hash, owner_group in sorted(owner_groups.items()):
            owner_sessions = {
                (
                    item["evidence"]["ledger_sha256"],
                    item["evidence"]["session_id"],
                )
                for item in owner_group
            }
            owner_tasks = {
                item["evidence"]["task_fingerprint"] for item in owner_group
            }
            owner_thresholds.append(
                {
                    "owner_attestation_sha256": owner_hash,
                    "distinct_real_session_count": len(owner_sessions),
                    "distinct_task_fingerprint_count": len(owner_tasks),
                    "threshold_count": min(
                        len(owner_sessions),
                        len(owner_tasks),
                    ),
                }
            )
        session_keys = {
            (
                item["evidence"]["ledger_sha256"],
                item["evidence"]["session_id"],
            )
            for item in eligible
        }
        task_fingerprints = {
            item["evidence"]["task_fingerprint"] for item in eligible
        }
        distinct_count = max(
            (item["threshold_count"] for item in owner_thresholds),
            default=0,
        )
        ready = distinct_count >= PROMOTION_THRESHOLD
        ready_owners = sorted(
            item["owner_attestation_sha256"]
            for item in owner_thresholds
            if item["threshold_count"] >= PROMOTION_THRESHOLD
        )
        candidates.append(
            {
                "candidate_id": decision_sha256,
                "decision_kind": group[0]["decision_kind"],
                "canonical_decision": group[0]["canonical_decision"],
                "canonical_decision_sha256": decision_sha256,
                "state": "ready_for_review" if ready else "observed",
                "threshold": PROMOTION_THRESHOLD,
                "distinct_real_session_count": len(session_keys),
                "distinct_task_fingerprint_count": len(task_fingerprints),
                "threshold_count": distinct_count,
                "owner_thresholds": owner_thresholds,
                "ready_owner_attestation_sha256s": ready_owners,
                "observation_ids": sorted(
                    item["observation_id"] for item in group
                ),
                "eligible_observation_ids": sorted(
                    item["observation_id"] for item in eligible
                ),
                "source_lanes": sorted(
                    {item["evidence"]["lane"] for item in eligible}
                ),
                "runtime_effect": False,
            }
        )
    return candidates


def build_promotion_candidates(
    collection_path: Path,
    *,
    output_path: Path | None = None,
) -> dict[str, Any]:
    resolved_collection = collection_path.expanduser().resolve()
    collection, collection_file_sha256 = _stable_load(
        resolved_collection,
        "promotion collection",
        lambda path: _validate_collection(path, replay=True),
    )
    observations = _required_list(
        collection.get("observations"),
        "promotion observations",
    )
    candidates = _candidate_rows(
        [_required_object(item, "promotion observation") for item in observations]
    )
    ready_count = sum(
        item["state"] == "ready_for_review" for item in candidates
    )
    payload = _bind_artifact(
        {
            "kind": PROMOTION_CANDIDATE_SET_KIND,
            "version": PROMOTION_ARTIFACT_VERSION,
            "generated_at": _now(),
            "status": "passed",
            "collection": {
                "path": str(resolved_collection),
                "file_sha256": collection_file_sha256,
                "collection_sha256": collection["collection_sha256"],
            },
            "candidates": candidates,
            "summary": {
                "candidate_count": len(candidates),
                "ready_for_review_count": ready_count,
                "observed_only_count": len(candidates) - ready_count,
            },
            "runtime_effect": False,
            "limitations": [
                "ready_for_review authorizes review only; it does not modify deterministic behavior.",
                "At least three distinct real sessions and task fingerprints are required.",
                "Candidate files are never read by plotting, readiness, rule, policy, or envelope execution paths.",
            ],
        },
        hash_field="candidate_set_sha256",
    )
    if output_path is not None:
        _write_artifact(output_path, payload)
    return payload


def _validate_candidate_set(
    candidate_set_path: Path,
) -> dict[str, Any]:
    path = candidate_set_path.expanduser().resolve()
    candidate_set = _validate_bound_artifact(
        _read_json(path, "promotion candidate set"),
        kind=PROMOTION_CANDIDATE_SET_KIND,
        hash_field="candidate_set_sha256",
        label="promotion candidate set",
    )
    collection_ref = _required_object(
        candidate_set.get("collection"),
        "candidate collection reference",
    )
    collection_path = Path(
        _required_text(collection_ref.get("path"), "collection path")
    )
    collection, collection_file_sha256 = _stable_load(
        collection_path,
        "candidate source collection",
        lambda source: _validate_collection(source, replay=True),
    )
    if collection_file_sha256 != _required_hash(
        collection_ref.get("file_sha256"),
        "collection file_sha256",
    ):
        raise ValueError("Candidate source collection file changed.")
    if collection["collection_sha256"] != _required_hash(
        collection_ref.get("collection_sha256"),
        "collection_sha256",
    ):
        raise ValueError("Candidate source collection identity changed.")
    expected = _candidate_rows(collection["observations"])
    if expected != candidate_set.get("candidates"):
        raise ValueError("Candidate set no longer reproduces from its collection.")
    return candidate_set


def _timestamp(value: object, label: str) -> str:
    text = _required_text(value, label, maximum=80)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO-8601 timestamp.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must include a timezone offset.")
    return text


def _decision_state(decision: str) -> str:
    return {
        "approve": "approved_for_implementation",
        "reject": "rejected_by_owner",
        "defer": "deferred_by_owner",
    }[decision]


def _load_owner_decision_receipt(
    path: Path,
    *,
    trust_registry_path: Path | None = None,
) -> dict[str, Any]:
    receipt = _read_json(path, "owner decision receipt")
    _reject_unknown(
        receipt,
        {
            "kind",
            "version",
            "candidate_id",
            "candidate_set_sha256",
            "decision",
            "owner",
            "owner_key_id",
            "signature_algorithm",
            "signature",
            "rationale",
            "owner_attested",
            "attestation",
            "implementation_contract",
            "recorded_at",
        },
        label="owner decision receipt",
    )
    if (
        receipt.get("kind") != PROMOTION_DECISION_RECEIPT_KIND
        or receipt.get("version") != PROMOTION_ARTIFACT_VERSION
    ):
        raise ValueError("Unsupported owner decision receipt.")
    _required_hash(receipt.get("candidate_id"), "receipt candidate_id")
    _required_hash(
        receipt.get("candidate_set_sha256"),
        "receipt candidate_set_sha256",
    )
    decision = _required_text(receipt.get("decision"), "owner decision")
    if decision not in OWNER_DECISIONS:
        raise ValueError(f"Owner decision must be one of {sorted(OWNER_DECISIONS)}.")
    _required_text(receipt.get("owner"), "receipt owner", maximum=200)
    _required_text(receipt.get("rationale"), "receipt rationale")
    if _required_bool(
        receipt.get("owner_attested"),
        "receipt owner_attested",
    ) is not True:
        raise ValueError("Owner decision receipt requires owner_attested=true.")
    if receipt.get("attestation") != OWNER_DECISION_ATTESTATION:
        raise ValueError("Owner decision receipt attestation text is invalid.")
    implementation_contract = receipt.get("implementation_contract")
    if decision == "approve":
        receipt["implementation_contract"] = _validate_implementation_contract(
            implementation_contract
        )
        if (
            receipt["implementation_contract"]["candidate_id"]
            != receipt["candidate_id"]
        ):
            raise ValueError(
                "Implementation contract is bound to another candidate."
            )
    elif implementation_contract is not None:
        raise ValueError(
            "Reject and defer receipts cannot pre-authorize an implementation."
        )
    _timestamp(receipt.get("recorded_at"), "receipt recorded_at")
    receipt["verified_owner_authority"] = _verify_owner_authority(
        receipt,
        trust_registry_path=trust_registry_path,
    )
    return receipt


def _decide_promotion_candidate(
    candidate_set_path: Path,
    receipt_path: Path,
    *,
    output_path: Path | None = None,
    trust_registry_path: Path | None,
) -> dict[str, Any]:
    resolved_candidates = candidate_set_path.expanduser().resolve()
    resolved_receipt = receipt_path.expanduser().resolve()
    candidate_set, candidate_set_file_sha256 = _stable_load(
        resolved_candidates,
        "promotion candidate set",
        _validate_candidate_set,
    )
    receipt, receipt_file_sha256 = _stable_load(
        resolved_receipt,
        "owner decision receipt",
        lambda path: _load_owner_decision_receipt(
            path,
            trust_registry_path=trust_registry_path,
        ),
    )
    if receipt["candidate_set_sha256"] != candidate_set["candidate_set_sha256"]:
        raise ValueError("Owner receipt names another candidate set.")
    matches = [
        item
        for item in candidate_set["candidates"]
        if item["candidate_id"] == receipt["candidate_id"]
    ]
    if len(matches) != 1:
        raise ValueError("Owner receipt candidate is absent or ambiguous.")
    candidate = matches[0]
    if (
        receipt["decision"] == "approve"
        and candidate["state"] != "ready_for_review"
    ):
        raise ValueError(
            "Only a three-real-session ready_for_review candidate can be approved."
        )
    owner_hash = _owner_attestation_sha256(receipt["owner"])
    if receipt["decision"] == "approve" and owner_hash not in set(
        candidate.get("ready_owner_attestation_sha256s") or []
    ):
        raise ValueError(
            "Approval signer does not own three qualifying candidate observations."
        )
    implementation_contract = receipt.get("implementation_contract")
    if receipt["decision"] == "approve":
        implementation_contract = _validate_candidate_specific_contract(
            implementation_contract,
            candidate,
        )
        receipt["implementation_contract"] = implementation_contract
        contract_lanes = set(implementation_contract["lifecycle_lanes"])
        candidate_lanes = set(candidate.get("source_lanes") or [])
        if not contract_lanes <= candidate_lanes:
            raise ValueError(
                "Implementation lifecycle lanes must come from candidate evidence."
            )
    state = _decision_state(receipt["decision"])
    authority = _required_object(
        receipt.get("verified_owner_authority"),
        "verified owner authority",
    )
    payload = _bind_artifact(
        {
            "kind": PROMOTION_DECISION_KIND,
            "version": PROMOTION_ARTIFACT_VERSION,
            "recorded_at": _now(),
            "status": "passed",
            "state": state,
            "candidate_set": {
                "path": str(resolved_candidates),
                "file_sha256": candidate_set_file_sha256,
                "candidate_set_sha256": candidate_set[
                    "candidate_set_sha256"
                ],
            },
            "candidate": candidate,
            "owner_receipt": {
                "path": str(resolved_receipt),
                "file_sha256": receipt_file_sha256,
                "decision": receipt["decision"],
                "owner": receipt["owner"],
                "rationale": receipt["rationale"],
                "owner_attested": True,
                "recorded_at": receipt["recorded_at"],
                "implementation_contract": implementation_contract,
                "owner_attestation_sha256": owner_hash,
                "owner_key_id": authority["owner_key_id"],
                "trust_registry": authority["trust_registry"],
                "trust_registry_sha256": authority[
                    "trust_registry_sha256"
                ],
                "signature_algorithm": authority["signature_algorithm"],
                "signature_sha256": authority["signature_sha256"],
                "protected_registry": authority["protected_registry"],
            },
            "runtime_effect": False,
            "limitations": [
                "Approval requires a detached signature from the external trusted-owner registry.",
                "Approval authorizes an ordinary reviewed implementation attempt only.",
                "This decision artifact cannot edit source, rules, policy, envelopes, or candidate state.",
            ],
        },
        hash_field="decision_sha256",
    )
    if output_path is not None:
        _write_artifact(output_path, payload)
    return payload


def decide_promotion_candidate(
    candidate_set_path: Path,
    receipt_path: Path,
    *,
    output_path: Path | None = None,
) -> dict[str, Any]:
    return _decide_promotion_candidate(
        candidate_set_path,
        receipt_path,
        output_path=output_path,
        trust_registry_path=None,
    )


def _validate_decision_state_binding(
    decision: dict[str, Any],
    *,
    receipt: dict[str, Any],
    candidate: dict[str, Any],
) -> None:
    expected_state = _decision_state(receipt["decision"])
    owner_hash = _owner_attestation_sha256(receipt["owner"])
    if decision.get("state") != expected_state:
        raise ValueError("Promotion decision state does not match its signed receipt.")
    if receipt["decision"] == "approve":
        if (
            candidate.get("state") != "ready_for_review"
            or owner_hash
            not in set(
                candidate.get("ready_owner_attestation_sha256s") or []
            )
        ):
            raise ValueError("Approved decision is no longer owner-eligible.")
        contract = _required_object(
            receipt.get("implementation_contract"),
            "implementation_contract",
        )
        _validate_candidate_specific_contract(contract, candidate)
        if not set(contract["lifecycle_lanes"]) <= set(
            candidate.get("source_lanes") or []
        ):
            raise ValueError("Approved lifecycle scope escaped candidate evidence.")


def _validate_decision(
    decision_path: Path,
    *,
    trust_registry_path: Path | None = None,
) -> dict[str, Any]:
    path = decision_path.expanduser().resolve()
    decision = _validate_bound_artifact(
        _read_json(path, "promotion decision"),
        kind=PROMOTION_DECISION_KIND,
        hash_field="decision_sha256",
        label="promotion decision",
    )
    candidate_set_ref = _required_object(
        decision.get("candidate_set"),
        "candidate set reference",
    )
    candidate_set_path = Path(
        _required_text(candidate_set_ref.get("path"), "candidate set path")
    )
    candidate_set, candidate_set_file_sha256 = _stable_load(
        candidate_set_path,
        "decision candidate set",
        _validate_candidate_set,
    )
    if candidate_set_file_sha256 != _required_hash(
        candidate_set_ref.get("file_sha256"),
        "candidate set file_sha256",
    ):
        raise ValueError("Decision candidate set file changed.")
    if candidate_set["candidate_set_sha256"] != _required_hash(
        candidate_set_ref.get("candidate_set_sha256"),
        "candidate_set_sha256",
    ):
        raise ValueError("Decision candidate set identity changed.")
    candidate = _required_object(decision.get("candidate"), "decision candidate")
    matches = [
        item
        for item in candidate_set["candidates"]
        if item["candidate_id"] == candidate.get("candidate_id")
    ]
    if matches != [candidate]:
        raise ValueError("Decision candidate snapshot changed.")
    receipt_ref = _required_object(
        decision.get("owner_receipt"),
        "owner receipt reference",
    )
    receipt_path = Path(
        _required_text(receipt_ref.get("path"), "owner receipt path")
    )
    receipt, receipt_file_sha256 = _stable_load(
        receipt_path,
        "owner decision receipt",
        lambda path: _load_owner_decision_receipt(
            path,
            trust_registry_path=trust_registry_path,
        ),
    )
    if receipt_file_sha256 != _required_hash(
        receipt_ref.get("file_sha256"),
        "owner receipt file_sha256",
    ):
        raise ValueError("Owner decision receipt file changed.")
    authority = _required_object(
        receipt.get("verified_owner_authority"),
        "verified owner authority",
    )
    owner_hash = _owner_attestation_sha256(receipt["owner"])
    if (
        receipt["candidate_id"] != candidate["candidate_id"]
        or receipt["candidate_set_sha256"]
        != candidate_set["candidate_set_sha256"]
        or receipt["decision"] != receipt_ref.get("decision")
        or receipt["owner"] != receipt_ref.get("owner")
        or receipt["rationale"] != receipt_ref.get("rationale")
        or receipt["recorded_at"] != receipt_ref.get("recorded_at")
        or receipt.get("implementation_contract")
        != receipt_ref.get("implementation_contract")
        or owner_hash != receipt_ref.get("owner_attestation_sha256")
        or authority["owner_key_id"] != receipt_ref.get("owner_key_id")
        or authority["trust_registry"] != receipt_ref.get("trust_registry")
        or authority["trust_registry_sha256"]
        != receipt_ref.get("trust_registry_sha256")
        or authority["signature_algorithm"]
        != receipt_ref.get("signature_algorithm")
        or authority["signature_sha256"]
        != receipt_ref.get("signature_sha256")
        or authority["protected_registry"]
        != receipt_ref.get("protected_registry")
    ):
        raise ValueError("Owner decision receipt binding changed.")
    _validate_decision_state_binding(
        decision,
        receipt=receipt,
        candidate=candidate,
    )
    return decision


def _trusted_git_executable() -> Path:
    for candidate in (Path("/usr/bin/git"), Path("/bin/git")):
        try:
            metadata = candidate.lstat()
        except FileNotFoundError:
            continue
        if (
            candidate.is_symlink()
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != 0
            or metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
        ):
            continue
        return candidate
    raise ValueError(
        "Promotion verification requires a root-owned, non-writable Git "
        "executable at /usr/bin/git or /bin/git."
    )


def _git_environment() -> dict[str, str]:
    return {
        "PATH": "/usr/bin:/bin",
        "HOME": str(_account_home()),
        "LANG": "C",
        "LC_ALL": "C",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_TERMINAL_PROMPT": "0",
    }


def _repository_git_dir(repo_root: Path) -> tuple[Path, Path]:
    repo = repo_root.expanduser().resolve()
    marker = repo / ".git"
    if marker.is_symlink():
        raise ValueError("Git metadata marker cannot be a symlink.")
    if marker.is_dir():
        git_dir = marker.resolve()
    elif marker.is_file():
        _target, data, _digest = _read_file_snapshot(
            marker,
            "Git worktree marker",
        )
        try:
            text = data.decode("utf-8").strip()
        except UnicodeDecodeError as exc:
            raise ValueError("Git worktree marker is not UTF-8.") from exc
        prefix = "gitdir:"
        if not text.casefold().startswith(prefix):
            raise ValueError("Git worktree marker does not name gitdir.")
        raw_git_dir = text[len(prefix) :].strip()
        if not raw_git_dir:
            raise ValueError("Git worktree marker has an empty gitdir.")
        candidate = Path(raw_git_dir)
        git_dir = (
            candidate
            if candidate.is_absolute()
            else marker.parent / candidate
        ).resolve()
    else:
        raise ValueError(f"Not a Git checkout: {repo}")
    if not git_dir.is_dir() or git_dir.is_symlink():
        raise ValueError("Git metadata directory is absent or unsafe.")
    return repo, git_dir


def _run_git(
    repo_root: Path,
    *args: str,
    check: bool = True,
    text: bool = True,
) -> subprocess.CompletedProcess[Any]:
    repo, git_dir = _repository_git_dir(repo_root)
    command = [
        str(_trusted_git_executable()),
        f"--git-dir={git_dir}",
        f"--work-tree={repo}",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.hooksPath=/dev/null",
        "-c",
        "diff.external=",
        *args,
    ]
    result = subprocess.run(
        command,
        cwd=repo,
        env=_git_environment(),
        check=False,
        capture_output=True,
        text=text,
    )
    if check and result.returncode != 0:
        stderr = result.stderr
        stdout = result.stdout
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        detail = (stderr or stdout or "").strip()
        raise ValueError(f"Git {' '.join(args)} failed: {detail}")
    return result


def _git(
    repo_root: Path,
    *args: str,
    check: bool = True,
) -> str:
    result = _run_git(repo_root, *args, check=check)
    return str(result.stdout).strip()


def _tracked_worktree_snapshot(
    repo_root: Path,
    expected_commit: str,
) -> list[dict[str, Any]]:
    repo = repo_root.expanduser().resolve()
    object_format = _git(
        repo,
        "rev-parse",
        "--show-object-format",
    )
    if object_format not in {"sha1", "sha256"}:
        raise ValueError(f"Unsupported Git object format: {object_format!r}")
    tree_result = _run_git(
        repo,
        "ls-tree",
        "-r",
        "-z",
        expected_commit,
        text=False,
    )
    tree_records: list[tuple[str, str, str]] = []
    for raw_record in bytes(tree_result.stdout).split(b"\0"):
        if not raw_record:
            continue
        metadata, separator, raw_path = raw_record.partition(b"\t")
        if not separator:
            raise ValueError("Git tree emitted a malformed tracked-file record.")
        try:
            mode, object_type, object_id = metadata.decode("ascii").split()
            relative = raw_path.decode("utf-8")
        except (UnicodeDecodeError, ValueError) as exc:
            raise ValueError(
                "Git tree contains an unsupported tracked-file record."
            ) from exc
        relative = _safe_repo_path(relative, "tracked Git path")
        if object_type != "blob" or mode not in {"100644", "100755"}:
            raise ValueError(
                "Promotion verification supports only regular tracked files."
            )
        tree_records.append((relative, mode, object_id))
    if not tree_records:
        raise ValueError("Reviewed Git commit has no tracked files.")
    tracked_paths = [record[0] for record in tree_records]
    if tracked_paths != sorted(set(tracked_paths)):
        raise ValueError("Reviewed Git tree paths are not unique and sorted.")

    index_result = _run_git(repo, "ls-files", "-v", "-z", text=False)
    index_paths: list[str] = []
    unsafe_flags: list[str] = []
    for raw_record in bytes(index_result.stdout).split(b"\0"):
        if not raw_record:
            continue
        tag, separator, raw_path = raw_record.partition(b" ")
        if not separator or len(tag) != 1:
            raise ValueError("Git index emitted a malformed tracked-file record.")
        try:
            relative = _safe_repo_path(
                raw_path.decode("utf-8"),
                "indexed Git path",
            )
        except UnicodeDecodeError as exc:
            raise ValueError(
                "Git index contains a non-UTF-8 tracked path."
            ) from exc
        index_paths.append(relative)
        if tag != b"H":
            unsafe_flags.append(f"{tag.decode('ascii', errors='replace')} {relative}")
    if unsafe_flags:
        raise ValueError(
            "Promotion verification rejects assume-unchanged, skip-worktree, "
            f"or non-normal index flags: {unsafe_flags!r}"
        )
    if sorted(index_paths) != tracked_paths:
        raise ValueError(
            "Git index paths differ from the exact reviewed commit."
        )

    snapshot: list[dict[str, Any]] = []
    for relative, mode, expected_object_id in tree_records:
        target = repo / relative
        cursor = repo
        for part in Path(relative).parts:
            cursor = cursor / part
            try:
                metadata = cursor.lstat()
            except FileNotFoundError as exc:
                raise ValueError(
                    f"Tracked worktree file is absent: {relative}"
                ) from exc
            if stat.S_ISLNK(metadata.st_mode):
                raise ValueError(
                    f"Tracked worktree path contains a symlink: {relative}"
                )
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError(
                f"Tracked worktree path is not a regular file: {relative}"
            )
        _path, data, sha256 = _read_file_snapshot(
            target,
            f"tracked worktree file {relative}",
        )
        object_hasher = hashlib.new(object_format)
        object_hasher.update(f"blob {len(data)}\0".encode("ascii"))
        object_hasher.update(data)
        if object_hasher.hexdigest() != expected_object_id:
            raise ValueError(
                "Tracked worktree bytes differ from the reviewed commit: "
                f"{relative}"
            )
        executable = bool(metadata.st_mode & 0o111)
        if executable != (mode == "100755"):
            raise ValueError(
                "Tracked worktree executable mode differs from the reviewed "
                f"commit: {relative}"
            )
        snapshot.append(
            {
                "path": relative,
                "mode": mode,
                "object_id": expected_object_id,
                "sha256": sha256,
                "device": metadata.st_dev,
                "inode": metadata.st_ino,
                "size": metadata.st_size,
                "mtime_ns": metadata.st_mtime_ns,
                "ctime_ns": metadata.st_ctime_ns,
            }
        )
    return snapshot


def _clean_git_state(
    repo_root: Path,
    *,
    expected_commit: str | None = None,
) -> dict[str, Any]:
    repo, git_dir = _repository_git_dir(repo_root)
    commit_before = _git(repo, "rev-parse", "HEAD")
    if _GIT_COMMIT.fullmatch(commit_before) is None:
        raise ValueError("Promotion verification requires a full Git commit.")
    if expected_commit is not None and commit_before != expected_commit:
        raise ValueError("Git HEAD differs from the expected reviewed commit.")
    status_before = _git(
        repo,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
    )
    if status_before:
        raise ValueError(
            "Promotion planning and verification require a clean worktree."
        )
    tracked_before = _tracked_worktree_snapshot(repo, commit_before)
    tracked_after = _tracked_worktree_snapshot(repo, commit_before)
    status_after = _git(
        repo,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
    )
    commit_after = _git(repo, "rev-parse", "HEAD")
    if (
        status_after
        or commit_after != commit_before
        or tracked_after != tracked_before
    ):
        raise ValueError(
            "Git checkout changed during exact-clean verification."
        )
    return {
        "repo": str(repo),
        "git_dir": str(git_dir),
        "git_executable": str(_trusted_git_executable()),
        "commit": commit_before,
        "branch": _git(repo, "branch", "--show-current"),
        "worktree_clean": True,
        "status_sha256": canonical_sha256([]),
        "tracked_files_sha256": canonical_sha256(tracked_before),
        "tracked_file_count": len(tracked_before),
        "index_flags": "normal_only",
    }


def plan_promotion_implementation(
    decision_path: Path,
    *,
    repo_root: Path,
    output_path: Path | None = None,
) -> dict[str, Any]:
    resolved_decision = decision_path.expanduser().resolve()
    decision, decision_file_sha256 = _stable_load(
        resolved_decision,
        "promotion decision",
        _validate_decision,
    )
    if decision.get("state") != "approved_for_implementation":
        raise ValueError("Only an owner-approved candidate can be planned.")
    git_state = _clean_git_state(repo_root)
    candidate = _required_object(decision.get("candidate"), "candidate")
    owner_receipt = _required_object(
        decision.get("owner_receipt"),
        "owner receipt",
    )
    implementation_contract = _validate_candidate_specific_contract(
        owner_receipt.get("implementation_contract"),
        candidate,
    )
    payload = _bind_artifact(
        {
            "kind": PROMOTION_PLAN_KIND,
            "version": PROMOTION_ARTIFACT_VERSION,
            "created_at": _now(),
            "status": "passed",
            "state": "awaiting_reviewed_source_change",
            "decision": {
                "path": str(resolved_decision),
                "file_sha256": decision_file_sha256,
                "decision_sha256": decision["decision_sha256"],
            },
            "candidate_id": candidate["candidate_id"],
            "canonical_decision_sha256": candidate[
                "canonical_decision_sha256"
            ],
            "decision_kind": candidate["decision_kind"],
            "implementation_contract": implementation_contract,
            "source_baseline": git_state,
            "required_gates": {
                "ordinary_reviewed_source_change": True,
                "changed_probe_or_fixture": True,
                "passing_probe_artifact": True,
                "provider_disabled_real_lifecycle": True,
                "same_frozen_commit_real_lifecycle": True,
                "owner_verification_receipt": True,
            },
            "forbidden_automatic_actions": [
                "edit_materials_rule",
                "edit_policy",
                "edit_validated_envelope",
                "change_candidate_state",
                "write_owner_receipt",
                "write_verification_receipt",
            ],
            "runtime_effect": False,
            "limitations": [
                "The plan names gates, not a source patch or executable instruction.",
                "Source implementation must use the ordinary review and Git path.",
                "The candidate remains powerless even after verification; behavior comes only from reviewed source.",
            ],
        },
        hash_field="plan_sha256",
    )
    if output_path is not None:
        _write_artifact(output_path, payload)
    return payload


def _load_plan_decision_snapshot(
    plan: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    decision_ref = _required_object(plan.get("decision"), "plan decision")
    decision_path = Path(
        _required_text(decision_ref.get("path"), "decision path")
    )
    decision, decision_file_sha256 = _stable_load(
        decision_path,
        "plan decision",
        _validate_decision,
    )
    if decision_file_sha256 != _required_hash(
        decision_ref.get("file_sha256"),
        "decision file_sha256",
    ):
        raise ValueError("Plan decision file changed.")
    if decision["decision_sha256"] != _required_hash(
        decision_ref.get("decision_sha256"),
        "decision_sha256",
    ):
        raise ValueError("Plan decision identity changed.")
    return decision, decision_file_sha256


def _validate_plan(plan_path: Path) -> dict[str, Any]:
    path = plan_path.expanduser().resolve()
    plan = _validate_bound_artifact(
        _read_json(path, "promotion implementation plan"),
        kind=PROMOTION_PLAN_KIND,
        hash_field="plan_sha256",
        label="promotion implementation plan",
    )
    decision, _decision_file_sha256 = _load_plan_decision_snapshot(plan)
    decision_contract = _validate_candidate_specific_contract(
        _required_object(
            decision.get("owner_receipt"),
            "decision owner receipt",
        ).get("implementation_contract"),
        _required_object(decision.get("candidate"), "decision candidate"),
    )
    if (
        decision.get("state") != "approved_for_implementation"
        or decision["candidate"]["candidate_id"] != plan.get("candidate_id")
        or decision["candidate"]["canonical_decision_sha256"]
        != plan.get("canonical_decision_sha256")
        or decision_contract != plan.get("implementation_contract")
        or plan.get("state") != "awaiting_reviewed_source_change"
    ):
        raise ValueError("Plan decision binding changed.")
    return plan


def _load_verification_receipt(
    path: Path,
    *,
    trust_registry_path: Path | None = None,
) -> dict[str, Any]:
    receipt = _read_json(path, "promotion verification receipt")
    _reject_unknown(
        receipt,
        {
            "kind",
            "version",
            "plan_sha256",
            "candidate_id",
            "owner",
            "owner_key_id",
            "signature_algorithm",
            "signature",
            "reviewed_by",
            "rationale",
            "owner_attested",
            "attestation",
            "expected_commit",
            "probe_artifacts",
            "real_sessions",
            "recorded_at",
        },
        label="promotion verification receipt",
    )
    if (
        receipt.get("kind") != PROMOTION_VERIFICATION_RECEIPT_KIND
        or receipt.get("version") != PROMOTION_ARTIFACT_VERSION
    ):
        raise ValueError("Unsupported promotion verification receipt.")
    _required_hash(receipt.get("plan_sha256"), "receipt plan_sha256")
    _required_hash(receipt.get("candidate_id"), "receipt candidate_id")
    _required_text(receipt.get("owner"), "receipt owner", maximum=200)
    _required_text(receipt.get("reviewed_by"), "receipt reviewed_by", maximum=400)
    _required_text(receipt.get("rationale"), "receipt rationale")
    if receipt.get("owner_attested") is not True:
        raise ValueError("Verification receipt requires owner_attested=true.")
    if receipt.get("attestation") != VERIFICATION_ATTESTATION:
        raise ValueError("Verification receipt attestation text is invalid.")
    _required_text(
        receipt.get("expected_commit"),
        "receipt expected_commit",
        maximum=64,
    )
    if _GIT_COMMIT.fullmatch(str(receipt.get("expected_commit") or "")) is None:
        raise ValueError("receipt expected_commit must be a full Git commit.")
    probes = _required_list(receipt.get("probe_artifacts"), "probe_artifacts")
    sessions = _required_list(receipt.get("real_sessions"), "real_sessions")
    if not probes or not sessions:
        raise ValueError(
            "Verification receipt requires probes and real sessions."
        )
    for index, item in enumerate(probes):
        probe = _required_object(item, f"probe_artifacts[{index}]")
        _reject_unknown(
            probe,
            {"path", "sha256", "probe_file"},
            label=f"probe_artifacts[{index}]",
        )
        probe_path = _required_text(probe.get("path"), "probe path")
        if probe_path != str(Path(probe_path).expanduser().resolve()):
            raise ValueError(
                "Verification receipt probe-artifact paths must be canonical."
            )
        _required_hash(probe.get("sha256"), "probe sha256")
        _safe_repo_path(probe.get("probe_file"), "probe source file")
    for index, item in enumerate(sessions):
        session = _required_object(item, f"real_sessions[{index}]")
        _reject_unknown(
            session,
            {
                "ledger",
                "session_id",
                "ledger_prefix_size_bytes",
                "ledger_prefix_sha256",
                "preregistration_event_sha256",
                "witness_event_sha256",
                "completion_event_sha256",
                "authority_artifacts",
            },
            label=f"real_sessions[{index}]",
        )
        ledger_text = _required_text(session.get("ledger"), "real ledger")
        if ledger_text != str(Path(ledger_text).expanduser().resolve()):
            raise ValueError(
                "Verification receipt real-session ledger paths must be canonical."
            )
        _required_text(
            session.get("session_id"),
            "real session_id",
            maximum=100,
        )
        prefix_size = session.get("ledger_prefix_size_bytes")
        if type(prefix_size) is not int or prefix_size <= 0:
            raise ValueError(
                "real session ledger_prefix_size_bytes must be positive."
            )
        for field in (
            "ledger_prefix_sha256",
            "preregistration_event_sha256",
            "witness_event_sha256",
            "completion_event_sha256",
        ):
            _required_hash(
                session.get(field),
                f"real session {field}",
            )
        authority_artifacts: list[dict[str, Any]] = []
        for artifact_index, raw_artifact in enumerate(
            _required_list(
                session.get("authority_artifacts"),
                "real session authority_artifacts",
            )
        ):
            artifact = _required_object(
                raw_artifact,
                "real session authority artifact",
            )
            _reject_unknown(
                artifact,
                {"role", "path", "sha256", "prefix_size_bytes"},
                label=(
                    f"real_sessions[{index}]."
                    f"authority_artifacts[{artifact_index}]"
                ),
            )
            role = _required_text(
                artifact.get("role"),
                "authority artifact role",
                maximum=160,
            )
            path_text = _required_text(
                artifact.get("path"),
                "authority artifact path",
            )
            if path_text != str(Path(path_text).expanduser().resolve()):
                raise ValueError(
                    "Authority artifact paths must be canonical."
                )
            normalized: dict[str, Any] = {
                "role": role,
                "path": path_text,
                "sha256": _required_hash(
                    artifact.get("sha256"),
                    "authority artifact sha256",
                ),
            }
            artifact_prefix_size = artifact.get("prefix_size_bytes")
            if artifact_prefix_size is not None:
                if (
                    type(artifact_prefix_size) is not int
                    or artifact_prefix_size < 0
                ):
                    raise ValueError(
                        "Authority artifact prefix_size_bytes must be "
                        "non-negative."
                    )
                normalized["prefix_size_bytes"] = artifact_prefix_size
            authority_artifacts.append(normalized)
        if not authority_artifacts:
            raise ValueError(
                "Verification receipt requires signed authority artifacts."
            )
        if authority_artifacts != sorted(
            authority_artifacts,
            key=lambda value: (
                value["role"],
                value["path"],
                value["sha256"],
                int(value.get("prefix_size_bytes", -1)),
            ),
        ):
            raise ValueError(
                "Verification receipt authority artifacts must be sorted."
            )
    probe_identities = {
        (
            str(
                Path(
                    str(
                        _required_object(
                            item,
                            "probe artifact",
                        ).get("path")
                    )
                )
                .expanduser()
                .resolve()
            ),
            str(_required_object(item, "probe artifact").get("probe_file")),
        )
        for item in probes
    }
    if len(probe_identities) != len(probes):
        raise ValueError("Verification receipt repeats a probe artifact.")
    session_identities = {
        (
            str(
                Path(
                    str(
                        _required_object(
                            item,
                            "real session",
                        ).get("ledger")
                    )
                )
                .expanduser()
                .resolve()
            ),
            str(_required_object(item, "real session").get("session_id")),
        )
        for item in sessions
    }
    if len(session_identities) != len(sessions):
        raise ValueError("Verification receipt repeats a real session.")
    _timestamp(receipt.get("recorded_at"), "receipt recorded_at")
    receipt["verified_owner_authority"] = _verify_owner_authority(
        receipt,
        trust_registry_path=trust_registry_path,
    )
    return receipt


def _materialize_reviewed_source_snapshot(
    *,
    repo_root: Path,
    expected_commit: str,
    destination: Path,
) -> None:
    archive_path = destination.parent / "reviewed_source.tar"
    archived = _run_git(
        repo_root,
        "archive",
        "--format=tar",
        f"--output={archive_path}",
        expected_commit,
        "src",
        check=False,
    )
    if archived.returncode != 0:
        detail = (archived.stderr or archived.stdout).strip()
        raise ValueError(
            f"Could not materialize reviewed source commit: {detail}"
        )
    if archive_path.stat().st_size > 250_000_000:
        raise ValueError("Reviewed source archive exceeds the 250 MB limit.")
    destination.mkdir(mode=0o700)
    directories: list[Path] = [destination]
    files: list[Path] = []
    try:
        with tarfile.open(archive_path, mode="r:") as archive:
            for member in archive:
                relative = Path(member.name)
                if (
                    relative.is_absolute()
                    or not relative.parts
                    or any(part in {"", ".", ".."} for part in relative.parts)
                    or "\\" in member.name
                ):
                    raise ValueError(
                        "Reviewed source archive contains an unsafe path."
                    )
                target = destination.joinpath(*relative.parts)
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True, mode=0o700)
                    directories.append(target)
                    continue
                if not member.isfile():
                    raise ValueError(
                        "Reviewed source archive contains a link or special file."
                    )
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                extracted = archive.extractfile(member)
                if extracted is None:
                    raise ValueError(
                        "Reviewed source archive member could not be read."
                    )
                data = extracted.read()
                if len(data) != member.size:
                    raise ValueError(
                        "Reviewed source archive member was truncated."
                    )
                with target.open("xb") as handle:
                    handle.write(data)
                    handle.flush()
                    os.fsync(handle.fileno())
                files.append(target)
    finally:
        archive_path.unlink(missing_ok=True)
    for path in files:
        path.chmod(0o400)
    directories.extend(
        path for path in destination.rglob("*") if path.is_dir()
    )
    for path in sorted(set(directories), key=lambda item: len(item.parts), reverse=True):
        path.chmod(0o500)


def _verify_probe_artifacts(
    records: list[Any],
    *,
    plan: dict[str, Any],
    expected_commit: str,
    repo_root: Path,
) -> list[dict[str, Any]]:
    contract = _validate_implementation_contract(
        plan.get("implementation_contract")
    )
    allowed_kinds = set(contract["probe_kinds"])
    verified: list[dict[str, Any]] = []
    for index, item in enumerate(records):
        record = _required_object(item, f"probe_artifacts[{index}]")
        path = Path(_required_text(record.get("path"), "probe path")).resolve()
        probe_file = _safe_repo_path(
            record.get("probe_file"),
            "probe source file",
        )
        if probe_file not in contract["probe_files"]:
            raise ValueError(
                f"Probe artifact names an unapproved producer: {probe_file}"
            )
        payload, digest = _read_json_snapshot(path, "probe artifact")
        if digest != _required_hash(record.get("sha256"), "probe sha256"):
            raise ValueError(f"Probe artifact changed: {path}")
        if payload.get("status") not in {"passed", "ready"}:
            raise ValueError(f"Probe artifact is not passing: {path}")
        if payload.get("kind") not in allowed_kinds:
            raise ValueError(
                f"Probe artifact kind is outside the approved contract: {path}"
            )
        binding = _required_object(
            payload.get("promotion_verification"),
            "probe promotion_verification",
        )
        _reject_unknown(
            binding,
            {
                "candidate_id",
                "canonical_decision_sha256",
                "plan_sha256",
                "verified_commit",
                "source_files",
                "probe_file",
                "status",
            },
            label="probe promotion_verification",
        )
        expected_binding = {
            "candidate_id": plan["candidate_id"],
            "canonical_decision_sha256": plan[
                "canonical_decision_sha256"
            ],
            "plan_sha256": plan["plan_sha256"],
            "verified_commit": expected_commit,
            "source_files": contract["source_files"],
            "probe_file": probe_file,
            "status": "passed",
        }
        if binding != expected_binding:
            raise ValueError(
                f"Probe artifact is not candidate-specific: {path}"
            )
        git_before = _clean_git_state(
            repo_root,
            expected_commit=expected_commit,
        )
        if git_before["commit"] != expected_commit:
            raise ValueError(
                "Candidate probe verification requires the exact reviewed HEAD."
            )
        context = {
            "kind": PROMOTION_PROBE_CONTEXT_KIND,
            "version": 1,
            **expected_binding,
        }
        with tempfile.TemporaryDirectory(
            prefix="sciplot_promotion_probe_execution_"
        ) as temporary:
            temporary_root = Path(temporary)
            snapshot_root = temporary_root / "reviewed_source"
            _materialize_reviewed_source_snapshot(
                repo_root=repo_root,
                expected_commit=expected_commit,
                destination=snapshot_root,
            )
            probe_source = snapshot_root / probe_file
            resolved_probe_source = probe_source.resolve()
            if (
                not probe_source.is_file()
                or probe_source.is_symlink()
                or not resolved_probe_source.is_relative_to(
                    snapshot_root.resolve()
                )
            ):
                raise ValueError(
                    f"Approved probe source is absent from the reviewed commit: "
                    f"{probe_file}"
                )
            probe_source = resolved_probe_source
            source_tree_before = _tree_snapshot(
                snapshot_root,
                "reviewed source snapshot",
            )
            probe_source_sha256 = _read_file_snapshot(
                probe_source,
                "reviewed candidate probe source",
            )[2]
            context_path = temporary_root / "promotion_context.json"
            atomic_write_json(context_path, context)
            environment = os.environ.copy()
            for key in list(environment):
                if re.search(
                    r"(?:API[_-]?KEY|AUTH|BEARER|CREDENTIAL|PASSWORD|SECRET|TOKEN)",
                    key,
                    re.IGNORECASE,
                ):
                    environment.pop(key, None)
            environment["PYTHONPATH"] = str(snapshot_root / "src")
            environment["PYTHONDONTWRITEBYTECODE"] = "1"
            environment["PYTHONNOUSERSITE"] = "1"
            execution = subprocess.run(
                [
                    sys.executable,
                    str(probe_source),
                    "--promotion-context",
                    str(context_path),
                    "--json",
                ],
                cwd=snapshot_root,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
                timeout=300,
            )
            source_tree_after = _tree_snapshot(
                snapshot_root,
                "reviewed source snapshot",
            )
            if source_tree_after != source_tree_before:
                raise ValueError(
                    "Candidate probe modified its reviewed source snapshot."
                )
        git_after = _clean_git_state(
            repo_root,
            expected_commit=expected_commit,
        )
        if git_after["commit"] != expected_commit:
            raise ValueError(
                "Candidate probe execution changed the reviewed checkout."
            )
        if execution.returncode != 0:
            detail = (execution.stderr or execution.stdout).strip()
            raise ValueError(
                f"Candidate probe execution failed for {probe_file}: {detail}"
            )
        try:
            executed_payload = json.loads(execution.stdout)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Candidate probe did not emit one JSON object: {probe_file}"
            ) from exc
        if not isinstance(executed_payload, dict):
            raise ValueError(
                f"Candidate probe output is not an object: {probe_file}"
            )
        if executed_payload != payload:
            raise ValueError(
                f"Stored probe artifact does not reproduce from {probe_file} "
                "at the reviewed commit."
            )
        verified.append(
            {
                "path": str(path),
                "sha256": digest,
                "kind": payload.get("kind"),
                "status": payload.get("status"),
                "promotion_verification": binding,
                "executed_probe_file_sha256": probe_source_sha256,
                "reproduced_from_reviewed_commit": True,
            }
        )
    covered_probe_files = sorted(
        {
            item["promotion_verification"]["probe_file"]
            for item in verified
        }
    )
    if covered_probe_files != contract["probe_files"]:
        raise ValueError(
            "Probe artifacts do not cover every approved changed probe file."
        )
    return verified


def _field_path_value(value: Any, path: list[str], label: str) -> Any:
    current = value
    for field in path:
        if not isinstance(current, dict) or field not in current:
            raise ValueError(f"{label} field path is absent at {field!r}.")
        current = current[field]
    return current


def _canvas_record_descriptor(
    canvas_session: CanvasSession,
    object_path: str,
) -> dict[str, Any]:
    matches = [
        record
        for record in canvas_session.object_registry.records.values()
        if record.current_path.rstrip("/") == object_path.rstrip("/")
    ]
    if len(matches) != 1:
        raise ValueError(
            "Candidate-effect path does not resolve to one Canvas object."
        )
    record = matches[0]
    return {
        "object_type": _normalize_identifier(record.object_type),
        "structural_depth": len(
            [part for part in record.current_path.split("/") if part]
        ),
    }


def _verify_lifecycle_assertions(
    *,
    assertions: list[dict[str, Any]],
    canonical_decision: dict[str, Any],
    document: Any,
    canvas_session: CanvasSession,
    preregistration: dict[str, Any],
    witness: dict[str, Any],
    completion: dict[str, Any],
    project_root: Path,
) -> list[dict[str, Any]]:
    manifest_payload: dict[str, Any] | None = None
    manifest_sha256: str | None = None
    results: list[dict[str, Any]] = []

    def load_completion_manifest() -> dict[str, Any]:
        nonlocal manifest_payload, manifest_sha256
        if manifest_payload is None:
            manifest = _required_object(
                completion.get("manifest"),
                "completion manifest",
            )
            manifest_path = _within(
                project_root,
                Path(
                    _required_text(
                        manifest.get("path"),
                        "completion manifest path",
                    )
                ),
                "Completion manifest",
            )
            manifest_payload, manifest_sha256 = _stable_load(
                manifest_path,
                "completion manifest",
                lambda path: _read_json(path, "completion manifest"),
            )
            if manifest_sha256 != _required_hash(
                manifest.get("sha256"),
                "completion manifest sha256",
            ):
                raise ValueError(
                    "Completion manifest changed after lifecycle completion."
                )
        return manifest_payload

    for assertion in assertions:
        kind = assertion["kind"]
        if kind == "candidate_effect_manifest_equals":
            actual = _field_path_value(
                load_completion_manifest(),
                assertion["path"],
                "Candidate-effect manifest assertion",
            )
            expected = canonical_decision
        elif kind == "mapping_execution_matches_candidate":
            optional = _required_object(
                witness.get("optional_evidence"),
                "promotion lifecycle optional evidence",
            )
            mapping = _required_object(
                optional.get("data_mapping"),
                "promotion lifecycle data mapping",
            )
            mapping_path = _within(
                project_root,
                Path(
                    _required_text(
                        mapping.get("path"),
                        "promotion lifecycle mapping path",
                    )
                ),
                "Promotion lifecycle data mapping",
            )
            mapping_payload, mapping_sha256 = _read_json_snapshot(
                mapping_path,
                "promotion lifecycle mapping execution",
            )
            if mapping_sha256 != _required_hash(
                mapping.get("sha256"),
                "promotion lifecycle mapping sha256",
            ):
                raise ValueError(
                    "Promotion lifecycle mapping execution changed."
                )
            execution = load_data_mapping_execution(mapping_path)
            if any(
                execution.get(key) != value
                for key, value in mapping_payload.items()
            ):
                raise ValueError(
                    "Promotion lifecycle mapping loader did not validate the "
                    "captured execution manifest."
                )
            source_lineage = verify_regular_source_lineage(
                load_completion_manifest(),
                preregistration=preregistration,
                witnessed_mapping=mapping,
            )
            if (
                source_lineage.get("mapping_bound") is not True
                or _required_object(
                    completion.get("manifest"),
                    "completion manifest",
                ).get("transform_ledger_sha256")
                != source_lineage.get("transform_ledger_sha256")
            ):
                raise ValueError(
                    "Final run lineage does not reproduce the witnessed "
                    "mapping execution."
                )
            actual = canonicalize_data_mapping_execution(mapping_path)
            expected = canonical_decision
        elif kind == "veusz_setting_matches_operation":
            operation = _required_object(
                _required_list(
                    canonical_decision.get("operations"),
                    "candidate Canvas operations",
                )[assertion["operation_index"]],
                "candidate Canvas operation",
            )
            try:
                setting = document.resolveSettingPath(
                    None,
                    assertion["path"],
                )
                current = setting.get()
            except ValueError as exc:
                raise ValueError(
                    "Promotion candidate-effect Veusz setting is absent: "
                    f"{assertion['path']}"
                ) from exc
            relative = _required_text(
                operation.get("setting_path"),
                "candidate operation setting_path",
            )
            if not assertion["path"].endswith(relative):
                raise ValueError(
                    "Candidate-effect setting path does not match the "
                    "canonical operation."
                )
            object_path = assertion["path"][: -len(relative)].rstrip("/")
            actual = {
                "operation_type": "set_setting",
                "target": _canvas_record_descriptor(
                    canvas_session,
                    object_path,
                ),
                "setting_path": relative,
                "value": _canonical_canvas_setting_value(
                    relative,
                    current,
                ),
            }
            expected = operation
        elif kind == "veusz_widget_matches_operation":
            operation = _required_object(
                _required_list(
                    canonical_decision.get("operations"),
                    "candidate Canvas operations",
                )[assertion["operation_index"]],
                "candidate Canvas operation",
            )
            widget_path = assertion["path"].rstrip("/")
            try:
                widget = document.resolveWidgetPath(None, widget_path)
            except ValueError as exc:
                raise ValueError(
                    "Promotion candidate-effect Veusz widget is absent: "
                    f"{widget_path}"
                ) from exc
            parent_path = widget_path.rsplit("/", 1)[0] or "/"
            children = list(getattr(widget.parent, "children", []))
            try:
                draw_index = children.index(widget)
            except ValueError as exc:
                raise ValueError(
                    "Candidate-effect widget is detached from its parent."
                ) from exc
            settings: dict[str, Any] = {}
            for key, setting_path in assertion["setting_paths"].items():
                try:
                    current = document.resolveSettingPath(
                        None,
                        setting_path,
                    ).get()
                except ValueError as exc:
                    raise ValueError(
                        "Promotion candidate-effect widget setting is absent: "
                        f"{setting_path}"
                    ) from exc
                if key in {
                    "xpos",
                    "ypos",
                    "xpos2",
                    "ypos2",
                    "width",
                    "height",
                }:
                    settings[key] = _value_shape(current)
                else:
                    settings[key] = _canonical_canvas_setting_value(
                        f"/{key}",
                        current,
                    )
            actual = {
                "operation_type": "add_widget",
                "target": _canvas_record_descriptor(
                    canvas_session,
                    parent_path,
                ),
                "widget_type": _normalize_identifier(widget.typename),
                "front_or_append": (
                    operation["front_or_append"]
                    if len(children) == 1
                    else (
                        "front"
                        if draw_index == 0
                        else (
                            "append"
                            if draw_index == len(children) - 1
                            else "middle"
                        )
                    )
                ),
                "settings": settings,
            }
            expected = operation
        else:
            raise ValueError(
                f"Unsupported lifecycle assertion kind: {kind!r}"
            )
        if json_safe(actual) != json_safe(expected):
            raise ValueError(
                "Promotion lifecycle candidate-effect assertion failed: "
                f"{assertion['assertion_id']}"
            )
        results.append(
            {
                "assertion_id": assertion["assertion_id"],
                "kind": kind,
                "actual_sha256": canonical_sha256(json_safe(actual)),
                "status": "passed",
            }
        )
    return results


def _verify_real_lifecycle(
    records: list[Any],
    *,
    expected_commit: str,
    plan: dict[str, Any],
    decision: dict[str, Any],
) -> list[dict[str, Any]]:
    contract = _validate_candidate_specific_contract(
        plan.get("implementation_contract"),
        _required_object(decision.get("candidate"), "decision candidate"),
    )
    lifecycle_lanes = set(contract["lifecycle_lanes"])
    expected_owner_hash = _required_hash(
        _required_object(
            decision.get("owner_receipt"),
            "decision owner receipt",
        ).get("owner_attestation_sha256"),
        "decision owner_attestation_sha256",
    )
    verified: list[dict[str, Any]] = []
    for index, item in enumerate(records):
        record = _required_object(item, f"real_sessions[{index}]")
        snapshot, session, signed_binding = (
            _verify_signed_session_reference(record)
        )
        session_id = signed_binding["session_id"]
        prereg = _required_object(
            session["preregistration"]["payload"],
            "real preregistration",
        )
        witness = _required_object(
            session["witness"]["payload"],
            "real witness",
        )
        completion = _required_object(
            session["completion"]["payload"],
            "real completion",
        )
        checks = _required_object(
            completion.get("evidence_checks"),
            "real evidence checks",
        )
        _evidence, eligible = _session_base_evidence(
            session["preregistration"],
            session["witness"],
            session["completion"],
            ledger_sha256=snapshot["ledger_sha256"],
        )
        build = _required_object(prereg.get("build"), "real build")
        git_state = _required_object(build.get("git"), "real build git")
        promotion_binding = _required_object(
            prereg.get("promotion_binding"),
            "real promotion_binding",
        )
        lane_assertions = [
            assertion
            for assertion in contract["lifecycle_assertions"]
            if assertion["lane"] == prereg.get("lane")
        ]
        expected_binding = {
            "candidate_id": plan["candidate_id"],
            "decision_sha256": decision["decision_sha256"],
            "plan_sha256": plan["plan_sha256"],
            "assertion_ids": sorted(
                assertion["assertion_id"]
                for assertion in lane_assertions
            ),
        }
        if (
            not eligible
            or prereg.get("lane") not in lifecycle_lanes
            or checks.get("provider_disabled") is not True
            or git_state.get("commit") != expected_commit
            or git_state.get("worktree_clean") is not True
            or promotion_binding != expected_binding
            or _owner_attestation_sha256(prereg.get("owner"))
            != expected_owner_hash
        ):
            raise ValueError(
                f"Session {session_id!r} is not an applicable provider-disabled "
                "real lifecycle on the reviewed commit."
            )
        _verified_journal_segment(prereg, witness)
        authority = _required_object(
            witness.get("authority"),
            "real witness authority",
        )
        if witness.get("authority_mode") != "canvas":
            raise ValueError(
                "Provider-disabled promotion verification requires Canvas authority."
            )
        project_root = Path(
            _required_text(
                _required_object(prereg.get("project"), "real project").get(
                    "root"
                ),
                "real project root",
            )
        )
        canvas_session_path = _within(
            project_root,
            Path(
                _required_text(
                    authority.get("canvas_session"),
                    "real CanvasSession path",
                )
            ),
            "Real CanvasSession",
        )
        document_path = _within(
            project_root,
            Path(
                _required_text(
                    authority.get("document"),
                    "real document path",
                )
            ),
            "Real Canvas document",
        )
        canvas_session, canvas_session_sha256 = _stable_load(
            canvas_session_path,
            "real CanvasSession",
            load_canvas_session,
        )
        document, document_sha256 = _stable_load(
            document_path,
            "real Canvas document",
            _load_veusz_document,
        )
        if (
            canvas_session_sha256
            != _required_hash(
                authority.get("canvas_session_sha256"),
                "real CanvasSession sha256",
            )
            or document_sha256
            != _required_hash(
                authority.get("document_sha256"),
                "real document sha256",
            )
        ):
            raise ValueError("Real Canvas authority changed after completion.")
        if (
            canvas_session.state != "ready"
            or canvas_session.document_sha256 != document_sha256
            or not (
                canvas_session.revision
                == canvas_session.saved_revision
                == canvas_session.exported_revision
            )
            or canvas_session.qa_summary.get("status") != "passed"
            or canvas_session.qa_summary.get("ready_to_use") is not True
        ):
            raise ValueError("Real Canvas authority is no longer handoff-ready.")
        assertion_results = _verify_lifecycle_assertions(
            assertions=lane_assertions,
            canonical_decision=_required_object(
                _required_object(
                    decision.get("candidate"),
                    "decision candidate",
                ).get("canonical_decision"),
                "candidate canonical_decision",
            ),
            document=document,
            canvas_session=canvas_session,
            preregistration=prereg,
            witness=witness,
            completion=completion,
            project_root=project_root,
        )
        verified.append(
            {
                "ledger_prefix_sha256": signed_binding[
                    "ledger_prefix_sha256"
                ],
                "ledger_prefix_size_bytes": signed_binding[
                    "ledger_prefix_size_bytes"
                ],
                "session_id": session_id,
                "preregistration_event_sha256": signed_binding[
                    "preregistration_event_sha256"
                ],
                "witness_event_sha256": signed_binding[
                    "witness_event_sha256"
                ],
                "completion_event_sha256": session["completion"][
                    "event_sha256"
                ],
                "authority_artifacts_sha256": canonical_sha256(
                    signed_binding["authority_artifacts"]
                ),
                "lane": prereg["lane"],
                "source_class": prereg["source_class"],
                "build_commit": expected_commit,
                "provider_disabled": True,
                "promotion_binding": promotion_binding,
                "behavior_assertions": assertion_results,
                "outcome": "pass",
            }
        )
    covered_lanes = {item["lane"] for item in verified}
    if covered_lanes != lifecycle_lanes:
        raise ValueError(
            "Real promotion lifecycles do not cover every approved lane."
        )
    return verified


def verify_promotion_implementation(
    plan_path: Path,
    receipt_path: Path,
    *,
    repo_root: Path,
    output_path: Path | None = None,
) -> dict[str, Any]:
    resolved_plan = plan_path.expanduser().resolve()
    resolved_receipt = receipt_path.expanduser().resolve()
    plan, plan_file_sha256 = _stable_load(
        resolved_plan,
        "promotion implementation plan",
        _validate_plan,
    )
    receipt, receipt_file_sha256 = _stable_load(
        resolved_receipt,
        "promotion verification receipt",
        lambda path: _load_verification_receipt(
            path,
            trust_registry_path=None,
        ),
    )
    if (
        receipt["plan_sha256"] != plan["plan_sha256"]
        or receipt["candidate_id"] != plan["candidate_id"]
    ):
        raise ValueError("Verification receipt names another plan or candidate.")
    current = _clean_git_state(
        repo_root,
        expected_commit=_required_text(
            receipt.get("expected_commit"),
            "expected_commit",
            maximum=64,
        ),
    )
    expected_commit = _required_text(
        receipt.get("expected_commit"),
        "expected_commit",
        maximum=64,
    )
    baseline = _required_object(
        plan.get("source_baseline"),
        "source baseline",
    )
    baseline_commit = _required_text(
        baseline.get("commit"),
        "baseline commit",
        maximum=64,
    )
    if Path(str(baseline.get("repo") or "")).expanduser().resolve() != (
        repo_root.expanduser().resolve()
    ):
        raise ValueError("Verification must use the repository bound by the plan.")
    if current["commit"] != expected_commit or expected_commit == baseline_commit:
        raise ValueError(
            "Verification requires the exact clean reviewed commit after baseline."
        )
    ancestor = _run_git(
        repo_root,
        "merge-base",
        "--is-ancestor",
        baseline_commit,
        expected_commit,
        check=False,
    )
    if ancestor.returncode != 0:
        raise ValueError("Reviewed commit is not descended from the plan baseline.")
    changed_files = [
        line
        for line in _git(
            repo_root,
            "diff",
            "--name-only",
            f"{baseline_commit}..{expected_commit}",
        ).splitlines()
        if line
    ]
    decision, _decision_file_sha256 = _load_plan_decision_snapshot(plan)
    decision_receipt = _required_object(
        decision.get("owner_receipt"),
        "decision owner receipt",
    )
    receipt_authority = _required_object(
        receipt.get("verified_owner_authority"),
        "verification owner authority",
    )
    if (
        receipt["owner"] != decision_receipt.get("owner")
        or _owner_attestation_sha256(receipt["owner"])
        != decision_receipt.get("owner_attestation_sha256")
        or receipt_authority.get("owner_key_id")
        != decision_receipt.get("owner_key_id")
    ):
        raise ValueError(
            "Verification receipt must use the same trusted owner authority."
        )
    contract = _validate_candidate_specific_contract(
        plan.get("implementation_contract"),
        _required_object(decision.get("candidate"), "decision candidate"),
    )
    _validate_changed_file_scope(changed_files, contract)
    probes = _verify_probe_artifacts(
        receipt["probe_artifacts"],
        plan=plan,
        expected_commit=expected_commit,
        repo_root=repo_root,
    )
    real_sessions = _verify_real_lifecycle(
        receipt["real_sessions"],
        expected_commit=expected_commit,
        plan=plan,
        decision=decision,
    )
    final_git_state = _clean_git_state(
        repo_root,
        expected_commit=expected_commit,
    )
    if final_git_state["commit"] != expected_commit:
        raise ValueError(
            "Candidate probes or lifecycle replay changed the reviewed checkout."
        )
    payload = _bind_artifact(
        {
            "kind": PROMOTION_VERIFICATION_KIND,
            "version": PROMOTION_ARTIFACT_VERSION,
            "verified_at": _now(),
            "status": "passed",
            "state": "reviewed_implementation_verified",
            "plan": {
                "path": str(resolved_plan),
                "file_sha256": plan_file_sha256,
                "plan_sha256": plan["plan_sha256"],
            },
            "owner_receipt": {
                "path": str(resolved_receipt),
                "file_sha256": receipt_file_sha256,
                "owner": receipt["owner"],
                "reviewed_by": receipt["reviewed_by"],
                "owner_attested": True,
                "owner_key_id": receipt_authority["owner_key_id"],
                "trust_registry": receipt_authority["trust_registry"],
                "trust_registry_sha256": receipt_authority[
                    "trust_registry_sha256"
                ],
                "signature_algorithm": receipt_authority[
                    "signature_algorithm"
                ],
                "signature_sha256": receipt_authority[
                    "signature_sha256"
                ],
                "protected_registry": receipt_authority[
                    "protected_registry"
                ],
            },
            "candidate_id": plan["candidate_id"],
            "source_change": {
                "baseline_commit": baseline_commit,
                "verified_commit": expected_commit,
                "changed_files": changed_files,
                "approved_source_files": contract["source_files"],
                "approved_probe_files": contract["probe_files"],
                "worktree_clean": True,
            },
            "probe_artifacts": probes,
            "real_sessions": real_sessions,
            "runtime_effect": False,
            "behavior_authority": (
                "ordinary_reviewed_source_at_verified_commit"
            ),
            "limitations": [
                "This artifact records verification; it is never consulted by runtime behavior.",
                "Deterministic behavior comes from the reviewed source commit, not the candidate or decision.",
                "Owner approval is signature-verified; reviewed_by remains an owner-signed local review attestation.",
            ],
        },
        hash_field="verification_sha256",
    )
    if output_path is not None:
        _write_artifact(output_path, payload)
    return payload


def _validate_verification(verification_path: Path) -> dict[str, Any]:
    path = verification_path.expanduser().resolve()
    verification = _validate_bound_artifact(
        _read_json(path, "promotion verification"),
        kind=PROMOTION_VERIFICATION_KIND,
        hash_field="verification_sha256",
        label="promotion verification",
    )
    plan_ref = _required_object(
        verification.get("plan"),
        "verification plan reference",
    )
    plan_path = Path(_required_text(plan_ref.get("path"), "plan path"))
    plan, plan_file_sha256 = _stable_load(
        plan_path,
        "verification plan",
        _validate_plan,
    )
    if plan_file_sha256 != _required_hash(
        plan_ref.get("file_sha256"),
        "plan file_sha256",
    ):
        raise ValueError("Verification plan file changed.")
    if plan["plan_sha256"] != _required_hash(
        plan_ref.get("plan_sha256"),
        "plan_sha256",
    ):
        raise ValueError("Verification plan identity changed.")
    if (
        verification.get("state") != "reviewed_implementation_verified"
        or verification.get("candidate_id") != plan.get("candidate_id")
        or verification.get("behavior_authority")
        != "ordinary_reviewed_source_at_verified_commit"
    ):
        raise ValueError("Promotion verification state or authority changed.")
    receipt_ref = _required_object(
        verification.get("owner_receipt"),
        "verification owner receipt",
    )
    receipt_path = Path(
        _required_text(receipt_ref.get("path"), "verification receipt path")
    )
    receipt, receipt_file_sha256 = _stable_load(
        receipt_path,
        "verification owner receipt",
        _load_verification_receipt,
    )
    if receipt_file_sha256 != _required_hash(
        receipt_ref.get("file_sha256"),
        "verification receipt file_sha256",
    ):
        raise ValueError("Verification owner receipt changed.")
    authority = _required_object(
        receipt.get("verified_owner_authority"),
        "verification owner authority",
    )
    if (
        receipt["plan_sha256"] != plan["plan_sha256"]
        or receipt["candidate_id"] != plan["candidate_id"]
        or receipt["owner"] != receipt_ref.get("owner")
        or receipt["reviewed_by"] != receipt_ref.get("reviewed_by")
        or authority["owner_key_id"] != receipt_ref.get("owner_key_id")
        or authority["trust_registry"] != receipt_ref.get("trust_registry")
        or authority["trust_registry_sha256"]
        != receipt_ref.get("trust_registry_sha256")
        or authority["signature_algorithm"]
        != receipt_ref.get("signature_algorithm")
        or authority["signature_sha256"]
        != receipt_ref.get("signature_sha256")
        or authority["protected_registry"]
        != receipt_ref.get("protected_registry")
    ):
        raise ValueError("Verification owner receipt binding changed.")
    source_change = _required_object(
        verification.get("source_change"),
        "verified source change",
    )
    baseline = _required_object(
        plan.get("source_baseline"),
        "source baseline",
    )
    baseline_commit = _required_text(
        baseline.get("commit"),
        "baseline commit",
        maximum=64,
    )
    expected_commit = receipt["expected_commit"]
    repo = Path(_required_text(baseline.get("repo"), "source repository"))
    contract = _validate_implementation_contract(
        plan.get("implementation_contract")
    )
    if (
        source_change.get("baseline_commit") != baseline_commit
        or source_change.get("verified_commit") != expected_commit
        or source_change.get("worktree_clean") is not True
        or source_change.get("approved_source_files")
        != contract["source_files"]
        or source_change.get("approved_probe_files")
        != contract["probe_files"]
    ):
        raise ValueError("Verified source-change binding changed.")
    commit_exists = _run_git(
        repo,
        "cat-file",
        "-e",
        f"{expected_commit}^{{commit}}",
        check=False,
    )
    if commit_exists.returncode != 0:
        raise ValueError("Verified source commit is no longer available.")
    current_git_state = _clean_git_state(
        repo,
        expected_commit=expected_commit,
    )
    if current_git_state["commit"] != expected_commit:
        raise ValueError(
            "Verification replay requires the exact clean reviewed checkout."
        )
    changed_files = [
        line
        for line in _git(
            repo,
            "diff",
            "--name-only",
            f"{baseline_commit}..{expected_commit}",
        ).splitlines()
        if line
    ]
    if changed_files != source_change.get("changed_files"):
        raise ValueError("Verified source-change inventory changed.")
    _validate_changed_file_scope(changed_files, contract)
    probes = _verify_probe_artifacts(
        receipt["probe_artifacts"],
        plan=plan,
        expected_commit=expected_commit,
        repo_root=repo,
    )
    if probes != verification.get("probe_artifacts"):
        raise ValueError("Verified probe artifacts changed.")
    decision = _validate_decision(Path(plan["decision"]["path"]))
    decision_receipt = _required_object(
        decision.get("owner_receipt"),
        "decision owner receipt",
    )
    if (
        receipt["owner"] != decision_receipt.get("owner")
        or _owner_attestation_sha256(receipt["owner"])
        != decision_receipt.get("owner_attestation_sha256")
        or authority["owner_key_id"] != decision_receipt.get("owner_key_id")
    ):
        raise ValueError(
            "Verified implementation owner authority changed from the decision."
        )
    real_sessions = _verify_real_lifecycle(
        receipt["real_sessions"],
        expected_commit=expected_commit,
        plan=plan,
        decision=decision,
    )
    if real_sessions != verification.get("real_sessions"):
        raise ValueError("Verified real lifecycle evidence changed.")
    final_git_state = _clean_git_state(
        repo,
        expected_commit=expected_commit,
    )
    if final_git_state["commit"] != expected_commit:
        raise ValueError(
            "Verification replay changed the reviewed checkout."
        )
    return verification


def promotion_status(path: Path) -> dict[str, Any]:
    target = path.expanduser().resolve()
    validators: dict[str, tuple[str, Any]] = {
        PROMOTION_COLLECTION_KIND: (
            "collection_sha256",
            lambda snapshot: _validate_collection(snapshot, replay=True),
        ),
        PROMOTION_CANDIDATE_SET_KIND: (
            "candidate_set_sha256",
            _validate_candidate_set,
        ),
        PROMOTION_DECISION_KIND: (
            "decision_sha256",
            _validate_decision,
        ),
        PROMOTION_PLAN_KIND: (
            "plan_sha256",
            _validate_plan,
        ),
        PROMOTION_VERIFICATION_KIND: (
            "verification_sha256",
            _validate_verification,
        ),
    }

    def validate_snapshot(
        snapshot: Path,
    ) -> tuple[dict[str, Any], str, str]:
        initial = _read_json(snapshot, "promotion artifact")
        kind = str(initial.get("kind") or "")
        if kind not in validators:
            raise ValueError(
                f"Unsupported promotion artifact kind: {initial.get('kind')!r}"
            )
        hash_field, validator = validators[kind]
        payload = validator(snapshot)
        if payload.get("kind") != kind:
            raise ValueError(
                "Promotion artifact kind changed during validation."
            )
        return payload, kind, hash_field

    validated, artifact_sha256 = _stable_load(
        target,
        "promotion artifact",
        validate_snapshot,
    )
    payload, kind, hash_field = validated
    return {
        "kind": "sciplot_promotion_status",
        "version": 1,
        "status": "passed",
        "artifact": str(target),
        "artifact_kind": kind,
        "artifact_sha256": artifact_sha256,
        "content_sha256": payload[hash_field],
        "state": payload.get("state"),
        "summary": payload.get("summary"),
        "runtime_effect": False,
    }


def promotion_schema() -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "SciPlot reviewed promotion mechanism",
        "kind": "sciplot_promotion_schema",
        "version": 1,
        "status": "ready",
        "threshold": {
            "distinct_real_sessions": PROMOTION_THRESHOLD,
            "distinct_task_fingerprints": PROMOTION_THRESHOLD,
            "same_attested_owner": True,
            "source_classes": sorted(REAL_SOURCE_CLASSES),
            "session_scopes": sorted(REAL_SESSION_SCOPES),
            "owner_attestation_required": True,
        },
        "commands": [
            "collect",
            "build",
            "decide",
            "plan",
            "session-binding",
            "verify",
            "status",
            "schema",
        ],
        "artifacts": {
            "trusted_owner_registry": PROMOTION_TRUST_REGISTRY_KIND,
            "collection": PROMOTION_COLLECTION_KIND,
            "candidate_set": PROMOTION_CANDIDATE_SET_KIND,
            "decision_receipt": PROMOTION_DECISION_RECEIPT_KIND,
            "decision": PROMOTION_DECISION_KIND,
            "plan": PROMOTION_PLAN_KIND,
            "verification_receipt": PROMOTION_VERIFICATION_RECEIPT_KIND,
            "verification": PROMOTION_VERIFICATION_KIND,
        },
        "owner_decisions": sorted(OWNER_DECISIONS),
        "owner_decision_attestation": OWNER_DECISION_ATTESTATION,
        "verification_attestation": VERIFICATION_ATTESTATION,
        "receipt_contracts": {
            "owner_decision": {
                "required_fields": [
                    "kind",
                    "version",
                    "candidate_id",
                    "candidate_set_sha256",
                    "decision",
                    "owner",
                    "owner_key_id",
                    "signature_algorithm",
                    "signature",
                    "rationale",
                    "owner_attested",
                    "attestation",
                    "implementation_contract",
                    "recorded_at",
                ],
                "authored_by_program": False,
            },
            "implementation_verification": {
                "required_fields": [
                    "kind",
                    "version",
                    "plan_sha256",
                    "candidate_id",
                    "owner",
                    "owner_key_id",
                    "signature_algorithm",
                    "signature",
                    "reviewed_by",
                    "rationale",
                    "owner_attested",
                    "attestation",
                    "expected_commit",
                    "probe_artifacts",
                    "real_sessions",
                    "recorded_at",
                ],
                "real_session_required_fields": [
                    "ledger",
                    "session_id",
                    "ledger_prefix_size_bytes",
                    "ledger_prefix_sha256",
                    "preregistration_event_sha256",
                    "witness_event_sha256",
                    "completion_event_sha256",
                    "authority_artifacts",
                ],
                "authored_by_program": False,
            },
        },
        "state_machine": {
            "candidate": ["observed", "ready_for_review"],
            "decision": [
                "approved_for_implementation",
                "rejected_by_owner",
                "deferred_by_owner",
            ],
            "plan": ["awaiting_reviewed_source_change"],
            "verification": ["reviewed_implementation_verified"],
            "approval_requires": "ready_for_review",
            "plan_requires": "approved_for_implementation",
            "verification_requires": [
                "ordinary_reviewed_source_change",
                "changed_candidate_specific_promotion_probe",
                "passing_probe_artifact",
                "reexecuted_probe_from_private_reviewed_commit_snapshot",
                "exact_probe_output_reproduction",
                "provider_disabled_real_lifecycle",
                "same_frozen_commit_real_lifecycle",
                "owner_verification_receipt",
                "candidate_bound_probe_payload",
                "candidate_bound_session_preregistration",
                "owner_signed_ledger_prefix_and_event_hashes",
                "owner_signed_authority_artifact_hashes",
                "candidate_bound_behavior_assertions",
                "reopened_authority_behavior_match",
                "exact_tracked_worktree_blob_match",
                "normal_git_index_flags_only",
            ],
        },
        "implementation_contract": {
            "candidate_id_required": True,
            "probe_file_pattern": "src/**/*_promotion_probe.py",
            "probe_execution_source": "git_archive_of_exact_reviewed_commit",
            "lifecycle_assertion_kinds": [
                "candidate_effect_manifest_equals",
                "mapping_execution_matches_candidate",
                "veusz_setting_matches_operation",
                "veusz_widget_matches_operation",
            ],
            "whole_candidate_manifest_per_lane": "exactly_one",
            "data_mapping_execution_replay_per_lane": "exactly_one",
            "canvas_operation_vsz_coverage_per_lane": "every_operation",
            "health_only_assertions_allowed": False,
        },
        "trusted_owner_authority": {
            "registry": str(DEFAULT_PROMOTION_TRUST_REGISTRY),
            "registry_kind": PROMOTION_TRUST_REGISTRY_KIND,
            "signature_algorithm": PROMOTION_SIGNATURE_ALGORITHM,
            "minimum_rsa_bits": 2048,
            "program_writes_registry": False,
            "program_signs_receipts": False,
            "path_source": "os_account_database",
            "environment_redirect_allowed": False,
            "symlinks_allowed": False,
            "required_owner_uid": os.getuid(),
            "group_or_world_writable_allowed": False,
            "macos_user_immutable_required": sys.platform == "darwin",
        },
        "runtime_authority": "none",
        "additionalProperties": False,
        "trust_boundary": [
            "Collection replays completed session ledgers and bound journal or execution artifacts.",
            "Canonical decisions omit provider identity, timestamps, source paths, raw data values, and instance object IDs.",
            "Candidates never edit or feed plotting, rules, policy, readiness, or validated envelopes.",
            "Only owner-scoped repeated evidence can be approved.",
            "Decision and verification receipts require an external trusted-owner signature.",
            "Verification ignores ambient PATH and GIT_* redirection, rejects non-normal index flags, and compares every tracked worktree file directly with the expected commit blob.",
            "Verification materializes the exact reviewed Git src tree privately, re-executes its approved promotion probe, and requires exact signed-artifact reproduction.",
            "Every lifecycle lane must expose the whole canonical candidate in its final manifest; mapping candidates must replay the witnessed proposal, outputs, transforms, and final source lineage; Canvas candidates must reproduce every operation in the reopened VSZ.",
        ],
    }


__all__ = [
    "OWNER_DECISION_ATTESTATION",
    "DEFAULT_PROMOTION_TRUST_REGISTRY",
    "PROMOTION_SIGNATURE_ALGORITHM",
    "PROMOTION_TRUST_REGISTRY_KIND",
    "PROMOTION_THRESHOLD",
    "VERIFICATION_ATTESTATION",
    "build_promotion_candidates",
    "build_promotion_session_binding",
    "canonicalize_canvas_batch",
    "canonicalize_data_mapping_execution",
    "collect_promotion_observations",
    "decide_promotion_candidate",
    "plan_promotion_implementation",
    "promotion_schema",
    "promotion_status",
    "verify_promotion_implementation",
]
