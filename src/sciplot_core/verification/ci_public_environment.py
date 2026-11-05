"""Finite Ubuntu public-CI compatibility facts, not a whole-OS attestation."""
from __future__ import annotations

import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import stat
import subprocess
import sys
import sysconfig
import time
from typing import Any

from sciplot_core.verification.public_stage import _git, runtime_binding, source_binding

REPOSITORY = "tunghsutian-creator/Science-Plot"
PROTOCOL = "sciplot-public-ci-behavior-v2"
COMMANDS = ["python -m sciplot_core.verification.public_stage --profile public-focused --out .tmp_verify/ci_public_focused",
            "python -m sciplot_core.verification.public_stage --profile public-comprehensive --out .tmp_verify/ci_public_comprehensive"]

INPUT_SCOPE_CONTRACT = {"origin": "public_source_binding_excludes_private_namespaces",
                        "profiles": "public_stage_private_namespace_absent"}

FONTCONFIG_ROOT = Path("/etc/fonts")

BINDING_FIELDS = frozenset({"protocol", "commands", "input_scope_contract", "workspace", "source_sha256", "image", "os_release", "kernel",
    "cpu_class", "cpu_count", "python", "stdlib_sha256", "source_modes_sha256", "qt_plugins_sha256", "fontconfig_sha256", "distributions", "system_packages_sha256", "native_sha256", "font_sha256",
    "qmake", "compiler", "abi_build", "application_environment", "head", "focused_count", "focused_skips",
    "focused_nodes_sha256", "comprehensive_nodes_sha256"})

class UnsupportedEnvironment(ValueError):
    """An expected missing or incompatible supported environment fact."""

def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def application_environment(root: Path) -> dict[str, str]:
    """An explicit process environment; no ambient event/credential variables."""
    return {"PATH": f"{root}/.venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "HOME": str(root / ".tmp_verify/ci-public-home"), "TMPDIR": str(root / ".tmp_verify/ci-public-tmp"),
            "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TZ": "UTC", "QT_QPA_PLATFORM": "offscreen",
            "PYTHONNOUSERSITE": "1", "PYTHONPATH": str(root / "src"),
            "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPYCACHEPREFIX": str(root / ".tmp_verify/ci-public-pycache"),
            "SCIPLOT_REPO": str(root), "SCIPLOT_SOURCE_ROOT": str(root / "src"),
            "SCIPLOT_RUNTIME_REPO": str(root), "SCIPLOT_VEUSZ_ROOT": str(root / "third_party/veusz")}



def _qt_plugin_root() -> Path:
    from PyQt6.QtCore import QLibraryInfo
    return Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath))


def _head_source(root: Path, source: dict[str, str]) -> str:
    """Check actual bytes against HEAD objects, including hidden index flags."""
    rows = _git(root, "ls-tree", "-r", "-z", "HEAD").split("\0")
    entries = {}
    modes = {}
    for row in rows:
        if not row:
            continue
        metadata, name = row.split("\t", 1)
        mode, kind, object_id = metadata.split()
        if name in source:
            if kind != "blob" or mode not in {"100644", "100755"}:
                raise UnsupportedEnvironment("unsupported_head_source_mode")
            entries[name] = object_id
            actual_mode = (root / name).stat().st_mode
            if bool(actual_mode & 0o111) != (mode == "100755"):
                raise UnsupportedEnvironment("head_source_execute_mode_drift")
            source_stat = (root / name).stat()
            modes[name] = {"mode": stat.S_IMODE(actual_mode), "uid": source_stat.st_uid, "gid": source_stat.st_gid}
    if set(entries) != set(source):
        raise UnsupportedEnvironment("head_source_membership_drift")
    names = sorted(entries)
    # Delegate byte identity to the existing Git owner. Its environment preserves
    # active public guards; --no-filters compares actual bytes with HEAD blob IDs.
    # Bounded argv batches avoid a second subprocess/environment implementation.
    for start in range(0, len(names), 200):
        batch = names[start:start + 200]
        observed = _git(root, "hash-object", "--no-filters", "--", *batch).splitlines()
        if observed != [entries[name] for name in batch]:
            raise UnsupportedEnvironment("head_source_bytes_drift")
    return digest(modes)


def collect_environment(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Hash supported installed inputs; never traverse HOME/private namespaces."""
    if sys.platform == "linux":
        return _collect_ubuntu(root)
    raise UnsupportedEnvironment("unsupported_platform_or_python")


def _collect_ubuntu(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    started = time.monotonic()
    if platform.python_version_tuple()[:2] != ("3", "12"):
        raise UnsupportedEnvironment("unsupported_platform_or_python")
    image = {key: os.environ.get(key, "") for key in ("ImageOS", "ImageVersion")}
    if image["ImageOS"] != "ubuntu24" or not image["ImageVersion"]:
        raise UnsupportedEnvironment("unsupported_or_unknown_runner_image")
    os_release = Path("/etc/os-release").read_text()
    if 'ID=ubuntu' not in os_release or 'VERSION_ID="24.04"' not in os_release:
        raise UnsupportedEnvironment("unsupported_distribution")
    environment = application_environment(root)
    if not sys.dont_write_bytecode or sys.pycache_prefix != environment["PYTHONPYCACHEPREFIX"]:
        raise UnsupportedEnvironment("collector_requires_owned_bytecode_policy")
    try:
        # Original checkout may contain tracked historical fixtures. The existing
        # source owner excludes them without reading; each profile stage owns absence.
        source = source_binding(root)
    except ValueError as error:
        raise UnsupportedEnvironment("source_binding: " + str(error)) from error
    source_modes = _head_source(root, source)
    cache: dict[Path, tuple[tuple[int, ...], str]] = {}
    aliases: dict[Path, Path] = {}
    byte_count = file_count = 0
    def file_identity(path: Path) -> str:
        nonlocal byte_count, file_count
        logical = path
        path = path.resolve(strict=True)
        aliases[logical] = path
        allowed = (root / ".venv", root / "src", Path("/usr/lib"), Path("/usr/local/lib"),
                   Path("/usr/bin"), Path("/usr/local/bin"), Path("/usr/share/fonts"),
                   Path("/usr/local/share/fonts"), Path("/usr/share"), Path("/etc/fonts"), root / "third_party/veusz")
        tracked_source = path.is_relative_to(root) and str(path.relative_to(root)) in source
        if not path.is_file() or not (tracked_source or any(path.is_relative_to(base) for base in allowed)):
            raise UnsupportedEnvironment("unsupported_installed_input_root")
        before = path.stat()
        stamp = (before.st_dev, before.st_ino, before.st_mode, before.st_uid, before.st_gid,
                 before.st_size, before.st_mtime_ns, before.st_ctime_ns)
        if path in cache:
            if cache[path][0] != stamp:
                raise UnsupportedEnvironment("installed_input_drift")
            return cache[path][1]
        value = digest({"bytes_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                        "mode": stat.S_IMODE(before.st_mode), "uid": before.st_uid, "gid": before.st_gid, "resolved_path": str(path)})
        after = path.stat()
        if stamp != (after.st_dev, after.st_ino, after.st_mode, after.st_uid, after.st_gid,
                     after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise UnsupportedEnvironment("installed_input_drift")
        cache[path] = (stamp, value)
        file_count += 1
        byte_count += after.st_size
        return value
    def command(*argv: str) -> str:
        text = subprocess.run(argv, env=environment, cwd=root, check=True, capture_output=True,
                              text=True, timeout=30).stdout.strip()
        if not text:
            raise UnsupportedEnvironment("missing_tool_observation:" + argv[0])
        return text
    distributions: dict[str, Any] = {}
    distribution_members: dict[str, dict[str, str]] = {}
    extensions: set[Path] = {Path(sys.executable).resolve()}
    stdlib_files = {}
    stdlib = Path(sysconfig.get_path("stdlib"))
    for directory, names, filenames in os.walk(stdlib, followlinks=False):
        names[:] = [name for name in names if name not in {"site-packages", "dist-packages", "__pycache__"}]
        if any((Path(directory) / name).is_symlink() for name in names):
            raise UnsupportedEnvironment("stdlib_directory_alias")
        for filename in filenames:
            path = Path(directory) / filename
            if path.suffix == ".pyc":
                if not path.with_suffix(".py").is_file():
                    raise UnsupportedEnvironment("unsupported_sourceless_stdlib")
                continue
            stdlib_files[str(path)] = file_identity(path)
            if ".so" in path.name:
                extensions.add(path.resolve())
    if not stdlib_files:
        raise UnsupportedEnvironment("missing_stdlib_identity")
    for dist in importlib.metadata.distributions():
        name = dist.name
        if not name or not isinstance(dist.version, str) or not dist.version:
            raise UnsupportedEnvironment("unknown_installed_distribution")
        recorded_files = dist.files
        files: list[Path] | None = ([Path(str(dist.locate_file(member))) for member in recorded_files]
                                   if recorded_files is not None else None)
        if files is None:
            if not isinstance(dist, importlib.metadata.PathDistribution):
                raise UnsupportedEnvironment("unknown_system_distribution")
            metadata = Path(str(dist._path))
            owners = command("dpkg-query", "-S", str(metadata)).splitlines()
            if len(owners) != 1 or ": " not in owners[0]:
                raise UnsupportedEnvironment("unknown_system_distribution_owner")
            package = owners[0].rsplit(": ", 1)[0]
            files = [Path(name) for name in command("dpkg-query", "-L", package).splitlines() if Path(name).is_file()]
            if not files:
                raise UnsupportedEnvironment("empty_system_distribution")
        name = name.lower().replace("_", "-")
        if name in distributions and distributions[name]["version"] != dist.version:
            raise UnsupportedEnvironment("conflicting_installed_distribution")
        members = distribution_members.setdefault(name, {})
        for path in files:
            if path.suffix == ".pyc":
                candidate = Path(importlib.util.source_from_cache(str(path))) if "__pycache__" in path.parts else path.with_suffix(".py")
                if not candidate.is_file():
                    raise UnsupportedEnvironment("unsupported_sourceless_bytecode")
                continue
            members[str(path)] = file_identity(path)
            if ".so" in path.name:
                extensions.add(path.resolve())
        distributions[name] = {"version": dist.version, "files_sha256": digest(members)}
    helpers = list((root / "third_party/veusz/veusz/helpers").glob("*.so"))
    extensions.update(path.resolve() for path in helpers)
    if not helpers or len(extensions) > 800:
        raise UnsupportedEnvironment("unsupported_native_extension_set")
    plugin_root = _qt_plugin_root()
    if not any(plugin_root.resolve().is_relative_to(base) for base in (Path("/usr/lib"), root / ".venv")):
        raise UnsupportedEnvironment("unsupported_qt_plugin_root")
    if (not (plugin_root / "platforms/libqoffscreen.so").is_file()
            or not (plugin_root / "imageformats/libqtiff.so").is_file()):
        raise UnsupportedEnvironment("missing_supported_qt_plugins")
    plugins = {}
    for path in plugin_root.rglob("*"):
        if path.is_symlink() and path.is_dir():
            raise UnsupportedEnvironment("qt_plugin_directory_alias")
        if path.is_file():
            plugins[str(path)] = file_identity(path)
            if ".so" in path.name:
                extensions.add(path.resolve())
    fontconfig = {}
    if not any(FONTCONFIG_ROOT.resolve().is_relative_to(base) for base in (Path("/etc/fonts"), root / ".venv")):
        raise UnsupportedEnvironment("unsupported_fontconfig_root")
    for path in FONTCONFIG_ROOT.rglob("*"):
        if path.is_symlink() and path.is_dir():
            raise UnsupportedEnvironment("fontconfig_directory_alias")
        if path.is_file():
            fontconfig[str(path)] = file_identity(path)
    if not fontconfig:
        raise UnsupportedEnvironment("missing_fontconfig")
    native = {}
    for extension in sorted(extensions):
        native[str(extension)] = file_identity(extension)
        output = command("ldd", str(extension))
        if "not found" in output:
            raise UnsupportedEnvironment("unresolved_native_dependency")
        for line in output.splitlines():
            match = re.search(r"(?:=>\s*)?(/\S+)\s+\(", line)
            if match:
                path = Path(match.group(1)).resolve(strict=True)
                native[str(path)] = file_identity(path)
    fonts = {str(path): file_identity(path) for path in sorted({Path(name) for name in command("fc-list", "--format", "%{file}\\n").splitlines() if name})}
    if not fonts:
        raise UnsupportedEnvironment("missing_font_identity")
    cpu: dict[str, set[str]] = {}
    for line in Path("/proc/cpuinfo").read_text().splitlines():
        key, separator, value = line.partition(":")
        if separator and key.strip() in {"vendor_id", "model name", "flags", "CPU implementer", "CPU part"}:
            cpu.setdefault(key.strip(), set()).add(value.strip())
    if not cpu or any(not value for values in cpu.values() for value in values) or not os.cpu_count():
        raise UnsupportedEnvironment("missing_cpu_class")
    facts = {"protocol": PROTOCOL, "commands": COMMANDS, "input_scope_contract": INPUT_SCOPE_CONTRACT, "workspace": str(root),
             "source_sha256": digest(source), "source_modes_sha256": source_modes, "image": image,
             "qt_plugins_sha256": digest(plugins), "fontconfig_sha256": digest(fontconfig),
             "os_release": os_release, "kernel": [platform.system(), platform.release(), platform.machine()],
             "cpu_class": {key: sorted(value) for key, value in cpu.items()}, "cpu_count": os.cpu_count(),
             "python": runtime_binding(root, environment), "stdlib_sha256": digest(stdlib_files), "distributions": distributions,
             "system_packages_sha256": digest(command("dpkg-query", "-W", "-f=${Package}=${Version}:${Architecture}\\n").splitlines()),
             "native_sha256": digest(native), "font_sha256": digest(fonts),
             "qmake": command("qmake6", "-query"), "compiler": command("c++", "--version"),
             "abi_build": {key: sysconfig.get_config_var(key) for key in
                           ("SOABI", "MULTIARCH", "CONFIG_ARGS", "CFLAGS", "LDFLAGS", "LDSHARED", "CC", "CXX", "Py_ENABLE_SHARED")},
             "application_environment": environment}
    if any(path.resolve(strict=True) != target for path, target in aliases.items()):
        raise UnsupportedEnvironment("installed_alias_drift")
    for path, (stamp, _value) in cache.items():
        current = path.stat()
        if stamp != (current.st_dev, current.st_ino, current.st_mode, current.st_uid, current.st_gid,
                     current.st_size, current.st_mtime_ns, current.st_ctime_ns):
            raise UnsupportedEnvironment("installed_input_drift")
    return facts, {"elapsed_seconds": time.monotonic() - started, "files_hashed": file_count,
                   "bytes_hashed": byte_count, "native_extension_count": len(extensions),
                   "claim": "collector_cost_only_not_suite_speedup"}
