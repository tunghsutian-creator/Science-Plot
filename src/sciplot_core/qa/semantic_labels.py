"""Verify labels, scientific units, and panel typography."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import re
import unicodedata
from typing import Any


_VEUSZ_SYMBOLS = {
    "alpha": "α",
    "beta": "β",
    "delta": "δ",
    "eta": "η",
    "gamma": "γ",
    "mu": "μ",
    "omega": "ω",
    "phi": "φ",
    "pi": "π",
    "rho": "ρ",
    "sigma": "σ",
    "tau": "τ",
    "theta": "θ",
    "times": "×",
}


_SUPERSCRIPT_TRANSLATION = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻", "0123456789+-")


def _plain_veusz_label(value: object) -> str:
    text = str(value or "")
    wrapper = re.compile(r"\\(?:italic|textit|emph|bold|textbf|underline)\{([^{}]*)\}")
    while wrapper.search(text):
        text = wrapper.sub(r"\1", text)
    for name, symbol in _VEUSZ_SYMBOLS.items():
        text = re.sub(rf"\\{name}(?![A-Za-z])", symbol, text)
    # Veusz escapes literal markup characters in saved labels. PDF text
    # extraction returns the rendered character, so compare against that
    # rendered form instead of treating the escape slash as label content.
    text = re.sub(r"\\([\[\]_{}^\\])", r"\1", text)
    text = re.sub(r"\^\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"_\{([^{}]*)\}", r"\1", text)
    text = text.replace("{", "").replace("}", "")
    return text


def _normalized_label(value: object) -> str:
    text = unicodedata.normalize("NFKC", _plain_veusz_label(value)).translate(
        _SUPERSCRIPT_TRANSLATION
    )
    text = text.casefold().replace("−", "-").replace("–", "-").replace("’", "′")
    return "".join(character for character in text if not character.isspace())


def _flatten_label_values(value: object, *, source: str) -> list[dict[str, str]]:
    if isinstance(value, str) and value.strip():
        return [{"source": source, "text": value.strip()}]
    if isinstance(value, dict):
        return [
            item
            for key, nested in value.items()
            for item in _flatten_label_values(nested, source=f"{source}.{key}")
        ]
    if isinstance(value, list):
        return [
            item
            for index, nested in enumerate(value)
            for item in _flatten_label_values(nested, source=f"{source}[{index}]")
        ]
    return []


def _verified_single_page_exports(
    documents: list[dict[str, Any]],
    pdfs: list[dict[str, Any]],
    exports: list[dict[str, Any]],
) -> dict[str, tuple[dict[str, Any], dict[str, Any]]]:
    """Map a one-page VSZ to its PDF using the existing native export receipt."""
    native = {str(Path(item["path"]).resolve()): item for item in documents if item.get("path")}
    rendered = {str(Path(item["path"]).resolve()): item for item in pdfs}
    matches: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = {}
    for record in exports:
        if not isinstance(record, dict) or record.get("format") != "pdf":
            continue
        source, target = record.get("document"), record.get("path")
        if not isinstance(source, str) or not isinstance(target, str):
            continue
        key = str(Path(source).resolve())
        document = native.get(key)
        pdf = rendered.get(str(Path(target).resolve()))
        if (document is not None and pdf is not None
                and document.get("sha256") and document["sha256"] == record.get("document_sha256")
                and pdf["sha256"] == record.get("sha256")
                and len(document.get("pages", [])) == pdf["page_count"] == 1
                and document["pages"][0].get("page") == 1):
            matches.setdefault(key, []).append((record, pdf))
    pdf_owners = Counter(pdf["path"] for values in matches.values() for _, pdf in values)
    return {key: values[0] for key, values in matches.items()
            if len(values) == 1 and pdf_owners[values[0][1]["path"]] == 1}


def _semantic_label_report(
    audit: dict[str, Any] | None,
    intent: dict[str, Any],
    pdfs: list[dict[str, Any]],
    exports: list[dict[str, Any]],
) -> dict[str, Any]:
    documents = [item for item in (audit or {}).get("documents", []) if isinstance(item, dict)]
    owned = _verified_single_page_exports(documents, pdfs, exports)
    observed_owned = {
        pdf["path"]: {_normalized_label(line)
                      for line in pdf["text_objects"]["plain_text_by_page"][0].get("visible_lines", [])}
        for pdf in pdfs if pdf["page_count"] == 1
    }
    observed_lines = [
        line for pdf in pdfs for page in pdf["text_objects"]["plain_text_by_page"]
        for line in page.get("visible_lines", [])
    ]
    observed_everywhere = {_normalized_label(line) for line in observed_lines}
    expected: list[dict[str, Any]] = []
    matched: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    unverified: list[dict[str, Any]] = []
    seen: set[tuple[str | None, str]] = set()

    def compare(item: dict[str, Any], *, document_path: str | None = None,
                observed: set[str] | None) -> None:
        normalized = _normalized_label(item["text"])
        identity = document_path, normalized
        if not normalized or identity in seen:
            return
        seen.add(identity)
        item = {**item, "normalized": normalized}
        expected.append(item)
        if observed is None:
            unverified.append(item)
        elif normalized in observed:
            matched.append(item)
        else:
            missing.append(item)

    for document in documents:
        document_path = str(document.get("path") or "")
        scope = owned.get(str(Path(document_path).resolve()))
        page_root = document["pages"][0]["path"].rstrip("/") + "/" if scope else None
        for item in document.get("semantic_labels", []):
            if not isinstance(item, dict) or not isinstance(item.get("text"), str) or not item["text"].strip():
                continue
            expectation = {
                "source": f"current_vsz:{document_path}:{item.get('role')}:{item.get('path')}",
                "text": item["text"].strip(),
            }
            owner = str(item.get("path") or "")
            if scope is None or page_root is None or not owner.startswith(page_root):
                compare(expectation, document_path=document_path, observed=None)
            else:
                record, pdf = scope
                compare({**expectation, "figure_id": record.get("figure_id"), "pdf_path": pdf["path"], "page": 1},
                        document_path=document_path, observed=observed_owned[pdf["path"]])

    for item in _flatten_label_values(intent.get("exact_labels"), source="publication_intent.exact_labels"):
        compare(item, observed=observed_everywhere)

    panel_labels: list[str] = []
    if str(intent.get("layout_status") or "").casefold() == "confirmed":
        for index, panel in enumerate(intent.get("panels", [])):
            if not isinstance(panel, dict):
                continue
            if str(panel.get("confirmation_status") or "").casefold() != "confirmed":
                continue
            label = str(panel.get("panel_label") or "").strip()
            if label:
                panel_labels.append(label)
                compare({"source": f"publication_intent.panels[{index}].panel_label", "text": label},
                        observed=observed_everywhere)
    return {
        "available": bool(documents) or bool(intent.get("exact_labels")),
        "coverage_complete": bool(documents) and bool(expected) and not unverified,
        "passed": not missing and not unverified and bool(expected),
        "expected": expected,
        "matched": matched,
        "missing": missing,
        "unverified": unverified,
        "observed_lines": observed_lines,
        "panel_labels": panel_labels,
        "evidence_model": (
            "Native labels are compared on the identified single-page figure. "
            "Unbound native labels cannot be verified. This report checks text "
            "presence, not the widget role of a PDF span."
        ),
    }


def _scientific_unit_expression_report(
    audit: dict[str, Any] | None,
) -> dict[str, Any]:
    documents = audit.get("documents", []) if isinstance(audit, dict) else []
    contracts = [
        document.get("unit_expression_contract")
        for document in documents
        if isinstance(document, dict)
        and isinstance(document.get("unit_expression_contract"), dict)
    ]
    violations = [
        {
            "document": str(document.get("path") or ""),
            **violation,
        }
        for document in documents
        if isinstance(document, dict)
        for violation in (
            document.get("unit_expression_contract", {}).get("violations", [])
            if isinstance(document.get("unit_expression_contract"), dict)
            else []
        )
        if isinstance(violation, dict)
    ]
    coverage_complete = (
        bool(documents)
        and len(contracts) == len(documents)
        and all(contract.get("coverage_complete") is True for contract in contracts)
    )
    return {
        "available": bool(contracts),
        "coverage_complete": coverage_complete,
        "passed": coverage_complete
        and not violations
        and all(contract.get("passed") is True for contract in contracts),
        "contracts": contracts,
        "violations": violations,
        "evidence_model": (
            "Every visible exact-current VSZ semantic label is checked for "
            "solidus-based unit division; mathematical variable ratios are excluded."
        ),
    }


def _panel_typography_report(
    semantic: dict[str, Any],
    pdfs: list[dict[str, Any]],
    profile: dict[str, Any],
) -> dict[str, Any]:
    panel_labels = [str(value) for value in semantic.get("panel_labels", [])]
    panel_profile = (
        profile.get("typography", {}).get("panel_label")
        if isinstance(profile.get("typography"), dict)
        else None
    )
    if not panel_labels or not isinstance(panel_profile, dict):
        return {
            "applicable": False,
            "coverage_complete": True,
            "passed": True,
            "panel_labels": panel_labels,
            "matches": [],
        }
    spans = [
        span for pdf in pdfs for span in pdf["text_objects"].get("visible_spans", [])
    ]
    matches: list[dict[str, Any]] = []
    expected_size = float(panel_profile.get("size_pt") or 0.0)
    for label in panel_labels:
        candidates = [
            span
            for span in spans
            if _normalized_label(span.get("text")) == _normalized_label(label)
        ]
        valid = [
            span
            for span in candidates
            if abs(float(span.get("size") or 0.0) - expected_size) <= 0.15
            and (
                panel_profile.get("weight") != "bold"
                or "bold" in str(span.get("font") or "").casefold()
            )
            and (
                panel_profile.get("style") != "upright"
                or all(
                    token not in str(span.get("font") or "").casefold()
                    for token in ("italic", "oblique")
                )
            )
        ]
        matches.append({"label": label, "candidates": candidates, "valid": valid})
    return {
        "applicable": True,
        "coverage_complete": True,
        "passed": all(item["valid"] for item in matches),
        "panel_labels": panel_labels,
        "expected": panel_profile,
        "matches": matches,
    }
