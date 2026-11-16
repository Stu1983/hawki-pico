"""Updates from GitHub (runs on MicroPython; the HTTPS part also on CPython for testing).

A release is one commit on GitHub, tagged vX.Y.Z, holding firmware/* and manifest.json:
  {"version": "1.0.1", "ref": "v1.0.1", "notes": "...", "files": {"app.py": [sha256, size], ...}}
The Pico reads manifest.json from the main branch, then downloads each file from the TAG (never
changes, so files and hashes always match) over HTTPS with the certificate checked against
ca.pem. Every file is checked against its SHA-256 before anything is replaced; then the old
files are kept as .bak and upd.pending is written. main.py/rollback.py put the .bak files back
if the new version fails to start, and app.py deletes upd.pending once it's running happily.
Only the person at the web page can start an install; nothing updates by itself.
"""
import json, os, socket, ssl
try:
    import hashlib
except ImportError:
    import uhashlib as hashlib

REPO = 'Stu1983/hawki-pico'
HOST = 'raw.githubusercontent.com'
BRANCH = 'main'
# Never replaced over the air: the boot path and the rescue/rollback code that must always work.
KEEP = ('main.py', 'rescue.py', 'rollback.py', 'config.json', 'deliv.json')


def _ctx():
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.verify_mode = ssl.CERT_REQUIRED
    with open('ca.pem', 'rb') as f:
        ca = f.read()
    try:
        ctx.load_verify_locations(cadata=ca)  # MicroPython: PEM bytes
    except Exception:
        ctx.load_verify_locations(cadata=ca.decode())  # CPython wants PEM as str
    return ctx


def _get(path, sink=None, limit=200000):
    """HTTPS GET https://HOST/path. Returns the body, or feeds it to sink(chunk) and returns its size."""
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


def check(current):
    m = json.loads(_get('/%s/%s/manifest.json' % (REPO, BRANCH)))
    return {'current': current, 'latest': m['version'], 'notes': m.get('notes', ''),
            'newer': vtuple(m['version']) > vtuple(current), 'manifest': m}


def _ok_name(n):
    if n in KEEP or '/' in n or '..' in n or not (n.endswith('.py') or n.endswith('.html') or n.endswith('.pem')):
        return False
    return all(c.isalpha() or c.isdigit() or c in '_.' for c in n)


def install(m, current):
    files = m['files']
    for n in files:
        if not _ok_name(n):
            raise ValueError('refusing to write %s' % n)
    need = sum(v[1] for v in files.values()) * 2 + 20000  # .new copies + .bak copies
    st = os.statvfs('/')
    if st[0] * st[3] < need:
        raise OSError('not enough flash for the update')
    done = []
    try:
        for n, (sha, size) in files.items():
            h = hashlib.sha256()
            with open(n + '.new', 'wb') as f:
                def sink(c):
                    h.update(c)
                    f.write(c)
                got = _get('/%s/%s/firmware/%s' % (REPO, m['ref'], n), sink, size + 1)
            done.append(n)
            dig = ''.join('%02x' % b for b in h.digest())
            if got != size or dig != sha:
                raise ValueError('%s did not match the release (download damaged?)' % n)
    except Exception:
        for n in done + [x for x in files if x not in done]:
            try:
                os.remove(n + '.new')
            except OSError:
                pass
        raise
    # everything downloaded and verified: swap in, keeping the old files for rollback
    had = []
    for n in files:
        try:
            os.stat(n)
            try:
                os.remove(n + '.bak')
            except OSError:
                pass
            os.rename(n, n + '.bak')
            had.append(n)
        except OSError:
            pass
        os.rename(n + '.new', n)
    with open('upd.pending', 'w') as f:
        json.dump({'from': current, 'to': m['version'], 'files': list(files), 'had': had}, f)
    return m['version']


def commit():
    """The new version is running fine: forget the backups."""
    try:
        p = json.load(open('upd.pending'))
    except (OSError, ValueError):
        return None
    for n in p.get('had', []):
        try:
            os.remove(n + '.bak')
        except OSError:
            pass
    os.remove('upd.pending')
    with open('upd.last', 'w') as f:
        json.dump({'ok': True, 'from': p.get('from'), 'to': p.get('to')}, f)
    return p
