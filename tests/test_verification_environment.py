"""Generated semantic identity controls; execution/audit closure stays separate."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from sciplot_core.verification.evidence_environment import POLICY, ROUTING
from sciplot_core.verification.evidence_identity import capture_identity, digest, identity_valid
from sciplot_core.verification.private_observer import write_bootstrap
from sciplot_core.verification.public_input_guard import (
    BOOTSTRAP_KEY, ENVIRONMENT_KEY, _owned_bootstrap, configure_environment, rebind_bootstrap,
)
from test_verification_evidence import spec as _spec

spec = _spec


@pytest.mark.parametrize("drift", (
    "routing_only", "directory", "run", "roots", "bootstrap_env", "import_path",
    "dropped_observer", "unknown_audit_key", "startup_bytes", "plugin_as_startup", "ordinary_environment",
))
def test_actual_observer_projects_only_routing_and_keeps_other_identity_bindings(spec, drift):
    root = spec["repo_root"]
    plugin = root / "generated-bootstrap"
    write_bootstrap(plugin)
    environment = dict(os.environ)
    if not environment.get("SCIPLOT_PRIVATE_AUDIT_DIR") or not environment.get("SCIPLOT_PRIVATE_AUDIT_ROOTS"):
        output = root / "generated-observation"
        output.mkdir()
        watched = root / "generated-watched"
        watched.mkdir()
        environment.update(SCIPLOT_PRIVATE_AUDIT_DIR=str(output), SCIPLOT_PRIVATE_AUDIT_ROOTS=json.dumps([str(watched)]),
                           SCIPLOT_PRIVATE_AUDIT_RUN="generated-semantic-environment-control")
    if ENVIRONMENT_KEY in environment:
        environment = rebind_bootstrap(environment, plugin)
    else:
        environment["PYTHONPATH"] = os.pathsep.join(filter(None, [str(plugin), environment.get("PYTHONPATH", "")]))
    request = root / "generated-spec.json"
    request.write_text(json.dumps({key: str(value) if key == "repo_root" else value
                                  for key, value in spec.items() if key != "environment"}))
    code = """
import copy,json,os,sys
from pathlib import Path
from sciplot_core.verification import private_observer
from sciplot_core.verification.evidence import ARTIFACT_NAMES,check_reuse,make_receipt
from sciplot_core.verification.evidence_identity import capture_identity,identity_valid
request=json.loads(Path(sys.argv[1]).read_text());request['repo_root']=Path(request['repo_root'])
environment=dict(os.environ)
before=capture_identity(**request,environment=environment)
assert identity_valid(before) and 'environment_binding' in before
assert 'evidence_environment.py' in private_observer.source_hashes()
finish={'complete':True,'exit_code':0,'selected_tests':before['selected_tests'],'executed_tests':before['selected_tests']}
receipt=make_receipt(before=before,after=copy.deepcopy(before),exit_code=0,session_finish=finish,wall_seconds=0.1,
                     artifacts={name:'a'*64 for name in ARTIFACT_NAMES})
current=dict(environment)
drift=sys.argv[2]
if drift=='routing_only':
    current.update(SCIPLOT_PRIVATE_AUDIT_PARENT='new-routing-parent',SCIPLOT_PRIVATE_AUDIT_CHILD='new-routing-child')
elif drift=='directory': current['SCIPLOT_PRIVATE_AUDIT_DIR']+='-different'
elif drift=='run': current['SCIPLOT_PRIVATE_AUDIT_RUN']+='-different'
elif drift=='roots': current['SCIPLOT_PRIVATE_AUDIT_ROOTS']=json.dumps([str(request['repo_root']/'different-root')])
elif drift=='bootstrap_env': current['SCIPLOT_PUBLIC_GUARD_BOOTSTRAP']='different-binding'
elif drift=='import_path': current['PYTHONPATH']+=os.pathsep+str(request['repo_root']/'different-imports')
elif drift=='dropped_observer': private_observer._observer=None
elif drift=='unknown_audit_key': current['SCIPLOT_PRIVATE_AUDIT_UNKNOWN']='not-source-owned'
elif drift=='startup_bytes':
    path=Path(sys.modules['sitecustomize'].__file__);path.write_bytes(path.read_bytes()+b'# changed generated startup\\n')
elif drift=='plugin_as_startup':
    path=Path(sys.modules['sitecustomize'].__file__)
    path.write_text(private_observer.bootstrap_sources()['sciplot_closure_audit.py'])
else: current['QT_QPA_PLATFORM']='different-platform'
after=capture_identity(**request,environment=current)
result=check_reuse(receipt,after,artifacts=receipt['artifacts'])
assert result['status']==('PASS' if drift=='routing_only' else 'BLOCKED'),result
if drift in {'directory','run','roots','dropped_observer','unknown_audit_key','startup_bytes','plugin_as_startup'}:
    assert 'environment_binding' not in after and before!=after
print('ROUTING ONLY' if drift=='routing_only' else 'DRIFT BLOCKED')
"""
    result = subprocess.run([sys.executable, "-c", code, str(request), drift],
                            cwd=Path(__file__).parents[1], env=environment, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == ("ROUTING ONLY" if drift == "routing_only" else "DRIFT BLOCKED")


def test_environment_flags_or_scope_declaration_cannot_self_authorize_projection(spec):
    source = Path(__file__).parents[1]
    bootstrap = source / "src/sciplot_core/verification/public_guard_bootstrap/sitecustomize.py"
    assert _owned_bootstrap(bootstrap, [str(bootstrap.parent)], source)
    fake = spec["repo_root"] / "fake-source"
    (fake / "sciplot_core").mkdir(parents=True)
    (fake / "sciplot_core/__init__.py").write_text("# generated wrong source owner\n")
    assert not _owned_bootstrap(bootstrap, [str(bootstrap.parent), str(fake)], source)
    relocated = spec["repo_root"] / "copied-startup.py"
    relocated.write_bytes(bootstrap.read_bytes())
    assert not _owned_bootstrap(relocated, [str(relocated.parent)], source)
    alias = spec["repo_root"] / "aliased-startup.py"
    alias.symlink_to(bootstrap)
    assert not _owned_bootstrap(alias, [str(alias.parent)], source)
    spec["environment"].update(SCIPLOT_PRIVATE_AUDIT_DIR=str(spec["repo_root"] / "unstarted"),
                               SCIPLOT_PRIVATE_AUDIT_ROOTS=json.dumps([str(spec["repo_root"])]),
                               SCIPLOT_PRIVATE_AUDIT_RUN="not-an-active-observation",
                               SCIPLOT_PRIVATE_AUDIT_PARENT="parent", SCIPLOT_PRIVATE_AUDIT_CHILD="child")
    spec["scope"]["environment_binding"] = {"policy": POLICY, "excluded_keys": ROUTING}
    before = capture_identity(**spec)
    assert "environment_binding" not in before
    assert before["environment_sha256"] == digest(spec["environment"])
    spec["environment"]["SCIPLOT_PRIVATE_AUDIT_CHILD"] = "different-child"
    assert capture_identity(**spec) != before


@pytest.mark.parametrize("unsupported", ("source_shadow", "module_shadow", "cwd_module_shadow", "zip_shadow", "copied_startup", "aliased_startup"))
def test_actual_common_to_public_startup_rejects_unknown_source_and_aliases(tmp_path, unsupported):
    source = Path(__file__).parents[1]
    public = source / "src/sciplot_core/verification/public_guard_bootstrap"
    plugin = tmp_path / "common"
    write_bootstrap(plugin)
    secret = tmp_path / "generated-private.csv"
    secret.write_text("generated sentinel")
    environment = dict(os.environ)
    if not environment.get("SCIPLOT_PRIVATE_AUDIT_DIR") or not environment.get("SCIPLOT_PRIVATE_AUDIT_ROOTS"):
        audit = tmp_path / "raw"
        audit.mkdir()
        environment.update(SCIPLOT_PRIVATE_AUDIT_DIR=str(audit), SCIPLOT_PRIVATE_AUDIT_ROOTS=json.dumps([str(tmp_path)]),
                           SCIPLOT_PRIVATE_AUDIT_RUN="generated-bootstrap-negative")
    environment = configure_environment(source, environment, bootstrap=plugin)
    environment[ENVIRONMENT_KEY] = json.dumps(json.loads(environment[ENVIRONMENT_KEY]) + [str(secret)])
    code = """
import os,sys,subprocess,zipfile
from pathlib import Path
from sciplot_core.verification.public_input_guard import rebind_bootstrap
public,root,secret=map(Path,sys.argv[1:4]);mode=sys.argv[4]
child=rebind_bootstrap(dict(os.environ),public)
child['PYTHONPATH']=str(public)
cwd=None
if mode=='source_shadow':
    fake=root/'fake';(fake/'sciplot_core').mkdir(parents=True)
    (fake/'sciplot_core/__init__.py').write_text('# generated unknown package owner\\n')
    child['PYTHONPATH']+=os.pathsep+str(fake)
elif mode in {'module_shadow','cwd_module_shadow'}:
    fake=root/'fake';fake.mkdir();(fake/'sciplot_core.py').write_text('# generated unknown module owner\\n')
    if mode=='module_shadow': child['PYTHONPATH']+=os.pathsep+str(fake)
    else: cwd=fake
elif mode=='zip_shadow':
    archive=root/'fake.zip'
    with zipfile.ZipFile(archive,'w') as stream: stream.writestr('sciplot_core/__init__.py','# generated unknown zip owner\\n')
    child['PYTHONPATH']+=os.pathsep+str(archive)
elif mode=='copied_startup':
    copy=root/'copy';copy.mkdir();(copy/'sitecustomize.py').write_bytes((public/'sitecustomize.py').read_bytes())
    child=rebind_bootstrap(child,copy);child['PYTHONPATH']=str(copy)
else:
    alias=root/'alias';alias.symlink_to(public,target_is_directory=True)
    child=rebind_bootstrap(child,alias);child['PYTHONPATH']=str(alias)
try:
    subprocess.run([sys.executable,'-c',f'from pathlib import Path;Path({str(secret)!r}).read_bytes()'],cwd=cwd,env=child,check=False)
except PermissionError:
    print('REJECTED BEFORE LAUNCH')
else:
    raise AssertionError('unsupported startup reached child launch')
"""
    result = subprocess.run([sys.executable, "-c", code, str(public), str(tmp_path), str(secret), unsupported],
                            env=environment, cwd=source, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "REJECTED BEFORE LAUNCH"


def test_actual_same_common_binding_still_checks_the_child_source_owner(tmp_path):
    source = Path(__file__).parents[1]
    plugin = tmp_path / "common"
    write_bootstrap(plugin)
    secret = tmp_path / "generated-private.csv"
    secret.write_text("generated sentinel")
    environment = dict(os.environ)
    if not environment.get("SCIPLOT_PRIVATE_AUDIT_DIR") or not environment.get("SCIPLOT_PRIVATE_AUDIT_ROOTS"):
        audit = tmp_path / "raw"
        audit.mkdir()
        environment.update(SCIPLOT_PRIVATE_AUDIT_DIR=str(audit), SCIPLOT_PRIVATE_AUDIT_ROOTS=json.dumps([str(tmp_path)]),
                           SCIPLOT_PRIVATE_AUDIT_RUN="generated-same-binding-source-control")
    environment = configure_environment(source, environment, bootstrap=plugin)
    environment[ENVIRONMENT_KEY] = json.dumps(json.loads(environment[ENVIRONMENT_KEY]) + [str(secret)])
    code = """
import os,sys,subprocess
from pathlib import Path
root,secret=map(Path,sys.argv[1:])
child=dict(os.environ)
command=[sys.executable,'-c',f'from pathlib import Path;Path({str(secret)!r}).read_bytes()']
valid=subprocess.run(command,env=child,capture_output=True,text=True,check=False)
assert valid.returncode!=0 and 'Public input scope forbids private access' in valid.stderr,valid
fake=root/'fake';package=fake/'sciplot_core';verification=package/'verification';verification.mkdir(parents=True)
(package/'__init__.py').write_text('')
(verification/'__init__.py').write_text('')
for name in ('private_observer','public_input_guard'):
    (verification/(name+'.py')).write_text('def install(): pass\\n')
child['PYTHONPATH']=str(fake)+os.pathsep+child['PYTHONPATH']
assert child['SCIPLOT_PUBLIC_GUARD_BOOTSTRAP']==os.environ['SCIPLOT_PUBLIC_GUARD_BOOTSTRAP']
try:
    subprocess.run(command,env=child,capture_output=True,text=True,check=False)
except PermissionError:
    print('OWNED GUARDED; SAME-BINDING SHADOW REJECTED')
else:
    raise AssertionError('same binding bypassed actual child source ownership')
"""
    result = subprocess.run([sys.executable, "-c", code, str(tmp_path), str(secret)],
                            env=environment, cwd=source, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "OWNED GUARDED; SAME-BINDING SHADOW REJECTED"


@pytest.mark.parametrize("mutation", ("policy", "extra_key", "extra_exclusion", "scope_hash", "source_hash", "startup_hash"))
def test_offline_routing_policy_metadata_is_finite_and_fail_closed(spec, mutation):
    snapshot = capture_identity(**spec)
    binding = {"policy": POLICY, "excluded_keys": list(ROUTING), "audit_scope_sha256": "a" * 64,
               "observer_sources_sha256": "b" * 64, "startup_sha256": "c" * 64}
    if mutation == "policy":
        binding["policy"] = "arbitrary-exclusions"
    elif mutation == "extra_key":
        binding["caller_claim"] = True
    elif mutation == "extra_exclusion":
        binding["excluded_keys"].append(BOOTSTRAP_KEY)
    else:
        binding[{"scope_hash": "audit_scope_sha256", "source_hash": "observer_sources_sha256", "startup_hash": "startup_sha256"}[mutation]] = "unknown"
    snapshot["environment_binding"] = copy.deepcopy(binding)
    snapshot["sha256"] = digest({key: value for key, value in snapshot.items() if key != "sha256"})
    assert not identity_valid(snapshot)
