"""Immutable three-way golden-master helpers; deliberately no update mode."""

from dataclasses import dataclass
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.qa.rendering_regression import rendering_contract_regression, structural_diff
from sciplot_core.veusz_runtime import veusz_worker_environment


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


@dataclass(frozen=True)
class Profile:
    manifest_path: Path
    manifest: dict
    files: dict


@dataclass(frozen=True)
class NativeSnapshot:
    directory: Path
    structure: dict
    environment: dict
    image: Path
    inventory: dict
    datasets: dict
    capture: dict


def load_profile(manifest_path):
    """Resolve only fixture-relative files and require every byte pin to match."""
    path = Path(manifest_path).resolve()
    manifest, files = _read(path), {}
    if manifest.get("schema_version") != 1:
        raise AssertionError("Unsupported rendering profile schema")
    for required in ("profile_id", "family", "roles", "identity", "unsupported"):
        if required not in manifest:
            raise AssertionError(f"Rendering profile requires {required}")
    for role, record in manifest["files"].items():
        file = (path.parent / record["path"]).resolve()
        if not file.is_relative_to(path.parent):
            raise AssertionError(f"Pinned fixture escapes its directory: {role}")
        if not file.is_file() or file_sha256(file) != record["sha256"]:
            raise AssertionError(f"Immutable fixture changed or missing: {role}")
        files[role] = file
    required_files = {"accepted_vsz", "golden_png", "golden_structure", "golden_environment"}
    if not required_files.issubset(files) or not any(name == "raw" or name.startswith("raw_") for name in files):
        raise AssertionError("Accepted VSZ, raw source and complete pinned golden evidence are required")
    return Profile(path, manifest, files)


def _select(mapping, keys):
    return {key: mapping[key] for key in keys if key in mapping}


def selected_groups(mapping, groups):
    return {key: value for key, value in mapping.items() if any(key.startswith(group + "/") for group in groups)}


def effective_channels(value):
    """Hidden channel properties remain in the full inventory, not visible identity."""
    if isinstance(value, list):
        return [effective_channels(item) for item in value]
    if not isinstance(value, dict):
        return value
    hidden = [key[:-5] for key, item in value.items() if key.endswith("/hide") and item is True]
    return {key: effective_channels(item) for key, item in value.items()
            if not any(key.startswith(prefix + "/") and key != prefix + "/hide" for prefix in hidden)}


def project_xy_snapshot(payload, projection):
    """One declared graph and semantic XY series; no native-name inference."""
    nodes, graph_path = payload["inventory"], projection["graph"]
    graph = next(item for item in payload["geometry"]["graphs"] if item["path"] == graph_path)
    axes = {}
    for role, path in projection["axes"].items():
        if nodes[path]["type"] != "axis":
            raise AssertionError(f"Declared {role} is not a native axis")
        value = nodes[path]["settings"]
        axes[role] = _select(value, ["hide", "label", "direction", "min", "max", "log", "autoMirror",
                                     "outerticks", "otherPosition", "mode", "reflect"])
        if not value["hide"]:
            axes[role].update(selected_groups(value, ["Line", "Label", "TickLabels", "MajorTicks",
                                                     "MinorTicks", "GridLines", "MinorGridLines"]))
    series = []
    for declaration in projection["series"]:
        record = {"id": declaration["id"]}
        for path in declaration["paths"]:
            node = nodes[path]
            if node["type"] != "xy":
                raise AssertionError("Non-XY marks require an explicit mechanical role projector")
            value = node["settings"]
            arrays = [payload["datasets"][value[name]]["data"] for name in ("xData", "yData")]
            coordinates_hash = canonical_json_sha256(arrays)
            if record.get("coordinates_hash", coordinates_hash) != coordinates_hash:
                raise AssertionError("Line/point members disagree on source coordinates")
            record.update(coordinates_hash=coordinates_hash, point_count=len(arrays[0]))
            if not value["PlotLine/hide"]:
                if "line" in record:
                    raise AssertionError("Duplicate line channel in a semantic series")
                record["line"] = selected_groups(value, ["PlotLine"])
            if value["marker"] != "none" and (not value["MarkerFill/hide"] or not value["MarkerLine/hide"]):
                if "marker" in record:
                    raise AssertionError("Duplicate marker channel in a semantic series")
                record["marker"] = {**_select(value, ["marker", "markerSize", "thinfactor"]),
                                    **selected_groups(value, ["MarkerFill", "MarkerLine"])}
            record["errors_visible"] = record.get("errors_visible", False) or not value["ErrorBarLine/hide"]
        series.append(record)
    legends = []
    for path, node in nodes.items():
        value = node["settings"]
        if path.startswith(graph_path + "/") and node["type"] == "key" and not value["hide"]:
            legends.append({**_select(value, ["horzPosn", "vertPosn", "horzManual", "vertManual", "keyLength",
                                             "marginSize", "columns", "symbolswap"]),
                            **selected_groups(value, ["Text", "Border", "Background"])})
    result = {"canvas_mm": payload["geometry"]["pages"][0]["size_mm"],
              "plot_rectangle_mm": graph["plot_bounds_mm"], "margins_mm": graph["margins_mm"],
              "graph": selected_groups(nodes[graph_path]["settings"], ["Background", "Border"]),
              "axes": axes, "series": series, "legends": legends,
              "painted_text": [{key: val for key, val in item.items() if key != "widget_path"}
                               for item in payload["painted_text"]], "export": payload["export"]}
    return effective_channels(result)


def capture_native(document, output_dir, projection, *, font_files=None):
    """Run native capture in its correct Qt environment, then project declared roles.

    A custom projection callable receives the complete captured evidence for
    categorical primitives. The built-in dictionary form supports XY profiles.
    """
    document, output = Path(document).resolve(), Path(output_dir).resolve()
    if document.is_relative_to(output):
        raise AssertionError("Capture output must be separate from its immutable input")
    output.mkdir(parents=True, exist_ok=True)
    if font_files is None:
        font_files = {path.name: str(path) for path in sorted(Path("/System/Library/Fonts/Supplemental").glob("Arial*.ttf"))}
    request = output / "capture-request.json"
    _write(request, {"document": str(document), "output": str(output),
                     "font_files": {name: str(path) for name, path in font_files.items()}})
    result = subprocess.run([sys.executable, str(Path(__file__).with_name("rendering_profiles_native.py")), str(request)],
                            env=veusz_worker_environment(), capture_output=True, text=True, timeout=120, check=False)
    (output / "native-worker.log").write_text(result.stdout + result.stderr, encoding="utf-8")
    if result.returncode:
        raise AssertionError(f"Native profile capture failed ({result.returncode}): {output / 'native-worker.log'}\n{result.stderr[-2000:]}")
    payload = _read(output / "capture.json")
    structure = projection(payload) if callable(projection) else project_xy_snapshot(payload, projection)
    if not structure:
        raise AssertionError("Profile projection must retain a nonempty resolved structure")
    _write(output / "structure.json", structure)
    return NativeSnapshot(output, structure, _read(output / "environment.json"), output / "native.png",
                          payload["inventory"], payload["datasets"], payload)


def _assert_authority(profile, accepted):
    fresh = load_profile(profile.manifest_path)
    if fresh.manifest != profile.manifest:
        raise AssertionError("Profile manifest changed during its regression run")
    if accepted.capture.get("document_sha256") != profile.manifest["files"]["accepted_vsz"]["sha256"]:
        raise AssertionError("Accepted-route snapshot did not reopen the immutable accepted VSZ")


def _normalize_native_text(structure, policy):
    """One reviewed native symbol spelling; not a general markup interpreter."""
    from sciplot_core._paths import REPO_ROOT

    value = deepcopy(structure)
    for rule in policy:
        evidence = rule.get("renderer_evidence", {})
        source = REPO_ROOT / "third_party/veusz/veusz/utils/textrender.py"
        if (rule.get("from") != r"\omega (rad s⁻¹)" or rule.get("to") != "ω (rad s⁻¹)"
                or evidence.get("file") != str(source.relative_to(REPO_ROOT))
                or evidence.get("sha256") != file_sha256(source)
                or evidence.get("symbol") != r"\omega" or evidence.get("codepoint") != "U+03C9"):
            raise AssertionError("Unreviewed native text equivalence or changed renderer evidence")
        for pointer in rule["paths"]:
            keys = pointer.lstrip("/").split("/")
            if not (pointer == "/axes/x/label" or
                    (len(keys) == 3 and keys[0] == "painted_text" and keys[1].isdigit() and keys[2] == "text")):
                raise AssertionError("Native text equivalence requires an explicit reviewed text path")
            target = value
            for key in keys[:-1]:
                target = target[int(key)] if isinstance(target, list) else target[key]
            if target[keys[-1]] == rule["from"]:
                target[keys[-1]] = rule["to"]
    return value


def _compare_golden(profile, snapshot, output):
    golden = _read(profile.files["golden_structure"])
    policy = profile.manifest.get("native_text_equivalences", [])
    result = rendering_contract_regression(
        _normalize_native_text(golden, policy), _normalize_native_text(snapshot.structure, policy),
        old_image=profile.files["golden_png"], new_image=snapshot.image, output_dir=Path(output),
        old_environment=_read(profile.files["golden_environment"]), new_environment=snapshot.environment)
    # Full original encoded states and their differences remain reviewable;
    # pinned fixture files are only read, never rewritten by normalization.
    raw = structural_diff(golden, snapshot.structure)
    for name, value in (("raw-golden-structure", golden), ("raw-current-structure", snapshot.structure),
                        ("raw-structural-diff", raw)):
        _write(Path(output) / (name + ".json"), value)
    result["raw_structure"] = raw
    result["native_text_equivalences"] = policy
    if policy and result["raster"]["raw_changed_pixels"] != 0:
        result["status"] = "failed"
        result["text_equivalence_gate"] = "requires_exact_pixels_not_antialias_tolerance"
    _write(Path(output) / "regression.json", result)
    return result


def assert_accepted_golden(profile, accepted, *, output_dir):
    """First gate: stop on native environment drift before rebuilding either route."""
    _assert_authority(profile, accepted)
    result = _compare_golden(profile, accepted, output_dir)
    assert result["status"] == "passed", f"Accepted native golden changed: {output_dir}"
    return result


def assert_three_way(profile, accepted, legacy, managed, *, output_dir):
    """Compare every route to immutable evidence; never compare only two new runs."""
    # Recheck pins after generation, including raw and accepted native inputs.
    _assert_authority(profile, accepted)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    gates = {}
    for name, snapshot in (("accepted_current_environment", accepted), ("legacy_fresh_replay", legacy), ("managed", managed)):
        gates[name] = _compare_golden(profile, snapshot, output / name)
    report = {"profile_id": profile.manifest["profile_id"], "kind": "three_way_immutable_golden_regression",
              "status": "passed" if all(item["status"] == "passed" for item in gates.values()) else "failed",
              "manifest_sha256": file_sha256(profile.manifest_path), "gates": gates,
              "identity": profile.manifest["identity"], "unsupported": profile.manifest["unsupported"]}
    _write(output / "three-way-report.json", report)
    assert report["status"] == "passed", f"Three-way profile failed: {output / 'three-way-report.json'}"
    return report
