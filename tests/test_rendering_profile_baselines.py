"""Generated controls for additive baselines; no private/native fixture reads."""

from copy import deepcopy
from hashlib import sha256
import json
import sys

from PIL import Image, ImageDraw
import pytest

from rendering_profile_baselines import FILE_ROLES, select_baseline, validate_baseline
from rendering_profiles_helpers import NativeSnapshot, assert_three_way, load_profile


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n")


def _sha(path):
    return sha256(path.read_bytes()).hexdigest()


def _pin(root, path):
    return {"path": path.relative_to(root).as_posix(), "sha256": _sha(path)}


def _case(tmp_path, *, old_primitives=False):
    root = tmp_path / "fixture"
    root.mkdir()
    (root / "raw.csv").write_text("x,y\n1,2\n")
    (root / "accepted.vsz").write_text("# generated authority\n")
    image = Image.new("RGB", (50, 50), "white")
    ImageDraw.Draw(image).line((10, 10, 10, 40), fill="black", width=2)
    image.save(root / "native.png")
    environment = {"platform": {"system": "Darwin", "release": "27.0.0", "machine": "arm64"},
                   "export": {"preview_dpi": 150, "antialias": 1}, "font_files_sha256": {"fixed": "font"},
                   "python": "3.14.7", "python_binary_sha256": "binary",
                   "packages": {"PyQt6": "test", "PyQt6-Qt6": "test", "numpy": "test"}}
    structure = {"axis": {"width_pt": .8}}
    capture = {"document_sha256": _sha(root / "accepted.vsz"), "inventory": {"axis": {"width": .8}},
               "datasets": {"observations": [1, 2]}}
    if old_primitives:
        capture["painted_primitives"] = [{"kind": "bar", "points": [1, 2]}]
    producer = {"runtime_identity": "old-runtime", "capture_helper_sha256": "old-helper",
                "document_sha256": capture["document_sha256"]}
    for name, value in (("environment", environment), ("structure", structure),
                        ("capture", capture), ("producer", producer)):
        _write(root / (name + ".json"), value)
    roles = {"raw": "raw.csv", "accepted_vsz": "accepted.vsz", "golden_png": "native.png",
             "golden_structure": "structure.json", "golden_environment": "environment.json",
             "golden_capture": "capture.json", "golden_producer": "producer.json"}
    manifest = {"schema_version": 1, "profile_id": "generated", "family": "test", "roles": {},
                "identity": {"science": "original values"}, "unsupported": [],
                "files": {role: _pin(root, root / name) for role, name in roles.items()}}
    _write(root / "manifest.json", manifest)
    parent = load_profile(root / "manifest.json")
    bundle = root / "new-baseline"
    bundle.mkdir()
    files = {"parent_manifest": root / "manifest.json"}
    new_environment = deepcopy(environment)
    new_environment["platform"]["release"] = "27.2.0"
    new_capture = deepcopy(capture)
    new_capture.setdefault("painted_primitives", [])
    (bundle / "capture_helper.py").write_text("# generated capture source\n")
    (bundle / "capture-runner.py").write_text("# generated child driver\n")
    files.update(capture_helper=bundle / "capture_helper.py", capture_driver=bundle / "capture-runner.py")
    files["capture_controller"] = bundle / "capture-controller.py"
    files["capture_controller"].write_text("# generated original waiter\n")
    files["native_pdf"], files["native_tiff"] = bundle / "native.pdf", bundle / "native.tiff"
    files["native_pdf"].write_bytes(b"generated opaque PDF closure member\n")
    files["native_tiff"].write_bytes(b"generated opaque TIFF closure member\n")
    inputs = {"sciplot": {"source.py": "source"}, "veusz": {"renderer.py": "renderer"},
              "python": "3.14.7 generated", "executable": "binary", "installation": "/renderer",
              "environment": {"QT_QPA_PLATFORM": "offscreen"}, "versions": environment["packages"]}
    new_producer = {"runtime_identity": sha256(json.dumps(inputs, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
                    "capture_helper_sha256": _sha(files["capture_helper"]), "document_sha256": capture["document_sha256"]}
    for role, value in (("golden_environment", new_environment), ("golden_structure", structure),
                        ("golden_capture", new_capture), ("golden_producer", new_producer),
                        ("golden_inventory", capture["inventory"]), ("golden_datasets", capture["datasets"]),
                        ("producer_inputs", inputs)):
        files[role] = bundle / (role + ".json")
        _write(files[role], value)
    files["golden_png"] = bundle / "native.png"
    files["golden_png"].write_bytes((root / "native.png").read_bytes())
    files["capture_request"] = bundle / "capture-request.json"
    _write(files["capture_request"], {"document": str(root / "accepted.vsz"), "output": str(bundle), "font_files": {"font": "/font"}})
    commit = "a" * 40
    run = {"schema_version": 1, "argv": [sys.executable, str(files["capture_driver"]), str(files["capture_request"])],
           "cwd": str(root), "pid": 123, "waited_pid": 123, "exit_code": 0,
           "started_ns": 1, "finished_ns": 2, "stdout": "", "stderr": "",
           "stdout_sha256": sha256(b"").hexdigest(), "stderr_sha256": sha256(b"").hexdigest(),
           "request_sha256": _sha(files["capture_request"]), "driver_sha256": _sha(files["capture_driver"]),
           "helper_sha256": _sha(files["capture_helper"]), "producer_sha256": _sha(files["golden_producer"]),
           "controller_sha256": _sha(files["capture_controller"]), "controller_pid": 122,
           "source_commit": commit}
    files["capture_run"] = bundle / "capture-run.json"
    _write(files["capture_run"], run)
    files["capture_state"] = bundle / "capture-state.json"
    _write(files["capture_state"], {"before_inputs": inputs, "after_inputs": inputs,
           "helper_before_sha256": run["helper_sha256"], "helper_after_sha256": run["helper_sha256"],
           "commit_before": commit, "commit_after": commit})
    files["bridge"] = bundle / "bridge.json"
    _write(files["bridge"], {"schema_version": 1, "parent_manifest_sha256": _sha(parent.manifest_path),
           "document_sha256": capture["document_sha256"],
           "environment_delta": [{"path": "/platform/release", "old": "27.0.0", "new": "27.2.0"}],
           "capture_added_empty_paths": [] if old_primitives else ["/painted_primitives"],
           "structure_sha256": _sha(files["golden_structure"]), "png_sha256": _sha(files["golden_png"]),
           "datasets_sha256": _sha(files["golden_datasets"]), "old_producer": producer,
           "new_producer": new_producer, "source_commit": commit})
    descriptor = root / "manifest--darwin-27.2.0-v1.json"
    _write(descriptor, {"schema_version": 2, "kind": "sciplot_native_environment_baseline",
                       "baseline_id": "darwin-27.2.0-arm64-v1", "files": {k: _pin(root, p) for k, p in files.items()}})
    assert set(files) == FILE_ROLES
    return parent, new_environment, descriptor, files


def _repin(descriptor, files):
    value = json.loads(descriptor.read_text())
    value["files"] = {role: _pin(descriptor.parent, path) for role, path in files.items()}
    _write(descriptor, value)


@pytest.mark.parametrize("old_primitives", [False, True])
def test_complete_baseline_inherits_authority_and_all_three_strict_gates(tmp_path, old_primitives):
    parent, environment, descriptor, files = _case(tmp_path, old_primitives=old_primitives)
    before = {path: path.read_bytes() for path in parent.files.values()}
    selected = select_baseline(parent, environment)
    assert selected.manifest == parent.manifest and selected.manifest_path == parent.manifest_path
    assert selected.baseline_path == descriptor
    assert select_baseline(parent, json.loads(parent.files["golden_environment"].read_text())) == parent
    snapshot = NativeSnapshot(tmp_path, json.loads(files["golden_structure"].read_text()), environment,
                              files["golden_png"], {}, {}, json.loads(files["golden_capture"].read_text()))
    report = assert_three_way(selected, snapshot, snapshot, snapshot, output_dir=tmp_path / "comparison")
    assert report["status"] == "passed" and report["baseline_descriptor"]["sha256"] == _sha(descriptor)
    assert all(gate["environment"]["status"] == "passed" for gate in report["gates"].values())
    assert {path: path.read_bytes() for path in before} == before


@pytest.mark.parametrize("change", ["unknown_release", "font", "extra_key", "boolean_dpi", "numeric_type"])
def test_actual_environment_requires_unique_complete_type_sensitive_match(tmp_path, change):
    parent, environment, _, _ = _case(tmp_path)
    if change == "unknown_release":
        environment["platform"]["release"] = "27.3.0"
    elif change == "font":
        environment["font_files_sha256"]["fixed"] = "other"
    elif change == "extra_key":
        environment["additional"] = "unknown"
    elif change == "numeric_type":
        environment["export"]["preview_dpi"] = 150.0
    else:
        environment["export"]["antialias"] = True
    with pytest.raises(AssertionError, match="No unique"):
        select_baseline(parent, environment)


@pytest.mark.parametrize("role,mutation", [
    ("golden_environment", "font"), ("golden_environment", "old_environment"),
    ("golden_structure", "structure"), ("golden_capture", "science"),
    ("golden_capture", "document"), ("golden_capture", "primitive"),
    ("golden_inventory", "inventory"), ("golden_datasets", "datasets"),
    ("golden_producer", "helper"), ("producer_inputs", "producer"),
    ("capture_run", "wait"), ("capture_run", "exit"), ("capture_run", "argv"),
    ("capture_run", "stream"), ("capture_state", "source_drift"),
    ("bridge", "approval"), ("bridge", "bridge"),
])
def test_repinned_forgery_cannot_replace_recomputed_transition_facts(tmp_path, role, mutation):
    parent, environment, descriptor, files = _case(tmp_path)
    value = json.loads(files[role].read_text())
    if mutation == "font":
        value["font_files_sha256"]["fixed"] = "other"
    elif mutation == "old_environment":
        value["platform"]["release"] = "27.0.0"
    elif mutation == "structure":
        value["axis"]["width_pt"] = .9
    elif mutation == "science":
        value["datasets"]["observations"][0] = 100
    elif mutation == "document":
        value["document_sha256"] = "replacement"
    elif mutation == "primitive":
        value["painted_primitives"] = [{"kind": "new"}]
    elif mutation == "inventory":
        value["axis"]["width"] = 1
    elif mutation == "datasets":
        value["observations"] = [100, 2]
    elif mutation == "helper":
        value["capture_helper_sha256"] = "forged"
    elif mutation == "producer":
        value["python"] = "different"
    elif mutation == "wait":
        value["waited_pid"] = 456
    elif mutation == "exit":
        value["exit_code"] = 1
    elif mutation == "argv":
        value["argv"][-1] = "/other/request.json"
    elif mutation == "stream":
        value["stdout"] = "unbound text"
    elif mutation == "source_drift":
        value["after_inputs"]["sciplot"] = {"source.py": "changed"}
    elif mutation == "approval":
        value["approved"] = True
    else:
        value["environment_delta"] = []
    _write(files[role], value)
    _repin(descriptor, files)
    with pytest.raises(AssertionError):
        select_baseline(parent, environment)


def test_even_one_pixel_change_and_coordinated_current_drift_fail(tmp_path):
    parent, environment, descriptor, files = _case(tmp_path)
    with Image.open(files["golden_png"]) as original:
        image = original.convert("RGB")
    image.putpixel((10, 10), (1, 1, 1))
    image.save(files["golden_png"])
    _repin(descriptor, files)
    with pytest.raises(AssertionError, match="Historical drawing"):
        select_baseline(parent, environment)


@pytest.mark.parametrize("alias", ["file", "directory", "descriptor"])
def test_in_root_symlinks_are_rejected_before_resolution(tmp_path, alias):
    parent, environment, descriptor, files = _case(tmp_path)
    if alias == "descriptor":
        target = descriptor
    elif alias == "directory":
        target = files["golden_png"].parent
    else:
        target = files["golden_png"]
    saved = target.with_name(target.name + "-original")
    target.rename(saved)
    target.symlink_to(saved.name, target_is_directory=saved.is_dir())
    with pytest.raises(AssertionError, match="ordinary"):
        select_baseline(parent, environment)


def test_descriptor_pin_is_revalidated_after_selection(tmp_path):
    parent, environment, descriptor, files = _case(tmp_path)
    selected = select_baseline(parent, environment)
    _write(files["bridge"], {"approved": True})
    _repin(descriptor, files)
    with pytest.raises(AssertionError, match="descriptor changed"):
        validate_baseline(selected)


def test_historical_raw_and_parent_pins_remain_required(tmp_path):
    parent, environment, _, _ = _case(tmp_path)
    parent.files["raw"].write_text("x,y\n1,200\n")
    with pytest.raises(AssertionError, match="Immutable fixture changed"):
        select_baseline(parent, environment)


def test_selected_descriptor_symlink_is_rejected_before_read(tmp_path, monkeypatch):
    parent, environment, descriptor, _ = _case(tmp_path)
    selected = select_baseline(parent, environment)
    original = descriptor.with_name("saved-descriptor.json")
    descriptor.rename(original)
    descriptor.symlink_to(original.name)
    from rendering_profile_baselines import _hash
    import rendering_profile_baselines as baselines

    def guarded_hash(path):
        assert path != descriptor, "A substituted descriptor was read before lstat"
        return _hash(path)

    monkeypatch.setattr(baselines, "_hash", guarded_hash)
    with pytest.raises(AssertionError, match="ordinary"):
        validate_baseline(selected)


@pytest.mark.parametrize("mutation", ["unknown_key", "escape", "missing", "alias", "parent", "duplicate_json"])
def test_descriptor_is_closed_and_cannot_substitute_or_escape_ancestry(tmp_path, mutation):
    parent, environment, descriptor, files = _case(tmp_path)
    value = json.loads(descriptor.read_text())
    if mutation == "unknown_key":
        value["approved"] = True
    elif mutation == "escape":
        value["files"]["golden_png"]["path"] = "../native.png"
    elif mutation == "missing":
        del value["files"]["capture_state"]
    elif mutation == "alias":
        value["files"]["golden_datasets"] = value["files"]["golden_inventory"]
    elif mutation == "parent":
        other = descriptor.parent / "other-manifest.json"
        other.write_bytes(parent.manifest_path.read_bytes())
        value["files"]["parent_manifest"] = _pin(descriptor.parent, other)
    else:
        descriptor.write_text(descriptor.read_text().replace('"schema_version": 2,', '"schema_version": 2, "schema_version": 2,'))
        with pytest.raises(AssertionError, match="Duplicate"):
            select_baseline(parent, environment)
        return
    _write(descriptor, value)
    with pytest.raises(AssertionError):
        select_baseline(parent, environment)
