"""python3 tests/test_release.py - release.py refuses to publish a release every Pico would refuse (tools/release.py).

It used to sign whatever it found: a file over 200 KB, or a manifest over 20 KB, would be published and then
refused by every Pico (and the version number burnt). Now the final text goes through the Pico's own
updater.parse() and size limit first. Signs with a throwaway key (needs openssl), like test_updater.py.
"""
import importlib.util, os, shutil, subprocess, sys, tempfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
spec = importlib.util.spec_from_file_location('release', os.path.join(ROOT, 'tools', 'release.py'))
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)
sys.path.insert(0, os.path.join(ROOT, 'firmware'))
import updater

fails = 0


def ok(c, m):
    global fails
    print(('ok   ' if c else 'FAIL ') + m)
    fails += 0 if c else 1


d = tempfile.mkdtemp()
key = os.path.join(d, 'k.pem')
subprocess.run(['openssl', 'genpkey', '-algorithm', 'RSA', '-pkeyopt', 'rsa_keygen_bits:2048', '-out', key], check=True, capture_output=True)
n = int(subprocess.run(['openssl', 'rsa', '-in', key, '-noout', '-modulus'], check=True, capture_output=True, text=True).stdout.split('=')[1], 16)
real_n, updater.PUB_N = updater.PUB_N, n  # (the throwaway key stands in for the release key)


def fw(files):
    p = tempfile.mkdtemp()
    for name, b in files.items():
        open(os.path.join(p, name), 'wb').write(b)
    return p


def refused(files, notes='n'):
    try:
        release.check_text(release.build('9.9.9', notes, key, fw(files)))
        return None
    except (ValueError, KeyError) as ex:
        return str(ex)


ok(refused({'app.py': b'x' * 1000, 'ui.html': b'y' * 2000}) is None, 'an ordinary release passes the Pico\'s own checks')
e = refused({'app.py': b'x' * 1000, 'ui.html': b'y' * 200001})
ok(e and 'ui.html' in e, 'a file over 200 KB: refused before publishing (%s)' % e)
e = refused({'app.py': b'x' * 1000, 'empty.py': b''})
ok(e and 'empty.py' in e, 'an empty file: refused (%s)' % e)
e = refused({'f%03d.py' % i: b'x' for i in range(130)})
ok(e and '20000' in e, 'a manifest over 20 KB: refused (%s)' % e)
e = refused({'app.py': b'x'}, notes='n' * 20000)
ok(e is not None, 'release notes so long the manifest is over 20 KB: refused')
ok(set(release.KEEP) >= {'main.py', 'rescue.py', 'rollback.py', 'boot.py'}, 'start-up files are never put in a release')
updater.PUB_N = real_n
ok(refused({'app.py': b'x'}) and True, 'signed with a key that isn\'t the one in updater.py: refused')
shutil.rmtree(d)
print('all ok' if not fails else '%d FAILED' % fails)
raise SystemExit(1 if fails else 0)
