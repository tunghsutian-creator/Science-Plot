# ruff: noqa: E501
# Embedded self-contained HTML/CSS is intentionally kept literal for auditability.

from __future__ import annotations

import csv
import hashlib
import html
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sciplot_core._paths import real_world_fixture_root
from sciplot_core._utils import file_sha256, json_safe
from sciplot_core.materials_rules import SemanticRule

DATA_SUFFIXES = frozenset({".csv", ".tsv", ".txt", ".dat", ".tab", ".xlsx", ".xls"})
HASH_PATTERN = re.compile(r"^[0-9a-fA-F]{32}(?:[0-9a-fA-F]{32})?$")
def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _fixture_files(fixture: Path) -> list[Path]:
    if fixture.is_file():
        return [fixture]
    if not fixture.is_dir():
        return []
    return sorted(
        path
        for path in fixture.rglob("*")
        if path.is_file() and path.suffix.casefold() in DATA_SUFFIXES
    )


def _fixture_hash_inventory(fixture: Path) -> tuple[list[dict[str, str]], str | None]:
    files = _fixture_files(fixture)
    inventory: list[dict[str, str]] = []
    tree_digest = hashlib.sha256()
    for path in files:
        relative = path.name if fixture.is_file() else path.relative_to(fixture).as_posix()
        sha256 = file_sha256(path)
        inventory.append({"path": relative, "sha256": sha256})
        tree_digest.update(relative.encode("utf-8"))
        tree_digest.update(b"\0")
        tree_digest.update(sha256.encode("ascii"))
        tree_digest.update(b"\n")
    return inventory, tree_digest.hexdigest() if inventory else None


def _provenance_candidates(fixture: Path, metadata: dict[str, Any], repo_root: Path) -> list[Path]:
    candidates: list[Path] = []
    provenance_value = metadata.get("provenance_path")
    if isinstance(provenance_value, str) and provenance_value.strip():
        candidates.append((real_world_fixture_root(repo_root=repo_root) / provenance_value).resolve())
    base = fixture if fixture.is_dir() else fixture.parent
    candidates.extend(
        [
            base / "source_provenance.json",
            base / "digitization_provenance.json",
        ]
    )
    seen: set[Path] = set()
    return [candidate for candidate in candidates if not (candidate in seen or seen.add(candidate))]


def _expected_fixture_hashes(payload: object) -> dict[str, str]:
    expected: dict[str, str] = {}

    def visit(value: object) -> None:
        if isinstance(value, dict):
            path_value = next(
                (
                    value.get(key)
                    for key in ("fixture_file", "fixture_path", "path")
                    if isinstance(value.get(key), str) and str(value.get(key)).strip()
                ),
                None,
            )
            hash_value = next(
                (
                    value.get(key)
                    for key in ("fixture_sha256", "sha256")
                    if isinstance(value.get(key), str) and HASH_PATTERN.fullmatch(str(value.get(key)))
                ),
                None,
            )
            if path_value and hash_value:
                expected[Path(str(path_value)).name] = str(hash_value).casefold()
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(payload)
    return expected


def _registered_source_hashes(payload: object) -> list[str]:
    registered: list[str] = []

    def visit(value: object, parent_key: str = "") -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                key_token = key.casefold()
                if (
                    isinstance(item, str)
                    and HASH_PATTERN.fullmatch(item)
                    and ("source" in key_token or "archive" in key_token or "member" in key_token)
                ):
                    registered.append(item.casefold())
                visit(item, key)
        elif isinstance(value, list):
            for item in value:
                visit(item, parent_key)

    visit(payload)
    return sorted(set(registered))


def _fixture_hash_status(
    fixture: Path,
    inventory: list[dict[str, str]],
    metadata: dict[str, Any],
    provenance: dict[str, Any],
) -> tuple[str, list[dict[str, str]]]:
    expected = _expected_fixture_hashes(provenance)
    if fixture.is_file():
        direct = provenance.get("fixture_sha256") or metadata.get("sha256") or metadata.get("fixture_sha256")
        if isinstance(direct, str) and HASH_PATTERN.fullmatch(direct):
            expected.setdefault(fixture.name, direct.casefold())
    checks: list[dict[str, str]] = []
    for item in inventory:
        expected_hash = expected.get(Path(item["path"]).name)
        checks.append(
            {
                **item,
                "expected_sha256": expected_hash or "",
                "status": (
                    "verified"
                    if expected_hash and expected_hash == item["sha256"]
                    else ("mismatch" if expected_hash else "computed_unregistered")
                ),
            }
        )
    if not checks:
        return "missing", checks
    if any(item["status"] == "mismatch" for item in checks):
        return "mismatch", checks
    if all(item["status"] == "verified" for item in checks):
        return "verified", checks
    return "computed_unregistered", checks


def _authorization_status(
    evidence: dict[str, Any],
    metadata: dict[str, Any],
    provenance: dict[str, Any],
) -> str:
    explicit = metadata.get("authorization_status") or provenance.get("authorization_status")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    if not evidence.get("real_data_evidence"):
        return "rejected_as_real_data"
    tier = str(evidence.get("tier") or "")
    license_value = str(evidence.get("license") or provenance.get("license") or "")
    if license_value and "not asserted" not in license_value.casefold():
        return "license_recorded"
    if tier.startswith("user_authorized"):
        return "user_authorized"
    if tier == "archived_project_data":
        return "user_authorized_archive"
    return "authorization_not_registered"


def _first_mapping(*values: object) -> dict[str, Any]:
    for value in values:
        if isinstance(value, dict) and value:
            return {str(key): item for key, item in value.items()}
    return {}


def enrich_rule_evidence(
    rule: SemanticRule,
    evidence: dict[str, Any],
    *,
    fixture: Path,
    repo_root: Path,
) -> dict[str, Any]:
    metadata = evidence.get("manifest_metadata") if isinstance(evidence.get("manifest_metadata"), dict) else {}
    provenance_path = next(
        (candidate for candidate in _provenance_candidates(fixture, metadata, repo_root) if candidate.exists()),
        None,
    )
    provenance = _load_json(provenance_path) if provenance_path is not None else {}
    inventory, tree_sha256 = _fixture_hash_inventory(fixture)
    fixture_hash_status, hash_checks = _fixture_hash_status(fixture, inventory, metadata, provenance)
    source_hashes = _registered_source_hashes({"metadata": metadata, "provenance": provenance})
    source_units = _first_mapping(metadata.get("source_units"), provenance.get("source_units"))
    output_units = _first_mapping(metadata.get("output_units"), provenance.get("output_units"))
    canonical_units = {
        "x": rule.x_axis.canonical_unit,
        "y": rule.y_axis.canonical_unit,
    }
    if source_units and output_units:
        unit_status = "source_and_output_registered"
    elif source_units:
        unit_status = "source_registered_canonical_output"
    else:
        unit_status = "canonical_contract_only"
    limitations = [
        str(value)
        for key in ("control_mode_limitation", "replicate_policy")
        for value in [provenance.get(key)]
        if isinstance(value, str) and value.strip()
    ]
    merged = dict(evidence)
    merged.pop("manifest_metadata", None)
    merged.update(
        {
            "source_url": evidence.get("source_url") or metadata.get("source_url") or provenance.get("source_url"),
            "doi": evidence.get("doi") or metadata.get("doi") or provenance.get("doi"),
            "license": evidence.get("license") or metadata.get("license") or provenance.get("license"),
            "authorization_status": _authorization_status(evidence, metadata, provenance),
            "source_hash_status": "registered" if source_hashes else "unregistered",
            "registered_source_hash_count": len(source_hashes),
            "fixture_hash_status": fixture_hash_status,
            "fixture_tree_sha256": tree_sha256,
            "fixture_hashes": hash_checks,
            "source_units": source_units,
            "output_units": output_units,
            "canonical_units": canonical_units,
            "unit_status": unit_status,
            "provenance_path": str(provenance_path) if provenance_path is not None else None,
            "rejection_reason": (
                None
                if evidence.get("real_data_evidence")
                else str(evidence.get("description") or "Not accepted as real-data evidence.")
            ),
            "limitations": limitations,
        }
    )
    return merged


def load_candidate_rejections(*, repo_root: Path) -> list[dict[str, Any]]:
    payload = _load_json(real_world_fixture_root(repo_root=repo_root) / "candidate_rejections.json")
    entries = payload.get("entries") if isinstance(payload.get("entries"), list) else []
    return [entry for entry in entries if isinstance(entry, dict)]


def _status_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    authorization_ready = {
        "license_verified",
        "license_recorded",
        "user_authorized",
        "user_authorized_archive",
    }
    return {
        "rule_count": len(rows),
        "real_data_evidence_count": sum(bool(row["evidence"].get("real_data_evidence")) for row in rows),
        "authorization_ready_count": sum(
            row["evidence"].get("authorization_status") in authorization_ready for row in rows
        ),
        "source_hash_registered_count": sum(
            row["evidence"].get("source_hash_status") == "registered" for row in rows
        ),
        "fixture_hash_verified_count": sum(
            row["evidence"].get("fixture_hash_status") == "verified" for row in rows
        ),
        "fixture_hash_computed_count": sum(
            row["evidence"].get("fixture_hash_status") in {"verified", "computed_unregistered"} for row in rows
        ),
        "source_and_output_units_registered_count": sum(
            row["evidence"].get("unit_status") == "source_and_output_registered" for row in rows
        ),
        "lifecycle_passed_count": sum(row.get("lifecycle_status") == "passed" for row in rows),
        "physical_size_passed_count": sum(
            row.get("artifact_review", {}).get("status") == "passed" for row in rows
        ),
        "real_data_gap_count": sum(not row["evidence"].get("real_data_evidence") for row in rows),
    }


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = [
        "rule_id",
        "tier",
        "real_data_evidence",
        "authorization_status",
        "source_hash_status",
        "fixture_hash_status",
        "unit_status",
        "canonical_x_unit",
        "canonical_y_unit",
        "lifecycle_status",
        "physical_size_status",
        "source_url",
        "doi",
        "license",
        "fixture_path",
        "fixture_tree_sha256",
        "provenance_path",
        "rejection_reason",
        "limitations",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            evidence = row["evidence"]
            writer.writerow(
                {
                    "rule_id": row["rule_id"],
                    "tier": evidence.get("tier"),
                    "real_data_evidence": evidence.get("real_data_evidence"),
                    "authorization_status": evidence.get("authorization_status"),
                    "source_hash_status": evidence.get("source_hash_status"),
                    "fixture_hash_status": evidence.get("fixture_hash_status"),
                    "unit_status": evidence.get("unit_status"),
                    "canonical_x_unit": evidence.get("canonical_units", {}).get("x"),
                    "canonical_y_unit": evidence.get("canonical_units", {}).get("y"),
                    "lifecycle_status": row.get("lifecycle_status"),
                    "physical_size_status": row.get("artifact_review", {}).get("status", "not_run"),
                    "source_url": evidence.get("source_url"),
                    "doi": evidence.get("doi"),
                    "license": evidence.get("license"),
                    "fixture_path": row.get("fixture_path"),
                    "fixture_tree_sha256": evidence.get("fixture_tree_sha256"),
                    "provenance_path": evidence.get("provenance_path"),
                    "rejection_reason": evidence.get("rejection_reason"),
                    "limitations": " | ".join(evidence.get("limitations") or []),
                }
            )


def _write_markdown(path: Path, payload: dict[str, Any]) -> None:
    summary = payload["summary"]
    lines = [
        "# SciPlot 23-rule evidence status",
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


def _pill(value: object) -> str:
    text = str(value or "missing")
    good = text in {
        "verified",
        "registered",
        "passed",
        "license_verified",
        "license_recorded",
        "user_authorized",
        "user_authorized_archive",
        "source_and_output_registered",
    }
    warning = text in {"computed_unregistered", "canonical_contract_only", "not_run", "in_progress"}
    css = "good" if good else ("warn" if warning else "bad")
    return f'<span class="pill {css}">{html.escape(text)}</span>'


def _write_html(path: Path, payload: dict[str, Any]) -> None:
    summary = payload["summary"]
    cards = [
        ("Rules", summary["rule_count"]),
        ("Real evidence", summary["real_data_evidence_count"]),
        ("Authorization", summary["authorization_ready_count"]),
        ("Source hashes", summary["source_hash_registered_count"]),
        ("Fixture verified", summary["fixture_hash_verified_count"]),
        ("Lifecycle passed", summary["lifecycle_passed_count"]),
        ("Final size passed", summary["physical_size_passed_count"]),
    ]
    card_html = "".join(
        f'<article class="card"><span>{html.escape(label)}</span><strong>{value}</strong></article>'
        for label, value in cards
    )
    table_rows: list[str] = []
    for row in payload["matrix"]:
        evidence = row["evidence"]
        source_url = evidence.get("source_url")
        source = (
            f'<a href="{html.escape(str(source_url), quote=True)}">source</a>' if source_url else "—"
        )
        limitation = " | ".join(evidence.get("limitations") or []) or evidence.get("rejection_reason") or ""
        search_text = " ".join(
            str(value or "")
            for value in (
                row["rule_id"],
                evidence.get("tier"),
                evidence.get("authorization_status"),
                evidence.get("fixture_hash_status"),
                row.get("lifecycle_status"),
                row.get("artifact_review", {}).get("status"),
                limitation,
            )
        ).casefold()
        table_rows.append(
            f'<tr data-search="{html.escape(search_text, quote=True)}" '
            f'data-lifecycle="{html.escape(str(row.get("lifecycle_status") or ""), quote=True)}">'
            f'<td><code>{html.escape(row["rule_id"])}</code></td>'
            f'<td>{html.escape(str(evidence.get("tier") or ""))}</td>'
            f'<td>{_pill(evidence.get("authorization_status"))}</td>'
            f'<td>{_pill(evidence.get("source_hash_status"))}</td>'
            f'<td>{_pill(evidence.get("fixture_hash_status"))}</td>'
            f'<td>{_pill(evidence.get("unit_status"))}</td>'
            f'<td>{_pill(row.get("lifecycle_status"))}</td>'
            f'<td>{_pill(row.get("artifact_review", {}).get("status", "not_run"))}</td>'
            f'<td>{source}</td>'
            f'<td class="notes">{html.escape(str(limitation))}</td></tr>'
        )
    rejection_rows = "".join(
        "<tr>"
        f"<td><code>{html.escape(str(item.get('candidate_id') or ''))}</code></td>"
        f"<td>{html.escape(str(item.get('candidate') or ''))}</td>"
        f"<td>{_pill(item.get('decision'))}</td>"
        f"<td>{html.escape(str(item.get('reason') or ''))}</td>"
        "</tr>"
        for item in payload["candidate_rejections"]
    )
    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SciPlot 23-rule evidence status</title>
<style>
:root{{--ink:#17211d;--muted:#607068;--line:#dbe3de;--paper:#f5f7f5;--card:#fff;--green:#176b46;--amber:#8a5a00;--red:#9f2d2d}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--paper);color:var(--ink);font:14px/1.45 ui-sans-serif,system-ui,-apple-system,sans-serif}}
main{{max-width:1500px;margin:auto;padding:34px 28px 60px}} h1{{font-size:28px;margin:0 0 4px}} .lede{{color:var(--muted);margin:0 0 24px}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin:18px 0 24px}} .card{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px}}
.card span{{display:block;color:var(--muted);font-size:12px}} .card strong{{display:block;font-size:27px;margin-top:2px}}
.controls{{display:flex;gap:10px;margin:0 0 12px}} input,select{{background:#fff;border:1px solid var(--line);border-radius:8px;padding:9px 11px;color:var(--ink)}} input{{min-width:300px}}
.table-wrap{{overflow:auto;background:#fff;border:1px solid var(--line);border-radius:12px}} table{{border-collapse:collapse;width:100%;min-width:1180px}} th,td{{padding:10px 11px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}} th{{position:sticky;top:0;background:#eef2ef;font-size:12px;color:#45534c}} tr:last-child td{{border-bottom:0}}
.pill{{display:inline-block;border-radius:999px;padding:2px 8px;font-size:11px;white-space:nowrap}} .pill.good{{background:#e3f3ea;color:var(--green)}} .pill.warn{{background:#fff2d6;color:var(--amber)}} .pill.bad{{background:#f8e2e2;color:var(--red)}}
.notes{{max-width:360px;color:var(--muted)}} h2{{margin-top:34px;font-size:20px}} .definitions{{color:var(--muted);max-width:1000px}} code{{font-size:12px}} a{{color:#126247}}
@media(max-width:1000px){{.cards{{grid-template-columns:repeat(3,1fr)}}}} @media(max-width:620px){{main{{padding:24px 14px}}.cards{{grid-template-columns:repeat(2,1fr)}}.controls{{display:block}}input,select{{width:100%;margin-bottom:8px}}}}
</style></head><body><main>
<h1>SciPlot 23-rule evidence status</h1>
<p class="lede">Generated {html.escape(payload['generated_at'])}. Evidence, lifecycle, and visual publication review remain separate gates.</p>
<section class="cards">{card_html}</section>
<div class="controls"><input id="search" type="search" placeholder="Filter rule, tier, status, or limitation">
<select id="lifecycle"><option value="">All lifecycle states</option><option>passed</option><option>failed</option><option>not_run</option></select></div>
<div class="table-wrap"><table id="matrix"><thead><tr><th>Rule</th><th>Evidence tier</th><th>Authorization</th><th>Source hash</th><th>Fixture hash</th><th>Units</th><th>Lifecycle</th><th>Final size</th><th>Source</th><th>Boundary / rejection</th></tr></thead><tbody>{''.join(table_rows)}</tbody></table></div>
<h2>Rejected or non-selected candidates</h2><div class="table-wrap"><table><thead><tr><th>ID</th><th>Candidate</th><th>Decision</th><th>Reason</th></tr></thead><tbody>{rejection_rows}</tbody></table></div>
<h2>Definitions</h2><div class="definitions"><p><b>Verified fixture hash</b> means current bytes match an independently registered SHA-256. <b>Computed unregistered</b> means current bytes are hashed but lack an expected fixture hash. A registered source hash refers to the upstream file, archive, or archive member. Final-size status checks PDF/TIFF dimensions and TIFF DPI; generated contact sheets still require explicit visual inspection. Lifecycle success does not itself establish real-data or journal-compliance evidence.</p></div>
</main><script>
const q=document.querySelector('#search'), state=document.querySelector('#lifecycle'), rows=[...document.querySelectorAll('#matrix tbody tr')];
function filter(){{const text=q.value.trim().toLowerCase(), lifecycle=state.value;for(const row of rows){{row.hidden=!!((text&&!row.dataset.search.includes(text))||(lifecycle&&row.dataset.lifecycle!==lifecycle));}}}}
q.addEventListener('input',filter);state.addEventListener('change',filter);
</script></body></html>"""
    path.write_text(document, encoding="utf-8")


def write_evidence_status_dashboard(
    *,
    output_dir: Path,
    rows: list[dict[str, Any]],
    repo_root: Path,
    generated_at: str | None = None,
) -> dict[str, Any]:
    timestamp = generated_at or datetime.now(UTC).isoformat()
    payload = {
        "kind": "sciplot_23_rule_evidence_status",
        "version": 1,
        "generated_at": timestamp,
        "summary": _status_summary(rows),
        "matrix": rows,
        "candidate_rejections": load_candidate_rejections(repo_root=repo_root),
        "definitions": {
            "lifecycle": "Studio prepare, exact VSZ reopen/export, manual-edit preservation, PDF/TIFF pair, QA, delivery, and provenance checks.",
            "evidence": "Authorization, source identity, fixture identity, units, and real-data tier are evaluated independently of lifecycle.",
            "visual_review": "Final physical-size visual review is a separate artifact-level gate and is not inferred from lifecycle success.",
        },
    }
    json_path = output_dir / "evidence_status.json"
    csv_path = output_dir / "evidence_status.csv"
    markdown_path = output_dir / "evidence_status.md"
    html_path = output_dir / "evidence_dashboard.html"
    json_path.write_text(json.dumps(json_safe(payload), indent=2, ensure_ascii=False), encoding="utf-8")
    _write_csv(csv_path, rows)
    _write_markdown(markdown_path, payload)
    _write_html(html_path, payload)
    return {
        "summary": payload["summary"],
        "artifacts": {
            "evidence_json": str(json_path),
            "evidence_csv": str(csv_path),
            "evidence_markdown": str(markdown_path),
            "evidence_dashboard": str(html_path),
        },
    }


__all__ = [
    "enrich_rule_evidence",
    "load_candidate_rejections",
    "write_evidence_status_dashboard",
]
