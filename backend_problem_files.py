"""Private immutable backend assets; no network fallback or HTTP file serving.

Metadata stays in Postgres. Only trusted publishers write these roots; compiler
and contestant UIDs receive neither directory permissions nor Landlock access.
"""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile

MAX_FILE = 64 * 1024 * 1024
MAX_INDEX = 16 * 1024 * 1024
HEX = re.compile(r'[a-f0-9]{64}\Z')
_INDEX_CACHE = {}


class FilesUnavailable(RuntimeError):
    pass


def backend():
    mode = os.environ.get('GRADER_FILE_STORAGE', 'supabase')
    if mode not in ('local', 'supabase'):
        raise FilesUnavailable('GRADER_FILE_STORAGE must be local or supabase')
    return mode


def encode(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def _logical(bucket, name):
    for value in (bucket, name):
        if not isinstance(value, str) or not value or len(value) > 1024 or any(
                ord(c) < 32 or c == '\\' for c in value):
            raise FilesUnavailable('invalid asset path')
        path = PurePosixPath(value)
        if path.is_absolute() or any(p in ('.', '..') for p in value.split('/')) or str(path) != value:
            raise FilesUnavailable('noncanonical asset path')
    if '/' in bucket:
        raise FilesUnavailable('invalid asset bucket')
    return bucket + '/' + name


def _public(name):
    # Public here means API-readable, not anonymously exposed. HTTP authorization
    # still runs before opening PDFs, including unpublished/contest problems.
    return name.endswith('.pdf')


def root(public, create=False):
    setting = 'GRADER_PUBLIC_FILE_ROOT' if public else 'GRADER_PRIVATE_FILE_ROOT'
    value = os.environ.get(setting, '')
    path = Path(value)
    if not value or not path.is_absolute() or '..' in path.parts or path.resolve() != path:
        raise FilesUnavailable('asset root must be canonical and absolute')
    if create:
        path.mkdir(mode=0o700, parents=False, exist_ok=True)
    application = Path(__file__).resolve().parent
    workspace = Path(os.environ.get('GRADER_WORKSPACE_ROOT', '/var/lib/newbiegrader/workspaces'))
    if application == path or application in path.parents or workspace == path or workspace in path.parents or path in workspace.parents:
        raise FilesUnavailable('asset roots must be outside application/static/workspaces')
    info = path.lstat()
    allowed = (0o700, 0o750, 0o2750) if public else (0o700,)
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid not in (0, os.geteuid())
            or stat.S_IMODE(info.st_mode) not in allowed):
        raise FilesUnavailable('asset root needs trusted ownership/private permissions')
    for parent in path.parents:
        s = parent.lstat()
        if s.st_uid not in (0, os.geteuid()) or (s.st_mode & 0o022 and not s.st_mode & stat.S_ISVTX):
            raise FilesUnavailable('unsafe asset ancestor')
    return path


def _read(folder, name, limit):
    fd = os.open(folder / name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        s = os.fstat(fd)
        mask = 0o027 if folder.stat().st_mode & 0o050 else 0o077
        if (not stat.S_ISREG(s.st_mode) or s.st_uid not in (0, os.geteuid()) or
                s.st_nlink != 1 or s.st_mode & mask or s.st_size > limit):
            raise FilesUnavailable('unsafe or oversized asset')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            data = stream.read(limit + 1)
        if len(data) > limit:
            raise FilesUnavailable('oversized asset')
        return data
    finally:
        os.close(fd)


def _index(folder, missing_ok=False):
    try:
        info = (folder / 'index.json').lstat()
        signature = (info.st_dev, info.st_ino, info.st_mtime_ns, info.st_ctime_ns,
                     info.st_mode, info.st_uid, info.st_gid, info.st_nlink, info.st_size)
        cached = _INDEX_CACHE.get(str(folder))
        if cached and cached[0] == signature:
            return cached[1]
        value = json.loads(_read(folder, 'index.json', MAX_INDEX))
    except FileNotFoundError:
        if missing_ok:
            return {'schema': 1, 'objects': {}}
        raise FilesUnavailable('asset index is missing')
    if not isinstance(value, dict) or value.get('schema') != 1 or not isinstance(value.get('objects'), dict):
        raise FilesUnavailable('invalid asset index')
    for key, item in value['objects'].items():
        if '/' not in key:
            raise FilesUnavailable('invalid indexed path')
        bucket, name = key.split('/', 1)
        _logical(bucket, name)
        if (not isinstance(item, dict) or not isinstance(item.get('sha256'), str)
                or not HEX.fullmatch(item['sha256']) or type(item.get('size')) is not int
                or not 0 <= item['size'] <= MAX_FILE):
            raise FilesUnavailable('invalid indexed object')
    if len(_INDEX_CACHE) >= 2:
        _INDEX_CACHE.clear()
    _INDEX_CACHE[str(folder)] = (signature, value)
    return value


def _atomic(folder, name, data):
    reserve = int(os.environ.get('GRADER_FILE_MIN_FREE_MB', '1024'))
    if reserve < 256 or shutil.disk_usage(folder).free < len(data) + reserve * 1024 * 1024:
        raise FilesUnavailable('insufficient disk reserve')
    fd, temporary = tempfile.mkstemp(prefix='.publish-', dir=folder)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            if folder.stat().st_mode & 0o050:
                os.fchown(stream.fileno(), -1, folder.stat().st_gid)
                os.fchmod(stream.fileno(), 0o440)
            else:
                os.fchmod(stream.fileno(), 0o400)
            os.fsync(stream.fileno())
        os.replace(temporary, folder / name)
        directory = os.open(folder, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.lexists(temporary):
            os.unlink(temporary)


@contextmanager
def _lock(folder):
    import fcntl
    fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def download(bucket, name):
    key = _logical(bucket, name)
    folder = root(_public(name))
    value = _index(folder)
    item = value['objects'].get(key)
    if item is None:
        raise FilesUnavailable('required backend asset is missing')
    data = _read(folder, item['sha256'] + '.blob', MAX_FILE)
    if len(data) != item['size'] or hashlib.sha256(data).hexdigest() != item['sha256']:
        raise FilesUnavailable('backend asset checksum mismatch')
    return data


def publish(bucket, jobs):
    """Trusted author tool. Atomically publish each index; never delete versions.

    Files are written before metadata updates. The caller must fence/drain problem
    changes; old metadata/test hashes must not be paired with an unverified suite.
    A failed publication retains the affected old index and may leave orphan blobs.
    """
    public, private = root(True, create=True), root(False, create=True)
    if public == private or public in private.parents or private in public.parents:
        raise FilesUnavailable('public/private asset roots must be separate')
    with _lock(public), _lock(private):
        indexes = {kind: {'schema': 1, 'objects': dict(_index(folder, True)['objects'])}
                   for kind, folder in [(True, public), (False, private)]}
        changed = set()
        count = 0
        for name, data, _content_type in jobs:
            key = _logical(bucket, name)
            if not isinstance(data, bytes) or len(data) > MAX_FILE:
                raise FilesUnavailable('invalid asset bytes/size')
            if _public(name) and not data.startswith(b'%PDF'):
                raise FilesUnavailable('invalid statement PDF')
            kind = _public(name)
            folder = public if kind else private
            digest = hashlib.sha256(data).hexdigest()
            item = {'sha256': digest, 'size': len(data)}
            blob = folder / (digest + '.blob')
            if os.path.lexists(blob):
                if _read(folder, blob.name, MAX_FILE) != data:
                    raise FilesUnavailable('existing immutable asset is corrupt')
            else:
                _atomic(folder, blob.name, data)
            if indexes[kind]['objects'].get(key) != item:
                indexes[kind]['objects'][key] = item
                changed.add(kind)
            count += 1
        # Ensure even an empty category has a valid initial index.
        for kind, folder in [(False, private), (True, public)]:
            if kind in changed or not (folder / 'index.json').exists():
                raw = encode(indexes[kind])
                if len(raw) > MAX_INDEX:
                    raise FilesUnavailable('asset index exceeds limit')
                _atomic(folder, 'index.json', raw)
    return {'objects_published': count, 'storage': 'local', 'remote_writes': 0}


def validate(role='worker', verify_bytes=False):
    if backend() != 'local':
        return {'storage': 'supabase'}
    public_root = root(True)
    private_root = Path(os.environ.get('GRADER_PRIVATE_FILE_ROOT', ''))
    if (not private_root.is_absolute() or private_root.resolve() != private_root or
            public_root == private_root or public_root in private_root.parents or private_root in public_root.parents):
        raise FilesUnavailable('public/private asset roots must be separate/canonical')
    indexes = []
    for public in ((True,) if role == 'api' else (True, False)):
        folder = root(public)
        value = _index(folder)
        if verify_bytes:
            for key in value['objects']:
                bucket, name = key.split('/', 1)
                if _public(name) != public:
                    raise FilesUnavailable('asset in wrong access category')
                download(bucket, name)
        indexes.append(len(value['objects']))
    return {'storage': 'local', 'objects': sum(indexes), 'checksums_verified': verify_bytes}
