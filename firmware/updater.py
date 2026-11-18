"""Updates from GitHub (runs on MicroPython; also on CPython for the tests).

A release is one tagged commit (vX.Y.Z) holding firmware/* and manifest.json:
  {"signed": {"body": "<JSON text>", "sig": "<hex RSA signature of body>"}, ...}
body = {"version", "ref" (the tag), "notes", "files": {name: [sha256, size]}}.
The Pico reads manifest.json from main, CHECKS THE SIGNATURE against the public key below
(the private key never leaves the maintainer's machine), then downloads each listed file from
the tag over HTTPS (certificate checked against ca.pem) and checks its SHA-256 against the
signed body. So neither a hijacked GitHub account nor a tampered download can produce an
update a Pico will install. Top-level version/files fields are for 1.0.x Picos only and are
never trusted here.

Install is journalled: upd.pending (stage "swapping") is written BEFORE any file is replaced,
so a power cut part-way is undone at the next boot (main.py -> rollback.undo). Only the person
at the web page (with the PIN) can start an install; nothing updates by itself.
"""
import gc, json, os, socket, ssl
try:
    import hashlib
except ImportError:
    import uhashlib as hashlib

REPO = 'Stu1983/hawki-pico'
HOST = 'raw.githubusercontent.com'
BRANCH = 'main'
# Release signing key (RSA-2048, e=65537, PKCS#1 v1.5 + SHA-256): public modulus.
PUB_N = int(
    '961278eef48b634563dcd464b5b42a88af95fbee268d95a86c8deba0935e2206'
    '05289ca6e1555d5d69a23d265591c1f0b131e700b1f75d73aa86f6ba8c7b84f1'
    '0c4ba2eca7c68ce03f8959ea6f7397c62d977ef6919019ca895a37952ed30d23'
    'fb15856b3053427533ad003c20086ce5981a28c2f46cb2bb54e67655e318d8c4'
    '5640fb0498d6b95cefa961af01c878d4ecca1c0b367eb199846fbfe43631ed64'
    '278d9342e9146007382f09c4e10332efde2ac034134abf9e6aad065345923801'
    '285ca8ef369a0e02846430c084c8acf4dac8885e347003a43fc0ca8dd44bd94a'
    '7e74a9d6d1d368fdd038e3b44ef29e499b542982417d76d6ebc7dc7a175e5301', 16)
PUB_E = 65537
# Files an update may never write: the boot path (boot.py runs before main.py!), recovery code
# and the user's data.
NEVER = ('boot.py', 'main.py', 'rescue.py', 'rollback.py', 'config.json', 'deliv.json')
_DI = bytes.fromhex('3031300d060960864801650304020105000420')  # DigestInfo prefix for SHA-256


def _hex(b):
    return ''.join('%02x' % x for x in b)


def verify(body, sig_hex):
    """True if sig_hex is the release key's signature over body (bytes)."""
    try:
        sig = bytes.fromhex(sig_hex)
    except (ValueError, TypeError):
        return False
    k = 256
    if len(sig) != k:
        return False
    s = int.from_bytes(sig, 'big')
    if s >= PUB_N:
        return False
    em = pow(s, PUB_E, PUB_N)
    h = hashlib.sha256(body).digest()
    want = b'\x00\x01' + b'\xff' * (k - 3 - len(_DI) - 32) + b'\x00' + _DI + h
    return em == int.from_bytes(want, 'big')


_CTX = [None, False]  # during an install (keep=True): one TLS context, ca.pem parsed once, for all its downloads


def _ctx():
    if _CTX[0] is not None:
        return _CTX[0]
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.verify_mode = ssl.CERT_REQUIRED
    with open('ca.pem', 'rb') as f:
        ca = f.read()
    try:
        ctx.load_verify_locations(cadata=ca)  # MicroPython: PEM bytes
    except Exception:
        ctx.load_verify_locations(cadata=ca.decode())  # CPython wants PEM as str
    if _CTX[1]:
        _CTX[0] = ctx
    return ctx


def _oom(ex):
    return isinstance(ex, MemoryError) or isinstance(ex, OSError) and (getattr(ex, 'errno', None) == 12 or bool(ex.args and ex.args[0] == 12))


def _get(path, sink=None, limit=200000):
    """HTTPS GET https://HOST/path. Returns the body, or feeds it to sink(chunk) and returns its size.
    TLS needs one big unbroken block of memory: collect first, and try once more if it still ran out."""
    for attempt in (0, 1):
        gc.collect()
        try:
            return _get1(path, sink, limit)
        except Exception as ex:
            if attempt or sink or not _oom(ex):  # (a file being written is retried by install(), from scratch)
                raise


def _get1(path, sink, limit):
    ai = socket.getaddrinfo(HOST, 443, 0, socket.SOCK_STREAM)[0]
    s = socket.socket(ai[0], socket.SOCK_STREAM, ai[2])
    s.settimeout(20)
    try:
        s.connect(ai[-1])
        s = _ctx().wrap_socket(s, server_hostname=HOST)
        req = 'GET %s HTTP/1.0\r\nHost: %s\r\nUser-Agent: hawki-pico\r\nConnection: close\r\n\r\n' % (path, HOST)
        (s.write if hasattr(s, 'write') else s.sendall)(req.encode())
        rd = s.read if hasattr(s, 'read') else s.recv
        buf = b''
        while b'\r\n\r\n' not in buf:
            c = rd(512)
            if not c:
                raise OSError('no reply')
            buf += c
            if len(buf) > 8192:
                raise OSError('bad reply')
        head, body = buf.split(b'\r\n\r\n', 1)
        status = int(head.split(b' ', 2)[1])
        if status != 200:
            raise OSError('GitHub said %d for %s' % (status, path))
        out, n = [], 0
        while True:
            if body:
                n += len(body)
                if n > limit:
                    raise OSError('file too big')
                if sink:
                    sink(body)
                else:
                    out.append(body)
            body = rd(1024)
            if not body:
                break
        return n if sink else b''.join(out)
    finally:
        s.close()


def vtuple(v):
    return tuple(int(x) for x in str(v).lstrip('v').split('.'))


def ok_name(n):
    if n in NEVER or n.startswith('upd.') or '/' in n or '..' in n:
        return False
    if not (n.endswith('.py') or n.endswith('.html') or n.endswith('.pem')):
        return False
    return all(c.isalpha() or c.isdigit() or c in '_.' for c in n)


def parse(raw):
    """Signed manifest text -> trusted body dict, or raise."""
    m = json.loads(raw)
    s = m.get('signed') or {}
    body = s.get('body')
    if not isinstance(body, str) or not verify(body.encode(), s.get('sig')):
        raise ValueError('the release is not signed by the hawki-pico release key')
    b = json.loads(body)
    vtuple(b['version'])
    for n, v in b['files'].items():
        if not ok_name(n):
            raise ValueError('release lists a file it may not replace: %s' % n)
        if len(v) != 2 or len(v[0]) != 64 or not 0 < int(v[1]) <= 200000:
            raise ValueError('bad entry for %s' % n)
    return b


def check(current):
    m = parse(_get('/%s/%s/manifest.json' % (REPO, BRANCH), limit=20000))
    return {'current': current, 'latest': m['version'], 'notes': m.get('notes', ''),
            'newer': vtuple(m['version']) > vtuple(current), 'verified': True, 'manifest': m}


def _rm(n):
    try:
        os.remove(n)
    except OSError:
        pass


def _exists(n):
    try:
        os.stat(n)
        return True
    except OSError:
        return False


def _same(n, sha, size):
    # is the file on the Pico already this one? (most files don't change from one release to the next)
    try:
        if os.stat(n)[6] != size:
            return False
        h = hashlib.sha256()
        with open(n, 'rb') as f:
            while True:
                b = f.read(1024)
                if not b:
                    break
                h.update(b)
        return _hex(h.digest()) == sha
    except OSError:
        return False


def install(m, current):
    """m must come from parse()/check(). Downloads + verifies the files that changed, then swaps them in."""
    for n in m['files']:
        if not ok_name(n):
            raise ValueError('refusing to write %s' % n)
    if _exists('upd.pending'):
        raise OSError('the last update is still being confirmed: try again in a few minutes')
    import rollback  # main.py/rollback.py never come over the air: make sure they can undo THIS kind of install
    try:
        boot_ok = b'why = rollback.boot_check()' in open('main.py', 'rb').read()
    except OSError:
        boot_ok = False
    if not hasattr(rollback, 'boot_check') or not boot_ok:
        raise OSError('this Pico needs its start-up files (main.py, rollback.py) updated over USB first: run tools/install.sh')
    # only what changed is downloaded, journalled and swapped (v1.2.52 -> 1.2.53 changed 4 of 17 files)
    files = {n: v for n, v in m['files'].items() if not _same(n, v[0], v[1])}
    need = sum(v[1] for v in files.values()) * 2 + 40000  # .new copies + .bak copies + slack
    st = os.statvfs('/')
    if st[0] * st[3] < need:
        raise OSError('not enough flash for the update')
    _CTX[0], _CTX[1] = None, True
    try:
        for n, (sha, size) in files.items():
            for attempt in (0, 1):  # out of memory part-way: collect and start this file again, once
                h = hashlib.sha256()
                try:
                    with open(n + '.new', 'wb') as f:
                        def sink(c):
                            h.update(c)
                            f.write(c)
                        got = _get('/%s/%s/firmware/%s' % (REPO, m['ref'], n), sink, size + 1)
                    break
                except Exception as ex:
                    if attempt or not _oom(ex):
                        raise
                    _CTX[0] = None  # (a fresh TLS context for the retry: the old one may be left unusable)
            if got != size or _hex(h.digest()) != sha:
                raise ValueError('%s did not match the release (download damaged?)' % n)
    except Exception:
        for n in files:
            _rm(n + '.new')
        raise
    finally:
        _CTX[0], _CTX[1] = None, False  # (not kept in memory after the install)
    # everything downloaded and verified. Journal first, then swap.
    for n in m['files']:  # (every file in the release, skipped ones too: an old .bak left by a power cut must never
        _rm(n + '.bak')   # be 'restored' over a current file by a rollback that can't read its journal)
    had = [n for n in files if _exists(n)]
    j = {'from': current, 'to': m['version'], 'files': list(files), 'had': had, 'stage': 'swapping', 'boots': 0}
    try:
        with open('upd.tmp', 'w') as f:
            json.dump(j, f)
        os.rename('upd.tmp', 'upd.pending')
    except Exception:  # (flash full?) nothing was replaced: leave no downloads behind
        for n in files:
            _rm(n + '.new')
        _rm('upd.tmp')
        raise
    try:
        for n in files:
            if n in had:
                os.rename(n, n + '.bak')
            os.rename(n + '.new', n)
        j['stage'] = 'installed'
        with open('upd.tmp', 'w') as f:
            json.dump(j, f)
        os.rename('upd.tmp', 'upd.pending')
    except Exception as ex:  # e.g. flash full: put everything back now (a power cut is handled at boot)
        rollback.undo('install failed while replacing files: %r' % ex)
        _rm('upd.tmp')
        raise
    return m['version']


BAD = object()


def _journal():
    """upd.pending as a dict, None if there is none, or BAD (unreadable). (Here too, not only in rollback.py:
    an older rollback.py, which never comes over the air, can't read a damaged one.)"""
    try:
        f = open('upd.pending')
    except OSError:
        return None
    try:
        with f:
            p = json.load(f)
    except Exception:
        return BAD
    return p if isinstance(p, dict) else BAD


def commit():
    """The new version is running fine: forget the backups. Removing upd.pending is the commit point: cut off
    before it, nothing is lost (a rollback still has every backup); after it, a left-over .bak is harmless
    (install() clears them first). An unreadable upd.pending is cleared the same way."""
    p = _journal()
    if p is None:
        return None
    if p is BAD:
        p = {'had': [n[:-4] for n in os.listdir() if n.endswith('.bak') and ok_name(n[:-4])]}
    elif p.get('stage') != 'installed':
        return None  # never confirm a half-finished install, or a rollback under way
    try:
        os.remove('upd.pending')
    except OSError:
        return None  # still there: keep every backup
    for n in p.get('had', []):
        _rm(n + '.bak')
    try:
        with open('upd.last', 'w') as f:
            json.dump({'ok': True, 'from': p.get('from'), 'to': p.get('to')}, f)
    except OSError:
        pass
    return p


def tidy():
    """At start, with no update pending: remove what a power cut during a download left (*.new, upd.tmp)."""
    try:
        os.stat('upd.pending')
        return
    except OSError:
        pass
    for n in os.listdir():
        if n == 'upd.tmp' or n.endswith('.new') and ok_name(n[:-4]):
            _rm(n)
