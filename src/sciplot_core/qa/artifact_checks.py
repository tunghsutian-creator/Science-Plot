"""Build publication checks for format pairing, frames, and raster exports."""

from __future__ import annotations

from typing import Any

from sciplot_core.qa.audit_support import _check, _matching_pdf
from sciplot_core.qa.format_pairing import _canonical_pairing_report


def build_artifact_checks(
    *,
    profile: dict[str, Any],
    pdfs: list[dict[str, Any]],
    tiffs: list[dict[str, Any]],
    required_formats: dict[str, Any],
    fixed_frame: dict[str, Any],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, Any],
    float,
    set[str],
]:
    """Check canonical pairs, pages, size, frame, DPI, and TIFF/PDF identity."""

    required_set = set(required_formats["formats"])
    pairing = _canonical_pairing_report(
        pdfs,
        tiffs,
        required_formats=required_set,
    )
    checks = [
        _check(
            "canonical_format_pairs",
            passed=bool(pairing["passed"]),
            actual=pairing,
            expected={
                "required_formats": sorted(required_set),
                "cardinality": (
                    "one PDF and one TIFF per canonical stem whenever TIFF "
                    "is required or present"
                ),
            },
            message=(
                "Canonical PDF/TIFF artifacts must be complete, uniquely "
                "named, and paired one-to-one."
            ),
        )
    ]
    page_counts = [int(pdf["page_count"]) for pdf in pdfs]
    checks.append(
        _check(
            "single_page_pdf",
            passed=all(count == 1 for count in page_counts),
            actual=page_counts,
            expected=1,
            message=(
                "Each canonical figure PDF must contain exactly one fully "
                "inspected page."
            ),
        )
    )
    page = profile.get("page") if isinstance(profile.get("page"), dict) else {}
    allowed_widths = [float(value) for value in page.get("allowed_widths_mm", [])]
    width_tolerance = float(page.get("width_tolerance_mm") or 0.5)
    maximum_height = float(page.get("maximum_height_mm") or float("inf"))
    observed_sizes = [
        page_info["physical_size_mm"] for pdf in pdfs for page_info in pdf["pages"]
    ]
    size_passed = all(
        any(abs(float(size[0]) - width) <= width_tolerance for width in allowed_widths)
        and float(size[1]) <= maximum_height + width_tolerance
        for size in observed_sizes
    )
    checks.append(
        _check(
            "physical_size",
            passed=size_passed,
            actual=observed_sizes,
            expected={
                "allowed_widths_mm": allowed_widths,
                "maximum_height_mm": maximum_height,
            },
            message=(
                "Final PDF page size must match a profile width and remain "
                "below the maximum height."
            ),
        )
    )
    checks.append(
        _check(
            "fixed_frame_current_vsz",
            passed=bool(fixed_frame["passed"]),
            actual=fixed_frame,
            expected=(
                "Every rendered graph uses the fixed physical frame; "
                "confirmed composites match exact slots."
            ),
            message=(
                "The exact current Veusz document must retain the fixed graph "
                "frame and declared slot geometry."
            ),
            severity="error" if fixed_frame["available"] else "warning",
        )
    )
    raster_checks = _raster_export_checks(
        profile=profile,
        pdfs=pdfs,
        tiffs=tiffs,
        pairing=pairing,
        required_set=required_set,
        width_tolerance=width_tolerance,
    )
    return checks, raster_checks, pairing, width_tolerance, required_set


def _raster_export_checks(
    *,
    profile: dict[str, Any],
    pdfs: list[dict[str, Any]],
    tiffs: list[dict[str, Any]],
    pairing: dict[str, Any],
    required_set: set[str],
    width_tolerance: float,
) -> list[dict[str, Any]]:
    minimum_dpi = float(profile.get("raster", {}).get("minimum_effective_dpi") or 300.0)
    embedded_images = [image for pdf in pdfs for image in pdf["embedded_rasters"]]
    checks = [
        _check(
            "embedded_raster_effective_dpi",
            passed=all(
                image.get("effective_dpi") is not None
                and float(image["effective_dpi"]) >= minimum_dpi - 0.5
                for image in embedded_images
            ),
            actual=embedded_images,
            expected={"minimum_dpi": minimum_dpi},
            message=(
                "Any raster embedded in a PDF must retain sufficient effective "
                "resolution at placed size."
            ),
        )
    ]
    tiff_required = "tiff_300" in required_set
    checks.append(
        _check(
            "tiff_dpi",
            passed=(not tiff_required or bool(tiffs))
            and all(min(tiff["dpi"]) >= minimum_dpi - 0.5 for tiff in tiffs),
            actual=[tiff["dpi"] for tiff in tiffs],
            expected={"minimum_dpi": minimum_dpi},
            message=(
                "Delivered TIFF previews must retain the declared "
                "publication-resolution metadata."
            ),
        )
    )
    size_pairs: list[dict[str, Any]] = []
    size_passed = bool(pairing["passed"])
    for tiff in tiffs:
        pdf = _matching_pdf(tiff, pdfs)
        if pdf is None:
            size_passed = False
            continue
        pair = {"tiff": tiff["physical_size_mm"], "pdf": pdf["physical_size_mm"]}
        size_pairs.append(pair)
        if any(value is None for value in tiff["physical_size_mm"]):
            size_passed = False
        else:
            size_passed = size_passed and all(
                abs(float(left) - float(right)) <= width_tolerance
                for left, right in zip(
                    tiff["physical_size_mm"],
                    pdf["physical_size_mm"],
                    strict=True,
                )
            )
    checks.append(
        _check(
            "tiff_pdf_physical_size_match",
            passed=size_passed,
            actual=size_pairs,
            expected={"tolerance_mm": width_tolerance},
            message=(
                "TIFF and PDF exports of the same figure must describe the "
                "same physical size."
            ),
        )
    )
    return checks
