"""Pure boundaries exercised by the existing repository-policy regression node."""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import subprocess
from pathlib import Path
import types
import urllib.error
import zipfile

import pytest


def exercise_public_reference(root, tmp_path, monkeypatch):
    from sciplot_core.verification import ci_public_reuse as reuse
    from sciplot_core.verification.ci_public_environment import (
        BINDING_FIELDS, COMMANDS, INPUT_SCOPE_CONTRACT, PROTOCOL, REPOSITORY, UnsupportedEnvironment, application_environment, collect_environment,
    )
    from sciplot_core.verification.ci_public_proof import (
        CLAIM, origin_eligible, policy_compatible, unpack_artifact,
    )
    now = datetime.now(timezone.utc)
    binding = {"protocol": PROTOCOL, "commands": COMMANDS, "input_scope_contract": INPUT_SCOPE_CONTRACT, "head": "a" * 40, "focused_count": 10,
               "focused_skips": 1, "focused_nodes_sha256": "e" * 64, "comprehensive_nodes_sha256": "b" * 64,
               "source_sha256": "c" * 64, "native_sha256": "d" * 64, "image": "supported", "cpu_count": 1}
    binding = {**{key: "finite-tested-fact" for key in BINDING_FIELDS}, **binding}
    proof = {"kind": "sciplot_public_ci_result", "version": 2, "claim": CLAIM, "fresh_execution": True,
             "created_at": now.isoformat(), "binding": binding,
             "origin": {"repository": REPOSITORY, "sha": "a" * 40, "run_id": 123, "attempt": 1,
                        "workflow": ".github/workflows/minimal-repository.yml"},
             "focused": {"passed": 9, "skipped": 1, "selected": 10, "selected_sha256": "e" * 64, "original_result_sha256": "f" * 64},
             "comprehensive": {"status": "PASS", "actual_exit_code": 0, "selected_sha256": "b" * 64, "original_result_sha256": "d" * 64}}
    run = {"id": 123, "run_attempt": 1, "head_sha": "a" * 40, "path": ".github/workflows/minimal-repository.yml",
           "event": "push", "status": "completed", "conclusion": "success", "repository": {"full_name": REPOSITORY},
           "head_repository": {"full_name": REPOSITORY, "fork": False}}
    jobs = {"jobs": [{"name": "runtime-integrity", "status": "completed", "conclusion": "success", "steps": [
        {"name": name, "status": "completed", "conclusion": "success"} for name in
        ("Run reviewed public focused behavior", "Run reviewed public comprehensive behavior")]}]}
    artifact = {"name": "public-result-123-1", "expired": False, "expires_at": (now + timedelta(days=1)).isoformat(),
                "workflow_run": {"id": 123, "head_sha": "a" * 40}}
    assert origin_eligible(proof, binding, run, jobs, artifact, now) is None
    for value in (True, float("nan"), {"not-json"}):
        wrong_type = copy.deepcopy(proof)
        wrong_type["binding"]["cpu_count"] = value
        assert origin_eligible(wrong_type, binding, run, jobs, artifact, now) is not None
    for key in ("protocol", "source_sha256", "native_sha256", "image", "comprehensive_nodes_sha256", "commands", "application_environment", "font_sha256", "abi_build", "system_packages_sha256"):
        changed = copy.deepcopy(binding)
        changed[key] = "changed"
        assert origin_eligible(proof, changed, run, jobs, artifact, now)
    incomplete = copy.deepcopy(binding)
    del incomplete["cpu_class"]
    assert origin_eligible(proof, incomplete, run, jobs, artifact, now) == "incomplete_current_binding"
    for target, path, value in (
        ("proof", ("fresh_execution",), False), ("proof", ("version",), 0), ("proof", ("version",), 1),
        ("proof", ("created_at",), (now - timedelta(days=8)).isoformat()),
        ("proof", ("focused", "passed"), 8), ("run", ("head_repository", "fork"), True),
        ("run", ("head_repository", "full_name"), "fork/repo"),
        ("run", ("conclusion",), "failure"), ("run", ("status",), "in_progress"),
        ("run", ("run_attempt",), 2), ("run", ("event",), "pull_request"),
        ("run", ("path",), "other.yml"), ("artifact", ("expired",), True),
        ("artifact", ("workflow_run", "id"), 999),
        ("jobs", ("jobs", 0, "steps", 0, "conclusion"), "skipped"),
    ):
        values = copy.deepcopy(dict(proof=proof, run=run, jobs=jobs, artifact=artifact))
        node = values[target]
        for part in path[:-1]:
            node = node[part]
        node[path[-1]] = value
        assert origin_eligible(values["proof"], binding, values["run"], values["jobs"], values["artifact"], now)
    supported_policy = {"name": "main", "protected": False, "protection": {"enabled": False,
                        "required_status_checks": {"enforcement_level": "off", "contexts": [], "checks": []}}}
    assert policy_compatible(supported_policy, [])
    for branch, rules in (({}, []), ({"name": "main", "protected": True}, []), ({"name": "main", "protected": False}, [{}]), (None, [])):
        assert not policy_compatible(branch, rules)
    def archive(name="public-result.json", content=None):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as output:
            output.writestr(name, json.dumps(proof) if content is None else content)
        return stream.getvalue()
    data = archive()
    assert unpack_artifact(data, "sha256:" + hashlib.sha256(data).hexdigest()) == proof
    for archive_bytes, expected in ((data, "sha256:" + "0" * 64), (archive("../public-result.json"), None), (archive(content="{"), None)):
        with pytest.raises((ValueError, json.JSONDecodeError)):
            unpack_artifact(archive_bytes, expected or "sha256:" + hashlib.sha256(archive_bytes).hexdigest())
    environment = application_environment(root)
    assert not any(key.startswith(("GITHUB_", "GH_", "RUNNER_")) for key in environment)
    assert not policy_compatible({"name": "main", "protected": False}, [])
    assert environment["PYTHONDONTWRITEBYTECODE"] == "1"
    assert environment["PYTHONPYCACHEPREFIX"] == str(root / ".tmp_verify/ci-public-pycache")
    assert environment["HOME"].startswith(str(root / ".tmp_verify/"))
    if reuse.sys.platform != "linux":
        with pytest.raises(UnsupportedEnvironment, match="unsupported_platform"):
            collect_environment(root)
    with monkeypatch.context() as context:
        context.setenv("SCIPLOT_PUBLIC_REUSE", "false")
        context.setenv("GITHUB_OUTPUT", str(tmp_path / "disabled-output"))
        context.setattr(reuse, "api", lambda *_a, **_k: pytest.fail("disabled made API call"))
        reuse.prepare(tmp_path)
        assert "reuse=false" in (tmp_path / "disabled-output").read_text()
        assert not (tmp_path / reuse.DIRECTORY).exists()
    with monkeypatch.context() as context:
        context.setenv("SCIPLOT_PUBLIC_REUSE", "true")
        context.setenv("GITHUB_REPOSITORY", REPOSITORY)
        context.setenv("GITHUB_EVENT_NAME", "push")
        context.setenv("GITHUB_REF", "refs/heads/main")
        context.setenv("GITHUB_RUN_ID", "456")
        context.setenv("GITHUB_OUTPUT", str(tmp_path / "enabled-output"))
        fresh_root = tmp_path / "fresh"
        fresh_root.mkdir()
        supported = copy.deepcopy(binding)
        supported["application_environment"] = application_environment(fresh_root)
        context.setattr(reuse, "binding", lambda _root: (supported, {"elapsed_seconds": 0.01}))
        def wire(path, **kwargs):
            if path.endswith("/" + REPOSITORY):
                return {"full_name": REPOSITORY, "fork": False}
            if path.endswith("/branches/main"):
                return supported_policy
            if "rulesets" in path:
                return []
            return {"workflow_runs": []}
        context.setattr(reuse, "api", wire)
        reuse.prepare(fresh_root)
        text = (tmp_path / "enabled-output").read_text()
        assert "reuse=false" in text and "FRESH:origin_absent" in text
        hit_root = tmp_path / "hit"
        hit_root.mkdir()
        hit_binding = {**binding, "application_environment": application_environment(hit_root)}
        hit_proof = {**proof, "binding": hit_binding}
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as output:
            output.writestr("public-result.json", json.dumps(hit_proof))
        hit_bytes = stream.getvalue()
        hit_artifact = {**artifact, "id": 77, "digest": "sha256:" + hashlib.sha256(hit_bytes).hexdigest()}
        context.setattr(reuse, "binding", lambda _root: (hit_binding, {"elapsed_seconds": 0.01}))
        def hit_wire(path, **kwargs):
            if "/workflows/" in path:
                return {"workflow_runs": [run]}
            if "/artifacts?" in path:
                return {"artifacts": [hit_artifact]}
            if path.endswith("/zip"):
                assert kwargs == {"archive": True}
                return hit_bytes
            if "/jobs?" in path:
                return jobs
            return wire(path, **kwargs)
        context.setattr(reuse, "api", hit_wire)
        reuse.prepare(hit_root)
        assert (hit_root / reuse.DIRECTORY / "reference.json").is_file()
        assert "reuse=true" in (tmp_path / "enabled-output").read_text()
        reuse.publish(hit_root)
        assert not (hit_root / reuse.DIRECTORY / "public-result.json").exists()
        context.setattr(reuse, "binding", lambda _root: ({**hit_binding, "native_sha256": "changed"}, {}))
        with pytest.raises(RuntimeError, match="binding drifted"):
            reuse.publish(hit_root)
        context.setattr(reuse, "binding", lambda _root: (hit_binding, {}))
        original_policy = reuse.fresh_policy
        context.setattr(reuse, "fresh_policy", lambda: (_ for _ in ()).throw(reuse.RemoteUnavailable("HTTP_403")))
        with pytest.raises(RuntimeError, match="lost final current facts/policy"):
            reuse.publish(hit_root)
        context.setattr(reuse, "fresh_policy", original_policy)
        # Internal defects are not swallowed into an expensive fresh retry.
        broken_root = tmp_path / "broken"
        broken_root.mkdir()
        def broken(_root):
            raise RuntimeError("programming defect")
        context.setattr(reuse, "binding", broken)
        with pytest.raises(RuntimeError, match="programming defect"):
            reuse.prepare(broken_root)
    workflow = (root / ".github/workflows/minimal-repository.yml").read_text()
    assert 'SCIPLOT_PUBLIC_REUSE: "true"' in workflow
    assert "actions: read" in workflow and "actions: write" not in workflow
    assert "include-hidden-files: true" in workflow and "retention-days: 7" in workflow


def exercise_collector(root, tmp_path, monkeypatch):
    from sciplot_core.verification import ci_public_environment as collector
    simulated = tmp_path / "collector"
    directory = simulated / ".venv/lib"
    directory.mkdir(parents=True)
    source = directory / "sample.py"
    source.write_text("x = 1\n")
    pycache = directory / "__pycache__/sample.cpython-312.pyc"
    pycache.parent.mkdir()
    pycache.write_bytes(b"old-cache")
    extension = directory / "sample.so"
    extension.write_bytes(b"finite-native-fixture")
    font = directory / "font.ttf"
    font.write_bytes(b"finite-font-fixture")
    plugins = directory / "qt-plugins"
    for name in ("platforms/libqoffscreen.so", "imageformats/libqtiff.so"):
        path = plugins / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(name.encode())
    configuration = directory / "fontconfig"
    configuration.mkdir()
    config_file = configuration / "fonts.conf"
    config_file.write_text("finite fontconfig")
    helpers = simulated / "third_party/veusz/veusz/helpers"
    helpers.mkdir(parents=True)
    for name in ("_nc_cntr", "qtmml", "qtloops", "recordpaint", "threed"):
        (helpers / (name + ".so")).write_bytes(name.encode())
    dist = types.SimpleNamespace(name="finite-package", version="1", files=[source, pycache, extension], locate_file=lambda member: member)
    private = simulated / "tests/fixtures/rendering_profiles/generated/input.csv"
    private.parent.mkdir(parents=True)
    private.write_text("generated namespace sentinel, not user data")
    (simulated / ".gitignore").write_text(".venv/\n.tmp_verify/\nthird_party/\n")
    (simulated / "public.py").write_text("PUBLIC = 1\n")
    for args in (("init", "-q"), ("config", "user.name", "finite fixture"),
                 ("config", "user.email", "fixture@invalid"), ("add", "."),
                 ("-c", "commit.gpgsign=false", "commit", "-qm", "tracked private-layout fixture")):
        subprocess.run(["git", *args], cwd=simulated, check=True, capture_output=True)
    real_run, read_bytes = subprocess.run, Path.read_bytes
    def public_bytes(path):
        assert not path.is_relative_to(private.parent), "collector read excluded private namespace"
        return read_bytes(path)
    read_text = Path.read_text
    def text(path, *args, **kwargs):
        if str(path) == "/etc/os-release":
            return 'ID=ubuntu\nVERSION_ID="24.04"'
        if str(path) == "/proc/cpuinfo":
            return "vendor_id: finite\nmodel name: finite CPU\nflags: finite"
        return read_text(path, *args, **kwargs)
    with monkeypatch.context() as context:
        context.setattr(collector.sys, "executable", str(extension))
        context.setattr(collector.sysconfig, "get_path", lambda _key: str(directory))
        context.setattr(collector.platform, "python_version_tuple", lambda: ("3", "12", "3"))
        context.setattr(collector.sys, "dont_write_bytecode", True)
        context.setattr(collector.sys, "pycache_prefix", str(simulated / ".tmp_verify/ci-public-pycache"))
        context.setenv("ImageOS", "ubuntu24")
        context.setenv("ImageVersion", "finite-image")
        context.setenv("GH_TOKEN", "never-collect-this-value")
        context.setattr(Path, "read_text", text)
        context.setattr(Path, "read_bytes", public_bytes)
        context.setattr(collector, "_qt_plugin_root", lambda: plugins)
        context.setattr(collector, "FONTCONFIG_ROOT", configuration)
        context.setattr(collector, "runtime_binding", lambda *_args: {"finite": "Python/Qt/helpers"})
        context.setattr(collector.importlib.metadata, "distributions", lambda: [dist])
        def tool(argv, **kwargs):
            if argv[0] == "git":
                return real_run(argv, **kwargs)
            assert "GH_TOKEN" not in kwargs["env"] and "GITHUB_REF" not in kwargs["env"]
            value = str(font) if argv[0] == "fc-list" else "finite tool facts"
            if argv[0] == "ldd":
                value = f"fixture => {extension} (0x0000)"
            return types.SimpleNamespace(stdout=value)
        context.setattr(collector.subprocess, "run", tool)
        from sciplot_core.verification.public_stage import assert_private_absent
        with pytest.raises(ValueError, match="private input namespace"):
            assert_private_absent(simulated, collector.application_environment(simulated))
        facts, costs = collector._collect_ubuntu(simulated)
        assert private.is_file()
        assert facts["input_scope_contract"]["origin"] == "public_source_binding_excludes_private_namespaces"
        assert costs["files_hashed"] >= 11 and costs["bytes_hashed"] > 0
        assert "never-collect-this-value" not in json.dumps(facts)
        pycache.write_bytes(b"different-legacy-cache")
        same, _ = collector._collect_ubuntu(simulated)
        assert same == facts  # The controlled Python mode cannot read legacy pyc.
        extension.write_bytes(b"changed-actual-native")
        changed, _ = collector._collect_ubuntu(simulated)
        assert changed["native_sha256"] != facts["native_sha256"]
        config_file.write_text("changed same-version font configuration")
        config_changed, _ = collector._collect_ubuntu(simulated)
        assert config_changed["fontconfig_sha256"] != changed["fontconfig_sha256"]
        (plugins / "platforms/libqoffscreen.so").write_bytes(b"changed-offscreen-plugin")
        plugin_changed, _ = collector._collect_ubuntu(simulated)
        assert plugin_changed["qt_plugins_sha256"] != config_changed["qt_plugins_sha256"]
        source.chmod(0o600)
        mode_changed, _ = collector._collect_ubuntu(simulated)
        assert mode_changed["distributions"] != plugin_changed["distributions"]
        context.setattr(collector.sys, "dont_write_bytecode", False)
        with pytest.raises(collector.UnsupportedEnvironment, match="bytecode"):
            collector._collect_ubuntu(simulated)
        context.setattr(collector.sys, "dont_write_bytecode", True)
        foreign = tmp_path / "foreign-installed-input.py"
        foreign.write_text("not a supported installed root")
        dist.files = [foreign]
        with pytest.raises(collector.UnsupportedEnvironment, match="input_root"):
            collector._collect_ubuntu(simulated)


def exercise_wire(tmp_path, monkeypatch):
    from sciplot_core.verification import ci_public_reuse as reuse
    with monkeypatch.context() as context:
        context.setenv("GH_TOKEN", "read-token-never-forward")
        def redirect(request, **kwargs):
            assert request.get_header("Authorization") == "Bearer read-token-never-forward"
            raise urllib.error.HTTPError(request.full_url, 302, "redirect", {"Location": "https://finite.blob.core.windows.net/result?signature=opaque"}, None)
        context.setattr(reuse.urllib.request, "build_opener", lambda *_args: types.SimpleNamespace(open=redirect))
        def storage(request, **kwargs):
            assert isinstance(request, str)  # No API Authorization header is forwarded.
            return io.BytesIO(b"finite-artifact")
        context.setattr(reuse.urllib.request, "urlopen", storage)
        assert reuse.api("/repos/" + reuse.REPOSITORY + "/actions/artifacts/1/zip", archive=True) == b"finite-artifact"
        def forbidden(request, **kwargs):
            raise urllib.error.HTTPError(request.full_url, 403, "denied-secret-detail", {}, None)
        context.setattr(reuse.urllib.request, "urlopen", forbidden)
        with pytest.raises(reuse.RemoteUnavailable, match="HTTP_403") as error:
            reuse.api("/repos/" + reuse.REPOSITORY)
        assert "denied-secret-detail" not in str(error.value)


def exercise_head_source(tmp_path):
    from sciplot_core.verification.ci_public_environment import UnsupportedEnvironment, _head_source
    root = tmp_path / "head-source"
    root.mkdir()
    def git(*args):
        return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)
    git("init", "-q")
    git("config", "user.name", "finite fixture")
    git("config", "user.email", "fixture@invalid")
    source = root / "sample.py"
    source.write_text("x = 1\n")
    git("add", "sample.py")
    git("-c", "commit.gpgsign=false", "commit", "-qm", "finite source")
    _head_source(root, {"sample.py": hashlib.sha256(source.read_bytes()).hexdigest()})
    git("update-index", "--assume-unchanged", "sample.py")
    source.write_text("x = 2\n")
    with pytest.raises(UnsupportedEnvironment, match="head_source_bytes"):
        _head_source(root, {"sample.py": hashlib.sha256(source.read_bytes()).hexdigest()})


def exercise_fresh_origin(tmp_path, monkeypatch):
    from sciplot_core.verification import ci_public_reuse as reuse
    from sciplot_core.verification.ci_public_environment import BINDING_FIELDS, COMMANDS, INPUT_SCOPE_CONTRACT, PROTOCOL, digest
    from sciplot_core.verification.public_stage import BINDING_CHECKS
    root = tmp_path / "producer"
    directory = root / reuse.DIRECTORY
    directory.mkdir(parents=True)
    node = "tests/test_generated.py::test_public"
    facts = {key: "finite-tested-fact" for key in BINDING_FIELDS}
    facts.update(protocol=PROTOCOL, commands=COMMANDS, input_scope_contract=INPUT_SCOPE_CONTRACT,
                 head="a" * 40, focused_count=1, focused_skips=0,
                 focused_nodes_sha256=digest([node]), comprehensive_nodes_sha256=digest([node]))
    (directory / "current.json").write_text(json.dumps({"binding": facts}))
    marker = {"complete": True, "exit_code": 0, "selected_tests": [node], "executed_tests": [node]}
    for index, profile in enumerate(("focused", "comprehensive")):
        (directory / (profile + ".exit.json")).write_text(json.dumps({
            "actual_exit_code": 0, "controlled": True, "command": COMMANDS[index]}))
        stage = root / (".tmp_verify/ci_public_" + profile)
        stage.mkdir()
        result = {"status": "PASS", "actual_exit_code": 0, "origin_head": "a" * 40,
                  "profile": "public-" + profile, "binding_checks": dict.fromkeys(BINDING_CHECKS, True), "finish": marker}
        (stage / "result.json").write_text(json.dumps(result))
        (stage / "reports.json").write_text(json.dumps({"selected_tests": [node], "exit_code": 0, "reports": [
            {"nodeid": node, "when": phase, "outcome": "passed"} for phase in ("setup", "call", "teardown")]}))
    with monkeypatch.context() as context:
        context.setattr(reuse, "binding", lambda _root: (facts, {"elapsed_seconds": 0.01}))
        context.setenv("GITHUB_RUN_ID", "123")
        context.setenv("GITHUB_RUN_ATTEMPT", "1")
        context.setenv("GITHUB_OUTPUT", str(tmp_path / "producer-output"))
        reuse.publish(root)
        proof = json.loads((directory / "public-result.json").read_text())
        assert proof["version"] == 2 and proof["fresh_execution"] is True
        assert {key: proof["focused"][key] for key in ("passed", "skipped", "selected")} == {"passed": 1, "skipped": 0, "selected": 1}
        for profile in ("focused", "comprehensive"):
            stage = root / (".tmp_verify/ci_public_" + profile)
            assert proof[profile]["original_result_sha256"] == hashlib.sha256((stage / "result.json").read_bytes()).hexdigest()
            original = json.loads((stage / "result.json").read_bytes())
            for bad_checks in ({}, {key: True for key in BINDING_CHECKS[1:]},
                               {**original["binding_checks"], BINDING_CHECKS[0]: "true"},
                               {**original["binding_checks"], BINDING_CHECKS[0]: 1},
                               {**original["binding_checks"], BINDING_CHECKS[0]: False}):
                (stage / "result.json").write_text(json.dumps({**original, "binding_checks": bad_checks}))
                with pytest.raises(ValueError, match=profile + " original evidence"):
                    reuse.publish(root)
            (stage / "result.json").write_text(json.dumps(original))
            reports_path = stage / "reports.json"
            original_reports = json.loads(reports_path.read_bytes())
            for mutation in ("missing_call", "failed_call", "duplicate_call"):
                broken = copy.deepcopy(original_reports)
                if mutation == "missing_call":
                    broken["reports"].pop(1)
                elif mutation == "failed_call":
                    broken["reports"][1]["outcome"] = "failed"
                else:
                    broken["reports"].append(copy.deepcopy(broken["reports"][1]))
                reports_path.write_text(json.dumps(broken))
                with pytest.raises(ValueError, match=profile + " original evidence"):
                    reuse.publish(root)
            reports_path.write_text(json.dumps(original_reports))
        assert "await_official_job_completion_not_yet_eligible" in (tmp_path / "producer-output").read_text()


def exercise_profile_stage_route(tmp_path, monkeypatch):
    from sciplot_core.verification import ci_public_reuse as reuse
    calls = []
    tails = []
    class Process:
        def __init__(self, command, **kwargs):
            self.is_tail = command[0] == "tail"
            self.stdout = io.StringIO("owner result\n") if not self.is_tail else None
            self.running = True
            calls.append(command)
            if self.is_tail:
                tails.append(self)
        def wait(self):
            self.running = False
            return 0
        def poll(self):
            return None if self.running else 0
        def terminate(self):
            self.running = False
    with monkeypatch.context() as context:
        context.setattr(reuse.subprocess, "Popen", Process)
        for profile in ("focused", "comprehensive"):
            assert reuse.run_profile(tmp_path, profile) == 0
            command = calls[-1]
            assert command[1:5] == ["-m", "sciplot_core.verification.public_stage", "--profile", "public-" + profile]
            assert command[-1] == ".tmp_verify/ci_public_" + profile
            assert str(tmp_path / (".tmp_verify/ci_public_" + profile + "/command.log")) in calls[-2]
        assert len(tails) == 2 and not any(tail.running for tail in tails)
