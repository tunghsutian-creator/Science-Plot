"""Finite source-owned Mach-O inspection, not arbitrary native-process capture."""
from __future__ import annotations

import inspect
import hashlib
import json
import os
from pathlib import Path
import plistlib
import subprocess
from typing import Any

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.verification.private_process_boundaries import owned_caller, owner_identity

_TOOL = Path('/Library/Developer/CommandLineTools/usr/bin/otool')
_SYSTEM = Path('/System/Library/CoreServices/SystemVersion.plist')
_MAGIC = frozenset({b'\xcf\xfa\xed\xfe', b'\xce\xfa\xed\xfe', b'\xca\xfe\xba\xbe', b'\xbe\xba\xfe\xca',
                    b'\xfe\xed\xfa\xcf', b'\xfe\xed\xfa\xce', b'\xca\xfe\xba\xbf', b'\xbf\xba\xfe\xca'})


def probe_environment() -> dict[str, str]:
    """The inspector does not inherit loader, SDK, toolchain or magic settings."""
    return {'PATH': '/usr/bin:/bin:/usr/sbin:/sbin', 'LANG': 'C', 'LC_ALL': 'C'}


def inspector_path() -> Path:
    """Use the finite CLT inspector directly, bypassing the selected-tool dispatcher."""
    path = _TOOL.resolve(strict=True)
    if (path.parent != _TOOL.parent or not path.is_file() or not os.access(path, os.X_OK)
            or not is_macho(path)):
        raise ValueError('The finite CLT Mach-O inspector is unavailable.')
    return path


def is_macho(path: Path) -> bool:
    with path.open('rb') as stream:
        return stream.read(4) in _MAGIC


def system_identity(path: Path) -> dict[str, Any]:
    """Read the already-bound sealed OS build, without spawning host probes."""
    value = plistlib.loads(path.read_bytes())
    keys = ('ProductName', 'ProductVersion', 'ProductBuildVersion')
    if not isinstance(value, dict) or any(not isinstance(value.get(key), str) or not value[key] for key in keys):
        raise ValueError('Sealed system build identity is malformed.')
    kernel = os.uname()
    return {'system': {key: value[key] for key in keys}, 'machine': kernel.machine,
            'kernel': {'sysname': kernel.sysname, 'release': kernel.release, 'version': kernel.version}}


def _boundary(mode: str, target: Path) -> dict[str, Any]:
    tool = inspector_path()
    return {'kind': 'owned_native_macho_inspection', 'mode': mode,
            'owner': owner_identity('evidence_runtime.py', 'native_dependencies'),
            'tool_path_sha256': canonical_json_sha256(str(tool), allow_nan=False), 'tool_sha256': file_sha256(tool),
            'target_path_sha256': canonical_json_sha256(str(target), allow_nan=False), 'target_sha256': file_sha256(target),
            'argv_sha256': hashlib.sha256(json.dumps({'argv': [str(tool), mode, str(target)]},
                sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest(),
            'environment_sha256': canonical_json_sha256(probe_environment(), allow_nan=False), 'system_sha256': file_sha256(_SYSTEM)}


def native_probe_call(bound: inspect.BoundArguments) -> dict[str, Any] | None:
    """Recognize only the unchanged native discovery owner and exact invocation."""
    command = bound.arguments.get('args')
    allowed = {'self', 'args', 'stdout', 'stderr', 'text', 'env'}
    if (set(bound.arguments) - allowed or not isinstance(command, (list, tuple)) or len(command) != 3
            or not all(isinstance(part, str) for part in command)
            or command[1] not in {'-L', '-l'}
            or bound.arguments.get('env') != probe_environment()
            or bound.arguments.get('stdout') != subprocess.PIPE or bound.arguments.get('stderr') != subprocess.PIPE
            or bound.arguments.get('text') is not True
            or owned_caller('evidence_runtime.py', 'native_dependencies') is None):
        return None
    try:
        target = Path(command[2])
        if (Path(command[0]) != inspector_path() or not target.is_absolute()
                or target != target.resolve(strict=True) or not is_macho(target)):
            return None
        return _boundary(command[1], target)
    except (OSError, ValueError):
        return None


def native_probe_bound(value: Any, records: dict[str, Any], attempt: dict[str, Any]) -> bool:
    """Require the actual tool, target and OS bytes in the original native domain."""
    if not isinstance(value, dict) or value.get('kind') != 'owned_native_macho_inspection':
        return False
    expected_keys = {'kind', 'mode', 'owner', 'tool_path_sha256', 'tool_sha256', 'target_path_sha256',
                     'target_sha256', 'environment_sha256', 'system_sha256', 'argv_sha256'}
    try:
        tool = inspector_path()
        return (set(value) == expected_keys and value['mode'] in {'-L', '-l'}
                and value['argv_sha256'] == attempt.get('argv_sha256')
                and value['tool_sha256'] == attempt.get('expected_executable_sha256')
                and value['owner'] == owner_identity('evidence_runtime.py', 'native_dependencies')
                and value['environment_sha256'] == canonical_json_sha256(probe_environment(), allow_nan=False)
                and value['tool_path_sha256'] == canonical_json_sha256(str(tool), allow_nan=False)
                and value['tool_sha256'] == file_sha256(tool)
                and records.get(canonical_json_sha256(str(tool), allow_nan=False), {}).get('sha256') == value['tool_sha256']
                and records.get(value['target_path_sha256'], {}).get('sha256') == value['target_sha256']
                and value['system_sha256'] == file_sha256(_SYSTEM)
                and records.get(canonical_json_sha256(str(_SYSTEM), allow_nan=False), {}).get('sha256') == value['system_sha256'])
    except (OSError, ValueError, TypeError):
        return False
