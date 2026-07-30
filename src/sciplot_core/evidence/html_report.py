"""Write the evidence status HTML dashboard."""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any


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
    warning = text in {
        "computed_unregistered",
        "canonical_contract_only",
        "not_run",
        "in_progress",
    }
    css = "good" if good else ("warn" if warning else "bad")
    return f'<span class="pill {css}">{html.escape(text)}</span>'


def _write_html(path: Path, payload: dict[str, Any]) -> None:
    summary = payload["summary"]
    rule_count = html.escape(str(summary["rule_count"]))
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
            f'<a href="{html.escape(str(source_url), quote=True)}">source</a>'
            if source_url
            else "—"
        )
        limitation = (
            " | ".join(evidence.get("limitations") or [])
            or evidence.get("rejection_reason")
            or ""
        )
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
            f"<td><code>{html.escape(row['rule_id'])}</code></td>"
            f"<td>{html.escape(str(evidence.get('tier') or ''))}</td>"
            f"<td>{_pill(evidence.get('authorization_status'))}</td>"
            f"<td>{_pill(evidence.get('source_hash_status'))}</td>"
            f"<td>{_pill(evidence.get('fixture_hash_status'))}</td>"
            f"<td>{_pill(evidence.get('unit_status'))}</td>"
            f"<td>{_pill(row.get('lifecycle_status'))}</td>"
            f"<td>{_pill(row.get('artifact_review', {}).get('status', 'not_run'))}</td>"
            f"<td>{source}</td>"
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
<title>SciPlot {rule_count}-rule evidence status</title>
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
<h1>SciPlot {rule_count}-rule evidence status</h1>
<p class="lede">Generated {html.escape(payload["generated_at"])}. Evidence, lifecycle, and visual publication review remain separate gates.</p>
<section class="cards">{card_html}</section>
<div class="controls"><input id="search" type="search" placeholder="Filter rule, tier, status, or limitation">
<select id="lifecycle"><option value="">All lifecycle states</option><option>passed</option><option>failed</option><option>not_run</option></select></div>
<div class="table-wrap"><table id="matrix"><thead><tr><th>Rule</th><th>Evidence tier</th><th>Authorization</th><th>Source hash</th><th>Fixture hash</th><th>Units</th><th>Lifecycle</th><th>Final size</th><th>Source</th><th>Boundary / rejection</th></tr></thead><tbody>{"".join(table_rows)}</tbody></table></div>
<h2>Rejected or non-selected candidates</h2><div class="table-wrap"><table><thead><tr><th>ID</th><th>Candidate</th><th>Decision</th><th>Reason</th></tr></thead><tbody>{rejection_rows}</tbody></table></div>
<h2>Definitions</h2><div class="definitions"><p><b>Verified fixture hash</b> means current bytes match an independently registered SHA-256. <b>Computed unregistered</b> means current bytes are hashed but lack an expected fixture hash. A registered source hash refers to the upstream file, archive, or archive member. Final-size status checks PDF/TIFF dimensions and TIFF DPI; generated contact sheets still require explicit visual inspection. Lifecycle success does not itself establish real-data or journal-compliance evidence.</p></div>
</main><script>
const q=document.querySelector('#search'), state=document.querySelector('#lifecycle'), rows=[...document.querySelectorAll('#matrix tbody tr')];
function filter(){{const text=q.value.trim().toLowerCase(), lifecycle=state.value;for(const row of rows){{row.hidden=!!((text&&!row.dataset.search.includes(text))||(lifecycle&&row.dataset.lifecycle!==lifecycle));}}}}
q.addEventListener('input',filter);state.addEventListener('change',filter);
</script></body></html>"""
    path.write_text(document, encoding="utf-8")
