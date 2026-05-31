from __future__ import annotations

# ruff: noqa: E501
import importlib.util
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.rendering.data_containers import (
    matrix_container_from_array,
    source_table_data_containers,
    table_container_from_frame,
)
from src.rendering.source_table_preview import source_table_preview


def _option(
    id: str,
    label: str,
    *,
    kind: str = "string",
    default_value: Any | None = None,
    choices: list[Any] | None = None,
    required: bool = False,
    help: str = "",
) -> dict[str, Any]:
    return {
        "id": id,
        "label": label,
        "kind": kind,
        "default_value": default_value,
        "choices": choices or [],
        "required": required,
        "help": help,
    }


TEXT_OPTIONS = [
    _option("encoding", "Encoding", default_value="auto", help="Text encoding. Leave empty to detect from the file."),
    _option("delimiter", "Delimiter", default_value="auto", choices=["auto", ",", ";", "tab", "|"], help="Column delimiter."),
    _option("header_row_index", "Header Row", kind="integer", default_value=None, help="Zero-based header row override."),
    _option("unit_row_index", "Unit Row", kind="integer", default_value=None, help="Zero-based unit row override."),
    _option("data_start_row_index", "Data Start Row", kind="integer", default_value=None, help="Zero-based first data row override."),
    _option("segment_id", "Segment", default_value=None, help="Detected source segment id."),
]
BINARY_OPTIONS = [
    _option("dtype", "Data Type", default_value="float32", choices=["float32", "float64", "int16", "int32", "uint16", "uint32"], required=True, help="NumPy dtype used to read raw values."),
    _option("shape", "Shape", kind="integer_array", required=True, help="Two-element [rows, columns] matrix shape."),
    _option("endianness", "Endianness", default_value="native", choices=["native", "little", "big"], help="Byte order for binary values."),
]


FILTERS: dict[str, dict[str, Any]] = {
    "import.csv": {
        "label": "CSV/TSV/TXT",
        "status": "enabled",
        "extensions": [".csv", ".tsv", ".txt"],
        "mime_types": ["text/csv", "text/tab-separated-values", "text/plain"],
        "preview_supported": True,
        "read_supported": True,
        "options": TEXT_OPTIONS,
        "output_container_kinds": ["table", "matrix", "statistics_summary", "transformed_view"],
        "help": "Delimited text import uses sidecar encoding, delimiter, structure, and column-role diagnostics.",
    },
    "import.excel": {
        "label": "Excel",
        "status": "enabled",
        "extensions": [".xls", ".xlsx", ".xlsm"],
        "mime_types": ["application/vnd.ms-excel", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"],
        "preview_supported": True,
        "read_supported": True,
        "options": [_option("sheet", "Sheet", default_value=0, help="Sheet name or zero-based index."), *TEXT_OPTIONS[2:]],
        "output_container_kinds": ["table", "matrix", "statistics_summary", "transformed_view"],
        "help": "Excel import previews workbook sheets through the shared source table engine.",
    },
    "import.json": {
        "label": "JSON",
        "status": "enabled",
        "extensions": [".json"],
        "mime_types": ["application/json"],
        "preview_supported": True,
        "read_supported": True,
        "options": [_option("encoding", "Encoding", default_value="utf-8", help="Text encoding for the JSON file.")],
        "output_container_kinds": ["table"],
        "help": "JSON import previews list records or an object with a records list.",
    },
    "import.binary_raw": {
        "label": "Binary/Raw",
        "status": "enabled",
        "extensions": [".raw", ".bin"],
        "mime_types": ["application/octet-stream"],
        "preview_supported": True,
        "read_supported": True,
        "options": BINARY_OPTIONS,
        "output_container_kinds": ["matrix"],
        "help": "Binary/raw preview is enabled only when explicit dtype and shape options are supplied.",
    },
    "import.hdf5": {"label": "HDF5", "status": "disabled", "extensions": [".h5", ".hdf5"], "mime_types": ["application/x-hdf5"], "dependency": "h5py", "output_container_kinds": ["table", "matrix"], "help": "HDF5 preview needs h5py plus structure-tree fixtures before it can be enabled."},
    "import.netcdf": {"label": "NetCDF", "status": "disabled", "extensions": [".nc", ".netcdf"], "mime_types": ["application/x-netcdf"], "dependency": "netCDF4", "output_container_kinds": ["table", "matrix"], "help": "NetCDF preview needs netCDF4 plus variable-tree fixtures before it can be enabled."},
    "import.fits": {"label": "FITS", "status": "disabled", "extensions": [".fits"], "mime_types": ["application/fits"], "dependency": "astropy", "output_container_kinds": ["table", "matrix"], "help": "FITS preview needs astropy plus HDU metadata fixtures before it can be enabled."},
    "import.ods": {"label": "ODS", "status": "disabled", "extensions": [".ods"], "mime_types": ["application/vnd.oasis.opendocument.spreadsheet"], "dependency": "odf", "output_container_kinds": ["table"], "help": "ODS preview needs odf plus workbook fixtures before it can be enabled."},
    "import.readstat": {"label": "SAS/Stata/SPSS", "status": "disabled", "extensions": [".sav", ".dta", ".sas7bdat"], "mime_types": ["application/octet-stream"], "dependency": "pyreadstat", "output_container_kinds": ["table"], "help": "ReadStat import needs pyreadstat plus privacy-safe fixtures before it can be enabled."},
    "import.sql": {"label": "SQL", "status": "disabled", "extensions": [".sqlite", ".db"], "mime_types": ["application/vnd.sqlite3"], "output_container_kinds": ["table"], "help": "SQL import is disabled until credential, sandbox, and preview-only policies are implemented."},
    "import.origin_scidavis_eval": {"label": "Origin/SciDAVis Evaluation", "status": "disabled", "extensions": [".opju", ".opj"], "mime_types": ["application/octet-stream"], "output_container_kinds": ["project"], "help": "Origin/SciDAVis project import remains disabled until clean-room parser policy and fixtures exist."},
    "import.image_digitizer": {"label": "Image Digitizer", "status": "disabled", "extensions": [".png", ".jpg", ".jpeg", ".tif", ".tiff"], "mime_types": ["image/png", "image/jpeg", "image/tiff"], "output_container_kinds": ["table"], "help": "Image digitizer belongs in a dedicated future workflow, not the generic import preview path."},
}


def _dependency_status(spec: dict[str, Any]) -> str:
    dependency = spec.get("dependency")
    if not dependency:
        return "not_required"
    return "available_disabled" if importlib.util.find_spec(str(dependency)) is not None else "missing"


def _options_schema(spec: dict[str, Any]) -> dict[str, Any]:
    options = list(spec.get("options") or [])
    properties: dict[str, Any] = {}
    required: list[str] = []
    for option in options:
        option_id = str(option["id"])
        kind = option.get("kind", "string")
        json_type = "array" if kind.endswith("_array") else ("integer" if kind == "integer" else "string")
        properties[option_id] = {"type": json_type, "description": option.get("help", "")}
        if option.get("choices"):
            properties[option_id]["enum"] = option["choices"]
        if option.get("required"):
            required.append(option_id)
    return {"type": "object", "required": required, "properties": properties}


def filter_profile(filter_id: str, spec: dict[str, Any]) -> dict[str, Any]:
    options_schema = _options_schema(spec)
    return {
        "id": filter_id,
        "label": spec["label"],
        "status": spec["status"],
        "extensions": list(spec.get("extensions", [])),
        "mime_types": list(spec.get("mime_types", [])),
        "dependency": spec.get("dependency"),
        "dependency_status": _dependency_status(spec),
        "preview_supported": bool(spec.get("preview_supported", False)),
        "read_supported": bool(spec.get("read_supported", False)),
        "write_supported": bool(spec.get("write_supported", False)),
        "options_schema": options_schema,
        "output_container_kinds": list(spec.get("output_container_kinds", [])),
        "help": spec.get("help", ""),
        "test_requirements": ["schema_decode", "import_preview_fixture", "data_studio_consumption"],
    }


def import_filter_capabilities() -> list[dict[str, Any]]:
    capabilities: list[dict[str, Any]] = []
    for filter_id, spec in FILTERS.items():
        profile = filter_profile(filter_id, spec)
        capabilities.append(
            {
                "id": filter_id,
                "label": profile["label"],
                "status": profile["status"],
                "owner": "sidecar",
                "surface": "project" if filter_id == "import.origin_scidavis_eval" else "plot,data_studio",
                "extensions": profile["extensions"],
                "mime_types": profile["mime_types"],
                "dependency": profile["dependency"],
                "dependency_status": profile["dependency_status"],
                "preview_supported": profile["preview_supported"],
                "read_supported": profile["read_supported"],
                "write_supported": profile["write_supported"],
                "typed_payload_schema": profile["options_schema"],
                "help": profile["help"],
                "introduced_in": "import_filter_2",
                "test_requirements": profile["test_requirements"],
            }
        )
    return capabilities


def _detect_filter(path: Path, requested: str | None) -> str:
    if requested:
        return requested
    suffix = path.suffix.lower()
    for filter_id, spec in FILTERS.items():
        if suffix in spec["extensions"]:
            return filter_id
    return "import.csv"


def _base_response(path: Path, filter_id: str, spec: dict[str, Any]) -> dict[str, Any]:
    profile = filter_profile(filter_id, spec)
    return {
        "input_path": str(path),
        "filter_id": filter_id,
        "status": spec["status"],
        "label": spec["label"],
        "profile": profile,
        "data_containers": [],
        "diagnostics": [],
        "available_options": list(spec.get("options") or []),
        "structure": [],
        "selected_sheet_or_segment": None,
        "options_schema": profile["options_schema"],
        "help": spec.get("help", ""),
    }


def _unavailable(path: Path, filter_id: str, spec: dict[str, Any]) -> dict[str, Any]:
    response = _base_response(path, filter_id, spec)
    dependency = spec.get("dependency")
    dependency_status = response["profile"]["dependency_status"]
    status_code = "dependency_missing" if dependency_status == "missing" else "policy_not_implemented"
    response["diagnostics"] = [
        {
            "status_code": status_code,
            "severity": "warning",
            "message": f"{spec['label']} is disabled in this runtime.",
            "dependency": dependency,
            "dependency_status": dependency_status,
            "help_action": (
                "Install the optional dependency and enable fixtures before exposing this filter."
                if dependency_status == "missing"
                else "Define the safety policy, preview contract, and fixtures before exposing this filter."
            ),
        }
    ]
    response["help"] = spec.get("help", "This import filter is disabled.")
    return response


def _source_structure(preview: Any) -> list[dict[str, Any]]:
    root_id = f"source:{Path(preview.input_path).name}"
    nodes = [
        {
            "id": root_id,
            "kind": "file",
            "label": Path(preview.input_path).name,
            "row_count": int(preview.total_rows),
            "column_count": int(preview.total_cols),
        },
        {
            "id": f"{root_id}:sheet:{preview.sheet}",
            "kind": "sheet",
            "label": str(preview.sheet),
            "parent_id": root_id,
            "row_count": int(preview.total_rows),
            "column_count": int(preview.total_cols),
        },
    ]
    for segment in preview.segments:
        nodes.append(
            {
                "id": segment.id,
                "kind": "segment",
                "label": segment.label,
                "parent_id": f"{root_id}:sheet:{preview.sheet}",
                "row_count": int(segment.row_count),
                "column_count": int(segment.column_count),
                "payload": {
                    "header_row_index": segment.header_row_index,
                    "unit_row_index": segment.unit_row_index,
                    "data_start_row_index": segment.data_start_row_index,
                },
            }
        )
    return nodes


def _binary_dtype(dtype: str, endianness: str) -> np.dtype[Any]:
    parsed = np.dtype(dtype)
    if endianness == "little":
        return parsed.newbyteorder("<")
    if endianness == "big":
        return parsed.newbyteorder(">")
    return parsed


def preview_import(
    *,
    input_path: str | Path,
    filter_id: str | None = None,
    sheet: str | int = 0,
    offset: int = 0,
    limit: int = 50,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    path = Path(input_path).expanduser()
    resolved_filter = _detect_filter(path, filter_id)
    spec = FILTERS.get(resolved_filter)
    if spec is None:
        raise ValueError(f"Unknown import filter `{resolved_filter}`.")
    if spec["status"] == "disabled":
        return _unavailable(path, resolved_filter, spec)
    opts = options or {}
    if resolved_filter in {"import.csv", "import.excel"}:
        preview = source_table_preview(
            path,
            sheet=opts.get("sheet", sheet),
            offset=offset,
            limit=limit,
            encoding=opts.get("encoding"),
            delimiter=opts.get("delimiter"),
            segment_id=opts.get("segment_id"),
            header_row_index=opts.get("header_row_index"),
            unit_row_index=opts.get("unit_row_index"),
            data_start_row_index=opts.get("data_start_row_index"),
        )
        response = _base_response(path, resolved_filter, spec)
        response.update(
            {
                "data_containers": source_table_data_containers(preview),
                "diagnostics": list(preview.diagnostics),
                "structure": _source_structure(preview),
                "selected_sheet_or_segment": preview.selected_segment_id or str(preview.sheet),
                "help": "Preview generated through the shared source table import engine.",
            }
        )
        return response
    if resolved_filter == "import.json":
        raw = json.loads(path.read_text(encoding=str(opts.get("encoding") or "utf-8")))
        records = raw.get("records") if isinstance(raw, dict) else raw
        if not isinstance(records, list):
            raise ValueError("JSON preview requires a list of records or an object with a `records` list.")
        frame = pd.DataFrame(records)
        response = _base_response(path, resolved_filter, spec)
        response.update(
            {
                "data_containers": [
                    table_container_from_frame(
                        frame,
                        input_path=path,
                        container_id=f"import-json:{path.name}",
                        label=f"{path.name} JSON table",
                        status="enabled",
                        help_text="JSON records table generated by import preview.",
                    )
                ],
                "diagnostics": [
                    {
                        "status_code": "json_records_loaded",
                        "severity": "info",
                        "message": "Loaded JSON records into a readonly table container.",
                        "row_count": int(frame.shape[0]),
                    }
                ],
                "structure": [
                    {
                        "id": f"source:{path.name}:records",
                        "kind": "records",
                        "label": "records",
                        "row_count": int(frame.shape[0]),
                        "column_count": int(frame.shape[1]),
                    }
                ],
                "selected_sheet_or_segment": "records",
                "help": "JSON records preview is enabled for list/object-with-records payloads.",
            }
        )
        return response
    dtype = str(opts.get("dtype") or "float32")
    shape = opts.get("shape")
    if not isinstance(shape, list) or len(shape) != 2:
        raise ValueError("Binary/raw preview requires options.shape as [rows, columns].")
    endianness = str(opts.get("endianness") or "native")
    array = np.fromfile(path, dtype=_binary_dtype(dtype, endianness)).reshape((int(shape[0]), int(shape[1])))
    response = _base_response(path, resolved_filter, spec)
    response.update(
        {
            "data_containers": [matrix_container_from_array(array, input_path=path, container_id=f"import-binary:{path.name}")],
            "diagnostics": [
                {
                    "status_code": "binary_raw_loaded",
                    "severity": "info",
                    "message": "Loaded binary/raw values into a readonly matrix container.",
                    "dtype": dtype,
                    "shape": shape,
                    "endianness": endianness,
                }
            ],
            "structure": [
                {
                    "id": f"source:{path.name}:matrix",
                    "kind": "matrix",
                    "label": "raw matrix",
                    "row_count": int(shape[0]),
                    "column_count": int(shape[1]),
                }
            ],
            "selected_sheet_or_segment": "raw matrix",
            "help": "Binary/raw preview is enabled when explicit dtype and shape are provided.",
        }
    )
    return response


__all__ = ["FILTERS", "filter_profile", "import_filter_capabilities", "preview_import"]
