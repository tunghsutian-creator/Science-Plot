"""Normalize fonts, discover VSZ files, and provide audit comparison helpers."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any
from sciplot_core.foundation.json_io import read_json_object
from sciplot_core.policy import canonical_figure_stem


def _check(
    check_id: str,
    *,
    passed: bool,
    actual: Any,
    expected: Any,
    message: str,
    severity: str = "error",
) -> dict[str, Any]:
    return {
        "id": check_id,
        "status": "passed" if passed else "failed",
        "severity": severity,
        "actual": actual,
        "expected": expected,
        "message": message,
    }


def _normalized_font_name(value: str) -> str:
    name = value.split("+", 1)[-1].casefold()
    return "".join(character for character in name if character.isalnum())


_FONT_FAMILY_ALIASES: dict[str, set[str]] = {
    "arial": {
        "arial",
        "arialbold",
        "arialbolditalic",
        "arialbolditalicmt",
        "arialboldmt",
        "arialitalic",
        "arialitalicmt",
        "arialmt",
        "arialregular",
    },
    "helvetica": {
        "helvetica",
        "helveticabold",
        "helveticaboldoblique",
        "helveticaoblique",
        "helveticaregular",
    },
    "liberationsans": {
        "liberationsans",
        "liberationsansbold",
        "liberationsansbolditalic",
        "liberationsansitalic",
        "liberationsansregular",
    },
}


def _font_family_key(value: str) -> str:
    normalized = _normalized_font_name(value)
    for family, aliases in _FONT_FAMILY_ALIASES.items():
        if normalized in aliases:
            return family
    return normalized


def _font_face_key(value: str) -> tuple[str, str]:
    normalized = _normalized_font_name(value)
    family = _font_family_key(value)
    bold = "bold" in normalized
    italic = "italic" in normalized or "oblique" in normalized
    if bold and italic:
        style = "bold_italic"
    elif bold:
        style = "bold"
    elif italic:
        style = "italic"
    else:
        style = "regular"
    return family, style


def _font_allowed(font: str, allowed: list[str]) -> bool:
    family = _font_family_key(font)
    return family in {_font_family_key(candidate) for candidate in allowed}


def _font_embedding_evidence(pdf: dict[str, Any]) -> list[dict[str, Any]]:
    resources = pdf["font_resources"]
    evidence = []
    for used_font in pdf["text_objects"]["fonts"]:
        face_key = _font_face_key(used_font)
        matches = [
            resource
            for resource in resources
            if _font_face_key(resource["base_font"]) == face_key
        ]
        evidence.append(
            {
                "font": used_font,
                "face_key": list(face_key),
                "matched_resources": matches,
                "embedded": bool(matches)
                and any(bool(resource["embedded"]) for resource in matches),
            }
        )
    return evidence


def _matching_pdf(
    tiff: dict[str, Any], pdfs: list[dict[str, Any]]
) -> dict[str, Any] | None:
    tiff_stem = canonical_figure_stem(tiff["path"])
    return next(
        (pdf for pdf in pdfs if canonical_figure_stem(pdf["path"]) == tiff_stem), None
    )


def _candidate_path(value: object, *, base_dir: Path) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = base_dir / candidate
    try:
        resolved = candidate.resolve()
    except OSError:
        return None
    return (
        resolved
        if resolved.exists()
        and resolved.is_file()
        and resolved.suffix.casefold() == ".vsz"
        else None
    )


def _discover_veusz_documents(
    output_dir: Path, explicit: list[Path] | None
) -> list[Path]:
    candidates: list[Path] = []
    if explicit is not None:
        candidates.extend(
            path.expanduser().resolve()
            for path in explicit
            if path.expanduser().exists()
        )
    manifest = read_json_object(output_dir / "manifest.json")
    if isinstance(manifest, dict):
        values: list[object] = [manifest.get("veusz_document")]
        values.extend(
            manifest.get("veusz_documents", [])
            if isinstance(manifest.get("veusz_documents"), list)
            else []
        )
        result = (
            manifest.get("result") if isinstance(manifest.get("result"), dict) else {}
        )
        values.append(result.get("veusz_document"))
        values.extend(
            result.get("veusz_documents", [])
            if isinstance(result.get("veusz_documents"), list)
            else []
        )
        for value in values:
            candidate = _candidate_path(value, base_dir=output_dir)
            if candidate is not None:
                candidates.append(candidate)
    candidates.extend(sorted((output_dir / "studio").glob("document.vsz")))
    candidates.extend(
        sorted((output_dir / "figures" / "_veusz").glob("**/studio/document.vsz"))
    )
    unique: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen or not resolved.exists() or not resolved.is_file():
            continue
        seen.add(resolved)
        unique.append(resolved)
    return unique


def _run_veusz_audit(paths: list[Path]) -> tuple[dict[str, Any] | None, str | None]:
    if not paths:
        return None, "No exact current Veusz document was available for artifact QA."
    from sciplot_core.veusz_runtime import veusz_worker_environment

    command = [
        sys.executable,
        "-m",
        "sciplot_core.veusz_worker",
        "audit-documents",
        *(str(path) for path in paths),
    ]
    try:
        completed = subprocess.run(
            command,
            text=True,
            capture_output=True,
            check=True,
            env=veusz_worker_environment(),
        )
        payload = json.loads(completed.stdout)
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        detail = str(exc)
        if isinstance(exc, subprocess.CalledProcessError) and exc.stderr:
            detail = exc.stderr.strip().splitlines()[-1]
        return None, f"Veusz document audit failed: {detail}"
    if not isinstance(payload, dict) or not isinstance(payload.get("documents"), list):
        return None, "Veusz document audit returned an invalid payload."
    return payload, None


def _publication_intent(output_dir: Path) -> dict[str, Any]:
    intent = read_json_object(output_dir / "publication_intent.json")
    if intent is not None:
        return intent
    request = read_json_object(output_dir / "request_snapshot.json")
    if isinstance(request, dict) and isinstance(
        request.get("publication_intent"), dict
    ):
        return request["publication_intent"]
    manifest = read_json_object(output_dir / "manifest.json")
    if isinstance(manifest, dict) and isinstance(
        manifest.get("publication_intent"), dict
    ):
        return manifest["publication_intent"]
    return {}


def _close(left: float, right: float, tolerance: float) -> bool:
    return abs(float(left) - float(right)) <= tolerance


def _bounds_close(actual: object, expected: object, tolerance: float) -> bool:
    return (
        isinstance(actual, list)
        and isinstance(expected, list)
        and len(actual) == len(expected)
        and all(
            _close(float(left), float(right), tolerance)
            for left, right in zip(actual, expected, strict=True)
        )
    )
