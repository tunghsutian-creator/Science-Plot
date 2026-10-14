"""Finite Mach-O diagnostic policy controls; no private inputs."""
from copy import deepcopy
import inspect
from pathlib import Path
import plistlib
import subprocess
import sys

import pytest

from sciplot_core.verification import native_probe_boundary as policy
from sciplot_core.verification.evidence_identity import digest


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    tool, target = tmp_path / 'llvm-otool', tmp_path / 'target'
    for path in (tool, target):
        path.write_bytes(b'\xcf\xfa\xed\xfe' + path.name.encode())
    system = tmp_path / 'system.plist'
    system.write_bytes(plistlib.dumps(dict(ProductName='TestOS', ProductVersion='1', ProductBuildVersion='A')))
    monkeypatch.setattr(policy, 'inspector_path', lambda: tool)
    monkeypatch.setattr(policy, '_SYSTEM', system)
    monkeypatch.setattr(policy, 'owned_caller', lambda *args: policy.owner_identity(*args))
    return tool, target, system


def invocation(tool, target, **changes):
    kwargs = dict(stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=policy.probe_environment())
    kwargs.update(changes)
    # Model the original bound fields, independent of an active observer port.
    return inspect.BoundArguments(inspect.Signature(),
        dict(self=None, args=[str(tool), '-L', str(target)], **kwargs))


def attempt_for(value):
    return {'argv_sha256': value['argv_sha256'], 'expected_executable_sha256': value['tool_sha256']}


def test_exact_inspection_requires_native_domain_tool_target_and_system(inputs):
    tool, target, system = inputs
    value = policy.native_probe_call(invocation(tool, target))
    records = {digest(str(p)): {'sha256': policy.file_sha256(p)} for p in inputs}
    assert policy.native_probe_bound(value, records, attempt_for(value))
    for path in inputs:
        missing = {k: v for k, v in records.items() if k != digest(str(path))}
        assert not policy.native_probe_bound(value, missing, attempt_for(value))
    target.write_bytes(b'changed')
    records[digest(str(target))]['sha256'] = policy.file_sha256(target)
    assert not policy.native_probe_bound(value, records, attempt_for(value))


@pytest.mark.parametrize('change', ['loader', 'shell', 'executable', 'cwd', 'fds', 'binary', 'mode', 'relative', 'non_macho', 'callsite'])
def test_unreviewed_native_invocation_cannot_obtain_boundary(inputs, monkeypatch, change):
    tool, target, _ = inputs
    kwargs = {'loader': {'env': {**policy.probe_environment(), 'DYLD_INSERT_LIBRARIES': '/injected'}},
              'shell': {'shell': True}, 'executable': {'executable': str(tool)},
              'cwd': {'cwd': str(target.parent)}, 'fds': {'pass_fds': (5,)}}.get(change, {})
    bound = invocation(tool, target, **kwargs)
    if change == 'binary':
        bound.arguments['args'][0] = '/usr/bin/otool'
    elif change == 'mode':
        bound.arguments['args'][1] = '-h'
    elif change == 'relative':
        bound.arguments['args'][2] = 'target'
    elif change == 'non_macho':
        target.write_text('ordinary bytes')
    elif change == 'callsite':
        monkeypatch.setattr(policy, 'owned_caller', lambda *args: None)
    assert policy.native_probe_call(bound) is None


@pytest.mark.parametrize('field', ['owner', 'mode', 'environment_sha256', 'tool_sha256', 'tool_path_sha256', 'system_sha256', 'extra'])
def test_altered_diagnostic_descriptor_is_rejected(inputs, field):
    tool, target, _ = inputs
    value = deepcopy(policy.native_probe_call(invocation(tool, target)))
    actual_attempt = attempt_for(value)
    value[field] = 'changed'
    records = {digest(str(p)): {'sha256': policy.file_sha256(p)} for p in inputs}
    assert not policy.native_probe_bound(value, records, actual_attempt)


@pytest.mark.parametrize('field', ['argv_sha256', 'expected_executable_sha256'])
def test_native_descriptor_cannot_replace_actual_launch_identity(inputs, field):
    tool, target, _ = inputs
    value = policy.native_probe_call(invocation(tool, target))
    actual_attempt = attempt_for(value)
    actual_attempt[field] = 'changed'
    records = {digest(str(p)): {'sha256': policy.file_sha256(p)} for p in inputs}
    assert not policy.native_probe_bound(value, records, actual_attempt)


def test_host_metadata_uses_actual_bound_build_and_kernel_without_probe(inputs, monkeypatch):
    monkeypatch.setattr(subprocess, 'Popen', lambda *a, **kw: pytest.fail('host spawned a probe'))
    _, _, system = inputs
    host = policy.system_identity(system)
    assert host['system'] == dict(ProductName='TestOS', ProductVersion='1', ProductBuildVersion='A')
    assert host['machine'] == policy.os.uname().machine
    assert host['kernel']['release'] == policy.os.uname().release


@pytest.mark.parametrize('value', [[], {}, {'ProductName': 'OS', 'ProductVersion': '1', 'ProductBuildVersion': ''}])
def test_unknown_host_build_remains_blocked(tmp_path, value):
    path = tmp_path / 'system'
    path.write_bytes(plistlib.dumps(value))
    with pytest.raises(ValueError, match='malformed'):
        policy.system_identity(path)


@pytest.mark.comprehensive
@pytest.mark.skipif(sys.platform != 'darwin', reason='finite CLT inspector is macOS-specific')
def test_actual_clt_inspector_uses_closed_environment_and_bound_native_target():
    from sciplot_core.verification.evidence_runtime import native_dependencies
    tool = policy.inspector_path()
    bindings = {}
    files = native_dependencies([], executable=Path(sys.executable), environment=dict(policy.os.environ), bindings=bindings)
    assert tool in files and Path(sys.executable).resolve() in files
    assert bindings[digest(str(tool))] == policy.file_sha256(tool)
