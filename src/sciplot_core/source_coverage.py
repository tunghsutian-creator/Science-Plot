from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable

from sciplot_core._utils import file_sha256, json_safe
from sciplot_core.scalar_visual import scalar_visual_contract
from sciplot_core.split import build_split_plan, normalize_split_policy
from sciplot_core.terminal_request import (
    authoritative_terminal_render_request,
    normalize_terminal_render_request,
)
from sciplot_core.veusz_runtime import veusz_worker_environment

_SHA256 = re.compile(r"[0-9a-f]{64}")


def _required_sha256(value: object, *, label: str) -> str:
    digest = str(value or "").strip().casefold()
    if not _SHA256.fullmatch(digest):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest.")
    return digest


def _current_source_artifact(
    path_value: object,
    sha256_value: object,
    *,
    label: str,
) -> dict[str, str]:
    if not isinstance(path_value, str) or not path_value.strip():
        raise ValueError(f"{label} has no source path.")
    path = Path(path_value).expanduser().resolve()
    digest = _required_sha256(sha256_value, label=f"{label} sha256")
    if not path.is_file():
        raise FileNotFoundError(f"{label} is not a current file: {path}")
    if file_sha256(path) != digest:
        raise ValueError(f"{label} changed after rendering: {path}")
    return {"path": str(path), "sha256": digest}


def _source_artifact_from_inventory(
    path_value: object,
    sha256_value: object,
    *,
    label: str,
    artifact_inventory: dict[str, str] | None,
) -> dict[str, str]:
    if artifact_inventory is None:
        return _current_source_artifact(
            path_value,
            sha256_value,
            label=label,
        )
    if not isinstance(path_value, str) or not path_value.strip():
        raise ValueError(f"{label} has no source path.")
    path = str(Path(path_value).expanduser().resolve())
    digest = _required_sha256(sha256_value, label=f"{label} sha256")
    captured_digest = artifact_inventory.get(path)
    if captured_digest is None:
        raise ValueError(
            f"{label} is outside the captured terminal artifact inventory: "
            f"{path}"
        )
    if captured_digest != digest:
        raise ValueError(f"{label} changed after rendering: {path}")
    return {"path": path, "sha256": digest}


def _series_source_artifacts(
    value: object,
    *,
    label: str,
    artifact_inventory: dict[str, str] | None = None,
) -> list[dict[str, str]]:
    if not isinstance(value, list | tuple) or not value:
        raise ValueError(f"{label} has no renderer-recorded source artifacts.")
    records: list[dict[str, str]] = []
    for index, raw in enumerate(value, start=1):
        if isinstance(raw, dict):
            path_value = raw.get("path")
            sha256_value = raw.get("sha256")
        elif (
            isinstance(raw, list | tuple)
            and len(raw) == 2
        ):
            path_value, sha256_value = raw
        else:
            raise ValueError(
                f"{label} source artifact {index} must be a path/hash pair."
            )
        records.append(
            _source_artifact_from_inventory(
                path_value,
                sha256_value,
                label=f"{label} source artifact {index}",
                artifact_inventory=artifact_inventory,
            )
        )
    keys = [(record["path"], record["sha256"]) for record in records]
    if len(keys) != len(set(keys)):
        raise ValueError(f"{label} repeats a renderer-recorded source artifact.")
    return sorted(records, key=lambda record: (record["path"], record["sha256"]))


def _expected_mapping_outputs(
    mapping_application: dict[str, Any],
    *,
    artifact_inventory: dict[str, str] | None = None,
) -> list[dict[str, str]]:
    values = mapping_application.get("mapped_outputs")
    if not isinstance(values, list) or not values:
        raise ValueError("Confirmed data mapping has no mapped output inventory.")
    expected: list[dict[str, str]] = []
    for index, raw in enumerate(values, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"Mapped output {index} is not an object.")
        expected.append(
            _source_artifact_from_inventory(
                raw.get("path"),
                raw.get("sha256"),
                label=f"mapped output {index}",
                artifact_inventory=artifact_inventory,
            )
        )
    keys = [(record["path"], record["sha256"]) for record in expected]
    paths = [record["path"] for record in expected]
    if len(keys) != len(set(keys)) or len(paths) != len(set(paths)):
        raise ValueError("Confirmed data mapping repeats a mapped output identity.")
    return sorted(expected, key=lambda record: (record["path"], record["sha256"]))


def _result_path_list(
    result: dict[str, Any],
    *,
    plural: str,
    singular: str,
    label: str,
) -> list[Path]:
    raw_values = result.get(plural)
    if raw_values is None:
        raw_value = result.get(singular)
        raw_values = [raw_value] if raw_value is not None else []
    if (
        not isinstance(raw_values, list)
        or not raw_values
        or any(
            not isinstance(value, str) or not value.strip()
            for value in raw_values
        )
    ):
        raise ValueError(f"A mapped render must identify its exact {label}.")
    paths = [Path(value).expanduser().resolve() for value in raw_values]
    if len(paths) != len(set(paths)):
        raise ValueError(f"Mapped render repeats a {label} path.")
    return paths


def _terminal_file_snapshots(
    result: dict[str, Any],
) -> list[dict[str, Any]]:
    paths = _result_path_list(
        result,
        plural="data_snapshot_sources",
        singular="data_snapshot_source",
        label="plotted data snapshot files",
    )
    snapshots = [
        _stable_file_snapshot(
            path,
            label=f"terminal plotted data snapshot {index}",
        )
        for index, path in enumerate(paths, start=1)
    ]
    return sorted(
        snapshots,
        key=lambda record: (str(record["path"]), record["sha256"]),
    )


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        json_safe(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _stat_identity(value: os.stat_result) -> dict[str, int]:
    return {
        "device": int(value.st_dev),
        "inode": int(value.st_ino),
        "mode": int(value.st_mode),
        "links": int(value.st_nlink),
        "size": int(value.st_size),
        "mtime_ns": int(value.st_mtime_ns),
        "ctime_ns": int(value.st_ctime_ns),
    }


def _stable_file_snapshot(path: Path, *, label: str) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(resolved, flags)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError(f"{label} is not a regular file: {resolved}")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    path_after = os.stat(resolved, follow_symlinks=False)
    identity = _stat_identity(before)
    if (
        _stat_identity(after) != identity
        or _stat_identity(path_after) != identity
    ):
        raise ValueError(f"{label} changed while it was captured: {resolved}")
    payload = b"".join(chunks)
    digest = hashlib.sha256(payload).hexdigest()
    if len(payload) != identity["size"]:
        raise ValueError(f"{label} size changed while it was captured: {resolved}")
    return {
        "path": resolved,
        "identity": identity,
        "bytes": payload,
        "sha256": digest,
    }


def _assert_snapshot_current(snapshot: dict[str, Any], *, label: str) -> None:
    current = _stable_file_snapshot(Path(snapshot["path"]), label=label)
    if (
        current["identity"] != snapshot["identity"]
        or current["sha256"] != snapshot["sha256"]
    ):
        raise ValueError(f"{label} changed during exact-current audit.")


def _write_private_snapshot(path: Path, payload: bytes) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o400,
    )
    try:
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _audit_exact_document_data(
    *,
    document_path: Path,
    spec_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    document_snapshot = _stable_file_snapshot(
        document_path,
        label="Veusz document",
    )
    spec_snapshot = _stable_file_snapshot(
        spec_path,
        label="Veusz specification",
    )
    _assert_snapshot_current(document_snapshot, label="Veusz document")
    _assert_snapshot_current(spec_snapshot, label="Veusz specification")
    try:
        spec_payload = json.loads(spec_snapshot["bytes"].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"Mapped render Veusz specification is invalid JSON: {spec_path}"
        ) from exc
    if not isinstance(spec_payload, dict):
        raise ValueError(
            f"Mapped render Veusz specification is not an object: {spec_path}"
        )
    with tempfile.TemporaryDirectory(prefix="sciplot_vsz_audit_") as temporary:
        snapshot_root = Path(temporary)
        os.chmod(snapshot_root, 0o700)
        private_document = snapshot_root / "document.vsz"
        private_spec = snapshot_root / "spec.json"
        _write_private_snapshot(private_document, document_snapshot["bytes"])
        _write_private_snapshot(private_spec, spec_snapshot["bytes"])
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "sciplot_core.veusz_worker",
                "audit-spec-data",
                str(private_document),
                str(private_spec),
            ],
            text=True,
            capture_output=True,
            check=False,
            timeout=120,
            env=veusz_worker_environment(),
        )
    if completed.returncode != 0:
        detail = completed.stderr.strip().splitlines()
        raise ValueError(
            "Exact-current Veusz data-consumption audit failed: "
            f"{detail[-1] if detail else completed.returncode}"
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "Exact-current Veusz data-consumption audit returned invalid JSON."
        ) from exc
    if (
        not isinstance(payload, dict)
        or payload.get("kind") != "sciplot_veusz_spec_data_audit"
        or payload.get("version") != 1
        or payload.get("status") != "passed"
    ):
        raise ValueError(
            "Exact-current Veusz data-consumption audit did not pass."
        )
    expected_document = {
        "path": str(private_document.resolve()),
        "sha256": document_snapshot["sha256"],
    }
    expected_spec = {
        "path": str(private_spec.resolve()),
        "sha256": spec_snapshot["sha256"],
    }
    if (
        payload.get("document") != expected_document
        or payload.get("spec") != expected_spec
    ):
        raise ValueError(
            "Exact-current Veusz data-consumption audit returned stale artifacts."
        )
    units = payload.get("units")
    if (
        not isinstance(units, list)
        or not units
        or payload.get("unit_count") != len(units)
    ):
        raise ValueError(
            "Exact-current Veusz data-consumption audit has no closed unit inventory."
        )
    _assert_snapshot_current(document_snapshot, label="Veusz document")
    _assert_snapshot_current(spec_snapshot, label="Veusz specification")
    payload["document"] = {
        "path": str(document_snapshot["path"]),
        "sha256": document_snapshot["sha256"],
    }
    payload["spec"] = {
        "path": str(spec_snapshot["path"]),
        "sha256": spec_snapshot["sha256"],
    }
    return payload, spec_payload


def _spec_render_data_units(
    spec: dict[str, Any],
    *,
    artifact_inventory: dict[str, str],
) -> list[dict[str, Any]]:
    axes = spec.get("axes")
    if (
        not isinstance(axes, dict)
        or not isinstance(axes.get("x"), dict)
        or not isinstance(axes.get("y"), dict)
    ):
        raise ValueError(
            "Veusz specification has no closed x/y axis contract."
        )
    axis_contract = json_safe(
        {
            "x": dict(axes["x"]),
            "y": dict(axes["y"]),
        }
    )
    categorical = spec.get("categorical")
    categorical_groups = {
        str(group.get("y_name") or ""): group
        for group in (
            categorical.get("groups", [])
            if isinstance(categorical, dict)
            else []
        )
        if isinstance(group, dict)
    }
    reference_guides = (
        spec.get("reference_guides")
        if isinstance(spec.get("reference_guides"), list)
        else []
    )
    direct_labels = (
        spec.get("direct_labels")
        if isinstance(spec.get("direct_labels"), list)
        else []
    )
    units: list[dict[str, Any]] = []
    series = spec.get("series")
    if not isinstance(series, list):
        raise ValueError("Veusz specification has no series list.")
    for index, raw_series in enumerate(series, start=1):
        if not isinstance(raw_series, dict):
            raise ValueError(f"Veusz specification series {index} is invalid.")
        y_name = str(raw_series.get("y_name") or "")
        group = categorical_groups.get(y_name)
        units.append(
            {
                "kind": "series",
                "name": str(raw_series.get("name") or ""),
                "label": str(raw_series.get("label") or ""),
                "x_name": str(raw_series.get("x_name") or ""),
                "y_name": y_name,
                "x_values": raw_series.get("x_values"),
                "y_values": raw_series.get("y_values"),
                "presentation_kind": str(
                    raw_series.get("presentation_kind") or "curve"
                ),
                "category_position": raw_series.get("category_position"),
                "plot_line_hide": raw_series.get("plot_line_hide") is True,
                "raw_points_visible": (
                    raw_series.get("raw_points_visible") is not False
                ),
                "boxplot_eligible": (
                    group.get("boxplot_eligible") is True
                    if isinstance(group, dict)
                    else False
                ),
                "axes": axis_contract,
                "reference_guides": json_safe(reference_guides),
                "direct_labels": json_safe(direct_labels),
                "source_artifacts": _series_source_artifacts(
                    raw_series.get("source_artifacts"),
                    label=f"specification series {index}",
                    artifact_inventory=artifact_inventory,
                ),
            }
        )
    scalar = spec.get("scalar_field")
    if isinstance(scalar, dict):
        units.append(
            {
                "kind": "scalar_field",
                "data_name": str(scalar.get("data_name") or ""),
                "x_values": scalar.get("x_values"),
                "y_values": scalar.get("y_values"),
                "z_values": scalar.get("z_values"),
                "z_label": str(scalar.get("z_label") or ""),
                "scalar_visual": scalar_visual_contract(
                    scalar,
                    label="specification scalar field",
                ),
                "axes": axis_contract,
                "reference_guides": json_safe(reference_guides),
                "direct_labels": json_safe(direct_labels),
                "source_artifacts": _series_source_artifacts(
                    scalar.get("source_artifacts"),
                    label="specification scalar field",
                    artifact_inventory=artifact_inventory,
                ),
            }
        )
    return units


def _declared_terminal_render_requests(
    result: dict[str, Any],
    *,
    spec_count: int,
) -> list[dict[str, Any]] | None:
    raw_requests = result.get("terminal_render_requests")
    if raw_requests is None:
        return None
    if (
        not isinstance(raw_requests, list)
        or len(raw_requests) != spec_count
        or any(not isinstance(item, dict) for item in raw_requests)
    ):
        raise ValueError(
            "Mapped render terminal-request inventory does not match its "
            "Veusz specification inventory."
        )
    return [
        normalize_terminal_render_request(
            raw,
            label=f"terminal render request {index}",
        )
        for index, raw in enumerate(raw_requests, start=1)
    ]


def _authoritative_terminal_render_requests(
    *,
    result: dict[str, Any],
    authoritative_request: dict[str, Any],
    declared_requests: list[dict[str, Any]] | None,
    private_sources: list[Path],
    spec_count: int,
) -> list[dict[str, Any]]:
    from sciplot_core.studio import derive_terminal_render_data_contract

    if isinstance(result.get("multi_metric_bundle"), dict):
        raise ValueError(
            "Mapped multi-metric bundles require an independently persisted "
            "authoritative panel plan before they can produce source evidence."
        )
    if isinstance(result.get("auto_split"), dict):
        raise ValueError(
            "Mapped auto-split output cannot become source evidence until the "
            "split policy is explicitly confirmed in the authoritative request."
        )
    base_request = authoritative_terminal_render_request(
        authoritative_request
    )
    baseline = derive_terminal_render_data_contract(
        request=base_request,
        terminal_sources=private_sources,
    )
    baseline_units = baseline.get("units")
    if not isinstance(baseline_units, list) or not baseline_units:
        raise ValueError(
            "Authoritative terminal request produced no baseline units."
        )
    split_plan = result.get("split_plan")
    requested_policy = normalize_split_policy(
        authoritative_request.get("split_policy")
    )
    expected_requests: list[dict[str, Any]]
    if split_plan is None:
        if requested_policy is not None:
            raise ValueError(
                "Mapped render omitted the explicitly confirmed split plan."
            )
        if spec_count != 1:
            raise ValueError(
                "A mapped multi-panel render has no authoritative split plan."
            )
        expected_requests = [base_request]
    else:
        if not isinstance(split_plan, dict) or requested_policy is None:
            raise ValueError(
                "Mapped render split metadata is not bound to an explicit "
                "authoritative split policy."
            )
        labels = [
            str(unit.get("label") or "")
            for unit in baseline_units
            if isinstance(unit, dict) and unit.get("kind") == "series"
        ]
        if not labels or any(not label for label in labels):
            raise ValueError(
                "Authoritative split planning requires stable series labels."
            )
        expected_plan = build_split_plan(labels, policy=requested_policy)
        if json_safe(split_plan) != json_safe(expected_plan):
            raise ValueError(
                "Mapped render split plan does not reproduce from the "
                "authoritative request and exact terminal tables."
            )
        chunks = [
            list(chunk["series"])
            for chunk in expected_plan["chunks"]
            if isinstance(chunk, dict)
        ]
        if len(chunks) != spec_count:
            raise ValueError(
                "Authoritative split plan and Veusz specification counts "
                "disagree."
            )
        expected_requests = []
        for chunk in chunks:
            panel_request = {
                **base_request,
                "render_options": {
                    **dict(base_request["render_options"]),
                    "series_include": list(chunk),
                    "series_order": list(chunk),
                },
            }
            expected_requests.append(panel_request)
    if (
        declared_requests is not None
        and declared_requests != expected_requests
    ):
        raise ValueError(
            "Declared terminal render requests do not reproduce from the "
            "authoritative request and exact terminal tables."
        )
    return expected_requests


def _remap_derived_source_artifacts(
    records: object,
    *,
    private_to_original: dict[str, dict[str, str]],
    label: str,
) -> list[dict[str, str]]:
    if not isinstance(records, list) or not records:
        raise ValueError(f"{label} has no source artifacts.")
    remapped: list[dict[str, str]] = []
    for index, raw in enumerate(records, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"{label} source artifact {index} is invalid.")
        private_path = str(
            Path(str(raw.get("path") or "")).expanduser().resolve()
        )
        original = private_to_original.get(private_path)
        if original is None or raw.get("sha256") != original["sha256"]:
            raise ValueError(
                f"{label} consumed an unapproved private terminal snapshot."
            )
        remapped.append(dict(original))
    return sorted(
        remapped,
        key=lambda record: (record["path"], record["sha256"]),
    )


def _terminal_render_derivation(
    *,
    result: dict[str, Any],
    authoritative_request: dict[str, Any],
    declared_requests: list[dict[str, Any]] | None,
    terminal_snapshots: list[dict[str, Any]],
    spec_unit_groups: list[list[dict[str, Any]]],
) -> dict[str, Any]:
    from sciplot_core.studio import derive_terminal_render_data_contract

    terminal_outputs = [
        {
            "path": str(snapshot["path"]),
            "sha256": str(snapshot["sha256"]),
        }
        for snapshot in terminal_snapshots
    ]
    snapshot_by_original = {
        str(snapshot["path"]): snapshot for snapshot in terminal_snapshots
    }
    signature_inventory: list[str] = []
    with tempfile.TemporaryDirectory(
        prefix="sciplot_terminal_data_audit_"
    ) as temporary:
        snapshot_root = Path(temporary)
        os.chmod(snapshot_root, 0o700)
        private_to_original: dict[str, dict[str, str]] = {}
        private_by_original: dict[str, Path] = {}
        for index, snapshot in enumerate(terminal_snapshots, start=1):
            source = Path(snapshot["path"])
            private_parent = snapshot_root / f"source_{index:04d}"
            private_parent.mkdir(mode=0o700)
            private_source = private_parent / source.name
            _write_private_snapshot(private_source, snapshot["bytes"])
            original_record = {
                "path": str(source),
                "sha256": str(snapshot["sha256"]),
            }
            private_to_original[str(private_source.resolve())] = original_record
            private_by_original[str(source)] = private_source

        requests = _authoritative_terminal_render_requests(
            result=result,
            authoritative_request=authoritative_request,
            declared_requests=declared_requests,
            private_sources=[
                private_by_original[str(snapshot["path"])]
                for snapshot in terminal_snapshots
            ],
            spec_count=len(spec_unit_groups),
        )
        if len(requests) != len(spec_unit_groups):
            raise ValueError(
                "Terminal render requests and specification groups disagree."
            )
        for request_index, (request, spec_units) in enumerate(
            zip(requests, spec_unit_groups, strict=True),
            start=1,
        ):
            expected_source_paths = sorted(
                {
                    str(record["path"])
                    for unit in spec_units
                    for record in unit["source_artifacts"]
                }
            )
            if not expected_source_paths:
                raise ValueError(
                    f"Veusz specification {request_index} has no terminal "
                    "source inventory."
                )
            if any(
                path not in snapshot_by_original
                for path in expected_source_paths
            ):
                raise ValueError(
                    f"Veusz specification {request_index} cites a source "
                    "outside the captured terminal snapshots."
                )
            derived = derive_terminal_render_data_contract(
                request=request,
                terminal_sources=[
                    private_by_original[path] for path in expected_source_paths
                ],
            )
            if (
                derived.get("kind")
                != "sciplot_terminal_render_data_contract"
                or derived.get("version") != 1
                or derived.get("status") != "passed"
            ):
                raise ValueError("Terminal render-data derivation did not pass.")
            derived_sources = _remap_derived_source_artifacts(
                derived.get("source_artifacts"),
                private_to_original=private_to_original,
                label=f"terminal derivation {request_index}",
            )
            expected_sources = sorted(
                (
                    {
                        "path": path,
                        "sha256": str(snapshot_by_original[path]["sha256"]),
                    }
                    for path in expected_source_paths
                ),
                key=lambda record: (record["path"], record["sha256"]),
            )
            if derived_sources != expected_sources:
                raise ValueError(
                    "Terminal render-data derivation did not consume the exact "
                    "private terminal snapshot inventory."
                )
            derived_units = derived.get("units")
            if (
                not isinstance(derived_units, list)
                or not derived_units
                or derived.get("unit_count") != len(derived_units)
            ):
                raise ValueError(
                    "Terminal render-data derivation has no closed unit "
                    "inventory."
                )
            for unit_index, unit in enumerate(derived_units, start=1):
                if not isinstance(unit, dict):
                    raise ValueError(
                        "Terminal render-data derivation contains an invalid "
                        "unit."
                    )
                unit["source_artifacts"] = _remap_derived_source_artifacts(
                    unit.get("source_artifacts"),
                    private_to_original=private_to_original,
                    label=(
                        f"terminal derivation {request_index} unit "
                        f"{unit_index}"
                    ),
                )
            signature_fields = (
                "kind",
                "name",
                "label",
                "x_name",
                "y_name",
                "data_name",
                "x_values",
                "y_values",
                "z_values",
                "z_label",
                "scalar_visual",
                "axes",
                "reference_guides",
                "direct_labels",
                "presentation_kind",
                "category_position",
                "plot_line_hide",
                "raw_points_visible",
                "boxplot_eligible",
                "source_artifacts",
            )
            derived_signatures = [
                _canonical_sha256(
                    {
                        field: unit.get(field)
                        for field in signature_fields
                        if field in unit
                    }
                )
                for unit in derived_units
            ]
            spec_signatures = [
                _canonical_sha256(
                    {
                        field: unit.get(field)
                        for field in signature_fields
                        if field in unit
                    }
                )
                for unit in spec_units
            ]
            if spec_signatures != derived_signatures:
                raise ValueError(
                    "Rendered specification data, axes, or ordered series "
                    "identity do not reproduce from the exact terminal "
                    "plotted tables."
                )
            signature_inventory.extend(derived_signatures)
    for index, snapshot in enumerate(terminal_snapshots, start=1):
        _assert_snapshot_current(
            snapshot,
            label=f"terminal plotted data snapshot {index}",
        )
    return {
        "kind": "sciplot_terminal_render_data_derivation",
        "version": 1,
        "status": "passed",
        "request_sha256": _canonical_sha256(requests),
        "terminal_artifacts": terminal_outputs,
        "terminal_artifact_count": len(terminal_outputs),
        "unit_signatures": signature_inventory,
        "unit_count": len(signature_inventory),
    }


def evaluate_mapping_source_coverage(
    rendered_units: Iterable[dict[str, Any]],
    *,
    mapping_application: dict[str, Any],
    template: str,
    allow_downstream_sources: bool = False,
    artifact_inventory: dict[str, str] | None = None,
) -> dict[str, Any]:
    mapped_output_values = mapping_application.get("mapped_outputs")
    mapped_output_paths = {
        str(Path(str(item.get("path") or "")).expanduser().resolve())
        for item in (
            mapped_output_values
            if isinstance(mapped_output_values, list)
            else []
        )
        if isinstance(item, dict)
    }
    expected_inventory = (
        artifact_inventory
        if artifact_inventory is not None
        and mapped_output_paths
        and mapped_output_paths <= set(artifact_inventory)
        else None
    )
    expected = _expected_mapping_outputs(
        mapping_application,
        artifact_inventory=expected_inventory,
    )
    normalized_units: list[dict[str, Any]] = []
    for index, raw in enumerate(rendered_units, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"Rendered unit {index} is not an object.")
        identity = str(raw.get("identity") or "").strip()
        if not identity:
            raise ValueError(f"Rendered unit {index} has no stable identity.")
        normalized_units.append(
            {
                "identity": identity,
                "kind": str(raw.get("kind") or "series"),
                "source_artifacts": _series_source_artifacts(
                    raw.get("source_artifacts"),
                    label=f"rendered unit {identity!r}",
                    artifact_inventory=artifact_inventory,
                ),
            }
        )
    if not normalized_units:
        raise ValueError("The rendered Veusz specification contains no data units.")
    unit_identities = [unit["identity"] for unit in normalized_units]
    if len(unit_identities) != len(set(unit_identities)):
        raise ValueError("Rendered source coverage repeats a unit identity.")

    expected_keys = {
        (record["path"], record["sha256"]) for record in expected
    }
    contribution_counts = {
        key: 0 for key in expected_keys
    }
    rendered_source_keys: set[tuple[str, str]] = set()
    for unit in normalized_units:
        unit_keys = {
            (record["path"], record["sha256"])
            for record in unit["source_artifacts"]
        }
        rendered_source_keys.update(unit_keys)
        for key in expected_keys & unit_keys:
            contribution_counts[key] += 1
    unexpected_keys = rendered_source_keys - expected_keys
    if unexpected_keys and not allow_downstream_sources:
        mapped_output_contributes = any(
            count > 0 for count in contribution_counts.values()
        )
        unambiguous_single_output_transform = (
            len(expected) == 1
            and not mapped_output_contributes
            and len(rendered_source_keys) == 1
        )
        if not unambiguous_single_output_transform:
            paths = ", ".join(path for path, _ in sorted(unexpected_keys))
            raise ValueError(
                "Rendered Veusz data consume files outside the confirmed "
                f"mapped output inventory: {paths}"
            )

    exact_missing = [
        record
        for record in expected
        if contribution_counts[(record["path"], record["sha256"])] == 0
    ]
    if not exact_missing:
        coverage_mode = "exact_per_output"
    elif len(expected) == 1:
        # With one confirmed mapping output there is no sibling source that can
        # be silently omitted. Downstream recipe/semantic transforms are bound
        # independently by the transform ledger and terminal snapshot checks.
        coverage_mode = "transitive_single_output"
    else:
        missing_paths = ", ".join(record["path"] for record in exact_missing)
        raise ValueError(
            "Rendered Veusz data do not consume every confirmed mapped output: "
            f"{missing_paths}"
        )

    return {
        "kind": "sciplot_rendered_mapping_source_coverage",
        "version": 1,
        "status": "passed",
        "proposal_id": mapping_application.get("proposal_id"),
        "template": str(template),
        "coverage_mode": coverage_mode,
        "expected_outputs": expected,
        "expected_output_count": len(expected),
        "rendered_units": normalized_units,
        "rendered_unit_count": len(normalized_units),
        "contribution_counts": [
            {
                **record,
                "rendered_unit_count": contribution_counts[
                    (record["path"], record["sha256"])
                ],
            }
            for record in expected
        ],
        "silent_omission_detected": False,
    }


def verify_rendered_mapping_source_coverage(
    result: dict[str, Any],
    *,
    mapping_application: dict[str, Any],
    request: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(request, dict):
        raise ValueError(
            "Mapped render source verification requires the authoritative request."
        )
    spec_paths = _result_path_list(
        result,
        plural="veusz_specs",
        singular="veusz_spec",
        label="Veusz specification files",
    )
    document_paths = _result_path_list(
        result,
        plural="veusz_documents",
        singular="veusz_document",
        label="exact-current Veusz document files",
    )
    if len(document_paths) != len(spec_paths):
        raise ValueError(
            "Mapped render Veusz document/specification counts disagree."
        )
    terminal_snapshots = _terminal_file_snapshots(result)
    terminal_outputs = [
        {
            "path": str(snapshot["path"]),
            "sha256": str(snapshot["sha256"]),
        }
        for snapshot in terminal_snapshots
    ]
    terminal_artifact_inventory = {
        record["path"]: record["sha256"] for record in terminal_outputs
    }
    declared_terminal_requests = _declared_terminal_render_requests(
        result,
        spec_count=len(spec_paths),
    )

    spec_artifacts: list[dict[str, Any]] = []
    document_artifacts: list[dict[str, Any]] = []
    document_data_audits: list[dict[str, Any]] = []
    rendered_units: list[dict[str, Any]] = []
    spec_unit_groups: list[list[dict[str, Any]]] = []
    templates: set[str] = set()
    for spec_index, (spec_path, document_path) in enumerate(
        zip(spec_paths, document_paths, strict=True),
        start=1,
    ):
        if not spec_path.is_file():
            raise FileNotFoundError(
                f"Mapped render Veusz specification not found: {spec_path}"
            )
        if not document_path.is_file():
            raise FileNotFoundError(
                f"Mapped render Veusz document not found: {document_path}"
            )
        document_audit, spec = _audit_exact_document_data(
            document_path=document_path,
            spec_path=spec_path,
        )
        template = str(spec.get("template") or result.get("template") or "")
        templates.add(template)
        spec_artifacts.append(
            dict(document_audit["spec"])
        )
        document_artifacts.append(
            dict(document_audit["document"])
        )
        document_data_audits.append(document_audit)
        spec_unit_groups.append(
            _spec_render_data_units(
                spec,
                artifact_inventory=terminal_artifact_inventory,
            )
        )
        series = spec.get("series")
        if not isinstance(series, list):
            raise ValueError(
                f"Mapped render Veusz specification has no series list: {spec_path}"
            )
        for series_index, raw_series in enumerate(series, start=1):
            if not isinstance(raw_series, dict):
                raise ValueError(
                    f"Mapped render series {series_index} is not an object."
                )
            rendered_units.append(
                {
                    "identity": (
                        f"spec_{spec_index}:series:"
                        f"{str(raw_series.get('name') or series_index)}"
                    ),
                    "kind": "series",
                    "source_artifacts": raw_series.get("source_artifacts"),
                }
            )
        scalar = spec.get("scalar_field")
        if isinstance(scalar, dict):
            rendered_units.append(
                {
                    "identity": f"spec_{spec_index}:scalar_field",
                    "kind": "scalar_field",
                    "source_artifacts": scalar.get("source_artifacts"),
                }
            )
    coverage = evaluate_mapping_source_coverage(
        rendered_units,
        mapping_application=mapping_application,
        template=",".join(sorted(templates)),
        allow_downstream_sources=True,
        artifact_inventory=terminal_artifact_inventory,
    )
    terminal_data_derivation = _terminal_render_derivation(
        result=result,
        authoritative_request=request,
        declared_requests=declared_terminal_requests,
        terminal_snapshots=terminal_snapshots,
        spec_unit_groups=spec_unit_groups,
    )
    terminal_keys = {
        (record["path"], record["sha256"]) for record in terminal_outputs
    }
    rendered_keys = {
        (record["path"], record["sha256"])
        for unit in coverage["rendered_units"]
        for record in unit["source_artifacts"]
    }
    if rendered_keys - terminal_keys:
        paths = ", ".join(
            path for path, _ in sorted(rendered_keys - terminal_keys)
        )
        raise ValueError(
            "Rendered Veusz data cite sources outside the terminal plotted "
            f"snapshot inventory: {paths}"
        )
    terminal_contribution_counts: list[dict[str, Any]] = []
    for record in terminal_outputs:
        key = (record["path"], record["sha256"])
        count = sum(
            key
            in {
                (artifact["path"], artifact["sha256"])
                for artifact in unit["source_artifacts"]
            }
            for unit in coverage["rendered_units"]
        )
        if count < 1:
            raise ValueError(
                "A terminal plotted data snapshot has no exact-current Veusz "
                f"consumer: {record['path']}"
            )
        terminal_contribution_counts.append(
            {**record, "rendered_unit_count": count}
        )
    for index, snapshot in enumerate(terminal_snapshots, start=1):
        _assert_snapshot_current(
            snapshot,
            label=f"terminal plotted data snapshot {index}",
        )
    return {
        **coverage,
        "terminal_outputs": terminal_outputs,
        "terminal_output_count": len(terminal_outputs),
        "terminal_contribution_counts": terminal_contribution_counts,
        "spec_artifacts": sorted(
            spec_artifacts,
            key=lambda record: (record["path"], record["sha256"]),
        ),
        "spec_count": len(spec_artifacts),
        "document_artifacts": sorted(
            document_artifacts,
            key=lambda record: (record["path"], record["sha256"]),
        ),
        "document_count": len(document_artifacts),
        "document_data_audits": document_data_audits,
        "terminal_data_derivation": terminal_data_derivation,
    }


__all__ = [
    "evaluate_mapping_source_coverage",
    "verify_rendered_mapping_source_coverage",
]
