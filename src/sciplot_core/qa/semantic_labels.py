"""Verify labels, scientific units, and panel typography."""

from __future__ import annotations

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


def _semantic_label_report(
    audit: dict[str, Any] | None,
    intent: dict[str, Any],
    pdfs: list[dict[str, Any]],
) -> dict[str, Any]:
    expected: list[dict[str, str]] = []
    documents = audit.get("documents", []) if isinstance(audit, dict) else []
    for document in documents:
        if not isinstance(document, dict):
            continue
        for item in document.get("semantic_labels", []):
            if (
                isinstance(item, dict)
                and isinstance(item.get("text"), str)
                and item["text"].strip()
            ):
                expected.append(
                    {
                        "source": f"current_vsz:{document.get('path')}:{item.get('role')}:{item.get('path')}",
                        "text": item["text"].strip(),
                    }
                )
    expected.extend(
        _flatten_label_values(
            intent.get("exact_labels"), source="publication_intent.exact_labels"
        )
    )
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
                expected.append(
                    {
                        "source": f"publication_intent.panels[{index}].panel_label",
                        "text": label,
                    }
                )
    deduplicated: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in expected:
        normalized = _normalized_label(item["text"])
        if normalized and normalized not in seen:
            seen.add(normalized)
            deduplicated.append({**item, "normalized": normalized})
    observed_lines = [
        str(line)
        for pdf in pdfs
        for page in pdf["text_objects"].get("plain_text_by_page", [])
        for line in page.get("lines", [])
    ]
    normalized_lines = [_normalized_label(line) for line in observed_lines]
    missing: list[dict[str, str]] = []
    matched: list[dict[str, str]] = []
    for item in deduplicated:
        target = item["normalized"]
        found = target in normalized_lines
        (matched if found else missing).append(item)
    return {
        "available": bool(documents) or bool(intent.get("exact_labels")),
        "coverage_complete": bool(documents) and bool(deduplicated),
        "passed": not missing and bool(deduplicated),
        "expected": deduplicated,
        "matched": matched,
        "missing": missing,
        "observed_lines": observed_lines,
        "panel_labels": panel_labels,
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
