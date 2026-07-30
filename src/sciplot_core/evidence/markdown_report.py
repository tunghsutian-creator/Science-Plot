"""Write the evidence status Markdown report."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _write_markdown(path: Path, payload: dict[str, Any]) -> None:
    summary = payload["summary"]
    lines = [
        f"# SciPlot {summary['rule_count']}-rule evidence status",
        "",
        f"Generated: {payload['generated_at']}",
        "",
        "Lifecycle success, evidence strength, authorization, hashes, units, and final visual review are separate gates.",
        "",
        f"- Real-data evidence: {summary['real_data_evidence_count']}/{summary['rule_count']}",
        f"- Authorization ready: {summary['authorization_ready_count']}/{summary['rule_count']}",
        f"- Registered source hashes: {summary['source_hash_registered_count']}/{summary['rule_count']}",
        f"- Verified fixture hashes: {summary['fixture_hash_verified_count']}/{summary['rule_count']}",
        f"- Lifecycle passed: {summary['lifecycle_passed_count']}/{summary['rule_count']}",
        f"- Physical size passed: {summary['physical_size_passed_count']}/{summary['rule_count']}",
        "",
        "| Rule | Evidence | Authorization | Source hash | Fixture hash | Units | Lifecycle | Final size |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in payload["matrix"]:
        evidence = row["evidence"]
        lines.append(
            f"| `{row['rule_id']}` | `{evidence['tier']}` | `{evidence['authorization_status']}` | "
            f"`{evidence['source_hash_status']}` | `{evidence['fixture_hash_status']}` | "
            f"`{evidence['unit_status']}` | `{row['lifecycle_status']}` | "
            f"`{row.get('artifact_review', {}).get('status', 'not_run')}` |"
        )
    lines.extend(["", "## Rejected or non-selected candidates", ""])
    for item in payload["candidate_rejections"]:
        lines.append(
            f"- **{item.get('candidate', item.get('candidate_id', 'candidate'))}** — "
            f"`{item.get('decision', 'rejected')}`: {item.get('reason', '')}"
        )
    lines.extend(
        [
            "",
            "## Definitions",
            "",
            "- `fixture_hash_status=verified` means the current fixture bytes match a registered expected SHA-256.",
            "- `computed_unregistered` means current bytes are hashed but no independent expected fixture hash is registered.",
            "- `source_hash_status=registered` means an upstream source, archive, or archive-member hash is recorded.",
            "- `canonical_contract_only` means SciPlot has canonical axis units but source/output unit metadata is incomplete.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")
