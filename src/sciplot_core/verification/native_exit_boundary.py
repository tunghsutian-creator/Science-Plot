"""Source-owned Darwin exit facts; never a parent wait or a process-finish event.

The caller owns source/Popen-generation binding and durable registration transport.
A queued request is not registration. Missing/late/changed observations stay unknown.
"""
from __future__ import annotations

import ctypes
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import select
import struct
import sys
import time
from typing import Any, Mapping

_EXIT, _EXITSTATUS, _EXEC, _RECEIPT = 0x80000000, 0x04000000, 0x20000000, 0x0040
_SYSTEM = Path('/System/Library/CoreServices/SystemVersion.plist')


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class ProcessIdentity:
    pid: int
    ppid: int
    uid: int
    start_sec: int
    start_usec: int
    executable: str
    cwd: str
    executable_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ProcessIdentity:
        keys = {'pid', 'ppid', 'uid', 'start_sec', 'start_usec', 'executable', 'cwd', 'executable_sha256'}
        if set(value) != keys:
            raise ValueError('unknown process identity fields')
        ints = ('pid', 'ppid', 'uid', 'start_sec', 'start_usec')
        if any(type(value[k]) is not int or value[k] < 0 for k in ints):
            raise ValueError('invalid process identity integers')
        if value['pid'] == 0 or value['start_sec'] == 0 or value['start_usec'] >= 1_000_000:
            raise ValueError('invalid process generation time')
        for key in ('executable', 'cwd'):
            if not isinstance(value[key], str) or not Path(value[key]).is_absolute():
                raise ValueError('process paths must be absolute')
        sha = value['executable_sha256']
        if not isinstance(sha, str) or len(sha) != 64 or any(c not in '0123456789abcdef' for c in sha):
            raise ValueError('invalid executable bytes identity')
        return cls(**value)


def _libproc() -> ctypes.CDLL:
    if sys.platform != 'darwin' or struct.calcsize('P') != 8 or sys.byteorder != 'little':
        raise OSError('unsupported libproc ABI')
    else:
        lib = ctypes.CDLL('/usr/lib/libproc.dylib', use_errno=True)
        lib.proc_pidinfo.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int]
        lib.proc_pidinfo.restype = ctypes.c_int
        lib.proc_pidpath.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
        lib.proc_pidpath.restype = ctypes.c_int
        return lib


def read_identity(pid: int) -> ProcessIdentity:
    """Read only the requested PID via public libproc; reject incomplete snapshots.

    Darwin's fixed-width proc_bsdinfo is 136 bytes; vnodepathinfo is 2352,
    with its first 1024-byte cwd path at offset 152 (public sys/proc_info.h).
    """
    if type(pid) is not int or pid <= 0:
        raise ValueError('invalid PID')
    lib = _libproc()
    bsd, vnode, exe = ctypes.create_string_buffer(136), ctypes.create_string_buffer(2352), ctypes.create_string_buffer(4096)
    if (lib.proc_pidinfo(pid, 3, 0, bsd, len(bsd)) != len(bsd)
            or lib.proc_pidpath(pid, exe, len(exe)) <= 0
            or lib.proc_pidinfo(pid, 9, 0, vnode, len(vnode)) != len(vnode)):
        raise OSError(ctypes.get_errno(), 'incomplete process identity')
    values = struct.unpack('<12I16s32s5Ii2Q', bsd.raw)
    cwd = os.fsdecode(vnode.raw[152:1176].split(b'\0', 1)[0])
    executable = os.fsdecode(exe.value)
    # A zombie/terminated snapshot cannot establish registration before exit.
    if values[1] not in {1, 2, 3, 4}:
        raise ValueError('target is not a live process')
    result = ProcessIdentity(pid, values[4], values[5], values[-2], values[-1],
                             executable, cwd, _sha(Path(executable)))
    if values[3] != pid:
        raise ValueError('PID identity changed')
    return ProcessIdentity.from_dict(result.to_dict())


class _DlInfo(ctypes.Structure):
    _fields_ = [('filename', ctypes.c_char_p), ('base', ctypes.c_void_p),
                ('symbol', ctypes.c_char_p), ('address', ctypes.c_void_p)]


def _runtime_binding() -> dict[str, Any]:
    """Bind actual function-address images; shared-cache images bind sealed OS bytes."""
    import _ctypes
    loader, lib = ctypes.CDLL(None), _libproc()
    loader.dladdr.argtypes = [ctypes.c_void_p, ctypes.POINTER(_DlInfo)]
    loader.dladdr.restype = ctypes.c_int
    system_sha = _sha(_SYSTEM)
    images: dict[str, Any] = {}
    for name, function in (('proc_pidinfo', lib.proc_pidinfo), ('proc_pidpath', lib.proc_pidpath),
                           ('kqueue', loader.kqueue), ('kevent', loader.kevent),
                           ('python_core', ctypes.pythonapi.Py_GetVersion)):
        info = _DlInfo()
        if not loader.dladdr(ctypes.cast(function, ctypes.c_void_p), ctypes.byref(info)) or not info.filename:
            raise OSError('native function image unavailable')
        path = Path(os.fsdecode(info.filename))
        if str(path).startswith(('/usr/lib/', '/System/Library/')):
            images[name] = {'path': str(path), 'sealed_system_sha256': system_sha}
        elif path.is_file():
            images[name] = {'path': str(path.resolve()), 'sha256': _sha(path)}
        else:
            raise OSError('unbound native function image')
    selected = Path(select.__file__).resolve(strict=True)
    return {'kind': 'darwin_kernel_exit_sensor', 'source_sha256': _sha(Path(__file__)),
            'watcher_identity': read_identity(os.getpid()).to_dict(),
            'select': {'path': str(selected), 'sha256': _sha(selected)},
            'ctypes': {'path': _ctypes.__file__, 'sha256': _sha(Path(_ctypes.__file__))},
            'native_images': images, 'system_sha256': system_sha, 'kernel': list(os.uname())}


def _new_queue() -> Any:
    if sys.platform == 'darwin':
        return select.kqueue()
    raise OSError('Darwin kqueue is unavailable')


def _change(pid: int) -> Any:
    if sys.platform == 'darwin':
        return select.kevent(pid, filter=-5, flags=0x0001 | 0x0004 | _RECEIPT,
                             fflags=_EXIT | _EXITSTATUS | _EXEC)
    raise OSError('Darwin kqueue is unavailable')


def _event(value: Any) -> dict[str, int]:
    return {key: int(getattr(value, key)) for key in ('ident', 'filter', 'flags', 'fflags', 'data')}


class NativeExitSensor:
    """One kqueue owned by the current watcher. No threads, scans, launch or policy."""

    def __init__(self) -> None:
        self.binding = _runtime_binding()
        self._binding_sha = _digest(self.binding)
        self._queue = _new_queue()
        self._pending: dict[int, tuple[str, ProcessIdentity, str]] = {}
        self._seen: set[str] = set()
        self._seen_pids: set[int] = set()
        self._owner_pid = os.getpid()
        self._closed = False

    @property
    def pending(self) -> int:
        return len(self._pending)

    def _fact(self, generation: str, identity: ProcessIdentity, kind: str, status: str,
              **values: Any) -> dict[str, Any]:
        return {'kind': kind, 'status': status, 'generation': generation,
                'identity': identity.to_dict(), 'watcher_binding_sha256': self._binding_sha,
                'observed_monotonic_ns': time.monotonic_ns(), 'is_parent_wait': False, **values}

    def register(self, generation: str, identity: ProcessIdentity) -> dict[str, Any]:
        """Only a successful receipt bracketed by matching live identities registers."""
        facts = self._fact(generation, identity, 'native_exit_registration', 'UNKNOWN')
        if (self._closed or os.getpid() != self._owner_pid
                or not isinstance(generation, str) or not 1 <= len(generation) <= 256
                or generation in self._seen or identity.pid in self._seen_pids
                or identity.uid != os.getuid()):
            return {**facts, 'reason': 'closed_duplicate_or_unowned_generation'}
        self._seen.add(generation)
        self._seen_pids.add(identity.pid)
        try:
            ProcessIdentity.from_dict(identity.to_dict())
            before = read_identity(identity.pid)
            facts['before'] = before.to_dict()
            if before != identity:
                return {**facts, 'reason': 'identity_mismatch_before_registration'}
            change = _change(identity.pid)
            events = self._queue.control([change], 1, 0)
            facts['receipts'] = [_event(e) for e in events]
            if (len(events) != 1 or events[0].ident != identity.pid
                    or events[0].filter != (-5)
                    or not events[0].flags & 0x4000 or events[0].data != 0):
                return {**facts, 'reason': 'kernel_registration_not_confirmed'}
            after = read_identity(identity.pid)
            facts['after'] = after.to_dict()
            if before != after:
                return {**facts, 'reason': 'identity_mismatch_after_registration'}
            facts.update(status='REGISTERED', registered_monotonic_ns=time.monotonic_ns())
            sha = _digest(facts)
            facts['registration_sha256'] = sha
            self._pending[identity.pid] = generation, identity, sha
            return facts
        except (OSError, ValueError, ProcessLookupError) as exc:
            return {**facts, 'reason': 'registration_identity_or_permission_unavailable',
                    'error_class': type(exc).__name__, 'errno': getattr(exc, 'errno', None)}

    def drain(self, timeout: float = 0.0) -> list[dict[str, Any]]:
        """Return genuine kernel facts; no event is no exit proof."""
        if self._closed:
            return []
        if os.getpid() != self._owner_pid:
            return self._unknown_all('watcher_process_changed')
        try:
            events = self._queue.control([], max(1, len(self._pending)), timeout)
        except (OSError, ValueError) as exc:
            return self._unknown_all('kernel_queue_unavailable', error_class=type(exc).__name__)
        results = []
        for event in events:
            pending = self._pending.pop(int(event.ident), None)
            if pending is None:
                continue
            generation, identity, sha = pending
            raw = _event(event)
            valid = (event.filter == (-5) and not event.flags & 0x4000
                     and event.fflags & _EXIT and event.fflags & _EXITSTATUS
                     and not event.fflags & _EXEC and 0 <= event.data <= 0xffff)
            if not valid:
                results.append(self._fact(generation, identity, 'kernel_exit_status', 'UNKNOWN',
                    registration_sha256=sha, raw_event=raw, reason='missing_status_or_process_exec_changed'))
                continue
            status = int(event.data)
            if not (os.WIFEXITED(status) or os.WIFSIGNALED(status)):
                results.append(self._fact(generation, identity, 'kernel_exit_status', 'UNKNOWN',
                    registration_sha256=sha, raw_event=raw, reason='nonterminal_kernel_status'))
                continue
            results.append(self._fact(generation, identity, 'kernel_exit_status', 'OBSERVED',
                registration_sha256=sha, raw_event=raw, raw_wait_status=status,
                returncode=os.waitstatus_to_exitcode(status)))
        return results

    def _unknown_all(self, reason: str, **values: Any) -> list[dict[str, Any]]:
        result = [self._fact(g, i, 'kernel_exit_status', 'UNKNOWN', registration_sha256=sha,
                            reason=reason, **values) for g, i, sha in self._pending.values()]
        self._pending.clear()
        return result

    def close(self) -> list[dict[str, Any]]:
        if not self._closed:
            self._closed = True
            self._queue.close()
        return self._unknown_all('watcher_closed_before_exit_observation')


def validate_registration(value: Any, *, expected_identity: ProcessIdentity,
                          generation: str, watcher_binding: dict[str, Any]) -> bool:
    """Check closed facts against the independently bound original watcher stream.

    This cannot authenticate arbitrary JSON. The caller must bind the original
    producer, source-owned Popen request and durable watcher PID/epoch separately.
    The exited primary is never queried; current reviewer runtime bytes are checked.
    """
    keys = {'kind', 'status', 'generation', 'identity', 'watcher_binding_sha256',
            'observed_monotonic_ns', 'is_parent_wait', 'before', 'after', 'receipts',
            'registered_monotonic_ns', 'registration_sha256'}
    try:
        if not isinstance(value, dict) or set(value) != keys:
            return False
        current = _runtime_binding()
        if set(watcher_binding) != set(current):
            return False
        original_watcher = ProcessIdentity.from_dict(watcher_binding['watcher_identity'])
        if _sha(Path(original_watcher.executable)) != original_watcher.executable_sha256:
            return False
        if any(current[k] != watcher_binding[k] for k in current if k != 'watcher_identity'):
            return False
        identity = ProcessIdentity.from_dict(expected_identity.to_dict()).to_dict()
        for key in ('identity', 'before', 'after'):
            ProcessIdentity.from_dict(value[key])
        if (not isinstance(value['receipts'], list) or len(value['receipts']) != 1
                or not isinstance(value['receipts'][0], dict)
                or any(type(v) is not int for v in value['receipts'][0].values())):
            return False
        receipt = {'ident': expected_identity.pid, 'filter': -5, 'flags': 0x4045,
                   'fflags': _EXIT | _EXITSTATUS | _EXEC, 'data': 0}
        digestable = {k: v for k, v in value.items() if k != 'registration_sha256'}
        return (value['kind'] == 'native_exit_registration' and value['status'] == 'REGISTERED'
                and value['generation'] == generation and value['is_parent_wait'] is False
                and value['identity'] == value['before'] == value['after'] == identity
                and value['receipts'] == [receipt]
                and type(value['observed_monotonic_ns']) is int
                and type(value['registered_monotonic_ns']) is int
                and 0 < value['observed_monotonic_ns'] <= value['registered_monotonic_ns']
                and value['watcher_binding_sha256'] == _digest(watcher_binding)
                and value['registration_sha256'] == _digest(digestable))
    except (OSError, ValueError, TypeError, KeyError):
        return False


def validate_exit_fact(value: Any, registration: dict[str, Any]) -> bool:
    """Validate raw terminal encoding after independently validating registration."""
    keys = {'kind', 'status', 'generation', 'identity', 'watcher_binding_sha256',
            'observed_monotonic_ns', 'is_parent_wait', 'registration_sha256',
            'raw_event', 'raw_wait_status', 'returncode'}
    try:
        if not isinstance(value, dict) or set(value) != keys:
            return False
        registered = {k: v for k, v in registration.items() if k != 'registration_sha256'}
        if (registration.get('status') != 'REGISTERED'
                or registration['registration_sha256'] != _digest(registered)):
            return False
        event = value['raw_event']
        if not isinstance(event, dict) or set(event) != {'ident', 'filter', 'flags', 'fflags', 'data'}:
            return False
        if any(type(v) is not int for v in event.values()):
            return False
        raw = event['data']
        return (value['kind'] == 'kernel_exit_status' and value['status'] == 'OBSERVED'
                and value['is_parent_wait'] is False
                and value['generation'] == registration['generation']
                and value['identity'] == registration['identity']
                and value['watcher_binding_sha256'] == registration['watcher_binding_sha256']
                and value['registration_sha256'] == registration['registration_sha256']
                and type(value['observed_monotonic_ns']) is int
                and value['observed_monotonic_ns'] > registration['registered_monotonic_ns']
                and event['ident'] == registration['identity']['pid'] and event['filter'] == -5
                and event['flags'] == 0x8075 and event['fflags'] == _EXIT | _EXITSTATUS
                and 0 <= raw <= 0xffff and (os.WIFEXITED(raw) or os.WIFSIGNALED(raw))
                and type(value['raw_wait_status']) is int and value['raw_wait_status'] == raw
                and type(value['returncode']) is int and value['returncode'] == os.waitstatus_to_exitcode(raw))
    except (ValueError, TypeError, KeyError):
        return False
def namespace_identity(path: Path) -> dict[str, int]:
    import stat
    row = path.lstat()
    if not stat.S_ISDIR(row.st_mode) or row.st_uid != os.getuid() or stat.S_IMODE(row.st_mode) != 0o700:
        raise ValueError('Audit engine namespace is not a private owned directory.')
    return dict(device=row.st_dev, inode=row.st_ino, uid=row.st_uid, mode=stat.S_IMODE(row.st_mode))

def endpoint_identity(address: Any, *, ready: bool = False) -> tuple[Path, dict[str, int]]:
    import stat
    path = Path(os.fsdecode(address)).absolute().resolve(strict=True)
    row = path.lstat()
    if not stat.S_ISSOCK(row.st_mode) or (ready and (path != Path(os.fsdecode(address)).absolute() or row.st_uid != os.getuid()
            or row.st_nlink != 1 or stat.S_IMODE(row.st_mode) != 0o600)):
        raise ValueError('Native actor endpoint is not the owned ready socket.')
    if ready:
        namespace_identity(path.parent)
    return path, dict(device=row.st_dev, inode=row.st_ino, ctime_ns=row.st_ctime_ns,
                      uid=row.st_uid, mode=stat.S_IMODE(row.st_mode))

def validate_actor_launch(request: dict[str, Any], frames: list[dict[str, Any]], primary: int, exclusions: set[str]) -> bool:
    """One fenced source launch, genuine live parentage and kernel peer readiness."""
    from sciplot_core.verification.private_process_boundaries import owner_identity
    try:
        actor, epoch = request['actor'], request['epoch']
        launch = actor['launch']
        origin, parent, peer = (ProcessIdentity.from_dict(v) for v in
                               (launch['initial'], launch['parent'], request['identity']))
        rows = [r for r in frames if r['epoch'] == epoch and r.get('child_token') == launch['token']]
        attempts = [r for r in rows if r['event'] == 'spawn_attempt']
        children = [r for r in rows if r['event'] == 'child_spawn' and r.get('child_pid') == origin.pid]
        sent = [r for r in frames if r['event'] == 'native_registration_request' and r['epoch'] == epoch and r.get('request') == request]
        fields = ('pid', 'ppid', 'uid', 'start_sec', 'start_usec')
        endpoint, owner = actor['ready']['endpoint'], actor['ready']['socket_owner']
        return (set(actor) == {'socket','default_owned','owner','launch','ready'} and type(actor['default_owned']) is bool
            and set(launch) == {'token','attempt_sha256','initial','parent'} and set(actor['ready']) == {'endpoint','socket_owner','peer_pid'}
            and len(attempts) == len(children) == len(sent) == 1 and attempts[0]['sha256'] == launch['attempt_sha256']
            and attempts[0]['sequence'] < children[0]['sequence'] < sent[0]['sequence']
            and attempts[0]['monotonic_ns'] <= children[0]['monotonic_ns'] < sent[0]['monotonic_ns']
            and epoch + ':' + launch['token'] in exclusions and origin.ppid == primary
            and tuple(getattr(origin,k) for k in fields) == tuple(getattr(parent,k) for k in fields)
            and (peer.pid == parent.pid or peer.ppid == parent.pid) and peer.uid == parent.uid
            and actor['owner'] == owner_identity('private_native_exit_port.py','_Port.discover')
            and actor['ready']['peer_pid'] == owner['pid'] == peer.pid and owner['device'] == endpoint['device'] and owner['inode'] == endpoint['inode']
            and endpoint['uid'] == peer.uid and endpoint['mode'] == 0o600)
    except (OSError, KeyError, TypeError, ValueError):
        return False

def settled_binding(row: dict[str, Any], creations: list[dict[str, Any]]) -> bool:
    from sciplot_core.verification.private_process_boundaries import owner_identity
    return (row.get('owner') == owner_identity('server.py','serve') and row.get('endpoint',{}).get('mode') == 0o600
        and len([old for old in creations if old.get('sha256') == row.get('creation_sha256')
            and all(old[k] == row[k] for k in ('pid','epoch','binding_token','socket')) and old['sequence'] < row['sequence']
            and all(old['endpoint'][k] == row['endpoint'][k] for k in ('device','inode','uid'))]) == 1)

def explicit_exit_bound(spawned: dict[str, Any], exits: list[dict[str, Any]], exclusions: set[str]) -> bool:
    from sciplot_core.verification.private_process_boundaries import owner_identity
    actual = [r for r in exits if r['epoch'] == spawned['epoch'] and r.get('child_token') == spawned['child_token']
              and r.get('child_pid') == spawned['child_pid']]
    return (spawned.get('owner') == owner_identity('socket_client.py','ensure_server') and len(actual) == 1
        and type(actual[0].get('returncode')) is int and (actual[0]['returncode'] == 0
             or spawned['epoch'] + ':' + spawned['child_token'] in exclusions))
