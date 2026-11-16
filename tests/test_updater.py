"""Update + rollback flow with GitHub replaced by a dict (runs on CPython)."""
import hashlib, json, os, sys, tempfile
FW = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'firmware')
sys.path.insert(0, FW)
import updater, rollback


def setup(files):
    d = tempfile.mkdtemp()
    os.chdir(d)
    for n, b in files.items():
        open(n, 'wb').write(b)
    return d


def fake_github(release):
    def _get(path, sink=None, limit=200000):
        n = path.rsplit('/', 1)[1]
        if n == 'manifest.json':
            return json.dumps(release['manifest']).encode()
        b = release['files'][n]
        if len(b) > limit:
            raise OSError('file too big')
        if sink:
            sink(b)
            return len(b)
        return b
    updater._get = _get


def make_release(ver, files, corrupt=None):
    m = {'version': ver, 'ref': 'v' + ver, 'notes': 'n', 'files': {n: [hashlib.sha256(b).hexdigest(), len(b)] for n, b in files.items()}}
    served = dict(files)
    if corrupt:
        served[corrupt] = served[corrupt][:-1] + b'X'
    return {'manifest': m, 'files': served}


def read(n):
    return open(n, 'rb').read()


def test_update_rollback_commit():
    setup({'app.py': b'old app', 'version.py': b"VERSION = '1.0.0'", 'ui.html': b'old ui', 'config.json': b'{}'})
    rel = make_release('1.0.1', {'app.py': b'new app', 'version.py': b"VERSION = '1.0.1'", 'ui.html': b'new ui', 'extra.py': b'added'})
    fake_github(rel)
    c = updater.check('1.0.0')
    assert c['newer'] and c['latest'] == '1.0.1'
    assert not updater.check('1.0.1')['newer']
    assert updater.install(c['manifest'], '1.0.0') == '1.0.1'
    assert read('app.py') == b'new app' and read('app.py.bak') == b'old app' and read('extra.py') == b'added'
    assert os.path.exists('upd.pending') and not [f for f in os.listdir() if f.endswith('.new')]
    # new version won't start -> main.py calls rollback.undo()
    assert rollback.undo('boom')
    assert read('app.py') == b'old app' and read('ui.html') == b'old ui' and not os.path.exists('extra.py')
    assert not os.path.exists('upd.pending') and json.load(open('upd.last'))['ok'] is False
    assert not rollback.undo('again')  # nothing pending
    # install again, this time it runs: commit removes backups
    updater.install(c['manifest'], '1.0.0')
    p = updater.commit()
    assert p['to'] == '1.0.1' and not [f for f in os.listdir() if f.endswith('.bak')]
    assert json.load(open('upd.last')) == {'ok': True, 'from': '1.0.0', 'to': '1.0.1'}
    assert read('config.json') == b'{}'


def test_bad_download_changes_nothing():
    setup({'app.py': b'old app', 'ui.html': b'old ui'})
    rel = make_release('1.0.1', {'app.py': b'new app', 'ui.html': b'new ui'}, corrupt='ui.html')
    fake_github(rel)
    try:
        updater.install(rel['manifest'], '1.0.0')
        raise AssertionError('accepted a damaged file')
    except ValueError:
        pass
    assert read('app.py') == b'old app' and read('ui.html') == b'old ui'
    assert sorted(os.listdir()) == ['app.py', 'ui.html']


def test_refuses_protected_names():
    setup({})
    for n in ('main.py', 'rescue.py', 'rollback.py', 'config.json', '../x.py', 'a/b.py', 'x.sh'):
        rel = make_release('1.0.1', {n: b'evil'})
        fake_github(rel)
        try:
            updater.install(rel['manifest'], '1.0.0')
            raise AssertionError('wrote ' + n)
        except ValueError:
            pass
    assert os.listdir() == []


def test_https_github():
    """Real HTTPS fetch with certificate checking against ca.pem (skipped offline)."""
    if os.environ.get('OFFLINE'):
        return
    os.chdir(FW)
    real = __import__('importlib').reload(updater)
    b = real._get('/micropython/micropython/master/README.md', limit=100000)
    assert b.startswith(b'<h1') or b'MicroPython' in b[:2000], b[:100]


if __name__ == '__main__':
    test_update_rollback_commit(); test_bad_download_changes_nothing(); test_refuses_protected_names(); test_https_github()
    print('all ok')
