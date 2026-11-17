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


def test_out_of_memory_retried():
    # TLS ran out of memory part-way through a file: collect, start that file again, install still matches
    setup(OLD)
    raw, served = release('1.0.1', NEW)
    serve(raw, served)
    c = updater.check('1.0.0')
    import importlib
    fresh = importlib.reload(updater)  # the real _get (serve() replaced it)
    fails = {'ui.html': 1}

    def fake1(path, sink, limit):
        n = path.rsplit('/', 1)[1]
        b = served[n]
        if fails.get(n):
            fails[n] -= 1
            sink(b[:3] + b'JUNKJUNKJUNK')  # a partial, damaged chunk, then the connection runs out of memory
            raise OSError(12, 'ENOMEM')
        sink(b)
        return len(b)
    fresh._get1 = fake1
    assert fresh.install(c['manifest'], '1.0.0') == '1.0.1'
    assert read('ui.html') == b'new ui' and read('app.py') == b'new app'
    # a different error is not retried, and nothing changes
    setup(OLD)
    fails = {}

    def broken(path, sink, limit):
        broken.n += 1
        raise OSError(113, 'EHOSTUNREACH')
    broken.n = 0
    fresh._get1 = broken
    try:
        fresh.install(c['manifest'], '1.0.0')
        raise AssertionError('installed')
    except OSError:
        assert broken.n == 1 and read('app.py') == b'old app'


def files_state():
    cur = {n: read(n) for n in NEW if os.path.exists(n)}
    if cur == NEW:
        return 'NEW'
    old = {n: read(n) for n in OLD if os.path.exists(n)}
    return 'OLD' if old == OLD and not os.path.exists('extra.py') else 'MIXED %r' % cur


def test_power_cut_during_commit():
    # commit() cut off part-way, then a rollback (no Wi-Fi for 10 min, or 3 restarts): never a mix of old and new
    for cut_after in range(0, 6):
        setup(OLD)
        serve(*release('1.0.1', NEW))
        updater.install(updater.check('1.0.0')['manifest'], '1.0.0')
        real_remove, count = os.remove, [0]

        def flaky(n):
            count[0] += 1
            if count[0] > cut_after:
                raise KeyboardInterrupt('power cut')
            real_remove(n)
        os.remove = flaky
        try:
            updater.commit()
        except KeyboardInterrupt:
            pass
        finally:
            os.remove = real_remove
        why = rollback.boot_check() or 'no Wi-Fi after the update'
        rollback.undo(why)
        st = files_state()
        assert st in ('OLD', 'NEW'), (cut_after, st)


def test_undo_keeps_journal_when_a_restore_fails():
    setup(OLD)
    serve(*release('1.0.1', NEW))
    updater.install(updater.check('1.0.0')['manifest'], '1.0.0')
    real_rename = os.rename

    def failing(a, b):
        if a == 'ui.html.bak':
            raise OSError(5, 'EIO')
        real_rename(a, b)
    os.rename = failing
    try:
        done = rollback.undo('boom')
    finally:
        os.rename = real_rename
    assert not done, 'claimed a rollback that left ui.html new'
    assert os.path.exists('upd.pending'), 'journal gone: nothing can finish the rollback'
    assert rollback.undo('again') and files_state() == 'OLD' and not os.path.exists('upd.pending')


def test_unreadable_journal():
    for junk in (b'', b'{"stage": "inst', b'[]', b'null', b'3'):
        # at boot: roll back to the backups that are there, and never block updates for good
        setup(OLD)
        serve(*release('1.0.1', NEW))
        m = updater.check('1.0.0')['manifest']
        updater.install(m, '1.0.0')
        open('upd.pending', 'wb').write(junk)
        why = rollback.boot_check()
        assert why and 'unreadable' in why, (junk, why)
        assert rollback.undo(why), junk
        assert {n: read(n) for n in OLD} == OLD and not os.path.exists('upd.pending'), (junk, os.listdir())
        assert not [f for f in os.listdir() if f.endswith(('.bak', '.new'))], os.listdir()
        assert updater.install(m, '1.0.0') == '1.0.1', junk  # updates work again
        # the new version has run fine for 2 minutes: confirming it clears the junk and the backups
        open('upd.pending', 'wb').write(junk)
        assert updater.commit() is not None, junk
        assert files_state() == 'NEW' and not os.path.exists('upd.pending'), junk
        assert not [f for f in os.listdir() if f.endswith('.bak')], os.listdir()


def test_leftovers_tidied():
    # power cut during the download: .new files stay behind with no journal; tidied at the next start
    setup(OLD)
    raw, served = release('1.0.1', NEW)
    serve(raw, served)
    m = updater.check('1.0.0')['manifest']
    real_get = updater._get
    n = [0]

    def cut(path, sink=None, limit=200000):
        n[0] += 1
        if n[0] == 3:
            raise KeyboardInterrupt('power cut')
        return real_get(path, sink, limit)
    updater._get = cut
    try:
        updater.install(m, '1.0.0')
    except KeyboardInterrupt:
        pass
    assert [f for f in os.listdir() if f.endswith('.new')]
    open('upd.tmp', 'w').write('{')
    open('h_abc123.bin.new', 'wb').write(b'x')  # not the updater's: left alone
    updater.tidy()
    left = sorted(os.listdir())
    assert left == sorted(list(OLD) + ['main.py', 'h_abc123.bin.new']), left
    # with an update pending, nothing is touched
    serve(raw, served)
    updater.install(m, '1.0.0')
    open('x.py.new', 'w').write('x')
    updater.tidy()
    assert os.path.exists('x.py.new') and os.path.exists('app.py.bak')


def test_journal_write_failure_leaves_nothing():
    setup(OLD)
    serve(*release('1.0.1', NEW))
    m = updater.check('1.0.0')['manifest']
    import builtins
    real_open = builtins.open

    def full(n, *a, **k):
        if n == 'upd.tmp':
            raise OSError(28, 'ENOSPC')
        return real_open(n, *a, **k)
    builtins.open = full
    try:
        updater.install(m, '1.0.0')
        raise AssertionError('no error')
    except OSError:
        pass
    finally:
        builtins.open = real_open
    assert sorted(os.listdir()) == sorted(list(OLD) + ['main.py']), os.listdir()


def boot_then_guard(wifi=True):
    # main.py at boot, then the app's update_guard (commit after 2 min with Wi-Fi, else roll back)
    why = rollback.boot_check()
    if why and rollback.undo(why):
        return 'reset'
    if os.path.exists('upd.pending'):
        if wifi:
            updater.commit()
        elif rollback.undo('no Wi-Fi after the update'):
            return 'reset'


def test_power_cut_during_undo():
    # a rollback cut off part-way must finish at the next boot: the half-restored files must never be confirmed
    for wifi in (True, False):
        for cut_after in range(0, 9):
            setup(OLD)
            serve(*release('1.0.1', NEW))
            updater.install(updater.check('1.0.0')['manifest'], '1.0.0')
            real_rename, real_remove, count = os.rename, os.remove, [0]

            def cut(f):
                def g(*a):
                    count[0] += 1
                    if count[0] > cut_after:
                        raise KeyboardInterrupt('power cut')
                    return f(*a)
                return g
            os.rename, os.remove = cut(real_rename), cut(real_remove)
            try:
                rollback.undo('boom')
            except KeyboardInterrupt:
                pass
            finally:
                os.rename, os.remove = real_rename, real_remove
            for _ in range(3):
                if boot_then_guard(wifi) != 'reset':
                    break
            st = files_state()
            assert st == 'OLD' or st == 'NEW' and not os.path.exists('upd.pending'), (wifi, cut_after, st)
            if st == 'NEW':  # only if the cut came before undo touched anything
                assert cut_after == 0, (wifi, cut_after)


def test_commit_keeps_backups_if_journal_stays():
    setup(OLD)
    serve(*release('1.0.1', NEW))
    updater.install(updater.check('1.0.0')['manifest'], '1.0.0')
    real_remove = os.remove

    def stuck(n):
        if n == 'upd.pending':
            raise OSError(5, 'EIO')
        real_remove(n)
    os.remove = stuck
    try:
        updater.commit()
    except OSError:
        pass
    finally:
        os.remove = real_remove
    assert os.path.exists('upd.pending') and read('app.py.bak') == b'old app', 'backups gone while the journal stays'
    assert rollback.undo('x') and files_state() == 'OLD'


def test_undo_with_a_stuck_journal_does_not_loop():
    setup(OLD)
    serve(*release('1.0.1', NEW))
    updater.install(updater.check('1.0.0')['manifest'], '1.0.0')
    real_remove = os.remove

    def stuck(n):
        if n == 'upd.pending':
            raise OSError(5, 'EIO')
        real_remove(n)
    os.remove = stuck
    try:
        assert not rollback.undo('x'), 'says done (so main.py restarts) though the journal is still there: a restart loop'
    finally:
        os.remove = real_remove
    assert files_state() == 'OLD'
    assert boot_then_guard() == 'reset' and not os.path.exists('upd.pending') and files_state() == 'OLD'


if __name__ == '__main__':
    test_signature(); test_rejects_unsigned_tampered_and_protected(); test_update_rollback_commit()
    test_bad_download_changes_nothing(); test_power_cut_mid_swap(); test_boot_loop_rolls_back(); test_refuses_without_new_recovery_files(); test_one_install_at_a_time(); test_old_main_py_refused(); test_swap_error_is_undone_at_once(); test_out_of_memory_retried(); test_https_github()
    test_power_cut_during_commit(); test_undo_keeps_journal_when_a_restore_fails(); test_unreadable_journal(); test_leftovers_tidied(); test_journal_write_failure_leaves_nothing()
    test_power_cut_during_undo(); test_commit_keeps_backups_if_journal_stays(); test_undo_with_a_stuck_journal_does_not_loop()
    print('all ok')
