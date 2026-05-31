from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

import pandas as pd

from src.data_loader import load_curve_table, load_replicate_table
from src.data_studio.builtin import tensile as tensile_builtin
from src.data_studio.io_utils import ensure_input_path, list_sheet_names
from src.data_studio.models import DataStudioWorkbook
from src.data_studio.workbook_template_authoring import slugify_template_label
from src.infrastructure.persistence.data_studio_imports import prepare_managed_data_studio_import_dir


def looks_like_comparison_bundle(path: Path, metadata: dict[str, Any]) -> bool:
    template_id = str(metadata.get("template_id", "")).strip()
    if template_id == "data_studio/comparison":
        return True
    try:
        representative_curves = load_curve_table(path, sheet_name=tensile_builtin.REPRESENTATIVE_CURVE_SHEET)
    except Exception:
        representative_curves = []
    if len(representative_curves) > 1:
        return True

    for sheet_name in list_sheet_names(path):
        if not sheet_name.endswith("_Replicates"):
            continue
        try:
            groups = load_replicate_table(path, sheet_name=sheet_name)
        except Exception:
            continue
        if len(groups) > 1:
            return True

    source_files = tuple(Path(item) for item in metadata.get("source_files", ()) if str(item).strip())
    return len(source_files) >= 2 and all(
        source_file.suffix.lower() in {".xlsx", ".xlsm", ".xls"} for source_file in source_files
    )


def import_source_workbooks_from_metadata(
    path: Path,
    metadata: dict[str, Any],
    *,
    import_workbook: Callable[[str | Path], DataStudioWorkbook],
) -> tuple[DataStudioWorkbook, ...]:
    source_files = tuple(Path(item) for item in metadata.get("source_files", ()) if str(item).strip())
    if not source_files:
        return ()
    imported: list[DataStudioWorkbook] = []
    seen_paths: set[str] = set()
    try:
        for source_file in source_files:
            resolved = ensure_input_path(str(source_file.expanduser()))
            resolved_key = str(resolved)
            if resolved_key == str(path) or resolved_key in seen_paths:
                continue
            seen_paths.add(resolved_key)
            imported.append(import_workbook(resolved))
    except Exception:
        return ()
    return tuple(imported)


def materialize_comparison_bundle_groups(
    path: Path,
    metadata: dict[str, Any],
    *,
    import_workbook: Callable[[str | Path], DataStudioWorkbook],
) -> tuple[DataStudioWorkbook, ...]:
    representative_curves = load_curve_table(path, sheet_name=tensile_builtin.REPRESENTATIVE_CURVE_SHEET)
    if not representative_curves:
        return ()

    replicate_sheet_names = [sheet_name for sheet_name in list_sheet_names(path) if sheet_name.endswith("_Replicates")]
    replicate_groups_by_sheet = {
        sheet_name: load_replicate_table(path, sheet_name=sheet_name)
        for sheet_name in replicate_sheet_names
    }
    source_files = tuple(Path(item) for item in metadata.get("source_files", ()) if str(item).strip())
    import_dir = prepare_managed_data_studio_import_dir(path)
    imported: list[DataStudioWorkbook] = []

    for index, curve in enumerate(representative_curves):
        label = curve.sample.strip() or f"Recovered Group {index + 1}"
        workbook_path = import_dir / f"{slugify_template_label(label) or 'group'}_{index + 1}.xlsx"
        selected_metric_groups: list[tuple[str, Any]] = []
        sample_count = 0
        for sheet_name, groups in replicate_groups_by_sheet.items():
            group = _select_group_for_label(groups, label, index)
            if group is None:
                continue
            selected_metric_groups.append((sheet_name, group))
            sample_count = max(sample_count, len(group.data.index))
        source_path = source_files[index] if index < len(source_files) else path
        metadata_sheet = _comparison_group_metadata_sheet_dataframe(
            label=label,
            source_files=(source_path,),
            representative_filename=curve.sample or label,
            sample_count=sample_count or len(curve.data.index),
            warnings=(f"Recovered from comparison workbook {path.name}.",),
        )
        with pd.ExcelWriter(workbook_path) as writer:
            _single_curve_table_dataframe(label=label, curve=curve).to_excel(
                writer,
                sheet_name=tensile_builtin.REPRESENTATIVE_CURVE_SHEET,
                header=False,
                index=False,
            )
            for sheet_name, group in selected_metric_groups:
                _single_replicate_table_dataframe(group).to_excel(
                    writer,
                    sheet_name=sheet_name,
                    header=False,
                    index=False,
                )
            metadata_sheet.to_excel(writer, sheet_name=tensile_builtin.METADATA_SHEET, header=False, index=False)
        imported.append(import_workbook(workbook_path))
    return tuple(imported)


def _select_group_for_label(groups: list[Any], label: str, index: int):
    if not groups:
        return None
    normalized_label = _normalize_group_key(label)
    for group in groups:
        if _normalize_group_key(group.group) == normalized_label:
            return group
    if index < len(groups):
        return groups[index]
    return None


def _normalize_group_key(value: object) -> str:
    return str(value).strip().casefold()


def _single_curve_table_dataframe(*, label: str, curve) -> pd.DataFrame:
    rows: list[list[object]] = [
        [curve.x_label, curve.y_label],
        [curve.x_unit, curve.y_unit],
        [label, label],
    ]
    for row_index in range(len(curve.data.index)):
        rows.append(
            [
                float(curve.data.iloc[row_index]["x"]),
                float(curve.data.iloc[row_index]["y"]),
            ]
        )
    return pd.DataFrame(rows)


def _single_replicate_table_dataframe(group) -> pd.DataFrame:
    rows: list[list[object]] = [
        [group.value_label],
        [group.group],
        [group.value_unit],
    ]
    rows.extend([[float(value)] for value in group.data.reset_index(drop=True).tolist()])
    return pd.DataFrame(rows)


def _comparison_group_metadata_sheet_dataframe(
    *,
    label: str,
    source_files: Iterable[Path],
    representative_filename: str,
    sample_count: int,
    warnings: Iterable[str],
) -> pd.DataFrame:
    rows = [
        ["label", label],
        ["source_files", " | ".join(str(path) for path in source_files)],
        ["warnings", " | ".join(str(item) for item in warnings)],
        ["representative_filename", representative_filename],
        ["sample_count", sample_count],
    ]
    return pd.DataFrame(rows)
