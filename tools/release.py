#!/usr/bin/env python3
"""Make a release that every Pico can install from its web page.

    python3 tools/release.py 1.0.1 "What's new, in a sentence or two"

Runs the tests, writes firmware/version.py and manifest.json: a body listing the SHA-256 + size
of each file the Pico downloads, SIGNED with the release key (RSA-2048, PKCS#1 v1.5, SHA-256).
Picos only install a body whose signature matches the public key built into updater.py.
Key: $HAWKI_RELEASE_KEY, default ~/.config/hawki-release/release_key.pem (keep it secret and
backed up; losing it means Picos can only be updated over USB).
Then commit, tag and push it, exactly as printed.
"""
import hashlib, json, os, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FW = os.path.join(ROOT, 'firmware')
KEEP = ('main.py', 'rescue.py', 'rollback.py', 'boot.py')  # boot path: installed by USB only, never over the air
KEY = os.environ.get('HAWKI_RELEASE_KEY', os.path.expanduser('~/.config/hawki-release/release_key.pem'))


def vt(v):
    return tuple(int(x) for x in v.split('.'))


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    ver, notes = sys.argv[1].lstrip('v'), sys.argv[2]
    if not os.path.exists(KEY):
        sys.exit('release key not found: ' + KEY)
    old = json.load(open(os.path.join(ROOT, 'manifest.json')))['version'] if os.path.exists(os.path.join(ROOT, 'manifest.json')) else '0.0.0'
    if vt(ver) <= vt(old):
        sys.exit('version %s must be newer than %s' % (ver, old))
    for t in sorted(os.listdir(os.path.join(ROOT, 'tests'))):
        if t.startswith('test_') and t.endswith('.py'):
            subprocess.run([sys.executable, os.path.join(ROOT, 'tests', t)], check=True)
    with open(os.path.join(FW, 'version.py'), 'w') as f:
        f.write("VERSION = '%s'\n" % ver)
    files = {}
    for n in sorted(os.listdir(FW)):
        p = os.path.join(FW, n)
        if n in KEEP or not os.path.isfile(p) or not n.endswith(('.py', '.html', '.pem')):
            continue
        b = open(p, 'rb').read()
        files[n] = [hashlib.sha256(b).hexdigest(), len(b)]
    m = {'version': ver, 'ref': 'v' + ver, 'notes': notes, 'files': files}
    body = json.dumps(m, sort_keys=True)
    with tempfile.NamedTemporaryFile('wb', delete=False) as t:
        t.write(body.encode())
    try:
        sig = subprocess.run(['openssl', 'dgst', '-sha256', '-sign', KEY, t.name], check=True,
                             capture_output=True).stdout.hex()
    finally:
        os.remove(t.name)
    sys.path.insert(0, FW)
    import updater  # check it with the Pico's own code before publishing
    assert updater.verify(body.encode(), sig), 'signature does not verify with the key in updater.py'
    # top-level fields only for Picos still on 1.0.x (they predate signing); 1.1+ trust 'signed' only
    out = dict(m, signed={'body': body, 'sig': sig})
    with open(os.path.join(ROOT, 'manifest.json'), 'w') as f:
        json.dump(out, f, indent=1)
        f.write('\n')
    print('manifest.json: %d files, %d bytes' % (len(files), sum(v[1] for v in files.values())))
    print('\nNow:\n  git add -A && git commit -m "Release v%s" && git tag v%s && git push origin main v%s' % (ver, ver, ver))


if __name__ == '__main__':
    main()
