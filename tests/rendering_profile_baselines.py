"""One additive, byte-proven Darwin baseline; historical authority never changes.

Descriptors are explicit source-owned inputs, not an environment allowlist or an
update mode. Every selection rechecks the parent, capture and transition facts.
"""

from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import stat

from rendering_profiles_helpers import load_profile


BASELINE_ID = "darwin-27.2.0-arm64-v1"
SUFFIX = "--darwin-27.2.0-v1.json"
GOLDEN_ROLES = frozenset({"golden_png", "golden_structure", "golden_environment",
                          "golden_capture", "golden_producer", "golden_inventory"})
FILE_ROLES = GOLDEN_ROLES | {"parent_manifest", "golden_datasets", "capture_request",
                            "capture_run", "capture_helper", "capture_driver",
                            "capture_controller", "native_pdf", "native_tiff",
                            "producer_inputs", "capture_state", "bridge"}


def _require(condition, message):
    if not condition:
        raise AssertionError(message)


def _object(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "Duplicate baseline JSON key")
        result[key] = value
    return result


def _read(path):
    def invalid(value):
        raise AssertionError(f"Nonfinite baseline JSON: {value}")
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_object,
                      parse_constant=invalid)


def _hash(path):
    return sha256(path.read_bytes()).hexdigest()


def _equal(left, right):
    return json.dumps(left, sort_keys=True, allow_nan=False) == json.dumps(right, sort_keys=True, allow_nan=False)


def _ordinary(root, value):
    """Reject aliases before resolution, including ordinary in-root symlinks."""
    _require(isinstance(value, str) and value and not Path(value).is_absolute()
             and ".." not in Path(value).parts and value == Path(value).as_posix(),
             "Unsafe baseline member path")
    current = root
    _require(stat.S_ISDIR(current.lstat().st_mode), "Baseline root must be ordinary")
    for index, part in enumerate(Path(value).parts):
        current = current / part
        mode = current.lstat().st_mode
        expected = stat.S_ISREG if index == len(Path(value).parts) - 1 else stat.S_ISDIR
        _require(expected(mode), "Baseline members and ancestors must be ordinary")
    return current


def _pinned_files(path, descriptor):
    _require(set(descriptor) == {"schema_version", "kind", "baseline_id", "files"}
             and descriptor["schema_version"] == 2
             and descriptor["kind"] == "sciplot_native_environment_baseline"
             and descriptor["baseline_id"] == BASELINE_ID,
             "Unsupported closed baseline descriptor")
    records = descriptor["files"]
    _require(isinstance(records, dict) and set(records) == FILE_ROLES,
             "Baseline requires its complete evidence closure")
    files = {}
    for role, record in records.items():
        _require(isinstance(record, dict) and set(record) == {"path", "sha256"},
                 "Invalid baseline file pin")
        file = _ordinary(path.parent, record["path"])
        _require(_hash(file) == record["sha256"], f"Baseline evidence changed: {role}")
        files[role] = file
    _require(len(set(files.values())) == len(files), "Aliased baseline evidence roles")
    return files


def _producer(files, capture):
    producer, inputs = _read(files["golden_producer"]), _read(files["producer_inputs"])
    _require(set(producer) == {"runtime_identity", "capture_helper_sha256", "document_sha256"},
             "Invalid native producer identity")
    _require(set(inputs) == {"sciplot", "veusz", "python", "executable", "installation",
                             "environment", "versions"}, "Invalid producer inputs")
    digest = sha256(json.dumps(inputs, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    _require(producer["runtime_identity"] == digest, "Producer inputs do not reproduce identity")
    _require(producer["capture_helper_sha256"] == _hash(files["capture_helper"])
             and producer["document_sha256"] == capture["document_sha256"],
             "Producer helper/document binding changed")
    environment = _read(files["golden_environment"])
    _require(inputs["executable"] == environment["python_binary_sha256"]
             and inputs["python"].split()[0] == environment["python"]
             and inputs["versions"] == {key: environment["packages"][key] for key in ("PyQt6", "PyQt6-Qt6", "numpy")},
             "Producer and captured interpreter/packages disagree")
    return producer


def _process(parent, files, producer):
    request, run = _read(files["capture_request"]), _read(files["capture_run"])
    _require(set(request) == {"document", "output", "font_files"}, "Invalid capture request")
    keys = {"schema_version", "argv", "cwd", "pid", "waited_pid", "exit_code",
            "started_ns", "finished_ns", "stdout", "stderr", "stdout_sha256",
            "stderr_sha256", "request_sha256", "driver_sha256", "helper_sha256",
            "producer_sha256", "controller_sha256", "controller_pid", "source_commit"}
    _require(set(run) == keys and type(run["schema_version"]) is int and run["schema_version"] == 1,
             "Invalid original capture execution record")
    argv = run["argv"]
    _require(isinstance(argv, list) and len(argv) == 3
             and all(isinstance(item, str) and Path(item).is_absolute() for item in argv)
             and Path(argv[1]).name == files["capture_driver"].name
             and Path(argv[2]).name == files["capture_request"].name
             and str(Path(argv[2]).parent) == request["output"]
             and Path(request["document"]).is_absolute()
             and Path(request["document"]).name == parent.files["accepted_vsz"].name
             and Path(run["cwd"]).is_absolute(), "Capture argv/request binding changed")
    _require(type(run["pid"]) is int and run["pid"] > 0
             and type(run["controller_pid"]) is int and run["controller_pid"] > 0
             and run["controller_pid"] != run["pid"]
             and type(run["waited_pid"]) is int and run["waited_pid"] == run["pid"]
             and type(run["exit_code"]) is int and run["exit_code"] == 0
             and type(run["started_ns"]) is int and type(run["finished_ns"]) is int
             and run["finished_ns"] > run["started_ns"],
             "Capture requires original successful child wait")
    for stream in ("stdout", "stderr"):
        _require(isinstance(run[stream], str)
                 and sha256(run[stream].encode()).hexdigest() == run[stream + "_sha256"],
                 "Capture raw stream hash changed")
    for field, role in (("request_sha256", "capture_request"), ("driver_sha256", "capture_driver"),
                        ("helper_sha256", "capture_helper"), ("producer_sha256", "golden_producer"),
                        ("controller_sha256", "capture_controller")):
        _require(run[field] == _hash(files[role]), "Capture process evidence binding changed")
    _require(run["helper_sha256"] == producer["capture_helper_sha256"]
             and isinstance(run["source_commit"], str) and len(run["source_commit"]) == 40
             and all(char in "0123456789abcdef" for char in run["source_commit"]),
             "Capture source identity missing")
    state, inputs = _read(files["capture_state"]), _read(files["producer_inputs"])
    _require(set(state) == {"before_inputs", "after_inputs", "helper_before_sha256",
                            "helper_after_sha256", "commit_before", "commit_after"}
             and _equal(state["before_inputs"], inputs) and _equal(state["after_inputs"], inputs)
             and state["helper_before_sha256"] == state["helper_after_sha256"] == run["helper_sha256"]
             and state["commit_before"] == state["commit_after"] == run["source_commit"],
             "Capture source/producer drifted during its original execution")
    return run


def _bridge(parent, files):
    old_environment = _read(parent.files["golden_environment"])
    new_environment = _read(files["golden_environment"])
    expected = json.loads(json.dumps(old_environment))
    _require(expected["platform"] == {"system": "Darwin", "release": "27.0.0", "machine": "arm64"},
             "This baseline transition requires its original Darwin environment")
    expected["platform"]["release"] = "27.2.0"
    _require(_equal(new_environment, expected), "Unreviewed renderer/font/environment transition")
    for role in ("golden_structure", "golden_png"):
        _require(parent.files[role].read_bytes() == files[role].read_bytes(),
                 f"Historical drawing changed: {role}")
    old_capture, capture = _read(parent.files["golden_capture"]), _read(files["golden_capture"])
    added = []
    if "painted_primitives" not in old_capture:
        _require(capture.get("painted_primitives") == [], "Unreviewed native capture addition")
        old_capture["painted_primitives"] = []
        added = ["/painted_primitives"]
    _require(_equal(capture, old_capture), "Historical full native/scientific capture changed")
    _require(capture["document_sha256"] == parent.manifest["files"]["accepted_vsz"]["sha256"],
             "Baseline did not reopen immutable accepted authority")
    _require(_equal(_read(files["golden_inventory"]), capture["inventory"])
             and _equal(_read(files["golden_datasets"]), capture["datasets"]),
             "Full scientific/native capture projections changed")
    producer = _producer(files, capture)
    run = _process(parent, files, producer)
    facts = {"schema_version": 1, "parent_manifest_sha256": _hash(parent.manifest_path),
             "document_sha256": capture["document_sha256"],
             "environment_delta": [{"path": "/platform/release", "old": "27.0.0", "new": "27.2.0"}],
             "capture_added_empty_paths": added,
             "structure_sha256": _hash(files["golden_structure"]),
             "png_sha256": _hash(files["golden_png"]),
             "datasets_sha256": _hash(files["golden_datasets"]),
             "old_producer": _read(parent.files["golden_producer"]), "new_producer": producer,
             "source_commit": run["source_commit"]}
    _require(_equal(_read(files["bridge"]), facts), "Baseline bridge facts do not reproduce")
    return files


def validate_baseline(profile):
    """Recompute evidence; a review/status flag cannot grant authority."""
    path = profile.baseline_path
    _require(path is not None, "Selected baseline descriptor missing")
    _require(path == _ordinary(profile.manifest_path.parent, path.name), "Baseline descriptor escaped authority")
    _require(_hash(path) == profile.baseline_sha256, "Selected baseline descriptor changed")
    descriptor = _read(path)
    files = _pinned_files(path, descriptor)
    _require(files["parent_manifest"] == profile.manifest_path,
             "Baseline parent authority changed")
    parent = load_profile(profile.manifest_path)
    _require(parent.manifest == profile.manifest, "Historical profile authority changed")
    _bridge(parent, files)
    effective = {**parent.files, **{role: files[role] for role in GOLDEN_ROLES}}
    _require(profile.files == effective, "Baseline cannot replace scientific authority")
    return profile


def select_baseline(profile, environment):
    """Select one explicit complete baseline by exact environment, never OS alone."""
    _require(profile.baseline_path is None, "Select a baseline only from historical authority")
    _require(load_profile(profile.manifest_path).manifest == profile.manifest, "Historical authority changed")
    candidates = [profile] if _equal(_read(profile.files["golden_environment"]), environment) else []
    path = profile.manifest_path.with_name(profile.manifest_path.stem + SUFFIX)
    if path.exists() or path.is_symlink():
        _ordinary(path.parent, path.name)
        files = _pinned_files(path, _read(path))
        selected = replace(profile, files={**profile.files, **{role: files[role] for role in GOLDEN_ROLES}},
                           baseline_path=path, baseline_sha256=_hash(path))
        validate_baseline(selected)
        if _equal(_read(files["golden_environment"]), environment):
            candidates.append(selected)
    _require(len(candidates) == 1, "No unique verified rendering baseline for actual environment")
    return candidates[0]
