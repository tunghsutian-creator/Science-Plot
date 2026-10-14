"""Content identities for explicitly bounded, local development verification.

The caller owns dependency closure. Unknown closure is deliberately not reusable.
Paths are used locally to read bytes; snapshots expose only opaque path digests.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path
from typing import Any

from sciplot_core.foundation.json_hashing import canonical_json_sha256

DOMAINS = frozenset({
    "implementation", "tests", "config", "owner_policy", "dependencies", "python",
    "qt", "native", "fonts", "golden", "raw", "corpus_policy",
})
REQUIRED_FILES = frozenset({
    "implementation", "tests", "config", "owner_policy", "dependencies", "python",
    "corpus_policy",
})
PUBLIC_INPUT_POLICY = "public-generated-behavior-closure-v1"
PUBLIC_RAW_REASON = "No pre-existing public raw fixture bytes; selected behavior generates its inputs. Real raw science remains private/full."
PUBLIC_GOLDEN_REASON = "Public behavior has no scientific native golden input; exact real golden nodes remain private/full."


def digest(value: Any) -> str:
    return canonical_json_sha256(value, allow_nan=False)


def public_test_members(root: Path) -> tuple[list[Path], str]:
    """Bind public test/helper membership without entering private fixture roots."""
    fixture = root / "tests/fixtures"
    tests = root / "tests"
    private = {"real_world", "rendering_profiles", "polymer_corpus", "archived_output_raw_data"}
    caches = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".git"}
    files: list[Path] = []
    layout = {}

    def visit(path: Path) -> None:
        if path.is_symlink():
            raise ValueError("Public test/input aliases are not supported.")
        relative = path.relative_to(root).as_posix()
        if path.is_dir():
            layout[relative] = "directory"
            for entry in sorted(path.iterdir()):
                if (entry.name not in caches and not entry.name.endswith((".pyc", ".pyo"))
                        and not (path == fixture and entry.name in private)):
                    visit(entry)
        elif path.is_file():
            layout[relative] = "file"
            files.append(path)
        else:
            raise ValueError("Public test/input member is missing or unsupported.")

    if tests.exists() or tests.is_symlink():
        visit(tests)
    else:
        layout["tests"] = "missing"
    return files, digest(layout)


def _public_scope(scope: dict[str, Any], corpus: dict[str, Any]) -> bool:
    return (str(scope.get("input_scope", "")).startswith("public-")
            or str(scope.get("check_id", "")).startswith("pytest_public-") or "public_inputs" in scope
            or scope.get("closure_policy") == PUBLIC_INPUT_POLICY or corpus.get("policy") == PUBLIC_INPUT_POLICY)


def _public_binding(scope: dict[str, Any], corpus: dict[str, Any], command: list[str],
                    selection: list[str], inputs: dict[str, Any]) -> dict[str, Any] | None:
    """Validate the source-owned public exception against actual input records."""
    if not _public_scope(scope, corpus):
        return None
    binding = scope.get("public_inputs")
    if not isinstance(binding, dict) or set(binding) != {
        "policy", "profile", "manifest_path_sha256", "manifest_sha256", "selected_tests_sha256", "raw", "tests_layout_sha256",
    } or any(not isinstance(value, str) for value in binding.values()):
        raise ValueError("Public input closure needs its exact manifest/profile binding.")
    profile = binding["profile"]
    if (profile not in {"public-focused", "public-comprehensive", "public-all"}
            or scope.get("kind") != "pytest" or scope.get("input_scope") != profile
            or scope.get("check_id") != f"pytest_{profile}" or scope.get("closure_policy") != PUBLIC_INPUT_POLICY
            or binding["policy"] != PUBLIC_INPUT_POLICY
            or corpus.get("policy") != PUBLIC_INPUT_POLICY
            or any(corpus.get(key) is not False for key in ("fresh_access_audit", "scientific_acceptance"))
            or command[1:] != ["-m", "pytest", "-p", "sciplot_core.verification.pytest_finish", "-q", "--input-scope", profile]
            or not selection or binding["selected_tests_sha256"] != digest(sorted(selection))):
        raise ValueError("Public input closure profile/command/selection policy mismatch.")
    for domain in ("inventory", "corpus_policy"):
        record = inputs.get(domain, {}).get("files", {}).get(binding["manifest_path_sha256"], {})
        if record.get("sha256") != binding["manifest_sha256"]:
            raise ValueError("Public manifest must be present in captured inventory/policy bytes.")
    exclusions = scope.get("excluded_domains", {})
    if (inputs.get("golden") != {"not_applicable": PUBLIC_GOLDEN_REASON}
            or exclusions.get("golden") != PUBLIC_GOLDEN_REASON):
        raise ValueError("Public golden exclusion lacks the exact source-owned policy.")
    if binding["raw"] == "not_applicable":
        if (corpus.get("mode") != "synthetic" or inputs.get("raw") != {"not_applicable": PUBLIC_RAW_REASON}
                or exclusions.get("raw") != PUBLIC_RAW_REASON):
            raise ValueError("Generated-only public inputs need the exact raw exclusion policy.")
    elif (binding["raw"] != "bound_public_files" or corpus.get("mode") != "declared"
          or not inputs.get("raw", {}).get("files") or "raw" in exclusions):
        raise ValueError("Public raw fixtures require actual declared bytes.")
    return binding


def _stable_file(path: Path) -> dict[str, Any]:
    content = hashlib.sha256()
    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("identity input is not a regular file")
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            content.update(chunk)
        after = os.fstat(stream.fileno())
    current = path.stat()
    fields = ("st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns", "st_ctime_ns")
    if any(getattr(before, key) != getattr(after, key) or getattr(before, key) != getattr(current, key)
           for key in fields):
        raise ValueError("identity input changed during hashing")
    return {"sha256": content.hexdigest(), "size": after.st_size, "mode": stat.S_IMODE(after.st_mode)}


def _members(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    if not path.is_dir():
        raise ValueError("identity input is missing")
    result = [path]
    for parent, dirs, files in os.walk(path, followlinks=False):
        dirs[:] = sorted(name for name in dirs if name != "__pycache__")
        if any((Path(parent) / name).is_symlink() for name in dirs):
            raise ValueError("identity trees cannot contain directory symlinks; bind resolved roots")
        result.extend(Path(parent) / name for name in dirs)
        result.extend(Path(parent) / name for name in sorted(files)
                      if not name.endswith((".pyc", ".pyo")))
    return sorted(result)


def discover_files(paths: list[Path], *, allow_missing: bool = False) -> tuple[list[str], str]:
    """Resolve links and bind logical membership, including empty/missing dirs."""
    files: set[str] = set()
    layout: dict[str, str] = {}
    caches = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".git"}

    def visit(path: Path, ancestors: frozenset[Path]) -> None:
        if allow_missing and not path.exists() and not path.is_symlink():
            layout[digest(str(path.absolute()))] = digest("missing")
            return
        resolved = path.resolve(strict=True)
        layout[digest(str(path.absolute()))] = digest(str(resolved))
        if resolved.is_dir():
            if resolved in ancestors:
                raise ValueError("identity input contains a directory cycle")
            for entry in sorted(path.iterdir()):
                if entry.name not in caches and not entry.name.endswith((".pyc", ".pyo")):
                    visit(entry, ancestors | {resolved})
        elif resolved.is_file():
            files.add(str(resolved))
        else:
            raise ValueError("identity input is not a regular file/directory")

    for path in sorted(set(paths)):
        visit(path, frozenset())
    if not files:
        raise ValueError("identity input domain has no files")
    return sorted(files), digest(layout)


def capture_inputs(inputs: dict[str, Any], *, repo_root: Path,
                   excluded_domains: dict[str, str] | None = None) -> dict[str, Any]:
    """Hash every declared file and directory membership, without storing paths."""
    if not isinstance(inputs, dict) or not DOMAINS <= inputs.keys():
        raise ValueError("all verification identity domains must be declared")
    result = {}
    captured_files: dict[Path, dict[str, Any]] = {}
    for domain, binding in sorted(inputs.items()):
        if not isinstance(binding, dict):
            raise ValueError("invalid identity binding")
        if set(binding) == {"not_applicable"}:
            if domain in REQUIRED_FILES or not isinstance(binding["not_applicable"], str) or not binding["not_applicable"].strip():
                raise ValueError("required domain cannot be omitted")
            if (excluded_domains or {}).get(domain) != binding["not_applicable"]:
                raise ValueError("domain exclusion must be explicitly bound to scope policy")
            result[domain] = dict(binding)
            continue
        resolving = set(binding) == {"paths", "symlinks", "allow_missing"} and binding["symlinks"] == "resolve" and type(binding["allow_missing"]) is bool
        if (set(binding) != {"paths"} and not resolving) or not isinstance(binding["paths"], list) or not binding["paths"]:
            raise ValueError("identity binding needs nonempty paths")
        if resolving:
            roots = [Path(name).expanduser() if Path(name).is_absolute() else repo_root / name
                     for name in binding["paths"]]
            names, layout = discover_files(roots, allow_missing=binding["allow_missing"])
            for name in names:
                path = Path(name)
                if path not in captured_files:
                    captured_files[path] = _stable_file(path)
            records = {digest(name): captured_files[Path(name)] for name in names}
            if (names, layout) != discover_files(roots, allow_missing=binding["allow_missing"]):
                raise ValueError("identity tree membership changed during hashing")
            targets = {digest(str(path.absolute())): digest(str(path.resolve()) if path.exists() else "missing") for path in roots}
            payload = {"files": records, "layout_sha256": layout, "root_targets": targets}
            result[domain] = {**payload, "sha256": digest(payload)}
            continue
        records = {}
        for name in binding["paths"]:
            if not isinstance(name, str) or not name:
                raise ValueError("invalid identity path")
            path = Path(name).expanduser()
            path = path if path.is_absolute() else repo_root / path
            path = path.resolve(strict=True)
            members = _members(path)
            if not members:
                raise ValueError("empty identity tree")
            for member in members:
                if member.is_symlink():
                    raise ValueError("identity tree file symlinks need explicit resolved binding")
                key = digest(str(member))
                if member not in captured_files:
                    captured_files[member] = ({"sha256": digest("directory"), "size": 0,
                                               "mode": stat.S_IMODE(member.stat().st_mode)}
                                              if member.is_dir() else _stable_file(member))
                records[key] = captured_files[member]
            if members != _members(path):
                raise ValueError("identity tree membership changed during hashing")
        result[domain] = {"files": records, "sha256": digest(records)}
    return result


def capture_identity(*, repo_root: Path, command: list[str], scope: dict[str, Any],
                     selected_tests: list[str], inputs: dict[str, Any],
                     environment: dict[str, str], corpus: dict[str, Any]) -> dict[str, Any]:
    """Capture a declared closure, exact command/scope and effective environment.

``scope`` must include nonempty ``kind`` and ``closure_policy``. Git commit
metadata belongs in receipt provenance, not here: identical executable content
can survive a documentation-only commit. Scope/selection are never widened.
    ``corpus`` is synthetic, declared, or audited. Declared mode is a caller-owned
    static closure for this command and explicitly disclaims fresh access audit
    and scientific acceptance. Audited mode also binds the access receipt bytes.
    Neither mode infers complete closure from a preliminary inventory.
"""
    if not command or not all(isinstance(arg, str) and arg for arg in command):
        raise ValueError("command must be an exact nonempty argument vector")
    if not isinstance(scope, dict) or any(not isinstance(scope.get(key), str) or not scope[key].strip()
                                         for key in ("kind", "closure_policy")):
        raise ValueError("scope and reviewed closure policy are required")
    if not isinstance(selected_tests, list) or any(not isinstance(node, str) or not node for node in selected_tests) or len(set(selected_tests)) != len(selected_tests):
        raise ValueError("selected tests must be unique exact identifiers")
    if not isinstance(environment, dict) or not environment or not all(isinstance(k, str) and isinstance(v, str) for k, v in environment.items()):
        raise ValueError("effective execution environment must be bound")
    if not isinstance(corpus, dict) or corpus.get("complete") is not True or corpus.get("mode") not in {"synthetic", "declared", "audited"} or not corpus.get("policy"):
        raise ValueError("unknown or preliminary corpus closure")
    if corpus["mode"] == "declared" and (
        any(corpus.get(key) is not False for key in ("fresh_access_audit", "scientific_acceptance"))
        or any("paths" not in inputs.get(key, {}) for key in ("raw", "inventory"))
    ):
        raise ValueError("declared closure needs inventory/raw bytes and explicit acceptance exclusions")
    if corpus["mode"] == "audited" and (
        not {"inventory", "access_receipt"} <= inputs.keys()
        or any("paths" not in inputs.get(key, {}) for key in ("raw", "inventory", "access_receipt"))
    ):
        raise ValueError("audited corpus needs actual raw, inventory and access receipt bytes")
    public_members = public_test_members(repo_root) if _public_scope(scope, corpus) else None
    payload: dict[str, Any] = {
        "kind": "sciplot_verification_identity", "version": 1,
        "root_sha256": digest(str(repo_root.resolve())), "command": list(command),
        "scope": scope, "selected_tests": list(selected_tests),
        "inputs": capture_inputs(inputs, repo_root=repo_root,
                                 excluded_domains=scope.get("excluded_domains")),
        "environment_sha256": digest(environment), "corpus": corpus,
    }
    public = _public_binding(scope, corpus, command, selected_tests, payload["inputs"])
    if public is not None:
        from sciplot_core.verification.input_scope import load_manifest

        path = repo_root / "src/sciplot_core/verification/input_scope_manifest.json"
        if public_members is None or public_members != public_test_members(repo_root) or public["tests_layout_sha256"] != public_members[1]:
            raise ValueError("Public test/input namespace membership changed before capture.")
        public_raw = {digest(str(member.resolve())) for member in public_members[0]
                      if member.is_relative_to(repo_root / "tests/fixtures")}
        if (set(payload["inputs"]["tests"]["files"]) != {digest(str(member.resolve())) for member in public_members[0]}
                or (public["raw"] == "not_applicable" and public_raw)
                or (public["raw"] == "bound_public_files" and set(payload["inputs"]["raw"]["files"]) != public_raw)):
            raise ValueError("Public test/input namespace files differ from captured bytes.")
        manifest = load_manifest(path)
        expected_nodes = set(manifest["scopes"]["public"])
        if public["profile"] != "public-all":
            expected_nodes.intersection_update(manifest["tiers"][public["profile"].removeprefix("public-")])
        if (set(selected_tests) != expected_nodes or digest(str(path.resolve())) != public["manifest_path_sha256"]
                or _stable_file(path)["sha256"] != public["manifest_sha256"]):
            raise ValueError("Public selection differs from its actual source-owned manifest.")
    if "reviewed_test_sources_sha256" in scope:
        # Reconstruct the review digest from this snapshot's actual bytes, not
        # subsequently reread files or a discovery-time pin that can be replaced.
        source_digest = hashlib.sha256()
        records = payload["inputs"]["tests"]["files"]
        for path in sorted((repo_root / "tests").rglob("*.py")):
            record = records.get(digest(str(path.resolve())))
            if record is None:
                raise ValueError("reviewed test source membership changed during capture")
            relative = path.relative_to(repo_root).as_posix()
            source_digest.update(relative.encode() + b"\0" + record["sha256"].encode() + b"\n")
        if source_digest.hexdigest() != scope["reviewed_test_sources_sha256"]:
            raise ValueError("reviewed test source bytes changed before capture")
    layouts = scope.get("discovery_layouts", {})
    if not isinstance(layouts, dict) or any(payload["inputs"].get(key, {}).get("layout_sha256") != value for key, value in layouts.items()):
        raise ValueError("dependency-discovery membership changed before capture")
    aliases = scope.get("discovery_aliases", {})
    actual_aliases = {key: value for binding in payload["inputs"].values() for key, value in binding.get("root_targets", {}).items()}
    if not isinstance(aliases, dict) or any(actual_aliases.get(key) != value for key, value in aliases.items()):
        raise ValueError("dependency-discovery loader aliases changed before capture")
    expected = scope.get("discovery_bindings", {})
    actual = {key: record["sha256"] for binding in payload["inputs"].values()
              for key, record in binding.get("files", {}).items()}
    if not isinstance(expected, dict) or any(actual.get(key) != value for key, value in expected.items()):
        raise ValueError("dependency-discovery inputs changed before capture")
    # Freeze caller-owned mappings so subsequent plan construction cannot mutate
    # the already captured before-state through an alias.
    payload = json.loads(json.dumps(payload, allow_nan=False))
    return {**payload, "sha256": digest(payload)}


def identity_valid(identity: object) -> bool:
    """Validate untrusted snapshot structure without reading its paths or code."""
    try:
        if not isinstance(identity, dict) or set(identity) != {
            "kind", "version", "root_sha256", "command", "scope", "selected_tests",
            "inputs", "environment_sha256", "corpus", "sha256",
        }:
            return False
        if identity["kind"] != "sciplot_verification_identity" or type(identity["version"]) is not int or identity["version"] != 1:
            return False
        if not DOMAINS <= identity["inputs"].keys():
            return False
        if any(not isinstance(identity.get(key), str) or not re.fullmatch("[0-9a-f]{64}", identity[key])
               for key in ("root_sha256", "environment_sha256", "sha256")):
            return False
        if not isinstance(identity["command"], list) or not identity["command"] or not all(
            isinstance(arg, str) and arg for arg in identity["command"]
        ):
            return False
        scope, corpus, selection = identity["scope"], identity["corpus"], identity["selected_tests"]
        if not isinstance(scope, dict) or any(not isinstance(scope.get(key), str) or not scope[key].strip()
                                             for key in ("kind", "closure_policy")):
            return False
        if not isinstance(corpus, dict) or corpus.get("complete") is not True or corpus.get("mode") not in {"synthetic", "declared", "audited"} or not corpus.get("policy"):
            return False
        if not isinstance(selection, list) or not all(isinstance(node, str) and node for node in selection) or len(set(selection)) != len(selection):
            return False
        for domain, binding in identity["inputs"].items():
            if set(binding) == {"not_applicable"}:
                if domain in REQUIRED_FILES or not binding["not_applicable"] or scope.get("excluded_domains", {}).get(domain) != binding["not_applicable"]:
                    return False
            elif set(binding) in ({"files", "sha256"}, {"files", "layout_sha256", "root_targets", "sha256"}):
                payload = ({key: value for key, value in binding.items() if key != "sha256"}
                           if "layout_sha256" in binding else binding["files"])
                if not isinstance(binding["files"], dict) or not binding["files"] or digest(payload) != binding["sha256"]:
                    return False
                if "layout_sha256" in binding and (
                    not re.fullmatch("[0-9a-f]{64}", binding["layout_sha256"])
                    or not isinstance(binding["root_targets"], dict)
                    or any(not re.fullmatch("[0-9a-f]{64}", key) or not re.fullmatch("[0-9a-f]{64}", value) for key, value in binding["root_targets"].items())
                ):
                    return False
                for key, record in binding["files"].items():
                    if not re.fullmatch("[0-9a-f]{64}", key) or set(record) != {"sha256", "size", "mode"}:
                        return False
                    if not re.fullmatch("[0-9a-f]{64}", record["sha256"]) or type(record["size"]) is not int or record["size"] < 0 or type(record["mode"]) is not int:
                        return False
            else:
                return False
        if corpus["mode"] == "audited" and any("files" not in identity["inputs"].get(key, {}) for key in ("raw", "inventory", "access_receipt")):
            return False
        if corpus["mode"] == "declared" and (
            any(corpus.get(key) is not False for key in ("fresh_access_audit", "scientific_acceptance"))
            or any("files" not in identity["inputs"].get(key, {}) for key in ("raw", "inventory"))
        ):
            return False
        _public_binding(scope, corpus, identity["command"], selection, identity["inputs"])
        return bool(identity["sha256"] == digest({key: value for key, value in identity.items() if key != "sha256"}))
    except (KeyError, TypeError, ValueError, AttributeError):
        return False
