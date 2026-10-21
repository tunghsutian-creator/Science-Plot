"""Native kernel status is distinct from a parent wait and from genuine finish."""
from __future__ import annotations

from dataclasses import replace
import copy
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import time
from typing import Any

import pytest

from sciplot_core.verification import native_exit_boundary as boundary


def test_identity_rejects_unknown_fields_and_fictional_generation() -> None:
    value = boundary.ProcessIdentity(7, 2, 501, 123, 456, '/bin/example', '/tmp', 'a' * 64).to_dict()
    assert boundary.ProcessIdentity.from_dict(value).to_dict() == value
    for update in ({'pid': True}, {'start_sec': 0}, {'start_usec': 1_000_000},
                   {'cwd': 'relative'}, {'executable_sha256': 'unknown'}, {'extra': 'claim'}):
        with pytest.raises(ValueError):
            boundary.ProcessIdentity.from_dict({**value, **update})


def test_unsupported_platform_has_no_sensor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(boundary.sys, 'platform', 'linux')
    with pytest.raises(OSError, match='unsupported libproc ABI'):
        boundary.read_identity(os.getpid())


def _target(tmp_path: Path, code: str) -> tuple[subprocess.Popen[bytes], boundary.ProcessIdentity]:
    script = ('import os,sys,signal;print("ready",flush=True);sys.stdin.buffer.read(1);'
              'signal.signal(signal.SIGTERM,signal.SIG_DFL);os.kill(os.getpid(),signal.SIGTERM)'
              if code == 'sigterm' else
              f'import sys;print("ready",flush=True);sys.stdin.buffer.read(1);sys.exit({int(code)})')
    process = subprocess.Popen([sys.executable, '-c', script], cwd=tmp_path,
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert process.stdout is not None
    assert select.select([process.stdout], [], [], 10)[0]
    assert process.stdout.readline() == b'ready\n'
    return process, boundary.read_identity(process.pid)


def _release_wait(process: subprocess.Popen[bytes], path: Path) -> dict[str, Any]:
    assert process.stdin is not None
    released = time.monotonic_ns()
    process.stdin.write(b'x')
    process.stdin.close()
    pid, raw = os.waitpid(process.pid, 0)
    process.returncode = os.waitstatus_to_exitcode(raw)
    result = {'kind': 'actual_parent_wait', 'pid': pid, 'parent_pid': os.getpid(),
              'raw_wait_status': raw, 'returncode': process.returncode, 'released_monotonic_ns': released}
    path.write_text(json.dumps(result))
    return result


_WATCHER = '''import json,sys,os,time
from sciplot_core.verification.native_exit_boundary import NativeExitSensor,ProcessIdentity
sensor=NativeExitSensor()
request=ProcessIdentity.from_dict(json.loads(sys.argv[1]))
try:
 os.waitpid(request.pid,os.WNOHANG)
 raise RuntimeError('watcher unexpectedly owns target')
except ChildProcessError:
 pass
registration=sensor.register('control:owned-popen',request)
print(json.dumps({'binding':sensor.binding,'registration':registration,'nonparent_ECHILD':True}),flush=True)
if registration['status']!='REGISTERED':sys.exit(2)
facts=sensor.drain(5)
print(json.dumps({'facts':facts,'close':sensor.close()}),flush=True)
sys.exit(0 if len(facts)==1 and facts[0]['status']=='OBSERVED' else 3)
'''


@pytest.mark.skipif(sys.platform != 'darwin', reason='Darwin public kqueue/libproc capability')
@pytest.mark.parametrize(('code', 'expected_raw', 'expected_returncode'), [('0', 0, 0), ('79', 20224, 79), ('sigterm', 15, -15)])
def test_real_nonparent_status_matches_original_parent_wait(
    tmp_path: Path, code: str, expected_raw: int, expected_returncode: int,
) -> None:
    target, identity = _target(tmp_path, code)
    watcher = subprocess.Popen([sys.executable, '-c', _WATCHER, json.dumps(identity.to_dict())],
                               cwd=tmp_path, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert watcher.stdout is not None
    assert select.select([watcher.stdout], [], [], 10)[0]
    first = json.loads(watcher.stdout.readline())
    (tmp_path / 'registration.json').write_text(json.dumps(first))
    assert first['nonparent_ECHILD'] is True
    registration = first['registration']
    assert registration['status'] == 'REGISTERED'
    assert registration['before'] == registration['after'] == identity.to_dict()
    assert first['binding']['watcher_identity']['pid'] == watcher.pid
    waited = _release_wait(target, tmp_path / 'actual-parent-wait.json')
    stdout, stderr = watcher.communicate(timeout=10)
    (tmp_path / 'watcher.stdout').write_bytes(stdout)
    (tmp_path / 'watcher.stderr').write_bytes(stderr)
    (tmp_path / 'watcher-external-wait.json').write_text(json.dumps({'pid': watcher.pid, 'returncode': watcher.returncode}))
    assert watcher.returncode == 0, stderr
    final = json.loads(stdout)
    fact = final['facts'][0]
    assert fact['kind'] == 'kernel_exit_status' and fact['is_parent_wait'] is False
    assert fact['registration_sha256'] == registration['registration_sha256']
    assert fact['raw_event']['data'] == fact['raw_wait_status'] == waited['raw_wait_status'] == expected_raw
    assert fact['returncode'] == waited['returncode'] == expected_returncode
    assert registration['registered_monotonic_ns'] < waited['released_monotonic_ns'] < fact['observed_monotonic_ns']
    assert final['close'] == []
    assert boundary.validate_registration(registration, expected_identity=identity,
        generation='control:owned-popen', watcher_binding=first['binding'])
    assert boundary.validate_exit_fact(fact, registration)
    for field, bad in [('raw_wait_status', expected_raw ^ 256), ('returncode', expected_returncode + 1),
                       ('is_parent_wait', True), ('generation', 'other:token')]:
        assert not boundary.validate_exit_fact({**fact, field: bad}, registration)
    for field, bad in [('data', expected_raw ^ 256), ('ident', target.pid + 1),
                       ('fflags', 0x80000000), ('flags', 0)]:
        altered = copy.deepcopy(fact)
        altered['raw_event'][field] = bad
        assert not boundary.validate_exit_fact(altered, registration)
    changed_binding = copy.deepcopy(first['binding'])
    changed_binding['source_sha256'] = '0' * 64
    assert not boundary.validate_registration(registration, expected_identity=identity,
        generation='control:owned-popen', watcher_binding=changed_binding)
    changed_receipt = copy.deepcopy(registration)
    changed_receipt['receipts'][0]['data'] = 13
    changed_receipt['registration_sha256'] = boundary._digest({
        k: v for k, v in changed_receipt.items() if k != 'registration_sha256'})
    assert not boundary.validate_registration(changed_receipt, expected_identity=identity,
        generation='control:owned-popen', watcher_binding=first['binding'])
    assert not any(item['kind'] in {'child_exit', 'process_finish'} for item in final['facts'])


@pytest.mark.skipif(sys.platform != 'darwin', reason='Darwin public kqueue/libproc capability')
def test_late_and_wrong_identity_do_not_register(tmp_path: Path) -> None:
    target, identity = _target(tmp_path, '79')
    sensor = boundary.NativeExitSensor()
    wrong = sensor.register('wrong:owned-popen', replace(identity, executable_sha256='0' * 64))
    assert wrong['status'] == 'UNKNOWN'
    waited = _release_wait(target, tmp_path / 'actual-parent-wait.json')
    late = sensor.register('late:owned-popen', identity)
    assert waited['returncode'] == 79 and late['status'] == 'UNKNOWN'
    assert sensor.pending == 0 and sensor.drain() == [] and sensor.close() == []


@pytest.mark.skipif(sys.platform != 'darwin', reason='Darwin public kqueue/libproc capability')
def test_missing_event_and_closed_watcher_remain_unknown(tmp_path: Path) -> None:
    target, identity = _target(tmp_path, '0')
    sensor = boundary.NativeExitSensor()
    registration = sensor.register('held:owned-popen', identity)
    assert registration['status'] == 'REGISTERED'
    assert sensor.pending == 1 and sensor.drain(0.001) == []
    duplicate = sensor.register('other:owned-popen', identity)
    assert duplicate['status'] == 'UNKNOWN'
    facts = sensor.close()
    assert len(facts) == 1 and facts[0]['status'] == 'UNKNOWN'
    assert facts[0]['registration_sha256'] == registration['registration_sha256']
    assert 'raw_wait_status' not in facts[0] and 'returncode' not in facts[0]
    waited = _release_wait(target, tmp_path / 'actual-parent-wait.json')
    assert waited['returncode'] == 0 and sensor.drain() == [] and sensor.close() == []
