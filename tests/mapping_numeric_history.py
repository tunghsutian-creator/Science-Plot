"""Portable path rebinding of synthetic records made by the actual 5dd producer.

This constructor is a generated regression fixture, not producer attestation.
It never relabels a v3 record as v2. Source/output bytes and numeric expectations
come from the recorded old public API; only path-dependent seals are rebound.
"""

import json
from pathlib import Path

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.json_hashing import canonical_json_sha256

HISTORY = Path(__file__).parent / "fixtures/generated_mapping_numeric_v2.json"


def read_json(path):
    return json.loads(path.read_text())


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def hashes(case):
    return {str(path.relative_to(case)): file_sha256(path) for path in sorted(case.rglob("*")) if path.is_file()}


def _replace_hashes(value, replacements):
    if isinstance(value, dict):
        return {key: _replace_hashes(item, replacements) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace_hashes(item, replacements) for item in value]
    return replacements.get(value, value) if isinstance(value, str) else value


def historical_case(root, name):
    corpus = read_json(HISTORY)
    template = corpus["cases"][name]
    case = root / name
    case.mkdir()
    for relative, text in template["files"].items():
        path = case / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text.replace(corpus["path_marker"], str(case.resolve())))
    manifest = case / template["execution_path"]
    record = read_json(manifest)
    assert record["version"] == 2
    base_hash = file_sha256(Path(record["base_request_snapshot"]))
    assert base_hash == file_sha256(Path(record["base_request"]))
    proposal_path = Path(record["proposal"])
    proposal = read_json(proposal_path)
    proposal["base_request_sha256"] = base_hash
    proposal_hash = canonical_json_sha256(proposal)
    replacements = {record["base_request_sha256"]: base_hash, record["proposal_sha256"]: proposal_hash}
    write_json(proposal_path, proposal)
    for path in case.rglob("*.json"):
        before = read_json(path)
        replaced = _replace_hashes(before, replacements)
        if replaced != before:
            write_json(path, replaced)
    for source in proposal["sources"]:
        assert file_sha256(Path(record["source_root"]) / source["relative_path"]) == source["sha256"]
    for output in record["outputs"]:
        assert file_sha256(Path(output["path"])) == output["sha256"]
    refresh_fixture_links(manifest)
    return case, manifest


def refresh_fixture_links(manifest):
    """Refresh only generated fixture links after path rebinding or a named attack."""
    record = read_json(manifest)
    ledger_path = Path(record["transform_ledger"])
    ledger = read_json(ledger_path)
    assert "source_numeric_encoding" not in ledger["steps"][0]["parameters"]
    seed_path = Path(record["request_seed"])
    seed = read_json(seed_path)
    seed["transform_ledger"] = ledger
    write_json(seed_path, seed)
    write_json(Path(record["request_candidate"]), seed)
    record["transform_steps"] = ledger["steps"]
    record["transform_ledger_sha256"] = file_sha256(ledger_path)
    record["request_seed_sha256"] = file_sha256(seed_path)
    record["request_candidate_initial_sha256"] = record["request_seed_sha256"]
    write_json(manifest, record)


def mixed_profile_attack(manifest, replacement_bytes):
    """Intentionally reseal one synthetic output; this is never historical proof."""
    record = read_json(manifest)
    output = record["outputs"][1]
    path = Path(output["path"])
    path.write_bytes(replacement_bytes)
    output["sha256"] = file_sha256(path)
    ledger_path = Path(record["transform_ledger"])
    ledger = read_json(ledger_path)
    artifact = next(item for item in ledger["steps"][0]["output_artifacts"] if item["path"] == str(path))
    artifact["sha256"] = output["sha256"]
    artifact["size_bytes"] = len(replacement_bytes)
    write_json(ledger_path, ledger)
    write_json(manifest, record)
    refresh_fixture_links(manifest)
