"""Exercise historical rheology through production owners, never repaint fixtures."""

import csv
import json
from pathlib import Path
import shutil

from rendering_profiles_helpers import assert_accepted_golden, assert_three_way, capture_native, load_profile
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.plot_engine.service import PlotService
from sciplot_core.plot_engine.storage import load_head
from sciplot_core.studio_core.veusz_save import save_veusz_document_from_spec


FIXTURES = Path(__file__).parent / "fixtures/rendering_profiles/rheology-v1"


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def audit_source_points(profile):
    """Audit literal raw row selection against both the table and historical spec."""
    case = profile.manifest["identity"]["scientific_quantity"]
    column = {"Storage Modulus": 4, "Loss Modulus": 5}[case]
    historical = read(profile.files["historical_spec"])
    evidence = []
    for index, series in enumerate(historical["series"]):
        raw = profile.files["raw_" + series["label"]]
        rows = list(csv.reader(raw.read_text(encoding="utf-16").splitlines(), delimiter="\t"))
        assert rows[7][3] == "Angular Frequency" and rows[7][column] == case
        assert rows[9][3] == "[rad/s]" and rows[9][column] == "[Pa]"
        points = [[float(row[3]), float(row[column])] for row in rows[10:26]]
        assert len(rows) == 26 and len(points) == 16
        assert all(len(row) == 12 for row in rows[10:26])
        assert points == [list(pair) for pair in zip(series["x_values"], series["y_values"], strict=True)]
        table = list(csv.reader(profile.files[f"paired_{index + 1}"].read_text().splitlines()))
        assert table[:3] == [["Angular Frequency", case], ["rad/s", "Pa"], [series["label"]] * 2]
        assert [[float(value) for value in row] for row in table[3:]] == points
        evidence.append({"sample": series["label"], "points": len(points), "raw_sha256": file_sha256(raw),
                         "selection": {"rows": [10, 26], "columns": [3, column]}, "exact": True})
    return evidence


def run_profile(case_id, output):
    """Golden first, legacy replay, canonical creation, three-way gate and rebuild."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    profile = load_profile(FIXTURES / ("manifest-" + case_id + ".json"))
    source_evidence = audit_source_points(profile)
    roles = profile.manifest["roles"]
    accepted = capture_native(profile.files["accepted_vsz"], output / "accepted", roles["accepted"])
    assert_accepted_golden(profile, accepted, output_dir=output / "accepted-first-gate")

    # A fresh legacy native is built from the original saved spec plus its
    # historical six-setting color correction. It is never copied from golden.
    spec = read(profile.files["replay_spec"])
    replay = output / "legacy-document/document.vsz"
    save_veusz_document_from_spec(replay, spec, spec_path=profile.files["replay_spec"])
    legacy = capture_native(replay, output / "legacy", roles["legacy"])

    request = read(profile.files["managed_request"])
    for index, source in enumerate(request["data_binding"]["data_sources"]):
        target = output / "sources" / f"series-{index + 1}.csv"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(profile.files[f"paired_{index + 1}"], target)
        assert file_sha256(target) == source["sha256"]
        source["path"] = str(target.resolve())
    request["data_binding"]["provenance"] = {"fixture_manifest": str(profile.manifest_path),
        "fixture_manifest_sha256": file_sha256(profile.manifest_path), "source_point_audit": source_evidence}
    request["idempotency_key"] += "-" + file_sha256(profile.manifest_path)[:12]
    request["out"] = str((output / "managed-artifacts").resolve())
    write(output / "managed-request.json", request)
    service = PlotService()
    try:
        created = service.create(request)
        write(output / "managed-created.json", created)
        assert created["ready_to_use"], created
        root = Path(created["plot"])
        head = load_head(root)
        binding = head["binding"]
        native = Path(binding["document"])
        ir = read(binding["ir_path"])
        write(output / "managed-ir.json", ir)
        managed = capture_native(native, output / "managed", roles["managed"])
        report = assert_three_way(profile, accepted, legacy, managed, output_dir=output / "comparison")
        before_png = (native.parent / "preview.png").read_bytes()
        before_native = read(native.parent / "build.json")["native_state_hash"]
        shutil.rmtree(Path(binding["output"]))
        shutil.rmtree(root / "ir")
        rebuilt = service.export(root)
        assert rebuilt["ready_to_use"] and rebuilt["scientific_hash"] == created["scientific_hash"]
        assert read(binding["ir_path"]) == ir
        assert (native.parent / "preview.png").read_bytes() == before_png
        assert read(native.parent / "build.json")["native_state_hash"] == before_native
        write(output / "rebuild.json", {"status": "passed", "source_points": source_evidence,
            "scientific_hash": created["scientific_hash"], "ir_hash": ir["ir_hash"],
            "native_state_hash": before_native, "identical_ir": True, "identical_preview": True,
            "exports": rebuilt["exports"], "deleted_backend_artifacts_and_ir": True})
        load_profile(profile.manifest_path)
        return report
    finally:
        service.close()
