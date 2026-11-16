"""Signed update + journal + rollback, with GitHub replaced by a dict (runs on CPython; needs openssl)."""
import hashlib, json, os, subprocess, sys, tempfile
FW = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'firmware')
sys.path.insert(0, FW)
import updater, rollback

KEYDIR = tempfile.mkdtemp()
KEY = os.path.join(KEYDIR, 'k.pem')
subprocess.run(['openssl', 'genpkey', '-algorithm', 'RSA', '-pkeyopt', 'rsa_keygen_bits:2048', '-out', KEY],
               check=True, capture_output=True)
TEST_N = int(subprocess.run(['openssl', 'rsa', '-in', KEY, '-noout', '-modulus'], check=True,
                            capture_output=True, text=True).stdout.split('=')[1], 16)
REAL_N = updater.PUB_N


def sign(body):
    p = os.path.join(KEYDIR, 'b')
    open(p, 'wb').write(body)
    return subprocess.run(['openssl', 'dgst', '-sha256', '-sign', KEY, p], check=True, capture_output=True).stdout.hex()


def setup(files):
    d = tempfile.mkdtemp()
    os.chdir(d)
    for n, b in files.items():
        open(n, 'wb').write(b)
    open('main.py', 'w').write('why = rollback.boot_check()\n')  # a Pico with 1.1 start-up files
    updater.PUB_N = TEST_N
    return d


def release(ver, files, corrupt=None, tamper=False, unsigned=False):
    m = {'version': ver, 'ref': 'v' + ver, 'notes': 'n',
         'files': {n: [hashlib.sha256(b).hexdigest(), len(b)] for n, b in files.items()}}
    body = json.dumps(m, sort_keys=True)
    sig = sign(body.encode())
    if tamper:  # attacker edits the signed body after signing
        body = body.replace('"n"', '"evil"')
    out = dict(m) if unsigned else dict(m, signed={'body': body, 'sig': sig})
    served = dict(files)
    if corrupt:
        served[corrupt] = served[corrupt][:-1] + b'X'
    return json.dumps(out).encode(), served


def serve(raw, served):
    def _get(path, sink=None, limit=200000):
        n = path.rsplit('/', 1)[1]
        b = raw if n == 'manifest.json' else served[n]
        if len(b) > limit:
            raise OSError('file too big')
        if sink:
            sink(b)
            return len(b)
        return b
    updater._get = _get


def read(n):
    return open(n, 'rb').read()


OLD = {'app.py': b'old app', 'version.py': b"VERSION = '1.0.0'", 'ui.html': b'old ui', 'config.json': b'{}'}
NEW = {'app.py': b'new app', 'version.py': b"VERSION = '1.0.1'", 'ui.html': b'new ui', 'extra.py': b'added'}


def test_signature():
    body = b'hello'
    s = sign(body)
    updater.PUB_N = TEST_N
    assert updater.verify(body, s)
    assert not updater.verify(b'hellp', s)
    assert not updater.verify(body, s[:-2] + ('00' if s[-2:] != '00' else '01'))
    assert not updater.verify(body, 'zz') and not updater.verify(body, None) and not updater.verify(body, '00' * 256)
    updater.PUB_N = REAL_N
    assert not updater.verify(body, s)  # test key is not the release key


def test_rejects_unsigned_tampered_and_protected():
    setup(OLD)
    for kw in ({'unsigned': True}, {'tamper': True}):
        serve(*release('1.0.1', NEW, **kw))
        try:
            updater.check('1.0.0')
            raise AssertionError('accepted %r' % kw)
        except ValueError as e:
            assert 'not signed' in str(e)
    for n in ('boot.py', 'main.py', 'rescue.py', 'rollback.py', 'config.json', 'upd.pending', '../x.py', 'a/b.py', 'x.sh'):
        serve(*release('1.0.1', {n: b'evil'}))  # even a properly SIGNED release can't touch these
        try:
            updater.check('1.0.0')
            raise AssertionError('allowed ' + n)
        except ValueError:
            pass
    assert sorted(os.listdir()) == sorted(list(OLD) + ['main.py'])


def test_update_rollback_commit():
    setup(OLD)
    serve(*release('1.0.1', NEW))
    c = updater.check('1.0.0')
    assert c['newer'] and c['verified'] and c['latest'] == '1.0.1'
    assert updater.install(c['manifest'], '1.0.0') == '1.0.1'
    assert read('app.py') == b'new app' and read('app.py.bak') == b'old app' and read('extra.py') == b'added'
    assert json.load(open('upd.pending'))['stage'] == 'installed'
    assert rollback.boot_check() is None  # first boot of the new version: fine
    assert rollback.undo('boom')
    assert read('app.py') == b'old app' and read('ui.html') == b'old ui' and not os.path.exists('extra.py')
    assert json.load(open('upd.last'))['ok'] is False and not os.path.exists('upd.pending')
    updater.install(c['manifest'], '1.0.0')
    assert updater.commit()['to'] == '1.0.1' and not [f for f in os.listdir() if f.endswith('.bak')]
    assert read('config.json') == b'{}'


def test_bad_download_changes_nothing():
    setup(OLD)
    raw, served = release('1.0.1', NEW, corrupt='ui.html')
    serve(raw, served)
    try:
        updater.install(updater.check('1.0.0')['manifest'], '1.0.0')
        raise AssertionError('accepted a damaged file')
    except ValueError:
        pass
    assert sorted(os.listdir()) == sorted(list(OLD) + ['main.py']) and read('app.py') == b'old app'


def test_power_cut_mid_swap():
    mid = 0
    for cut_after in range(1, 8):  # cut the power after N renames during the swap
        setup(OLD)
        serve(*release('1.0.1', NEW))
        m = updater.check('1.0.0')['manifest']
        real_rename, count = os.rename, [0]

        def flaky(a, b):
            if a != 'upd.tmp':
                count[0] += 1
                if count[0] > cut_after:
                    raise KeyboardInterrupt('power cut')
            real_rename(a, b)
        os.rename = flaky
        try:
            updater.install(m, '1.0.0')
        except KeyboardInterrupt:
            pass
        finally:
            os.rename = real_rename
        if not os.path.exists('upd.pending'):
            continue  # cut before anything was replaced
        if json.load(open('upd.pending'))['stage'] == 'installed':
            continue  # cut after the swap finished: a normal pending update
        mid += 1
        why = rollback.boot_check()
        assert why and 'interrupted' in why, (cut_after, why)
        assert updater.commit() is None  # never confirm a half-finished install
        assert rollback.undo(why)
        assert {n: read(n) for n in OLD} == OLD, cut_after
        assert not os.path.exists('extra.py') and not [f for f in os.listdir() if f.endswith(('.bak', '.new'))], os.listdir()
    assert mid >= 5, mid  # most cut points really were part-way through the swap


def test_boot_loop_rolls_back():
    setup(OLD)
    serve(*release('1.0.1', NEW))
    updater.install(updater.check('1.0.0')['manifest'], '1.0.0')
    assert [rollback.boot_check() for _ in range(3)] == [None, None, None]
    why = rollback.boot_check()
    assert why and 'restarted 3 times' in why
    rollback.undo(why)
    assert read('app.py') == b'old app'


def test_refuses_without_new_recovery_files():
    setup(OLD)
    serve(*release('1.0.1', NEW))
    m = updater.check('1.0.0')['manifest']
    saved = rollback.boot_check
    del rollback.boot_check  # a Pico still running the 1.0.x main.py/rollback.py
    try:
        updater.install(m, '1.0.0')
        raise AssertionError('installed without recovery support')
    except OSError as e:
        assert 'USB' in str(e)
    finally:
        rollback.boot_check = saved
    assert sorted(os.listdir()) == sorted(list(OLD) + ['main.py'])


def test_one_install_at_a_time():
    setup(OLD)
    serve(*release('1.0.1', NEW))
    m = updater.check('1.0.0')['manifest']
    updater.install(m, '1.0.0')
    try:  # a second install before the first is confirmed must not touch its backups
        updater.install(m, '1.0.0')
        raise AssertionError('second install ran')
    except OSError as e:
        assert 'still being confirmed' in str(e)
    assert read('app.py.bak') == b'old app'
    rollback.undo('x')
    assert read('app.py') == b'old app'


def test_old_main_py_refused():
    setup(OLD)
    open('main.py', 'w').write('import app\n')  # 1.0.x main.py: never calls boot_check
    serve(*release('1.0.1', NEW))
    try:
        updater.install(updater.check('1.0.0')['manifest'], '1.0.0')
        raise AssertionError('installed with an old main.py')
    except OSError as e:
        assert 'USB' in str(e)


def test_swap_error_is_undone_at_once():
    setup(OLD)
    serve(*release('1.0.1', NEW))
    m = updater.check('1.0.0')['manifest']
    real_rename, count = os.rename, [0]

    def failing(a, b):
        if a != 'upd.tmp':
            count[0] += 1
            if count[0] == 3:
                raise OSError(28, 'no space')
        real_rename(a, b)
    os.rename = failing
    try:
        updater.install(m, '1.0.0')
        raise AssertionError('no error')
    except OSError:
        pass
    finally:
        os.rename = real_rename
    assert {n: read(n) for n in OLD} == OLD and not os.path.exists('upd.pending') and not os.path.exists('extra.py')


def test_https_github():
    """Real HTTPS fetch with certificate checking against ca.pem (skipped offline)."""
    if os.environ.get('OFFLINE'):
        return
    os.chdir(FW)
    real = __import__('importlib').reload(updater)
    b = real._get('/micropython/micropython/master/README.md', limit=100000)
    assert b'MicroPython' in b[:3000], b[:100]


if __name__ == '__main__':
    test_signature(); test_rejects_unsigned_tampered_and_protected(); test_update_rollback_commit()
    test_bad_download_changes_nothing(); test_power_cut_mid_swap(); test_boot_loop_rolls_back(); test_refuses_without_new_recovery_files(); test_one_install_at_a_time(); test_old_main_py_refused(); test_swap_error_is_undone_at_once(); test_https_github()
    print('all ok')
